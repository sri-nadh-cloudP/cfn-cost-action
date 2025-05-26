import os
import sys
import json
import base64
import subprocess
import requests
import re
from typing import Dict, TypedDict
from pathlib import Path
from cfn_sanitizer import sanitize_template
from cfn_sanitizer.scanner import load_template
from cfn_sanitizer.utils import save_template


def run_command(cmd, check=True):
    """Run a shell command and return the output"""
    result = subprocess.run(cmd, capture_output=True, text=True, check=check, shell=True)
    return result.stdout.strip()


def get_changed_files(base_branch):
    """Get the list of changed CloudFormation files"""
    try:
        changed_files = run_command(f"git diff --name-only origin/{base_branch}...HEAD | grep -E '\\.ya?ml$|\\.json$'", check=False)
        return changed_files.splitlines() if changed_files else []
    except subprocess.CalledProcessError:
        # grep returns exit code 1 if no files match
        return []


class OutputState(TypedDict):
    Cost_Results: Dict[str, str]
    Service_Cost_Collector: Dict[str, str]
    Final_Infra_Cost: str
    Validation_Output: str


def extract_total_cost(service_cost: str) -> str:
    """Extract the total monthly cost from a service cost string"""
    match = re.search(r'Total Monthly Cost:\s*([\d.]+)', service_cost)
    if match:
        return match.group(1)
    return "N/A"


def create_cost_comment(template_name: str, cost_data: OutputState) -> str:
    """Create a GitHub comment with collapsible sections for cost breakdown"""
    
    # Check if validation failed
    if cost_data['Validation_Output'] != 'Template validated successfully.':
        return f"""### ❌ Template Validation Failed: {template_name}

<details>
<summary><b>Validation Output</b></summary>

```
{cost_data['Validation_Output']}
```
</details>
"""
    
    # Start building the comment with header
    comment = f"### 💰 CloudFormation Cost Estimation for `{template_name}`\n\n"
    
    # Add the final infrastructure cost
    final_cost = cost_data['Final_Infra_Cost'].strip()
    monthly_cost_match = re.search(r'Total Monthly Cost:\s*([\d.]+)', final_cost)
    monthly_cost = monthly_cost_match.group(1) if monthly_cost_match else "N/A"
    
    future_cost_match = re.search(r'Total Future Monthly Cost :\s*([\d.]+)', final_cost)
    future_cost = f" (Future: ${future_cost_match.group(1)})" if future_cost_match else ""
    
    comment += f"**Total Monthly Cost: ${monthly_cost}{future_cost}**\n\n"
    
    # Add a summary table of service costs
    comment += "| AWS Service | Monthly Cost |\n|------------|-------------|\n"
    
    for service_name, service_cost in cost_data['Service_Cost_Collector'].items():
        total_cost = extract_total_cost(service_cost)
        formatted_service_name = service_name.replace('_', ' ')
        comment += f"| {formatted_service_name} | ${total_cost} |\n"
    
    comment += "\n"
    
    # Add collapsible details for each service
    for service_name, detailed_cost in cost_data['Cost_Results'].items():
        formatted_service_name = service_name.replace('_', ' ')
        
        comment += f"<details>\n<summary><b>{formatted_service_name} Details</b></summary>\n\n"
        
        # Extract individual resource costs and create nested collapsible sections
        resource_sections = re.split(r'\nIndividual Resource Costs:', detailed_cost)
        
        for i, section in enumerate(resource_sections):
            if i > 0:  # Skip the first split since it's not a separate resource
                section = "Individual Resource Costs:" + section
            
            # Extract resource type
            resource_type_match = re.search(r'ResourceType:\s*([^\n]+)', section)
            if resource_type_match:
                resource_type = resource_type_match.group(1).strip()
                
                # Create nested collapsible for individual resource
                if i > 0:  # Only create nested dropdowns for additional resources
                    comment += f"<details>\n<summary><b>{resource_type}</b></summary>\n\n"
                    comment += f"```\n{section.strip()}\n```\n\n"
                    comment += "</details>\n\n"
                else:
                    comment += f"```\n{section.strip()}\n```\n\n"
        
        comment += "</details>\n\n"
    
    return comment


def main():
    # Get inputs from environment variables (set by GitHub Actions)
    github_token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("INPUT_GITHUB-TOKEN")
    repo_fullname = os.environ.get("GITHUB_REPOSITORY")
    
    # Parse the GitHub event data
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("ERROR: GITHUB_EVENT_PATH not found")
        sys.exit(1)
        
    with open(event_path, 'r') as f:
        event_data = json.load(f)
    
    pr_number = event_data.get('pull_request', {}).get('number')
    base_branch = event_data.get('pull_request', {}).get('base', {}).get('ref')
    
    if not pr_number or not base_branch:
        print("ERROR: Could not determine PR number or base branch")
        sys.exit(1)
    
    print(f"Fetching base branch: {base_branch}")
    run_command(f"git fetch origin {base_branch}")
    
    
    # Get list of changed CloudFormation files
    changed_files = get_changed_files(base_branch)
    if not changed_files:
        print("No CloudFormation templates changed. Exiting.")
        sys.exit(0)
    
    
    # Create temp directory for sanitized outputs
    sanitized_dir = Path("./sanitized_templates")
    sanitized_dir.mkdir(exist_ok=True)
    
    
    # Sanitize each changed template
    sanitized_list = []
    for file_path in changed_files:
        file_path = Path(file_path)
        base_name = file_path.name
        out_path = sanitized_dir / base_name
        
        print(f"Sanitizing {file_path}...")
        
        # Load the template
        template, fmt = load_template(file_path)
        
        # Sanitize the template
        sanitized, _ = sanitize_template(template)
        
        # Save the sanitized template
        save_template(out_path, sanitized, fmt)
        
        sanitized_list.append((str(out_path), file_path.name))
    
    # Prepare payload with all sanitized templates
    payload = {"templates": []}
    for sanitized_file, original_name in sanitized_list:
        with open(sanitized_file, 'rb') as f:
            content = base64.b64encode(f.read()).decode('utf-8')
        
        payload["templates"].append({
            "filename": original_name,
            "content": content
        })
    
    # Send to cost server
    cost_endpoint = "https://your-cost-api.example.com/evaluate"
    print(f"Sending sanitized templates to {cost_endpoint}")
    
    headers = {"Content-Type": "application/json"}
    response = requests.post(cost_endpoint, headers=headers, json=payload)
    response.raise_for_status()  # Raise an exception for 4XX/5XX responses
    
    cost_data_list = response.json()
    
    # Create a beautiful GitHub comment with collapsible sections
    main_comment = "### 💰 CloudFormation Cost Estimation\n\n"
    total_cost = 0.0
    future_cost = 0.0
    
    # Add a summary table for all templates
    main_comment += "| CloudFormation Template | Current Cost | Future Cost | Status |\n"
    main_comment += "|------------------------|--------------|-------------|--------|\n"
    
    # Create detailed comments for each template
    detailed_comments = []
    for i, template_data in enumerate(cost_data_list):
        template_name = template_data.get("filename")
        
        # Extract template costs
        try:
            template_output = template_data.get("output", {})
            
            # Check if validation succeeded
            validation_output = template_output.get('Validation_Output', 'Validation failed')
            status = "✅" if validation_output == 'Template validated successfully.' else "❌"
            
            # Get costs if validation succeeded
            if status == "✅":
                final_cost = template_output.get('Final_Infra_Cost', '')
                monthly_cost_match = re.search(r'Total Monthly Cost:\s*([\d.]+)', final_cost)
                current_cost = float(monthly_cost_match.group(1)) if monthly_cost_match else 0.0
                
                future_cost_match = re.search(r'Total Future Monthly Cost :\s*([\d.]+)', final_cost)
                template_future_cost = float(future_cost_match.group(1)) if future_cost_match else 0.0
                
                total_cost += current_cost
                future_cost += template_future_cost
            else:
                current_cost = 0.0
                template_future_cost = 0.0
            
            # Add row to summary table
            main_comment += f"| [{template_name}](#{template_name.replace('.', '')}) | ${current_cost:.2f} | ${template_future_cost:.2f} | {status} |\n"
            
            # Create detailed comment for this template
            template_comment = create_cost_comment(template_name, template_output)
            template_comment = f"<a name='{template_name.replace('.', '')}'></a>\n\n{template_comment}\n\n---\n\n"
            detailed_comments.append(template_comment)
            
        except Exception as e:
            print(f"Error processing template {template_name}: {str(e)}")
            main_comment += f"| {template_name} | Error | Error | ❌ |\n"
    
    # Add total cost to main comment
    main_comment += f"\n**Total Infrastructure Cost: ${total_cost:.2f}**"
    if future_cost > 0:
        main_comment += f" **(Future: ${future_cost:.2f})**"
    main_comment += "\n\n---\n\n"
    
    # Combine main comment with detailed comments
    full_comment = main_comment + "".join(detailed_comments)
    
    # Post comment to the PR
    print(f"Commenting on PR #{pr_number}")
    
    comment_url = f"https://api.github.com/repos/{repo_fullname}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {github_token}",
        "Content-Type": "application/json"
    }
    
    comment_payload = {"body": full_comment}
    response = requests.post(comment_url, headers=headers, json=comment_payload)
    response.raise_for_status()
    
    print("Comment posted successfully!")


if __name__ == "__main__":
    main() 
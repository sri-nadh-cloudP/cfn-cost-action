import os
import sys
import json
import base64
import subprocess
import requests
import re
import tempfile
from typing import Dict, List
from pathlib import Path


def run_command(cmd, check=True):
    """Run a shell command and return the output"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=check, shell=True)
    if result.stderr and not check:
        print(f"Command stderr: {result.stderr}")
    return result.stdout.strip()


def sanitize_template_cli(input_path, output_path):
    """Sanitize a CloudFormation template using the cfn-sanitizer CLI"""
    try:
        cmd = f"cfn-sanitizer -i {input_path} -o {output_path}"
        result = run_command(cmd)
        return True
    except Exception as e:
        print(f"Error sanitizing template: {str(e)}")
        return False


def get_changed_files(base_branch, pr_number, github_token, repo_fullname):
    """Get the list of changed CloudFormation files using the GitHub API"""
    try:
        # First try using git command if we have a full clone
        print("Trying to get changed files using git...")
        try:
            changed_files = run_command(f"git diff --name-only origin/{base_branch}...HEAD | grep -E '\\.ya?ml$|\\.json$'", check=False)
            if changed_files:
                return changed_files.splitlines()
        except Exception as e:
            print(f"Git diff failed: {str(e)}")
        
        # Fallback to GitHub API
        print("Falling back to GitHub API to get changed files...")
        api_url = f"https://api.github.com/repos/{repo_fullname}/pulls/{pr_number}/files"
        headers = {"Authorization": f"token {github_token}"}
        
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        
        files_data = response.json()
        changed_files = []
        
        for file_data in files_data:
            filename = file_data.get("filename", "")
            if filename.endswith(('.yaml', '.yml', '.json')):
                changed_files.append(filename)
        
        return changed_files
    except Exception as e:
        print(f"Error getting changed files: {str(e)}")
        return []


def get_file_content(filename, github_token, repo_fullname, pr_number):
    """Get file content either from local filesystem or using GitHub API"""
    try:
        # First try to read locally
        if Path(filename).exists():
            print(f"Reading {filename} from local filesystem")
            with open(filename, 'r') as f:
                return f.read()
        
        # If not found, try GitHub API
        print(f"Fetching {filename} using GitHub API")
        api_url = f"https://api.github.com/repos/{repo_fullname}/contents/{filename}"
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3.raw"
        }
        
        params = {"ref": f"refs/pull/{pr_number}/head"}
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        
        return response.text
    
    except Exception as e:
        print(f"Error reading file {filename}: {str(e)}")
        raise


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
    
    print(f"Processing PR #{pr_number} with base branch: {base_branch}")
    
    try:
        print(f"Setting up git authentication...")
        # Configure Git to use the token for authentication
        run_command(f"git config --global credential.helper 'store --file=/tmp/git-credentials'")
        with open('/tmp/git-credentials', 'w') as f:
            f.write(f"https://x-access-token:{github_token}@github.com\n")
        
        # Add repository to safe directories
        run_command("git config --global --add safe.directory /github/workspace", check=False)
        
        # Try to fetch, but don't fail if it doesn't work
        print(f"Fetching base branch: {base_branch}")
        try:
            run_command(f"git fetch origin {base_branch}", check=False)
        except Exception as e:
            print(f"Warning: Could not fetch base branch: {str(e)}")
    except Exception as e:
        print(f"Warning: Git setup failed: {str(e)}")
    
    # Get list of changed CloudFormation files
    changed_files = get_changed_files(base_branch, pr_number, github_token, repo_fullname)
    if not changed_files:
        print("No CloudFormation templates changed. Exiting.")
        sys.exit(0)
    
    print(f"Found {len(changed_files)} changed template(s): {', '.join(changed_files)}")
    
    # Create temp directory for sanitized outputs
    sanitized_dir = Path("./sanitized_templates")
    sanitized_dir.mkdir(exist_ok=True)
    
    # Create temp directory for original templates
    temp_dir = Path("./temp_templates")
    temp_dir.mkdir(exist_ok=True)
    
    # Sanitize each changed template
    sanitized_list = []
    for file_path in changed_files:
        try:
            file_path_obj = Path(file_path)
            base_name = file_path_obj.name
            temp_path = temp_dir / base_name
            out_path = sanitized_dir / base_name
            
            print(f"Processing {file_path}...")
            
            # Get file content and save to temp file
            try:
                template_content = get_file_content(file_path, github_token, repo_fullname, pr_number)
                
                # Save the content to a temporary file
                with open(temp_path, 'w') as f:
                    f.write(template_content)
                
                # Sanitize the template using CLI
                if sanitize_template_cli(temp_path, out_path):
                    sanitized_list.append((str(out_path), file_path_obj.name))
                    print(f"Successfully sanitized {file_path}")
                else:
                    print(f"Failed to sanitize {file_path}")
                
            except Exception as e:
                print(f"Error processing template {file_path}: {str(e)}")
                continue
        
        except Exception as e:
            print(f"Error processing file {file_path}: {str(e)}")
            continue
    
    if not sanitized_list:
        print("No templates were successfully sanitized. Exiting.")
        sys.exit(0)
    
    # Prepare payload with all sanitized templates
    payload = {"templates": []}
    for sanitized_file, original_name in sanitized_list:
        try:
            with open(sanitized_file, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')
            
            payload["templates"].append({
                "filename": original_name,
                "content": content
            })
        except Exception as e:
            print(f"Error reading sanitized file {sanitized_file}: {str(e)}")
    
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
            from create_cost_comment import create_cost_comment
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
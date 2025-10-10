import os
import sys
import json
import base64
import subprocess
import requests
from pathlib import Path

# Direct imports with proper handling
from cfn_flip import load_yaml, load_json, dump_yaml, dump_json
from cfn_sanitizer.sanitizer import sanitize_template


def run_command(cmd, check=True):
    """Run a shell command and return the output"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=check, shell=True)
    if result.stderr and not check:
        print(f"Command stderr: {result.stderr}")
    return result.stdout.strip()


def sanitize_template_direct(content, output_path, fmt='yaml'):
    """Sanitize a CloudFormation template directly using the module"""
    try:
        print(f"Sanitizing template and saving to {output_path}")
        
        # Parse template based on format
        if fmt == 'json':
            template = load_json(content)
        else:
            template = load_yaml(content)
        
        # Sanitize the template
        sanitized, _ = sanitize_template(template)
        
        # Write to output file
        with open(output_path, 'w') as f:
            if fmt == 'json':
                f.write(dump_json(sanitized))
            else:
                f.write(dump_yaml(sanitized))
        
        return True
    except Exception as e:
        print(f"Error sanitizing template: {str(e)}")
        return False


def is_cloudformation_template(content):
    """Check if the content is a CloudFormation template"""
    try:
        # Try parsing as YAML first
        try:
            template = load_yaml(content)
        except:
            # Try parsing as JSON
            try:
                template = load_json(content)
            except:
                return False
        
        # Check for CloudFormation-specific keys
        if not isinstance(template, dict):
            return False
            
        # A CloudFormation template must have either Resources or at least AWSTemplateFormatVersion
        has_resources = 'Resources' in template
        has_cfn_version = 'AWSTemplateFormatVersion' in template
        
        # Most CFN templates will have Resources, but some might only have Parameters/Outputs
        # So we check for typical CFN keys
        cfn_keys = {'Resources', 'AWSTemplateFormatVersion', 'Parameters', 'Outputs', 'Conditions', 'Mappings', 'Transform'}
        has_cfn_keys = bool(cfn_keys.intersection(template.keys()))
        
        return has_resources or (has_cfn_version and has_cfn_keys)
    except Exception as e:
        print(f"Error checking if file is CFN template: {str(e)}")
        return False


def get_changed_files(base_branch, pr_number, github_token, repo_fullname, event_action, before_sha, after_sha):
    """Get the list of changed CloudFormation files based on the event type"""
    try:
        changed_files = []
        
        # For 'synchronize' event, only get files changed in the latest commit
        if event_action == 'synchronize' and before_sha and after_sha:
            print(f"Event: synchronize - Getting files changed between {before_sha[:7]}...{after_sha[:7]}")
            
            # Use GitHub API to compare commits
            api_url = f"https://api.github.com/repos/{repo_fullname}/compare/{before_sha}...{after_sha}"
            headers = {"Authorization": f"token {github_token}"}
            
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            
            compare_data = response.json()
            files_data = compare_data.get('files', [])
            
            print(f"\nAnalyzing {len(files_data)} changed files in latest commit...")
            
        else:
            # For 'opened' or other events, get all files changed in the PR
            print(f"Event: {event_action} - Getting all files changed in PR #{pr_number}")
            api_url = f"https://api.github.com/repos/{repo_fullname}/pulls/{pr_number}/files"
            headers = {"Authorization": f"token {github_token}"}
            
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            
            files_data = response.json()
            
            print(f"\nAnalyzing {len(files_data)} changed files in PR...")
        
        # Process files
        for file_data in files_data:
            filename = file_data.get("filename", "")
            status = file_data.get("status", "")
            
            # Only process added or modified files (not deleted)
            if status == "removed":
                print(f"  ⏭️  Skipping deleted file: {filename}")
                continue
                
            # Check if it has a potential CFN extension
            if filename.endswith(('.yaml', '.yml', '.json')):
                print(f"  🔍 Found potential CFN file: {filename} (status: {status})")
                changed_files.append(filename)
            else:
                print(f"  ⏭️  Skipping non-template file: {filename}")
        
        print(f"\nTotal potential CFN templates to validate: {len(changed_files)}")
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
    
    # Debug token permissions (output first few chars only for security)
    if github_token:
        token_preview = github_token[:4] + "..." if len(github_token) > 4 else "invalid"
        print(f"Using GitHub token starting with: {token_preview}")
    else:
        print("WARNING: No GitHub token provided!")
    
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
    event_action = event_data.get('action', 'opened')  # opened, synchronize, closed, etc.
    
    # For synchronize events, get the before and after commit SHAs
    before_sha = event_data.get('before', '')
    after_sha = event_data.get('after', '')
    
    if not pr_number or not base_branch:
        print("ERROR: Could not determine PR number or base branch")
        sys.exit(1)
    
    print(f"Processing PR #{pr_number} (action: {event_action}) with base branch: {base_branch}")
    if event_action == 'synchronize':
        print(f"Synchronize event: comparing {before_sha[:7] if before_sha else 'N/A'}...{after_sha[:7] if after_sha else 'N/A'}")
    
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
    changed_files = get_changed_files(base_branch, pr_number, github_token, repo_fullname, event_action, before_sha, after_sha)
    if not changed_files:
        print("No potential CloudFormation templates changed. Exiting.")
        sys.exit(0)
    
    # Create temp directory for sanitized outputs
    sanitized_dir = Path("./sanitized_templates")
    sanitized_dir.mkdir(exist_ok=True)
    
    # Validate and sanitize each changed template
    sanitized_list = []
    validated_cfn_files = []
    
    print(f"\n{'='*60}")
    print("VALIDATING CLOUDFORMATION TEMPLATES")
    print(f"{'='*60}\n")
    
    for file_path in changed_files:
        try:
            file_path_obj = Path(file_path)
            base_name = file_path_obj.name
            
            print(f"📄 Checking: {file_path}")
            
            # Get file content
            try:
                template_content = get_file_content(file_path, github_token, repo_fullname, pr_number)
                
                # Validate that this is actually a CloudFormation template
                if not is_cloudformation_template(template_content):
                    print(f"  ⚠️  NOT a CloudFormation template - skipping")
                    print()
                    continue
                
                print(f"  ✅ Confirmed as CloudFormation template")
                validated_cfn_files.append(file_path)
                
                # Determine format based on file extension
                fmt = 'json' if file_path.endswith('.json') else 'yaml'
                
                # Sanitize the template directly
                out_path = sanitized_dir / base_name
                if sanitize_template_direct(template_content, out_path, fmt):
                    sanitized_list.append((str(out_path), file_path_obj.name))
                    print(f"  ✅ Successfully sanitized")
                else:
                    print(f"  ❌ Failed to sanitize")
                print()
                
            except Exception as e:
                print(f"  ❌ Error processing: {str(e)}")
                print()
                continue
        
        except Exception as e:
            print(f"❌ Error with file {file_path}: {str(e)}")
            print()
            continue
    
    print(f"\n{'='*60}")
    print(f"VALIDATION COMPLETE")
    print(f"{'='*60}")
    print(f"✅ Validated CFN templates: {len(validated_cfn_files)}")
    if validated_cfn_files:
        for f in validated_cfn_files:
            print(f"   - {f}")
    print(f"✅ Successfully sanitized: {len(sanitized_list)}")
    print(f"{'='*60}\n")
    
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
    cost_endpoint = "http://34.66.30.124:8000/evaluate"
    print(f"Sending sanitized templates to {cost_endpoint}")
    
    headers = {"Content-Type": "application/json"}
    response = requests.post(cost_endpoint, headers=headers, json=payload)
    response.raise_for_status()  # Raise an exception for 4XX/5XX responses
    
    cost_data_list = response.json()
    
    # Create a beautiful GitHub comment with collapsible sections for EACH template
    print("Generating GitHub PR comments...")
    
    # Process each template separately and post individual comments
    for i, template_data in enumerate(cost_data_list):
        template_name = template_data.get("filename")
        print(f"Processing comment for template: {template_name}")
        
        # Extract template costs
        try:
            template_output = template_data.get("output", {})
            
            # Generate cost comment for this template using the helper function
            from create_cost_comment import create_cost_comment, create_tag_guardrails_comment
            template_comment = create_cost_comment(template_name, template_output)
            
            # Post comment to the PR
            print(f"Posting comment for template: {template_name}")
            
            try:
                comment_url = f"https://api.github.com/repos/{repo_fullname}/issues/{pr_number}/comments"
                print(f"API URL: {comment_url}")
                
                headers = {
                    "Authorization": f"token {github_token}",
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json"
                }
                
                comment_payload = {"body": template_comment}
                
                # Debug request
                print(f"Sending comment with headers: {headers['Accept']}")
                print(f"Comment length: {len(template_comment)} characters")
                
                response = requests.post(comment_url, headers=headers, json=comment_payload)
                
                # Print response details
                print(f"Response status code: {response.status_code}")
                if response.status_code != 201:  # 201 is the success code for created
                    print(f"Response headers: {response.headers}")
                    print(f"Response content: {response.text[:500]}...")  # Print first 500 chars
                    
                response.raise_for_status()
                print(f"Cost comment for {template_name} posted successfully!")
                
                # Also post Tag Guardrails comment if available
                tag_guardrails = template_output.get('Tag_Guardrails', {})
                if tag_guardrails:  # Only post if there are guardrails to show
                    try:
                        tag_comment = create_tag_guardrails_comment(template_name, tag_guardrails)
                        print(f"Posting tag guardrails comment for template: {template_name}")
                        
                        tag_comment_payload = {"body": tag_comment}
                        tag_response = requests.post(comment_url, headers=headers, json=tag_comment_payload)
                        
                        print(f"Tag guardrails response status code: {tag_response.status_code}")
                        if tag_response.status_code != 201:
                            print(f"Tag guardrails response content: {tag_response.text[:500]}...")
                        
                        tag_response.raise_for_status()
                        print(f"Tag guardrails comment for {template_name} posted successfully!")
                        
                    except Exception as e:
                        print(f"Error posting tag guardrails comment for {template_name}: {str(e)}")
                        print("Continuing...")
                
            except Exception as e:
                print(f"Error posting comments for {template_name}: {str(e)}")
                print("Continuing with next template...")
            
        except Exception as e:
            print(f"Error processing template {template_name}: {str(e)}")
            continue
    
    print("All template comments processed!")


if __name__ == "__main__":
    main() 
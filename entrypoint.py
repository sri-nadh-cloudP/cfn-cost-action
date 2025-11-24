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
from create_cost_comment import create_cost_comment, create_tag_guardrails_comment, create_cost_guardrails_comment

# Import CDK detection and cleaning utilities
from detect_cdk_from_file import is_cdk_file
from cdk_template_cleaner import CDKTemplateCleaner

# Import CDK synthesis handler (3-step production approach)
from cdk_synthesis_handler import (
    detect_cdk_environment,
    safe_cdk_synth_with_fallbacks,
    create_cdk_error_pr_comment
)


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
    """Get the list of changed CloudFormation and CDK files based on the event type"""
    try:
        changed_cfn_files = []
        changed_cdk_files = []
        
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
                
            # Check if it's a potential CFN template (.yaml, .yml, .json)
            if filename.endswith(('.yaml', '.yml', '.json')):
                print(f"  🔍 Found potential CFN file: {filename} (status: {status})")
                changed_cfn_files.append(filename)
            # Check if it's a potential CDK file (.py, .ts, .js, .java, .cs, .go)
            elif filename.endswith(('.py', '.ts', '.js', '.mjs', '.java', '.cs', '.go')):
                print(f"  🔍 Found potential CDK file: {filename} (status: {status})")
                changed_cdk_files.append(filename)
            else:
                print(f"  ⏭️  Skipping non-template file: {filename}")
        
        print(f"\nTotal potential CFN templates to validate: {len(changed_cfn_files)}")
        print(f"Total potential CDK files to check: {len(changed_cdk_files)}")
        
        return changed_cfn_files, changed_cdk_files
    except Exception as e:
        print(f"Error getting changed files: {str(e)}")
        return [], []



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


def process_cdk_files(changed_cdk_files, sanitized_dir, github_token=None, repo_fullname=None, pr_number=None):
    """
    Process CDK files: detect CDK apps, run cdk synth, clean templates.
    Now with production-ready 3-step approach!
    
    Args:
        changed_cdk_files: List of changed CDK file paths
        sanitized_dir: Directory to store sanitized templates
        github_token: GitHub token for posting error comments (optional)
        repo_fullname: Repo fullname for posting comments (optional)
        pr_number: PR number for posting comments (optional)
        
    Returns:
        List of tuples (sanitized_file_path, original_name)
    """
    sanitized_list = []
    
    if not changed_cdk_files:
        return sanitized_list
    
    print(f"\n{'='*60}")
    print("PROCESSING CDK FILES")
    print(f"{'='*60}\n")
    
    # Step 1: Detect CDK apps and collect unique CDK roots
    cdk_apps = {}  # {cdk_root: {'language': ..., 'files': [...]}}
    
    for file_path in changed_cdk_files:
        print(f"🔍 Checking: {file_path}")
        
        result = is_cdk_file(file_path)
        
        if result['is_cdk']:
            cdk_root = result['cdk_root']
            language = result['language']
            
            print(f"  ✅ CDK file detected")
            print(f"     CDK Root: {cdk_root}")
            print(f"     Language: {language}")
            
            if cdk_root not in cdk_apps:
                cdk_apps[cdk_root] = {
                    'language': language,
                    'files': []
                }
            cdk_apps[cdk_root]['files'].append(file_path)
        else:
            print(f"  ⏭️  Not a CDK app file")
        print()
    
    if not cdk_apps:
        print("No CDK apps detected. Skipping CDK processing.")
        return sanitized_list
    
    print(f"\n{'='*60}")
    print(f"Found {len(cdk_apps)} unique CDK app(s)")
    print(f"{'='*60}\n")
    
    # Step 2: Process each unique CDK app
    cdk_cleaner = CDKTemplateCleaner()
    
    for cdk_root, app_info in cdk_apps.items():
        language = app_info['language']
        files = app_info['files']
        
        print(f"📦 Processing CDK App: {cdk_root}")
        print(f"   Language: {language}")
        print(f"   Changed files: {', '.join(files)}")
        print()
        
        try:
            cdk_root_path = Path(cdk_root).resolve()
            cdk_root_abs = str(cdk_root_path)
            
            # ============================================================
            # STEP 1: DETECT ENVIRONMENT
            # ============================================================
            print(f"   🔍 Step 1: Detecting environment...")
            env_info = detect_cdk_environment(cdk_root_path)
            
            if env_info['cdk_lib_version']:
                print(f"   ✅ Detected CDK version: {env_info['cdk_lib_version']}")
            else:
                print(f"   ⚠️  Could not detect CDK version")
            
            # ============================================================
            # INSTALL DEPENDENCIES (Use lock files for exact versions!)
            # ============================================================
            print(f"   📦 Installing dependencies...")
            
            if language == 'python':
                if (cdk_root_path / 'requirements.txt').exists():
                    # Use python3 -m pip to ensure correct Python version
                    install_result = subprocess.run(
                        ['python3', '-m', 'pip', 'install', '-r', 'requirements.txt'],
                        cwd=cdk_root_abs,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if install_result.returncode != 0:
                        print(f"   ⚠️  Warning: pip install failed: {install_result.stderr[:100]}")
                    else:
                        print(f"   ✅ Python dependencies installed")
                        
            elif language in ['javascript', 'typescript']:
                # Use npm ci if lock file exists (exact versions)
                # Otherwise fall back to npm install
                if (cdk_root_path / 'package-lock.json').exists():
                    print(f"   Using npm ci (exact versions from lock file)...")
                    install_cmd = ['npm', 'ci']
                else:
                    print(f"   Using npm install (no lock file found)...")
                    install_cmd = ['npm', 'install']
                
                install_result = subprocess.run(
                    install_cmd,
                    cwd=cdk_root_abs,
                    capture_output=True,
                    text=True,
                    check=False
                )
                if install_result.returncode != 0:
                    print(f"   ⚠️  Warning: {install_cmd[1]} failed: {install_result.stderr[:100]}")
                else:
                    print(f"   ✅ npm dependencies installed")
                        
            elif language == 'java':
                # Install Java dependencies using Maven or Gradle
                if (cdk_root_path / 'pom.xml').exists():
                    install_result = subprocess.run(
                        ['mvn', 'install', '-DskipTests'],
                        cwd=cdk_root_abs,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if install_result.returncode != 0:
                        print(f"   ⚠️  Warning: mvn install failed: {install_result.stderr}")
                    else:
                        print(f"   ✅ Maven dependencies installed")
                elif (cdk_root_path / 'build.gradle').exists() or (cdk_root_path / 'build.gradle.kts').exists():
                    install_result = subprocess.run(
                        ['gradle', 'build', '-x', 'test'],
                        cwd=cdk_root_abs,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if install_result.returncode != 0:
                        print(f"   ⚠️  Warning: gradle build failed: {install_result.stderr}")
                    else:
                        print(f"   ✅ Gradle dependencies installed")
                        
            elif language == 'go':
                # Install Go dependencies
                if (cdk_root_path / 'go.mod').exists():
                    install_result = subprocess.run(
                        ['go', 'mod', 'download'],
                        cwd=cdk_root_abs,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if install_result.returncode != 0:
                        print(f"   ⚠️  Warning: go mod download failed: {install_result.stderr}")
                    else:
                        print(f"   ✅ Go dependencies installed")
                        
            elif language == 'csharp':
                # Install .NET dependencies
                csproj_files = list(cdk_root_path.glob('*.csproj'))
                sln_files = list(cdk_root_path.glob('*.sln'))
                if csproj_files or sln_files:
                    install_result = subprocess.run(
                        ['dotnet', 'restore'],
                        cwd=cdk_root_abs,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if install_result.returncode != 0:
                        print(f"   ⚠️  Warning: dotnet restore failed: {install_result.stderr}")
                    else:
                        print(f"   ✅ .NET dependencies installed")
            
            # ============================================================
            # STEP 2: GRACEFUL DEGRADATION - CDK SYNTH WITH FALLBACKS
            # ============================================================
            print(f"   🔨 Step 2: Running CDK synthesis with fallbacks...")
            synth_result = safe_cdk_synth_with_fallbacks(cdk_root_path, language)
            
            if not synth_result['success']:
                # ========================================================
                # STEP 3: INTELLIGENT ERROR REPORTING
                # ========================================================
                print(f"   ❌ CDK synth failed after {len(synth_result['attempts'])} attempts")
                print(f"      Error type: {synth_result['error']['type']}")
                
                # Post helpful error comment to PR if credentials available
                if github_token and repo_fullname and pr_number:
                    try:
                        print(f"   💬 Step 3: Posting helpful guidance to PR...")
                        error_comment = create_cdk_error_pr_comment(cdk_root, env_info, synth_result)
                        
                        comment_url = f"https://api.github.com/repos/{repo_fullname}/issues/{pr_number}/comments"
                        headers = {
                            "Authorization": f"token {github_token}",
                            "Accept": "application/vnd.github.v3+json"
                        }
                        response = requests.post(comment_url, headers=headers, json={"body": error_comment})
                        
                        if response.status_code == 201:
                            print(f"   ✅ Error guidance posted to PR")
                        else:
                            print(f"   ⚠️  Could not post comment: {response.status_code}")
                    except Exception as e:
                        print(f"   ⚠️  Could not post error comment: {e}")
                
                # Continue with next CDK app instead of failing entire action
                print(f"   ⏭️  Skipping this CDK app, continuing with others...")
                continue
            
            # ============================================================
            # SUCCESS! Process generated templates
            # ============================================================
            print(f"   ✅ CDK synth succeeded using '{synth_result['strategy_used']}' strategy")
            print(f"   📄 Found {len(synth_result['templates'])} template(s)")
            
            # Show warnings if any
            for warning in synth_result['warnings']:
                print(f"   ⚠️  {warning}")
            
            # Process each generated template
            for template_file in synth_result['templates']:
                template_name = template_file.name
                print(f"\n   Processing: {template_name}")
                
                try:
                    # Load the CDK template
                    with open(template_file, 'r') as f:
                        template = json.load(f)
                    
                    # Step 1: Clean CDK metadata
                    print(f"      🧹 Cleaning CDK metadata...")
                    cleaned_template = cdk_cleaner.clean_template(template)
                    
                    resource_count = len(cleaned_template.get('Resources', {}))
                    print(f"      ✅ CDK metadata removed ({resource_count} resources)")
                    
                    # Step 2: Sanitize sensitive information
                    print(f"      🔒 Sanitizing sensitive information...")
                    
                    # Convert cleaned template to JSON string for sanitization
                    cleaned_json = json.dumps(cleaned_template, indent=2)
                    
                    # Sanitize the template
                    output_file = sanitized_dir / f"cdk_{template_name}"
                    if sanitize_template_direct(cleaned_json, output_file, 'json'):
                        sanitized_list.append((str(output_file), template_name))
                        print(f"      ✅ Sanitized and saved")
                    else:
                        print(f"      ❌ Sanitization failed")
                        continue
                    
                except Exception as e:
                    print(f"      ❌ Error processing template: {str(e)}")
                    continue
            
        except Exception as e:
            print(f"   ❌ Error processing CDK app: {str(e)}")
            continue
        
        print()
    
    print(f"{'='*60}")
    print(f"CDK PROCESSING COMPLETE")
    print(f"{'='*60}")
    print(f"✅ Successfully processed {len(sanitized_list)} CDK template(s)")
    print(f"{'='*60}\n")
    
    return sanitized_list



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
    
    # Get list of changed CloudFormation and CDK files
    changed_cfn_files, changed_cdk_files = get_changed_files(base_branch, pr_number, github_token, repo_fullname, event_action, before_sha, after_sha)
    
    if not changed_cfn_files and not changed_cdk_files:
        print("No CloudFormation or CDK files changed. Exiting.")
        sys.exit(0)
    
    # Create temp directory for sanitized outputs
    sanitized_dir = Path("./sanitized_templates")
    sanitized_dir.mkdir(exist_ok=True)
    
    # Step 1: Process CDK files first (with 3-step production approach)
    cdk_sanitized_list = process_cdk_files(
        changed_cdk_files, 
        sanitized_dir,
        github_token=github_token,
        repo_fullname=repo_fullname,
        pr_number=pr_number
    )
    
    # Step 2: Validate and sanitize normal CFN templates
    cfn_sanitized_list = []
    validated_cfn_files = []
    
    if changed_cfn_files:
        print(f"\n{'='*60}")
        print("VALIDATING CLOUDFORMATION TEMPLATES")
        print(f"{'='*60}\n")
    
    for file_path in changed_cfn_files:
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
                    cfn_sanitized_list.append((str(out_path), file_path_obj.name))
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
    
    if changed_cfn_files:
        print(f"\n{'='*60}")
        print(f"CFN VALIDATION COMPLETE")
        print(f"{'='*60}")
        print(f"✅ Validated CFN templates: {len(validated_cfn_files)}")
        if validated_cfn_files:
            for f in validated_cfn_files:
                print(f"   - {f}")
        print(f"✅ Successfully sanitized CFN: {len(cfn_sanitized_list)}")
        print(f"{'='*60}\n")
    
    # Combine both CDK and CFN templates
    all_sanitized_templates = cdk_sanitized_list + cfn_sanitized_list
    
    print(f"\n{'='*60}")
    print(f"FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"✅ CDK templates: {len(cdk_sanitized_list)}")
    print(f"✅ CFN templates: {len(cfn_sanitized_list)}")
    print(f"✅ Total templates to send: {len(all_sanitized_templates)}")
    print(f"{'='*60}\n")
    
    if not all_sanitized_templates:
        print("No templates were successfully processed. Exiting.")
        sys.exit(0)
    
    # Prepare payload with all sanitized templates
    payload = {"templates": []}
    for sanitized_file, original_name in all_sanitized_templates:
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
    cost_endpoint = "https://34.66.30.124:8000/evaluate"
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
                
                # Also post Cost Guardrails comment if available
                cost_guardrails = template_output.get('Cost_Guardrails', {})
                if cost_guardrails:  # Only post if there are cost guardrails to show
                    try:
                        cost_guardrail_comment = create_cost_guardrails_comment(template_name, cost_guardrails)
                        print(f"Posting cost guardrails comment for template: {template_name}")
                        
                        cost_guardrail_payload = {"body": cost_guardrail_comment}
                        cost_guardrail_response = requests.post(comment_url, headers=headers, json=cost_guardrail_payload)
                        
                        print(f"Cost guardrails response status code: {cost_guardrail_response.status_code}")
                        if cost_guardrail_response.status_code != 201:
                            print(f"Cost guardrails response content: {cost_guardrail_response.text[:500]}...")
                        
                        cost_guardrail_response.raise_for_status()
                        print(f"Cost guardrails comment for {template_name} posted successfully!")
                        
                    except Exception as e:
                        print(f"Error posting cost guardrails comment for {template_name}: {str(e)}")
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
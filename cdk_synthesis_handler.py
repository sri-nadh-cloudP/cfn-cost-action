"""
CDK Synthesis Handler - Production-ready 3-step approach for CDK synthesis

This module handles CDK environment detection, adaptive synthesis with fallbacks,
and intelligent error classification for diverse customer CDK setups.

Three-Step Approach:
1. Detect: Understand customer's CDK environment and versions
2. Adapt: Try multiple synthesis strategies with graceful degradation
3. Communicate: Provide clear, actionable error messages when issues occur
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List


# ========================================================================
# STEP 1: ENVIRONMENT DETECTION
# ========================================================================

def detect_cdk_environment(cdk_root_path: Path) -> Dict[str, Any]:
    """
    Detect customer's CDK environment and configuration.
    
    Args:
        cdk_root_path: Path to CDK app root directory
        
    Returns:
        Dictionary with environment information including:
        - cdk_lib_version: Detected CDK library version
        - language: CDK app language (python, javascript, typescript, etc.)
        - has_package_lock: Whether package-lock.json exists
        - has_requirements_txt: Whether requirements.txt exists
        - has_cdk_json: Whether cdk.json exists
        - warnings: List of warnings during detection
        - predicted_issues: Potential issues based on environment
    """
    env_info = {
        'cdk_lib_version': None,
        'cdk_cli_version': None,
        'language': None,
        'has_package_lock': False,
        'has_requirements_txt': False,
        'has_cdk_json': False,
        'warnings': [],
        'predicted_issues': []
    }
    
    # Detect lock files
    env_info['has_package_lock'] = (cdk_root_path / 'package-lock.json').exists()
    env_info['has_requirements_txt'] = (cdk_root_path / 'requirements.txt').exists()
    env_info['has_cdk_json'] = (cdk_root_path / 'cdk.json').exists()
    
    # Detect CDK library version from configuration files
    try:
        # Try Node.js/TypeScript projects
        package_json_path = cdk_root_path / 'package.json'
        if package_json_path.exists():
            with open(package_json_path, 'r') as f:
                pkg = json.load(f)
                cdk_lib = pkg.get('dependencies', {}).get('aws-cdk-lib', '')
                if cdk_lib:
                    env_info['cdk_lib_version'] = cdk_lib
                    env_info['language'] = 'javascript'
        
        # Try Python projects
        if not env_info['cdk_lib_version'] and env_info['has_requirements_txt']:
            requirements_path = cdk_root_path / 'requirements.txt'
            with open(requirements_path, 'r') as f:
                for line in f:
                    if 'aws-cdk-lib' in line:
                        env_info['cdk_lib_version'] = line.strip()
                        env_info['language'] = 'python'
                        break
    except Exception as e:
        env_info['warnings'].append(f"Could not detect CDK version: {e}")
    
    # Predict potential issues based on environment
    if not env_info['has_package_lock'] and not env_info['has_requirements_txt']:
        env_info['predicted_issues'].append({
            'type': 'missing_lock_files',
            'severity': 'medium',
            'message': 'No lock files found - versions may not be pinned'
        })
    
    return env_info


# ========================================================================
# STEP 2: ADAPTIVE SYNTHESIS WITH FALLBACKS
# ========================================================================

def safe_cdk_synth_with_fallbacks(cdk_root_path: Path, language: str) -> Dict[str, Any]:
    """
    Attempt CDK synthesis with multiple fallback strategies.
    
    Tries synthesis with progressively more permissive flags:
    1. Standard synth (optimal)
    2. --no-lookups (for CI/CD without AWS credentials)
    3. --no-version-reporting (for compatibility)
    4. Verbose mode (to get detailed error information)
    
    Args:
        cdk_root_path: Path to CDK app root directory
        language: CDK app language
        
    Returns:
        Dictionary with synthesis results:
        - success: Whether synthesis succeeded
        - strategy_used: Which strategy worked
        - templates: List of generated template file paths
        - warnings: List of warnings
        - error: Classified error information if failed
        - attempts: List of all attempts made
    """
    strategies = [
        ('standard', ['cdk', 'synth', '--quiet']),
        ('no-lookups', ['cdk', 'synth', '--no-lookups', '--quiet']),
        ('no-version', ['cdk', 'synth', '--no-version-reporting', '--quiet']),
        ('verbose', ['cdk', 'synth'])  # Last resort - get detailed error
    ]
    
    result = {
        'success': False,
        'strategy_used': None,
        'templates': [],
        'warnings': [],
        'error': None,
        'attempts': []
    }
    
    for strategy_name, command in strategies:
        attempt_result = {
            'strategy': strategy_name,
            'success': False,
            'error': None
        }
        
        try:
            process_result = subprocess.run(
                command,
                cwd=str(cdk_root_path),
                capture_output=True,
                text=True,
                check=False,
                timeout=300  # 5 minute timeout
            )
            
            if process_result.returncode == 0:
                # Success! Find templates
                cdk_out = cdk_root_path / 'cdk.out'
                if cdk_out.exists():
                    templates = list(cdk_out.glob('*.template.json'))
                    
                    if templates:
                        result['success'] = True
                        result['strategy_used'] = strategy_name
                        result['templates'] = templates
                        
                        # Add warning if fallback was used
                        if strategy_name != 'standard':
                            result['warnings'].append(
                                f"Used '{strategy_name}' strategy (standard synth failed)"
                            )
                        
                        attempt_result['success'] = True
                        result['attempts'].append(attempt_result)
                        return result
            else:
                # Failed - store error
                error_msg = process_result.stderr
                attempt_result['error'] = error_msg[:200]  # Truncate
                
                # Check if this is a fatal error
                if _is_fatal_cdk_error(error_msg):
                    result['error'] = classify_cdk_error(error_msg, language)
                    result['attempts'].append(attempt_result)
                    return result
        
        except subprocess.TimeoutExpired:
            attempt_result['error'] = "Timeout (>5 minutes)"
        except Exception as e:
            attempt_result['error'] = str(e)
        
        result['attempts'].append(attempt_result)
    
    # All strategies failed
    last_error = result['attempts'][-1]['error'] if result['attempts'] else 'Unknown error'
    result['error'] = classify_cdk_error(last_error, language)
    
    return result


def _is_fatal_cdk_error(error_msg: str) -> bool:
    """
    Check if error is fatal (no point trying other strategies).
    
    Fatal errors include syntax errors, missing files, etc.
    """
    fatal_patterns = [
        'SyntaxError',
        'ModuleNotFoundError',
        'Cannot find module',
        'ENOENT',
        'No such file or directory',
        'cdk.json not found'
    ]
    return any(pattern in error_msg for pattern in fatal_patterns)


# ========================================================================
# STEP 3: ERROR CLASSIFICATION AND REPORTING
# ========================================================================

def classify_cdk_error(error_msg: str, language: str) -> Dict[str, Any]:
    """
    Classify CDK synthesis error and provide actionable recommendations.
    
    Args:
        error_msg: Error message from CDK synthesis
        language: CDK app language
        
    Returns:
        Dictionary with error classification:
        - type: Error category
        - message: Human-readable error description
        - technical_details: Raw error details
        - recommendations: List of suggested fixes
        - user_fixable: Whether user can fix this
    """
    if not error_msg:
        return {
            'type': 'unknown',
            'message': 'CDK synthesis failed',
            'recommendations': ['Try running "cdk synth" locally to debug'],
            'user_fixable': True
        }
    
    # Runtime compatibility issue
    if 'nodejs22.x' in error_msg or 'E3030' in error_msg:
        return {
            'type': 'runtime_compatibility',
            'message': 'Lambda runtime not supported by AWS',
            'technical_details': error_msg[:300],
            'recommendations': [
                'Add to cdk.json context: "@aws-cdk/customresources:defaultRuntime": "nodejs20.x"',
                'Or use CDK version 2.100.0 or earlier',
                'AWS Lambda will support nodejs22.x soon'
            ],
            'user_fixable': True
        }
    
    # Missing dependencies
    elif 'ModuleNotFoundError' in error_msg or 'Cannot find module' in error_msg:
        install_cmd = 'pip install -r requirements.txt' if language == 'python' else 'npm install'
        return {
            'type': 'missing_dependencies',
            'message': 'Required dependencies not installed',
            'technical_details': error_msg[:300],
            'recommendations': [
                f'Run: {install_cmd}',
                'Ensure all dependencies are listed in your config files',
                'Check that dependency versions are compatible'
            ],
            'user_fixable': True
        }
    
    # AWS credentials (expected in CI/CD)
    elif 'not authorized' in error_msg or 'AccessDenied' in error_msg:
        return {
            'type': 'aws_credentials',
            'message': 'AWS API calls failed (expected in CI/CD)',
            'technical_details': 'Used --no-lookups fallback',
            'recommendations': [
                'This is normal in CI/CD environments',
                'Ensure cdk.context.json has cached values',
                'Context values will be used instead of AWS API lookups'
            ],
            'user_fixable': False  # Not really an error
        }
    
    # Timeout
    elif 'timeout' in error_msg.lower() or 'Timeout' in error_msg:
        return {
            'type': 'timeout',
            'message': 'CDK synthesis took longer than 5 minutes',
            'technical_details': 'Synthesis timeout',
            'recommendations': [
                'Optimize CDK app (reduce complexity)',
                'Split into smaller stacks',
                'Check for infinite loops in synthesis logic'
            ],
            'user_fixable': True
        }
    
    # Generic error
    else:
        return {
            'type': 'synthesis_error',
            'message': 'CDK synthesis failed',
            'technical_details': error_msg[:300],
            'recommendations': [
                'Run "cdk synth" locally to reproduce the error',
                'Check CDK code for syntax or configuration errors',
                'Review the error message above for specific guidance'
            ],
            'user_fixable': True
        }


def create_cdk_error_pr_comment(cdk_root: str, env_info: Dict[str, Any], 
                                synth_result: Dict[str, Any]) -> str:
    """
    Create a helpful GitHub PR comment when CDK synthesis fails.
    
    Args:
        cdk_root: CDK app root directory
        env_info: Environment information from detect_cdk_environment()
        synth_result: Synthesis result from safe_cdk_synth_with_fallbacks()
        
    Returns:
        Markdown-formatted PR comment with error explanation and guidance
    """
    error = synth_result['error']
    error_type = error['type']
    
    comment = f"""## 🔧 CDK Cost Analysis - Action Required

**CDK App:** `{cdk_root}`  
**Language:** {env_info.get('language', 'Unknown')}  
**CDK Version:** {env_info.get('cdk_lib_version', 'Unknown')}  
**Status:** ⚠️ Unable to generate CloudFormation template

### Issue: {error['message']}

"""
    
    # Type-specific guidance
    if error_type == 'runtime_compatibility':
        comment += """#### Quick Fix Options:

**Option 1: Update cdk.json** (Recommended)
```json
{
  "context": {
    "@aws-cdk/customresources:defaultRuntime": "nodejs20.x"
  }
}
```

**Option 2: Use Stable CDK Version**
Update your `package.json` or `requirements.txt`:
- Node.js: `"aws-cdk-lib": "2.100.0"`
- Python: `aws-cdk-lib==2.100.0`

#### Why This Happens:
Your CDK version generates Lambda functions with nodejs22.x runtime, which AWS Lambda doesn't support yet. This affects internal Lambda functions created by CDK for:
- S3 bucket auto-delete operations
- VPC security group restrictions
- Other custom resources

"""
    
    elif error_type == 'missing_dependencies':
        comment += """#### How to Fix:

"""
        if env_info.get('language') == 'python':
            comment += """**For Python:**
```bash
pip install -r requirements.txt
```
"""
        else:
            comment += """**For Node.js/TypeScript:**
```bash
npm install
# or for CI/CD:
npm ci
```
"""
    
    elif error_type == 'timeout':
        comment += """#### Possible Causes:
- Very large CDK app with many resources
- Complex computations during synthesis
- Network issues with AWS API lookups

#### Suggestions:
1. Optimize synthesis logic
2. Ensure `cdk.context.json` is committed to cache AWS lookups
3. Consider splitting into smaller stacks
"""
    
    else:
        comment += f"""#### Error Details:
```
{error.get('technical_details', 'No details available')}
```

"""
    
    # Always include recommendations
    comment += "\n#### Recommendations:\n"
    for rec in error.get('recommendations', []):
        comment += f"- {rec}\n"
    
    # Show what we tried
    if len(synth_result['attempts']) > 1:
        comment += f"\n### 🔍 Troubleshooting Attempts\n\n"
        for attempt in synth_result['attempts']:
            status = "✅" if attempt['success'] else "❌"
            comment += f"{status} **{attempt['strategy']}**: "
            if attempt['success']:
                comment += "Success\n"
            else:
                comment += f"{attempt.get('error', 'Failed')[:80]}...\n"
    
    # Environment info
    comment += f"""

### 📋 Environment Detected
- **Language:** {env_info.get('language', 'Unknown')}
- **CDK Lib Version:** {env_info.get('cdk_lib_version', 'Not detected')}
- **Has Lock Files:** {'✅' if env_info.get('has_package_lock') or env_info.get('has_requirements_txt') else '❌'}

---

💡 **Note:** This cost analysis action doesn't modify your code. You can proceed with your PR, but cost estimates aren't available for this CDK app.

🤖 *Powered by your Cost Computation Agent*
"""
    
    return comment


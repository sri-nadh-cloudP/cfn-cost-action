import re
import yaml
from importlib import resources
from typing import Dict, List, Any, Tuple, Union, Set

# Load patterns.yaml via importlib.resources
with resources.open_text('cfn_sanitizer', 'patterns.yaml') as f:
    PATTERNS = yaml.safe_load(f)['patterns']

# Keys that should be specifically scanned for sensitive content in string values
STRING_SCAN_KEYS = {'Description', 'Name', 'Value'}

# Common parameter names that likely contain sensitive data
SENSITIVE_PARAM_NAMES = {
    'password', 'secret', 'key', 'token', 'apikey', 'accesskey', 'privatekey', 
    'pwd', 'credential', 'auth', 'passwd'
}

# Parameters names that should NOT be considered sensitive even if matched by other rules
NON_SENSITIVE_PARAM_KEYWORDS = {
    'type', 'instance', 'size', 'region', 'az', 'availability', 'zone',
    'count', 'number', 'name', 'env', 'environment', 'stage', 'class'
}

class CloudFormationSanitizer:
    """Class for sanitizing CloudFormation templates."""
    
    def __init__(self, template: Dict[str, Any]):
        """
        Initialize the sanitizer with a CloudFormation template.
        
        Args:
            template: The CloudFormation template dictionary
        """
        self.template = template
        self.report = []
        
        # Extract parameter names for reference scanning
        self.parameter_names = set()
        if 'Parameters' in template:
            self.parameter_names = set(template['Parameters'].keys())
            
        # Set of sensitive parameters (determined during pre-scan)
        self.sensitive_params = set()
        
    def _is_sensitive_parameter_name(self, param_name: str) -> bool:
        """
        Determine if a parameter name indicates sensitive content.
        Returns False for parameters that are explicitly non-sensitive.
        """
        # First check if parameter contains non-sensitive keywords
        param_lower = param_name.lower()
        
        # Strong non-sensitive indicators that should override sensitivity checks
        STRONG_NON_SENSITIVE_TERMS = {'bucket', 'domain', 'path', 'url', 'endpoint', 'address', 
                                      'name', 'file', 'region', 'zone', 'id', 'arn', 'identifier'}
        
        # If parameter name contains any strong non-sensitive terms, it's likely not sensitive
        for term in STRONG_NON_SENSITIVE_TERMS:
            if term in param_lower:
                return False
        
        # If parameter name contains any non-sensitive keywords, check carefully
        for keyword in NON_SENSITIVE_PARAM_KEYWORDS:
            if keyword in param_lower:
                # If it contains both sensitive and non-sensitive keywords,
                # check if any sensitive term appears as a standalone word
                for sensitive_term in SENSITIVE_PARAM_NAMES:
                    # Check if the sensitive term appears as a whole word
                    if re.search(r'\b' + sensitive_term + r'\b', param_lower):
                        return True
                # If no standalone sensitive terms, it's probably not sensitive
                return False
                
        # Otherwise just check for any sensitive terms
        return any(sensitive_term in param_lower for sensitive_term in SENSITIVE_PARAM_NAMES)
    
    def _is_sensitive_value(self, value: str) -> bool:
        """
        Check if a string value is likely to be sensitive.
        Returns True for values matching common sensitive patterns.
        """
        if not isinstance(value, str):
            return False
            
        # Skip short values and common non-sensitive values
        if len(value) < 8:
            return False
            
        # Skip instance types (which follow specific formats)
        if re.match(r'^[a-z]+\d+\.(?:micro|small|medium|large|[0-9]?xl|metal)', value) or \
           re.match(r'^db\.[a-z]+\d+\.(?:micro|small|medium|large|[0-9]?xl|metal)', value):
            return False
            
        # Check for specific patterns that indicate sensitivity
        for pattern_name, pattern_def in PATTERNS.items():
            if 'regex' in pattern_def and re.search(pattern_def['regex'], value):
                return True
                
        # Check for common password patterns
        if re.search(r'[A-Z].*[0-9].*[!@#$%^&*()]|[0-9].*[A-Z].*[!@#$%^&*()]', value):
            return True
            
        return False
    
    def _pre_scan_parameters(self) -> None:
        """Pre-scan parameters to identify potentially sensitive ones."""
        if 'Parameters' not in self.template:
            return
        
        # Identify sensitive parameters based on:
        # 1. Parameter name containing sensitive terms (but not non-sensitive terms)
        # 2. NoEcho attribute set to true
        # 3. Default value matching any sensitive pattern regex
        for param_name, param_def in self.template['Parameters'].items():
            # Check for NoEcho flag - strongest indicator
            if param_def.get('NoEcho', False):
                self.sensitive_params.add(param_name)
                continue
            
            # Check parameter name for sensitive terms
            if self._is_sensitive_parameter_name(param_name):
                self.sensitive_params.add(param_name)
                continue
            
            # Check if default value matches any pattern regex
            if 'Default' in param_def and isinstance(param_def['Default'], str):
                default_val = param_def['Default']
                if self._is_sensitive_value(default_val):
                    self.sensitive_params.add(param_name)
    
    def _sanitize_parameter_default(self, param_name: str, default_value: Any, path: str) -> Any:
        """
        Sanitize parameter default values based on parameter name and content.
        
        Args:
            param_name: Name of the parameter
            default_value: The default value to sanitize
            path: Path to the current node for reporting
            
        Returns:
            Sanitized default value
        """
        # Skip sanitization for non-string defaults
        if not isinstance(default_value, str):
            return default_value
        
        # Skip empty values
        if not default_value.strip():
            return default_value
            
        # Skip sanitization for parameters that aren't in the sensitive set
        if param_name not in self.sensitive_params:
            # Double-check if it's a very obvious sensitive value we might have missed
            if not self._is_sensitive_value(default_value):
                return default_value
        
        # Try to find a specific pattern that matches this default value
        for pattern_name, pattern_def in PATTERNS.items():
            if 'regex' in pattern_def:
                if re.search(pattern_def['regex'], default_value):
                    # Use pattern-specific placeholder for detected sensitive data
                    placeholder = f"SANITIZED-{pattern_name.upper()}-VALUE"
                    self.report.append({
                        "path": path,
                        "pattern": pattern_name,
                        "original": default_value
                    })
                    return placeholder
        
        # If parameter name indicates sensitivity but no specific pattern matched,
        # use generic placeholder based on parameter name
        if param_name in self.sensitive_params:
            placeholder = f"SANITIZED-PARAMETER-VALUE"
            self.report.append({
                "path": path,
                "pattern": "parameter_defaults",
                "original": default_value
            })
            return placeholder
            
        return default_value
        
    def _sanitize_property(self, key: str, value: Any, path: str, section: str) -> Any:
        """
        Sanitize a property value if it contains sensitive information.
        
        Args:
            key: Property key
            value: Property value to sanitize
            path: Path to the current node for reporting
            section: Current template section
            
        Returns:
            Sanitized property value
        """
        # Handle different value types
        if isinstance(value, str):
            # Skip sanitizing simple names or identifiers in tags
            if key == 'Value' and 'Tags' in path:
                # Skip simple resource/instance names without special characters
                if re.match(r'^[A-Za-z0-9-]+$', value) and not self._is_sensitive_value(value):
                    return value
                    
            # Check if this is a key that directly indicates sensitivity
            for pattern_name, pattern_def in PATTERNS.items():
                pattern_keys = pattern_def.get('keys', [])
                
                # Key-based matching
                if key in pattern_keys:
                    # For Value fields, only consider sensitive if complex or contains sensitive data
                    if key == 'Value' and not self._is_sensitive_value(value):
                        # Skip sanitizing simple names
                        if re.match(r'^[A-Za-z0-9-]+$', value):
                            return value
                            
                    placeholder = f"{{{{resolve:secretsmanager:{pattern_name}:SecretString:{key}}}}}"
                    self.report.append({
                        "path": path,
                        "pattern": pattern_name,
                        "original": value
                    })
                    return placeholder
                
                # Regex-based matching for content scanning in specific fields
                if 'regex' in pattern_def and key in STRING_SCAN_KEYS:
                    if re.search(pattern_def['regex'], value):
                        placeholder = f"{{{{resolve:secretsmanager:{pattern_name}:SecretString:{key}}}}}"
                        self.report.append({
                            "path": path,
                            "pattern": pattern_name,
                            "original": value
                        })
                        return placeholder
                        
                # Special case for general credential scanning in descriptions and similar fields
                if pattern_name == 'general_credentials' and 'regex' in pattern_def:
                    if key in {'Description', 'Name'} and re.search(pattern_def['regex'], value):
                        # For general text fields, just replace the credential portion
                        sanitized_value = re.sub(
                            pattern_def['regex'],
                            r'\g<0>'.replace(r'\1', "SANITIZED-CREDENTIAL"),
                            value
                        )
                        self.report.append({
                            "path": path,
                            "pattern": pattern_name,
                            "original": value
                        })
                        return sanitized_value
        
        # Handle special case: Base64 encoded UserData
        elif isinstance(value, dict):
            # Case 1: Direct Base64 encoded UserData
            if key == 'UserData' and 'Fn::Base64' in value:
                base64_content = value['Fn::Base64']
                # Case 1a: Simple string content
                if isinstance(base64_content, str):
                    for pattern_name, pattern_def in PATTERNS.items():
                        pattern_keys = pattern_def.get('keys', [])
                        if 'UserData' in pattern_keys:
                            placeholder = f"{{{{resolve:secretsmanager:{pattern_name}:SecretString:{key}}}}}"
                            result = {'Fn::Base64': placeholder}
                            self.report.append({
                                "path": path,
                                "pattern": pattern_name,
                                "original": base64_content
                            })
                            return result
                
                # Case 1b: UserData with nested intrinsic function like !Sub
                elif isinstance(base64_content, dict) and 'Fn::Sub' in base64_content:
                    sub_content = base64_content['Fn::Sub']
                    # Replace with sanitized version regardless of content
                    placeholder = f"{{{{resolve:secretsmanager:generic_secret:SecretString:{key}}}}}"
                    result = {'Fn::Base64': placeholder}
                    self.report.append({
                        "path": path,
                        "pattern": "generic_secret",
                        "original": str(base64_content)[:100] + "..." if len(str(base64_content)) > 100 else str(base64_content)
                    })
                    return result
            
            # Case 2: Direct Sub in UserData (without Base64)
            elif key == 'UserData' and 'Fn::Sub' in value:
                sub_content = value['Fn::Sub']
                placeholder = f"{{{{resolve:secretsmanager:generic_secret:SecretString:{key}}}}}"
                self.report.append({
                    "path": path,
                    "pattern": "generic_secret",
                    "original": str(sub_content)[:100] + "..." if len(str(sub_content)) > 100 else str(sub_content)
                })
                return {'Fn::Sub': placeholder}
        
        # Handle list of strings (like Passwords)
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            if key in {'Passwords'}:  # Known list-type sensitive fields
                sanitized_list = []
                for idx, item in enumerate(value):
                    item_pattern_name = None
                    # Try to find a matching pattern
                    for pattern_name, pattern_def in PATTERNS.items():
                        if 'regex' in pattern_def and re.search(pattern_def['regex'], item):
                            item_pattern_name = pattern_name
                            break
                    
                    if not item_pattern_name:
                        item_pattern_name = 'generic_secret'
                        
                    placeholder = f"SANITIZED-{item_pattern_name.upper()}-VALUE-{idx}"
                    sanitized_list.append(placeholder)
                    self.report.append({
                        "path": f"{path}[{idx}]",
                        "pattern": item_pattern_name,
                        "original": item
                    })
                return sanitized_list
                
        return value
    
    def _sanitize_node(self, node: Any, path: str = "", parent: str = "", section: str = "") -> Any:
        """
        Recursively sanitize a node in the CloudFormation template.
        
        Args:
            node: Current node to sanitize
            path: Path to the current node
            parent: Parent node key/name
            section: Current section of the template
            
        Returns:
            Sanitized node
        """
        # Determine current section if none provided
        if not section and path:
            section = path.split('.')[0] if '.' in path else path
        
        if isinstance(node, dict):
            for key, val in list(node.items()):
                loc = f"{path}.{key}" if path else key
                
                # Handle different sections differently
                if section == 'Parameters':
                    if key == 'Default' and parent in self.parameter_names:
                        node[key] = self._sanitize_parameter_default(parent, val, loc)
                elif section == 'Resources':
                    sanitized_val = self._sanitize_property(key, val, loc, section)
                    if sanitized_val is not val:  # Only update if sanitization changed something
                        node[key] = sanitized_val
                        continue
                
                # Handle special nested structures
                if key == 'LoginProfile' and isinstance(val, dict):
                    if 'Password' in val and isinstance(val['Password'], str):
                        for pattern_name, pattern_def in PATTERNS.items():
                            pattern_keys = pattern_def.get('keys', [])
                            if 'Password' in pattern_keys:
                                placeholder = f"{{{{resolve:secretsmanager:{pattern_name}:SecretString:Password}}}}"
                                val['Password'] = placeholder
                                self.report.append({
                                    "path": f"{loc}.Password",
                                    "pattern": pattern_name,
                                    "original": val['Password']
                                })
                                break
                
                # Recurse into nested structures
                if isinstance(val, dict):
                    self._sanitize_node(val, loc, parent=key, section=section)
                elif isinstance(val, list):
                    for idx, item in enumerate(val):
                        if isinstance(item, (dict, list)):
                            self._sanitize_node(item, f"{loc}[{idx}]", parent=key, section=section)
        
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                if isinstance(item, (dict, list)):
                    self._sanitize_node(item, f"{path}[{idx}]", parent=parent, section=section)
        
        return node
        
    def sanitize(self) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
        """
        Sanitize the CloudFormation template.
        
        Returns:
            Tuple containing (sanitized_template, report)
        """
        # First scan parameters to identify sensitive ones
        self._pre_scan_parameters()
        
        # Now sanitize the entire template
        sanitized = self._sanitize_node(self.template)
        
        return sanitized, self.report


def sanitize_template(template: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """
    Recursively replaces sensitive values in a CFN template dict with
    appropriate placeholders. Returns (sanitized_template, report_list).
    
    Args:
        template: CloudFormation template dictionary
        
    Returns:
        Tuple containing (sanitized_template, report)
    """
    sanitizer = CloudFormationSanitizer(template)
    return sanitizer.sanitize()



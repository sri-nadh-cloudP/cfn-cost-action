import json
import yaml
import re
from pathlib import Path
from collections import OrderedDict

# Define correct CloudFormation template section order
CFN_SECTION_ORDER = [
    'AWSTemplateFormatVersion',
    'Description',
    'Metadata',
    'Parameters',
    'Mappings',
    'Conditions',
    'Transform',
    'Resources',
    'Outputs'
]

# Define correct resource property order
RESOURCE_PROPERTY_ORDER = [
    'Type',
    'Properties'
]

# Custom string representer to handle multiline strings and special characters
def str_representer(dumper, data):
    style = None
    if '\n' in data:
        style = '|'  # Use literal style for multiline strings
    elif any(c in data for c in '{}[]#&*!|>\'"%@`'):
        style = '"'  # Use double quotes for strings with special characters
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style=style)

# Custom OrderedDict representer
def represent_ordereddict(dumper, data):
    return dumper.represent_mapping('tag:yaml.org,2002:map', data.items())

# Custom list representer to keep short lists in flow style
def list_representer(dumper, data):
    # If the list is short and only contains simple types, use flow style
    if len(data) <= 10 and all(isinstance(item, (str, int, float, bool)) for item in data):
        return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)
    return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=False)

# Custom YAML representer for CloudFormation functions
class CFNDumper(yaml.SafeDumper):
    pass

def cfn_dict_representer(dumper, data):
    """
    Handle representation of CloudFormation intrinsic functions in YAML.
    """
    if isinstance(data, dict):
        # Handle !Ref
        if len(data) == 1 and 'Ref' in data:
            return dumper.represent_scalar('!Ref', str(data['Ref']))
        
        # Handle !GetAtt
        if len(data) == 1 and 'Fn::GetAtt' in data:
            value = data['Fn::GetAtt']
            if isinstance(value, list):
                return dumper.represent_scalar('!GetAtt', '.'.join(map(str, value)))
        
        # Handle !Sub
        if len(data) == 1 and 'Fn::Sub' in data:
            return dumper.represent_scalar('!Sub', str(data['Fn::Sub']))
        
        # Handle !Base64
        if len(data) == 1 and 'Fn::Base64' in data:
            return dumper.represent_scalar('!Base64', str(data['Fn::Base64']))
        
        # Handle other intrinsic functions
        for key, value in data.items():
            if key.startswith('Fn::'):
                tag_suffix = key[4:]  # Remove the 'Fn::' prefix
                # Handle different value types
                if isinstance(value, str):
                    return dumper.represent_scalar(f'!{tag_suffix}', str(value))
                elif isinstance(value, list):
                    # For sequence nodes like !Join
                    return dumper.represent_sequence(f'!{tag_suffix}', value, flow_style=True)
    
    # Default handling for regular dictionaries
    return dumper.represent_mapping('tag:yaml.org,2002:map', data)

def organize_template(template):
    """
    Reorganize template sections and resource properties in the correct order
    """
    # Create an ordered dict based on CFN_SECTION_ORDER
    ordered_template = OrderedDict()
    
    # Clean up the Description if present
    if 'Description' in template:
        # Ensure description doesn't have special Unicode characters or explicit newlines
        description = template['Description']
        description = description.replace('\u2011', '-')  # Replace Unicode hyphens
        description = description.replace('\\n', '\n')    # Replace escaped newlines with actual ones
        template['Description'] = description
    
    # Add sections in the correct order
    for section in CFN_SECTION_ORDER:
        if section in template:
            if section == 'Resources':
                # Handle Resources section separately to order resource properties
                resources = OrderedDict()
                for res_name, res_content in template[section].items():
                    ordered_res = OrderedDict()
                    
                    # Add Type first, then Properties, then other attributes
                    for prop in RESOURCE_PROPERTY_ORDER:
                        if prop in res_content:
                            ordered_res[prop] = res_content[prop]
                    
                    # Add remaining properties
                    for k, v in res_content.items():
                        if k not in RESOURCE_PROPERTY_ORDER:
                            ordered_res[k] = v
                    
                    resources[res_name] = ordered_res
                
                ordered_template[section] = resources
            else:
                ordered_template[section] = template[section]
    
    # Add any remaining sections that might not be in our predefined order
    for section, content in template.items():
        if section not in ordered_template:
            ordered_template[section] = content
    
    return ordered_template

def format_yaml_output(yaml_str):
    """
    Format CloudFormation YAML with proper spacing and structure.
    
    This function carefully formats CloudFormation templates for best readability:
    1. Adds blank lines between top-level sections
    2. Adds blank lines between individual parameters and resources
    3. Keeps each parameter/resource block internally compact
    """
    # Clean up any existing blank lines
    lines = [line for line in yaml_str.split('\n') if line.strip() or line == '']
    
    # Define the top-level sections
    top_level_sections = [
        'AWSTemplateFormatVersion:', 
        'Description:', 
        'Parameters:', 
        'Mappings:', 
        'Conditions:', 
        'Transform:', 
        'Resources:', 
        'Outputs:', 
        'Metadata:'
    ]
    
    # Completely rebuild the output line by line with proper formatting
    output_lines = []
    current_section = None
    parameter_count = 0
    inside_block = False
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Handle top-level sections
        if any(line.strip().startswith(section) for section in top_level_sections):
            # Add blank line before top-level sections (except first)
            if output_lines and output_lines[-1] != '':
                output_lines.append('')
                
            output_lines.append(line)
            current_section = line.strip().split(':')[0]
            parameter_count = 0
            inside_block = False
            i += 1
            continue
            
        # Handle level 2 items (parameters, resources)
        if line.strip() and len(line) - len(line.lstrip()) == 2 and ':' in line:
            if parameter_count > 0 and current_section in ['Parameters', 'Resources', 'Mappings', 'Outputs']:
                # Add blank line between parameters/resources
                if output_lines[-1] != '':
                    output_lines.append('')
            
            parameter_count += 1
            inside_block = True
            output_lines.append(line)
            
            # Process the parameter block properties
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > 2):
                if lines[j].strip():  # Only add non-empty lines
                    output_lines.append(lines[j])
                j += 1
                
            i = j
            continue
            
        # Add any other lines
        if line.strip():
            output_lines.append(line)
            
        i += 1
    
    # Join lines and ensure there's a trailing newline
    result = '\n'.join(output_lines)
    if not result.endswith('\n'):
        result += '\n'
        
    return result

def save_template(path: str, template: dict, fmt: str):
    """
    Write the sanitized template back to a file, preserving JSON or YAML.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fmt == 'json':
        p.write_text(json.dumps(template, indent=2))
    else:
        # Organize template sections and properties
        organized_template = organize_template(template)
        
        # Configure the dumper to handle CloudFormation intrinsic functions and strings
        CFNDumper.add_representer(dict, cfn_dict_representer)
        CFNDumper.add_representer(OrderedDict, represent_ordereddict)
        CFNDumper.add_representer(str, str_representer)
        CFNDumper.add_representer(list, list_representer)
        
        # Disable the default string representer
        yaml.add_representer(str, str_representer, Dumper=CFNDumper)
        
        # Configure YAML dumping
        yaml_output = yaml.dump(
            organized_template, 
            default_flow_style=False,
            sort_keys=False,  # Don't sort keys to maintain order
            allow_unicode=True,  # Allow Unicode characters
            indent=2,  # Standard indentation
            width=120,  # Wider line width to avoid unnecessary wrapping
            Dumper=CFNDumper
        )
        
        # Post-process to add blank lines for better readability
        yaml_output = format_yaml_output(yaml_output)
        
        p.write_text(yaml_output)

def save_report(path: str, report: list):
    """
    Serialize the report of replaced secrets as JSON.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2))

import json
import yaml
from pathlib import Path

# Custom tag handlers for CloudFormation intrinsic functions
def cfn_tag_constructor(loader, tag_suffix, node):
    """
    Handle CloudFormation intrinsic functions like !GetAtt, !Ref, etc.
    """
    if isinstance(node, yaml.ScalarNode):
        return {f"Fn::{tag_suffix}": loader.construct_scalar(node)}
    elif isinstance(node, yaml.SequenceNode):
        return {f"Fn::{tag_suffix}": loader.construct_sequence(node)}
    elif isinstance(node, yaml.MappingNode):
        return {f"Fn::{tag_suffix}": loader.construct_mapping(node)}

def sub_constructor(loader, node):
    if isinstance(node, yaml.ScalarNode):
        return {"Fn::Sub": loader.construct_scalar(node)}
    elif isinstance(node, yaml.SequenceNode):
        return {"Fn::Sub": loader.construct_sequence(node)}
    else:
        raise yaml.constructor.ConstructorError(
            None, None,
            f"expected a scalar or sequence node for !Sub, but found {node.id}",
            node.start_mark
        )

def load_template(path: str):
    """
    Load a CloudFormation template from a .json, .yaml, or .yml file.
    Returns a tuple: (template_dict, format), where format is 'json' or 'yaml'.
    """
    p = Path(path)
    content = p.read_text()
    if p.suffix.lower() == '.json':
        return json.loads(content), 'json'
    elif p.suffix.lower() in ('.yaml', '.yml'):
        # Create a yaml loader with CloudFormation tag handling
        loader = yaml.SafeLoader
        
        # Register handlers for common CloudFormation tags
        yaml.add_multi_constructor('!', cfn_tag_constructor, Loader=loader)
        
        # Special handling for specific tags that aren't prefixed with Fn::
        yaml.add_constructor('!Ref', lambda l, n: {"Ref": l.construct_scalar(n)}, Loader=loader)
        yaml.add_constructor('!GetAtt', lambda l, n: {"Fn::GetAtt": l.construct_scalar(n).split('.')}, Loader=loader)
        yaml.add_constructor('!Sub', sub_constructor, Loader=loader)
        yaml.add_constructor('!Base64', lambda l, n: {"Fn::Base64": l.construct_scalar(n)}, Loader=loader)
        
        return yaml.load(content, Loader=loader), 'yaml'
    else:
        raise ValueError("Unsupported extension: use .json, .yaml, or .yml")

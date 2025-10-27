"""
CDK Template Cleaner - Filters CDK-specific metadata from synthesized CloudFormation templates.

This utility removes CDK-specific elements that are not needed for cost analysis:
- CDK Metadata resources
- CDK bootstrap parameters and rules
- CDK-specific conditions
- aws:cdk:path metadata from resources
"""

import json
from typing import Dict, Any, Optional
from pathlib import Path


class CDKTemplateCleaner:
    """
    Cleans CDK-synthesized CloudFormation templates by removing CDK-specific metadata.
    """
    
    # CDK-specific identifiers
    CDK_METADATA_RESOURCE_TYPE = "AWS::CDK::Metadata"
    CDK_BOOTSTRAP_PARAM = "BootstrapVersion"
    CDK_METADATA_CONDITION = "CDKMetadataAvailable"
    CDK_BOOTSTRAP_RULE = "CheckBootstrapVersion"
    CDK_PATH_METADATA_KEY = "aws:cdk:path"
    
    def __init__(self, keep_resource_metadata: bool = False):
        """
        Initialize the cleaner.
        
        Args:
            keep_resource_metadata: If True, keeps aws:cdk:path in resource metadata.
                                   If False, removes all CDK metadata from resources.
        """
        self.keep_resource_metadata = keep_resource_metadata
    
    def clean_template(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean a CDK-synthesized CloudFormation template.
        
        Args:
            template: The CDK template as a dictionary
            
        Returns:
            A cleaned CloudFormation template with CDK-specific elements removed
        """
        cleaned = {}
        
        # Copy standard CloudFormation sections
        standard_sections = [
            "AWSTemplateFormatVersion",
            "Description",
            "Metadata",
            "Parameters",
            "Mappings",
            "Conditions",
            "Transform",
            "Resources",
            "Outputs"
        ]
        
        for section in standard_sections:
            if section in template:
                cleaned[section] = self._process_section(section, template[section])
        
        # Remove empty sections
        cleaned = {k: v for k, v in cleaned.items() if v}
        
        return cleaned
    
    def _process_section(self, section_name: str, content: Any) -> Any:
        """Process each section based on its type."""
        if section_name == "Resources":
            return self._clean_resources(content)
        elif section_name == "Parameters":
            return self._clean_parameters(content)
        elif section_name == "Conditions":
            return self._clean_conditions(content)
        elif section_name == "Rules":
            # Rules section is not standard CFN, it's added by CDK
            return None
        else:
            return content
    
    def _clean_resources(self, resources: Dict[str, Any]) -> Dict[str, Any]:
        """Remove CDK metadata resources and clean individual resource metadata."""
        cleaned_resources = {}
        
        for resource_name, resource_def in resources.items():
            # Skip CDK Metadata resources
            if resource_def.get("Type") == self.CDK_METADATA_RESOURCE_TYPE:
                continue
            
            # Skip resources that reference CDKMetadata condition
            if resource_def.get("Condition") == self.CDK_METADATA_CONDITION:
                continue
            
            # Clean the resource
            cleaned_resource = resource_def.copy()
            
            # Remove or clean Metadata
            if "Metadata" in cleaned_resource and not self.keep_resource_metadata:
                metadata = cleaned_resource["Metadata"]
                # Remove aws:cdk:path
                if self.CDK_PATH_METADATA_KEY in metadata:
                    del metadata[self.CDK_PATH_METADATA_KEY]
                # Remove Metadata section if empty
                if not metadata:
                    del cleaned_resource["Metadata"]
                else:
                    cleaned_resource["Metadata"] = metadata
            
            cleaned_resources[resource_name] = cleaned_resource
        
        return cleaned_resources
    
    def _clean_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Remove CDK bootstrap parameters."""
        cleaned_params = {}
        
        for param_name, param_def in parameters.items():
            # Skip BootstrapVersion parameter
            if param_name == self.CDK_BOOTSTRAP_PARAM:
                continue
            
            # Skip parameters with [cdk:skip] in description
            if isinstance(param_def, dict):
                description = param_def.get("Description", "")
                if "[cdk:skip]" in description:
                    continue
            
            cleaned_params[param_name] = param_def
        
        return cleaned_params
    
    def _clean_conditions(self, conditions: Dict[str, Any]) -> Dict[str, Any]:
        """Remove CDK-specific conditions."""
        cleaned_conditions = {}
        
        for condition_name, condition_def in conditions.items():
            # Skip CDKMetadataAvailable condition
            if condition_name == self.CDK_METADATA_CONDITION:
                continue
            
            cleaned_conditions[condition_name] = condition_def
        
        return cleaned_conditions
    
    def is_cdk_template(self, template: Dict[str, Any]) -> bool:
        """
        Check if a template is CDK-generated.
        
        Args:
            template: The template to check
            
        Returns:
            True if the template appears to be CDK-generated
        """
        # Check for CDK metadata resource
        resources = template.get("Resources", {})
        for resource in resources.values():
            if resource.get("Type") == self.CDK_METADATA_RESOURCE_TYPE:
                return True
        
        # Check for bootstrap parameter
        parameters = template.get("Parameters", {})
        if self.CDK_BOOTSTRAP_PARAM in parameters:
            return True
        
        # Check for bootstrap rule
        rules = template.get("Rules", {})
        if self.CDK_BOOTSTRAP_RULE in rules:
            return True
        
        return False
    
    def clean_template_file(
        self,
        input_path: str,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Clean a CDK template file.
        
        Args:
            input_path: Path to the input CDK template JSON file
            output_path: Optional path to save the cleaned template.
                        If None, doesn't save to file.
            
        Returns:
            The cleaned template as a dictionary
        """
        # Load template
        with open(input_path, 'r') as f:
            template = json.load(f)
        
        # Clean template
        cleaned = self.clean_template(template)
        
        # Save if output path provided
        if output_path:
            with open(output_path, 'w') as f:
                json.dump(cleaned, f, indent=2)
        
        return cleaned


def clean_cdk_template(template: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to clean a CDK template.
    
    Args:
        template: The CDK template dictionary
        
    Returns:
        Cleaned CloudFormation template
    """
    cleaner = CDKTemplateCleaner()
    return cleaner.clean_template(template)


def clean_cdk_template_file(
    input_path: str,
    output_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to clean a CDK template from a file.
    
    Args:
        input_path: Path to the CDK template file
        output_path: Optional path to save cleaned template
        
    Returns:
        Cleaned CloudFormation template
    """
    cleaner = CDKTemplateCleaner()
    return cleaner.clean_template_file(input_path, output_path)


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python cdk_template_cleaner.py <input_template.json> [output_template.json]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    cleaner = CDKTemplateCleaner()
    
    print(f"Reading template from: {input_file}")
    template = clean_cdk_template_file(input_file, output_file)
    
    if output_file:
        print(f"Cleaned template saved to: {output_file}")
    else:
        print("\nCleaned Template:")
        print(json.dumps(template, indent=2))
    
    print(f"\nCleaned template has {len(template.get('Resources', {}))} resources")


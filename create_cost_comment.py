import re
from typing import Dict, TypedDict

class OutputState(TypedDict):
    Cost_Results: Dict[str, str]
    Service_Cost_Collector: Dict[str, str]
    Final_Infra_Cost: str
    Tag_Guardrails: dict
    Validation_Output: str

def calculate_total_infrastructure_cost(cost_data: OutputState) -> tuple:
    """Calculate the total infrastructure cost from all services"""
    total_cost = 0.0
    future_cost = 0.0
    
    # Extract total cost from Final_Infra_Cost
    final_cost = cost_data.get('Final_Infra_Cost', '').strip()
    monthly_cost_match = re.search(r'Total Monthly Cost:\s*([\d.]+)', final_cost)
    if monthly_cost_match:
        total_cost = float(monthly_cost_match.group(1))
    
    # Extract future cost if available
    future_cost_match = re.search(r'Total Future Monthly Cost :\s*([\d.]+)', final_cost)
    if future_cost_match:
        future_cost = float(future_cost_match.group(1))
        
    # If we couldn't get the total from Final_Infra_Cost, sum up service costs
    if total_cost == 0:
        for service_name, service_cost in cost_data.get('Service_Cost_Collector', {}).items():
            cost_match = re.search(r'Total Monthly Cost:\s*([\d.]+)', service_cost)
            if cost_match:
                try:
                    total_cost += float(cost_match.group(1))
                except ValueError:
                    pass
    
    return total_cost, future_cost

def create_tag_guardrails_comment(template_name: str, tag_guardrails: dict) -> str:
    """Create a GitHub comment for Tag Guardrails information"""
    
    # Check if tag_guardrails is empty or None
    if not tag_guardrails:
        return f"### 🏷️ Tag Guardrails: `{template_name}`\n\n✅ **No tag issues found!** All resources follow the required tagging standards.\n\n"
    
    # Start building the comment
    comment = f"### 🏷️ Tag Guardrails: `{template_name}`\n\n"
    
    total_issues = 0
    total_resources = 0
    
    # Count total issues and resources
    for service_name, resources in tag_guardrails.items():
        for resource_name, resource_info in resources.items():
            total_resources += 1
            total_issues += len(resource_info.get('missing_tags', []))
            total_issues += len(resource_info.get('incorrect_tags', []))
    
    # Add summary
    comment += f"**Summary:** Found {total_issues} tag issues across {total_resources} resources\n\n"
    comment += "---\n\n"
    
    # Process each service
    for service_name, resources in tag_guardrails.items():
        formatted_service_name = service_name.replace('_', ' ')
        comment += f"## {formatted_service_name}\n\n"
        
        # Process each resource in this service
        for resource_name, resource_info in resources.items():
            comment += f"### Resource: `{resource_name}`\n\n"
            
            # Missing tags section
            missing_tags = resource_info.get('missing_tags', [])
            if missing_tags:
                comment += "#### ❌ Missing Required Tags\n\n"
                for tag in missing_tags:
                    comment += f"- `{tag}`\n"
                comment += "\n"
            
            # Incorrect tags section
            incorrect_tags = resource_info.get('incorrect_tags', [])
            if incorrect_tags:
                comment += "#### ⚠️ Incorrect Tags\n\n"
                
                for i, tag_issue in enumerate(incorrect_tags, 1):
                    comment += f"**Issue #{i}:**\n\n"
                    comment += "| Field | Current | Suggested |\n"
                    comment += "|-------|---------|----------|\n"
                    comment += f"| Key | `{tag_issue.get('current_key', 'N/A')}` | `{tag_issue.get('suggested_key', 'N/A')}` |\n"
                    comment += f"| Value | `{tag_issue.get('current_value', 'N/A')}` | `{tag_issue.get('suggested_value', 'N/A')}` |\n\n"
                    
                    issue_description = tag_issue.get('issue', 'No description provided')
                    comment += f"**Issue:** {issue_description}\n\n"
            
            # Recommendations section
            recommendations = resource_info.get('recommendations', '')
            if recommendations:
                comment += "#### 💡 Recommendations\n\n"
                comment += f"{recommendations}\n\n"
            
            # Add separator between resources
            comment += "---\n\n"
    
    return comment

def create_cost_comment(template_name: str, cost_data: OutputState) -> str:
    """Create a GitHub comment with collapsible sections for cost breakdown"""
    
    # Check if validation failed
    if cost_data.get('Validation_Output', '') != 'Template validated successfully.':
        return f"""### ❌ CloudFormation Cost Estimation Failed: `{template_name}`

<details>
<summary><b>Validation Output</b></summary>

```
{cost_data.get('Validation_Output', 'No validation output available')}
```
</details>
"""
    
    # Calculate total infrastructure cost
    total_cost, future_cost = calculate_total_infrastructure_cost(cost_data)
    
    # Start building the comment with header
    comment = f"### 💰 CloudFormation Cost Estimation: `{template_name}`\n\n"
    
    # Add a prominent total cost section (left-aligned)
    comment += "# Total Infrastructure Cost\n\n"
    
    # Make total monthly cost clear but smaller than the main heading
    comment += f"### Total Monthly Cost: ${total_cost:.2f}\n\n"
    
    # Add future cost if available
    if future_cost > 0:
        comment += f"### Future Monthly Cost: ${future_cost:.2f}\n\n"
    
    comment += "---\n\n"
    
    # Add a summary section with service costs
    comment += "## Service Cost Summary\n\n"
    
    # Process each service from Service_Cost_Collector
    for service_name, service_cost_info in cost_data.get('Service_Cost_Collector', {}).items():
        formatted_service_name = service_name.replace('_', ' ')
        
        # Display service name as a header
        comment += f"### {formatted_service_name}\n\n"
        
        # Display the full service cost info in a markdown code block
        comment += "```\n" + service_cost_info.strip() + "\n```\n\n"
        
        # If we have detailed calculations in Cost_Results, add them in a dropdown
        if service_name in cost_data.get('Cost_Results', {}):
            detailed_cost = cost_data['Cost_Results'][service_name]
            comment += "<details>\n<summary><b>Detailed Calculation Steps</b></summary>\n\n"
            
            # Extract individual resource costs and create nested dropdowns
            resource_sections = re.split(r'\nIndividual Resource Costs:', detailed_cost)
            
            # Process the first section
            if resource_sections and resource_sections[0].strip():
                main_section = resource_sections[0].strip()
                if "ResourceType:" in main_section:
                    comment += f"```\n{main_section}\n```\n\n"
            
            # Process additional resource sections
            for i, section in enumerate(resource_sections):
                if i == 0:  # Skip the first section (already processed)
                    continue
                    
                # Format this resource section
                section = "Individual Resource Costs:" + section
                
                # Extract resource type
                resource_type_match = re.search(r'ResourceType:\s*([^\n]+)', section)
                if resource_type_match:
                    resource_type = resource_type_match.group(1).strip()
                    
                    # Create nested dropdown for this resource
                    comment += f"<details>\n<summary><b>{resource_type}</b></summary>\n\n"
                    comment += f"```\n{section.strip()}\n```\n\n"
                    comment += "</details>\n\n"
            
            comment += "</details>\n\n"
    
    return comment 
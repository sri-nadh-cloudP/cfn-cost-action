import re
from typing import Dict, TypedDict

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
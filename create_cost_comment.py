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
    
    # Add the total infrastructure cost
    comment += f"**Total Monthly Cost: ${total_cost:.2f}"
    if future_cost > 0:
        comment += f" (Future: ${future_cost:.2f})"
    comment += "**\n\n"
    
    # Add a summary table of service costs
    comment += "| AWS Service | Monthly Cost |\n|------------|-------------|\n"
    
    for service_name, service_cost in cost_data.get('Service_Cost_Collector', {}).items():
        total_cost = extract_total_cost(service_cost)
        formatted_service_name = service_name.replace('_', ' ')
        comment += f"| {formatted_service_name} | ${total_cost} |\n"
    
    comment += "\n"
    
    # Add collapsible details for each service
    for service_name, detailed_cost in cost_data.get('Cost_Results', {}).items():
        formatted_service_name = service_name.replace('_', ' ')
        
        comment += f"<details>\n<summary><b>{formatted_service_name} Cost Details</b></summary>\n\n"
        
        # Extract individual resource costs and create nested collapsible sections
        resource_sections = re.split(r'\nIndividual Resource Costs:', detailed_cost)
        
        # Process the first section (usually service overview)
        if resource_sections and resource_sections[0].strip():
            main_section = resource_sections[0].strip()
            if "ResourceType:" in main_section:
                # This is already a resource section
                resource_type_match = re.search(r'ResourceType:\s*([^\n]+)', main_section)
                if resource_type_match:
                    resource_type = resource_type_match.group(1).strip()
                    comment += f"```\n{main_section}\n```\n\n"
        
        # Process additional resource sections as nested dropdowns
        for i, section in enumerate(resource_sections):
            if i == 0:  # Skip the first one as we already processed it
                continue
                
            section = "Individual Resource Costs:" + section
            
            # Extract resource type
            resource_type_match = re.search(r'ResourceType:\s*([^\n]+)', section)
            if resource_type_match:
                resource_type = resource_type_match.group(1).strip()
                
                # Create nested collapsible for individual resource
                comment += f"<details>\n<summary><b>{resource_type}</b></summary>\n\n"
                comment += f"```\n{section.strip()}\n```\n\n"
                comment += "</details>\n\n"
        
        comment += "</details>\n\n"
    
    return comment 
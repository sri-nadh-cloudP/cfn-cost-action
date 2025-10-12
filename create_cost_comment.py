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
        return f"## Tag Guardrails Summary : `{template_name}`\n\n✅ **No tag issues found!** All resources follow the required tagging standards.\n\n"
    
    # Helper function to check if recommendation is positive (no action required)
    def is_positive_recommendation(recommendations: str) -> bool:
        if not recommendations:
            return False
        recommendations_lower = recommendations.lower()
        return 'no action' in recommendations_lower or 'no actions' in recommendations_lower
    
    # Start building the comment
    comment = f"## Tag Guardrails Summary : `{template_name}`\n\n"
    
    total_issues = 0
    total_resources = 0
    affected_services_set = set()
    
    # Count total issues, resources, and collect affected services (excluding positive recommendations)
    for service_name, resources in tag_guardrails.items():
        service_has_violations = False
        for resource_name, resource_info in resources.items():
            recommendations = resource_info.get('recommendations', '')
            
            # Skip resources with positive recommendations (no action required)
            if is_positive_recommendation(recommendations):
                continue
            
            # Count this resource as it has actual violations
            total_resources += 1
            service_has_violations = True
            total_issues += len(resource_info.get('missing_tags', []))
            total_issues += len(resource_info.get('incorrect_tags', []))
        
        # Only add service if it has at least one resource with violations
        if service_has_violations:
            affected_services_set.add(service_name.replace('_', ' '))
    
    # Convert set to sorted list for consistent display
    affected_services = sorted(list(affected_services_set))
    
    # Add new summary format
    comment += f"#### Tag Violations Found: {total_issues}\n"
    comment += f"#### Services Affected: {', '.join(affected_services) if affected_services else 'None'}\n"
    comment += f"#### Resources Affected: {total_resources}\n"
    comment += "---\n\n"
    
    # Add new heading for service breakdown
    comment += "### Tag Violation Summary by Service\n\n"
    
    # Process each service
    for service_name, resources in tag_guardrails.items():
        formatted_service_name = service_name.replace('_', ' ')
        
        # Collect resources with actual violations for this service
        resources_with_violations = []
        for resource_name, resource_info in resources.items():
            recommendations = resource_info.get('recommendations', '')
            # Skip resources with positive recommendations
            if not is_positive_recommendation(recommendations):
                resources_with_violations.append((resource_name, resource_info))
        
        # Only display service section if it has resources with violations
        if not resources_with_violations:
            continue
        
        comment += f"### {formatted_service_name}\n\n"
        
        # Process each resource with violations in this service
        for resource_name, resource_info in resources_with_violations:
            comment += f"#### Resource: `{resource_name}`\n\n"
            
            # Recommendations section (displayed directly)
            recommendations = resource_info.get('recommendations', '')
            if recommendations:
                comment += "**Recommendations:** " + recommendations + "\n\n"
            
            # Check if there are any tag issues to show in dropdown
            missing_tags = resource_info.get('missing_tags', [])
            incorrect_tags = resource_info.get('incorrect_tags', [])
            
            if missing_tags or incorrect_tags:
                comment += "<details>\n<summary><b>Detailed Tag Analysis</b></summary>\n\n"
                
                # Missing tags section
                if missing_tags:
                    comment += "#### ❌ Missing Required Tags\n\n"
                    for tag in missing_tags:
                        comment += f"- `{tag}`\n"
                    comment += "\n"
                
                # Incorrect tags section
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
                
                comment += "</details>\n\n"
            
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
    
    # Collect list of services
    services_list = []
    for service_name in cost_data.get('Service_Cost_Collector', {}).keys():
        services_list.append(service_name.replace('_', ' '))
    # Also add services from Cost_Results that might not be in Service_Cost_Collector
    for service_name in cost_data.get('Cost_Results', {}).keys():
        formatted_name = service_name.replace('_', ' ')
        if formatted_name not in services_list:
            services_list.append(formatted_name)
    
    # Start building the comment with header
    comment = f"## Cost Summary of : `{template_name}`\n\n"
    
    # Add projected monthly cost and metadata
    comment += f"### Projected Monthly Cost : ${total_cost:.2f}\n"
    comment += f"#### IAC Language: CloudFormation\n"
    comment += f"#### Services Included : {', '.join(services_list)}\n"
    comment += f"#### Cloud Provider : AWS\n\n"
    
    comment += "---\n\n"
    
    # Add a summary section with service costs
    comment += "### Cost Summary by Service\n\n"
    
    # Create table header
    comment += "| # | Service Name | Projected Monthly Cost |\n"
    comment += "|---|--------------|------------------------|\n"
    
    # Track which Cost_Results entries we've already displayed
    displayed_cost_results = set()
    service_counter = 1
    
    # Collect all services data first
    services_data = []
    
    # Process each service from Service_Cost_Collector
    for service_name, service_cost_info in cost_data.get('Service_Cost_Collector', {}).items():
        formatted_service_name = service_name.replace('_', ' ')
        
        # Extract the monthly cost from service_cost_info
        cost_match = re.search(r'Total Monthly Cost:\s*\$?([\d,]+\.?\d*)', service_cost_info)
        monthly_cost = cost_match.group(1) if cost_match else "N/A"
        
        # Get detailed calculations if available
        detailed_cost = cost_data.get('Cost_Results', {}).get(service_name, None)
        if detailed_cost:
            displayed_cost_results.add(service_name)
        
        services_data.append({
            'name': formatted_service_name,
            'cost': monthly_cost,
            'summary': service_cost_info,
            'detailed': detailed_cost,
            'service_key': service_name
        })
    
    # Process any Cost_Results entries that weren't in Service_Cost_Collector
    for service_name, detailed_cost in cost_data.get('Cost_Results', {}).items():
        if service_name not in displayed_cost_results:
            formatted_service_name = service_name.replace('_', ' ')
            
            # Try to extract cost from detailed_cost
            summary_match = re.search(r'TOTAL MONTHLY COST:\s*\$?([\d,]+\.?\d*)', detailed_cost, re.IGNORECASE)
            monthly_cost = summary_match.group(1) if summary_match else "N/A"
            
            services_data.append({
                'name': formatted_service_name,
                'cost': monthly_cost,
                'summary': None,  # No summary from Service_Cost_Collector
                'detailed': detailed_cost,
                'service_key': service_name
            })
    
    # Build table rows (simple table without complex HTML in cells)
    for service_data in services_data:
        comment += f"| {service_counter} | {service_data['name']} | ${service_data['cost']} |\n"
        service_counter += 1
    
    comment += "\n"
    
    # Now add the detailed sections below the table
    service_counter = 1
    for service_data in services_data:
        comment += f"<details id=\"service-{service_counter}\">\n"
        comment += f"<summary><b>Service {service_counter}: {service_data['name']} - </b><code>📊 Show Details</code></summary>\n\n"
        
        # Add detailed calculations if available
        if service_data['detailed']:
            # Check if the detailed cost has the "Individual Resource Costs:" pattern
            if '\nIndividual Resource Costs:' in service_data['detailed']:
                # Extract individual resource costs and create nested dropdowns
                resource_sections = re.split(r'\nIndividual Resource Costs:', service_data['detailed'])
                
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
                    
                    # Extract resource type/name
                    resource_type_match = re.search(r'ResourceType:\s*([^\n]+)', section)
                    if resource_type_match:
                        resource_type = resource_type_match.group(1).strip()
                        
                        # Create nested dropdown for this resource with resource type as heading
                        comment += f"<details>\n<summary><b>{resource_type}</b></summary>\n\n"
                        comment += f"```\n{section.strip()}\n```\n\n"
                        comment += "</details>\n\n"
            else:
                # No "Individual Resource Costs:" pattern - display the entire detailed cost as-is
                comment += f"```\n{service_data['detailed'].strip()}\n```\n\n"
        elif service_data['summary']:
            # If only summary is available (no detailed), show just the cost from summary
            comment += "```\n" + service_data['summary'].strip() + "\n```\n\n"
        
        comment += "</details>\n\n"
        service_counter += 1
    
    return comment 
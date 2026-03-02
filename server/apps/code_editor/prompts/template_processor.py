"""
Template Processor for Prompt Templates.
Handles variable substitution in prompt strings using {{variable}} syntax.
"""

import re
import json
from typing import Dict, Any, Optional
from apps.code_editor.tools.descriptions import format_all_tools_markdown
from apps.code_editor.prompts.context_builder import PromptContext


def get_nested_value(data: Dict[str, Any], path: str, default: str = "") -> Any:
    """
    Get a nested value from a dict using dot notation.
    
    Args:
        data: Dictionary to search
        path: Dot-separated path (e.g., "system_info.os")
        default: Default value if path not found
        
    Returns:
        Value at path or default
    """
    keys = path.split(".")
    current = data
    
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    
    return current if current is not None else default


def process_template(
    template: str,
    context: PromptContext,
) -> str:
    """
    Process a template string with variable substitution.
    
    Supported variables:
    - {{system_info.os}} - Operating system
    - {{system_info.shell}} - Default shell
    - {{system_info.workspace}} - Workspace directory
    - {{system_info.home}} - Home directory
    - {{tools}} - Formatted tool definitions section (markdown)
    - {{tools_json}} - Tool definitions as JSON array (for GLM-style templates)
    - {{project_info.name}} - Project name
    - {{project_info.root}} - Project root path
    - {{project_info.structure}} - Overview of project folder structure
    - {{context_usage.usedPromptTokens}} - Tokens used in current context
    - {{context_usage.contextWindow}} - Total context window size
    - {{context_usage.fillPercent}} - Percentage of context window used
    - {{token_stats.totalTokens}} - Total tokens used in session
    - {{token_stats.promptTokens}} - Total prompt tokens in session
    - {{token_stats.completionTokens}} - Total completion tokens in session
    - {{token_stats.byFamily.<family>.totalTokens}} - Tokens by model family
    
    Args:
        template: Template string with {{variable}} placeholders
        context: PromptContext with available data
        
    Returns:
        Processed string with variables substituted
    """
    result = template
    
    # Handle {{tools_json}} variable - JSON array of tool definitions (for GLM-style templates)
    if "{{tools_json}}" in result:
        # Serialize tools to JSON, excluding the 'formatted' field
        tools_json_list = []
        for tool_def in context.available_tools:
            tool_json = {
                "name": tool_def.get("name", ""),
                "description": tool_def.get("description", ""),
                "parameters": tool_def.get("parameters", {}),
            }
            tools_json_list.append(tool_json)
        tools_json_str = json.dumps(tools_json_list, ensure_ascii=False, indent=2)
        result = result.replace("{{tools_json}}", tools_json_str)
    
    # Handle {{tools}} variable - special case for formatted tool definitions
    if "{{tools}}" in result:
        tools_markdown = format_all_tools_markdown(context.available_tools)
        result = result.replace("{{tools}}", tools_markdown)
    
    # Handle {{system_info.*}} variables
    system_info_pattern = r'\{\{system_info\.([\w]+)\}\}'
    matches = re.finditer(system_info_pattern, result)
    for match in reversed(list(matches)):  # Reverse to preserve indices
        var_path = f"system_info.{match.group(1)}"
        value = get_nested_value({"system_info": context.system_info}, var_path, "")
        result = result[:match.start()] + str(value) + result[match.end():]
    
    # Handle {{project_info.*}} variables
    if context.project_info:
        project_info_pattern = r'\{\{project_info\.([\w]+)\}\}'
        matches = re.finditer(project_info_pattern, result)
        for match in reversed(list(matches)):
            var_path = f"project_info.{match.group(1)}"
            value = get_nested_value({"project_info": context.project_info}, var_path, "")
            result = result[:match.start()] + str(value) + result[match.end():]
    else:
        # Remove project_info variables if no project info available
        project_info_pattern = r'\{\{project_info\.[\w]+\}\}'
        result = re.sub(project_info_pattern, "", result)
    
    # Handle {{user_context_summary}} variable
    if "{{user_context_summary}}" in result:
        summary = context.user_context_summary or "No user context provided."
        result = result.replace("{{user_context_summary}}", summary)
    
    # Handle {{context_usage.*}} variables for context window usage
    if context.context_usage:
        context_usage_dict = context.context_usage.to_dict()
        context_usage_pattern = r'\{\{context_usage\.([\w]+)\}\}'
        matches = re.finditer(context_usage_pattern, result)
        for match in reversed(list(matches)):
            var_name = match.group(1)
            value = context_usage_dict.get(var_name, "")
            result = result[:match.start()] + str(value) + result[match.end():]
    else:
        # Remove context_usage variables if not available
        context_usage_pattern = r'\{\{context_usage\.[\w]+\}\}'
        result = re.sub(context_usage_pattern, "", result)
    
    # Handle {{token_stats.*}} variables for session token usage
    if context.token_stats:
        token_stats_dict = context.token_stats.to_dict()
        # Handle simple token_stats variables like {{token_stats.totalTokens}}
        token_stats_pattern = r'\{\{token_stats\.([\w]+)\}\}'
        matches = re.finditer(token_stats_pattern, result)
        for match in reversed(list(matches)):
            var_name = match.group(1)
            value = token_stats_dict.get(var_name, "")
            result = result[:match.start()] + str(value) + result[match.end():]
        
        # Handle nested byFamily variables like {{token_stats.byFamily.claude.totalTokens}}
        by_family_pattern = r'\{\{token_stats\.byFamily\.(\w+)\.(\w+)\}\}'
        matches = re.finditer(by_family_pattern, result)
        for match in reversed(list(matches)):
            family = match.group(1)
            var_name = match.group(2)
            family_stats = token_stats_dict.get("byFamily", {}).get(family, {})
            value = family_stats.get(var_name, "0")
            result = result[:match.start()] + str(value) + result[match.end():]
    else:
        # Remove token_stats variables if not available
        token_stats_pattern = r'\{\{token_stats\.[\w.]+\}\}'
        result = re.sub(token_stats_pattern, "", result)
    
    # Handle simple conditionals: {% if variable %}...{% endif %}
    # Supports: {% if project_info.isMultiRoot %}...{% endif %}
    conditional_pattern = r'\{%\s*if\s+([\w.]+)\s*%\}(.*?)\{%\s*endif\s*%\}'
    matches = list(re.finditer(conditional_pattern, result, re.DOTALL))
    for match in reversed(matches):  # Process in reverse to preserve indices
        var_path = match.group(1)
        conditional_content = match.group(2)
        
        # Evaluate the condition
        if var_path.startswith("project_info."):
            value = get_nested_value({"project_info": context.project_info or {}}, var_path, False)
        elif var_path.startswith("system_info."):
            value = get_nested_value({"system_info": context.system_info}, var_path, False)
        elif var_path.startswith("context_usage."):
            if context.context_usage:
                value = get_nested_value(
                    {"context_usage": context.context_usage.to_dict()}, var_path, False
                )
            else:
                value = False
        else:
            value = False
        
        # Replace conditional block with content if true, empty string if false
        if value:
            result = result[:match.start()] + conditional_content + result[match.end():]
        else:
            result = result[:match.start()] + result[match.end():]
    
    # Clean up any remaining {{variable}} that weren't matched (leave as-is for debugging)
    # This allows prompts to have variables that aren't yet supported without breaking
    
    return result


def validate_template(template: str) -> tuple[bool, list[str]]:
    """
    Validate a template string for common issues.
    
    Args:
        template: Template string to validate
        
    Returns:
        Tuple of (is_valid, list_of_warnings)
    """
    warnings = []
    
    # Check for unmatched braces
    open_braces = template.count("{{")
    close_braces = template.count("}}")
    if open_braces != close_braces:
        warnings.append(f"Mismatched braces: {open_braces} opening, {close_braces} closing")
    
    # Check for common variable patterns
    variable_pattern = r'\{\{([^}]+)\}\}'
    matches = re.findall(variable_pattern, template)
    
    valid_prefixes = ["system_info.", "project_info.", "tools", "tools_json", "user_context_summary", "context_usage.", "token_stats."]
    for match in matches:
        if not any(match.startswith(prefix) for prefix in valid_prefixes):
            warnings.append(f"Unknown variable pattern: {{{{match}}}}")
    
    return len(warnings) == 0, warnings

"""
Tool Description Generator.
Generates detailed tool descriptions for prompts from tool implementations.
"""

from typing import Dict, Any, List, Optional
import inspect
from pathlib import Path

from apps.code_editor.tools.registry import get_tool_registry, SYSTEM_TOOLS
from apps.code_editor.tools.executor import ToolExecutor


# Tool descriptions extracted from executor and docstrings
TOOL_DESCRIPTIONS: Dict[str, Dict[str, Any]] = {
    "read_file": {
        "description": "Reads a file from the local filesystem. Returns structured JSON with: content (file text, possibly chunked for large files), totalLines (total line count), sizeBytes, truncated (boolean), and strategy ('full' or 'head_middle_tail'). For large files exceeding the threshold, content is automatically chunked showing head, middle, and tail sections with truncation markers. You can optionally specify offset and limit for explicit line ranges. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.",
        "parameters": {
            "target_file": {
                "type": "string",
                "required": True,
                "description": "The path of the file to read. You can use either a relative path in the workspace or an absolute path.",
            },
            "offset": {
                "type": "integer",
                "required": False,
                "description": "The line number to start reading from (0-based). Only provide if you need a specific range.",
            },
            "limit": {
                "type": "integer",
                "required": False,
                "description": "The number of lines to read. Only provide if you need a specific range.",
            },
        },
    },
    "write_file": {
        "description": "Writes a file to the local filesystem. This tool will overwrite the existing file if there is one at the provided path. If this is an existing file, you MUST use the read_file tool first to read the file's contents. ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.",
        "parameters": {
            "file_path": {
                "type": "string",
                "required": True,
                "description": "The path to the file to modify. Always specify the target file as the first argument. You can use either a relative path in the workspace or an absolute path.",
            },
            "contents": {
                "type": "string",
                "required": True,
                "description": "The contents of the file to write.",
            },
        },
    },
    "search_code": {
        "description": "Search for code using ripgrep. A powerful search tool built on ripgrep. Prefer grep for exact symbol/string searches. Whenever possible, use this instead of terminal grep/rg. This tool is faster and respects .gitignore/.cursorignore. Supports full regex syntax, e.g. \"log.*Error\", \"function\\s+\\w+\". Ensure you escape special chars to get exact matches, e.g. \"functionCall(\". Avoid overly broad glob patterns (e.g., '--glob *') as they bypass .gitignore rules and may be slow.",
        "parameters": {
            "query": {
                "type": "string",
                "required": True,
                "description": "The regular expression pattern to search for in file contents.",
            },
            "path": {
                "type": "string",
                "required": False,
                "description": "File or directory to search in. Defaults to workspace root.",
            },
            "type": {
                "type": "string",
                "required": False,
                "description": "File type to search (e.g., js, py, ts). More efficient than glob for standard file types.",
            },
            "glob": {
                "type": "string",
                "required": False,
                "description": "Glob pattern to filter files (e.g., \"*.js\", \"*.{ts,tsx}\").",
            },
            "-i": {
                "type": "boolean",
                "required": False,
                "description": "Case insensitive search. Defaults to false.",
            },
        },
    },
    "list_dir": {
        "description": "Lists files and directories in a given path. The result does not display dot-files and dot-directories by default.",
        "parameters": {
            "target_directory": {
                "type": "string",
                "required": True,
                "description": "Path to directory to list contents of.",
            },
            "ignore_globs": {
                "type": "array",
                "items": {"type": "string"},
                "required": False,
                "description": "Array of glob patterns to ignore. All patterns match anywhere in the target directory.",
            },
        },
    },
    "run_command": {
        "description": "PROPOSE a command to run on behalf of the user. If you have this tool, note that you DO have the ability to run commands directly on the USER's system. Note that the user may have to approve the command before it is executed. The user may reject it if it is not to their liking, or may modify the command before approving it. If they do change it, take those changes into account. In using these tools, adhere to the following guidelines: 1. Based on the contents of the conversation, you will be told if you are in the same shell as a previous step or a different shell. 2. If in a new shell, you should `cd` to the appropriate directory and do necessary setup in addition to running the command. By default, the shell will initialize in the project root. 3. If in the same shell, LOOK IN CHAT HISTORY for your current working directory. 4. For ANY commands that would require user interaction, ASSUME THE USER IS NOT AVAILABLE TO INTERACT and PASS THE NON-INTERACTIVE FLAGS (e.g. --yes for npx). 5. If the command would use a pager, append ` | cat` to the command. 6. For commands that are long running/expected to run indefinitely until interruption, please run them in the background. To run jobs in the background, set is_background to true rather than changing the details of the command. 7. Don't include any newlines in the command.",
        "parameters": {
            "command": {
                "type": "string",
                "required": True,
                "description": "The terminal command to execute.",
            },
            "is_background": {
                "type": "boolean",
                "required": False,
                "description": "Whether the command should be run in the background. Defaults to false.",
            },
        },
    },
    "create_file": {
        "description": "Create a new file with optional content. This is an alias for write_file when creating new files.",
        "parameters": {
            "path": {
                "type": "string",
                "required": True,
                "description": "The path of the file to create.",
            },
            "content": {
                "type": "string",
                "required": False,
                "description": "The contents of the file. If not provided, creates an empty file.",
            },
        },
    },
    "delete_file": {
        "description": "Deletes a file at the specified path. The operation will fail gracefully if: The file doesn't exist, The operation is rejected for security reasons, The file cannot be deleted.",
        "parameters": {
            "target_file": {
                "type": "string",
                "required": True,
                "description": "The path of the file to delete, relative to the workspace root.",
            },
        },
    },
    "file_exists": {
        "description": "Check if a file or directory exists and get metadata about it.",
        "parameters": {
            "path": {
                "type": "string",
                "required": True,
                "description": "The path to check.",
            },
        },
    },
    "search_replace": {
        "description": "Performs exact string replacements in files. When editing text, ensure you preserve the exact indentation (tabs/spaces) as it appears before. ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required. The edit will FAIL if old_string is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use replace_all to change every instance of old_string.",
        "parameters": {
            "file_path": {
                "type": "string",
                "required": True,
                "description": "The path to the file to modify.",
            },
            "old_string": {
                "type": "string",
                "required": True,
                "description": "The text to replace.",
            },
            "new_string": {
                "type": "string",
                "required": True,
                "description": "The text to replace it with (must be different from old_string).",
            },
            "replace_all": {
                "type": "boolean",
                "required": False,
                "description": "Replace all occurrences of old_string (default false).",
            },
        },
    },
    "todo_write": {
        "description": "Update todos in a plan file's frontmatter. This tool updates the todos section in a .plan.md file created by create_plan. It can merge with existing todos (updating by id) or replace them entirely. Use this to track progress on plan implementation tasks.",
        "parameters": {
            "plan_file_path": {
                "type": "string",
                "required": True,
                "description": "Absolute or relative path to the .plan.md file to update. Can also use 'path' as an alias.",
            },
            "path": {
                "type": "string",
                "required": False,
                "description": "Alias for plan_file_path. If plan_file_path is not provided, this will be used.",
            },
            "merge": {
                "type": "boolean",
                "required": True,
                "description": "Whether to merge the todos with the existing todos. If true, todos will be merged into existing todos based on the id field (updating existing ones, adding new ones). If false, all existing todos will be replaced with the provided todos.",
            },
            "todos": {
                "type": "array",
                "items": {"type": "object"},
                "required": True,
                "description": "Array of todo items to write to the plan file. Each todo item must have: id (required, unique identifier), content (optional, description of task), status (required: pending, in_progress, completed, cancelled).",
            },
        },
    },
    "semantic_search": {
        "description": "Perform semantic code search using vector embeddings. This tool searches the codebase using natural language queries to find semantically similar code chunks. It uses the project's code index (built from apps.code_editor.embeddings) to find code that matches the meaning of your query, not just exact text matches. This is particularly useful for finding code patterns, understanding how features are implemented, or locating related functionality across the codebase. The search results include file paths, line numbers, code previews, and relevance scores. The tool automatically uses the current project (resolved from the project root path). If no matching registered project is found, a helpful error message will be returned listing available projects.",
        "parameters": {
            "query": {
                "type": "string",
                "required": True,
                "description": "Natural language query describing what code you're looking for. Examples: 'where is user authentication handled?', 'how are API errors handled?', 'find database connection code'.",
            },
            "limit": {
                "type": "integer",
                "required": False,
                "description": "Maximum number of results to return. Defaults to 10.",
            },
            "folder_ids": {
                "type": "array",
                "items": {"type": "string"},
                "required": False,
                "description": "Optional list of folder IDs to limit the search scope to specific directories.",
            },
            "embedding_model_id": {
                "type": "string",
                "required": False,
                "description": "Optional embedding model ID to use. If not provided, uses the project's default embedding model.",
            },
            "hf_token": {
                "type": "string",
                "required": False,
                "description": "Optional HuggingFace token for accessing gated embedding models.",
            },
        },
    },
    "create_plan": {
        "description": "Use this tool to create a concise plan for accomplishing the user's request. This tool should be called at the end of the planning phase to finalize and store the plan. The plan you create should be properly formatted in markdown, using appropriate sections and headers. The plan should be very concise and actionable, providing the minimum amount of detail for the user to understand and action the plan. It may be helpful to identify the most important files you will change, and existing code you will leverage. Cite specific file paths and essential snippets of code. IMPORTANT: Do NOT use markdown tables in plan content (they cannot be rendered for the user); use bullet lists instead. The first line MUST BE A TITLE for the plan formatted as a level 1 markdown heading.",
        "parameters": {
            "name": {
                "type": "string",
                "required": True,
                "description": "A short 3-4 word name for the plan. Used for the filename.",
            },
            "overview": {
                "type": "string",
                "required": True,
                "description": "A 1-2 sentence high-level description of the plan that summarizes what will be accomplished.",
            },
            "plan": {
                "type": "string",
                "required": True,
                "description": "A detailed, concrete plan for accomplishing the user's request. Must be valid markdown with title as level 1 heading.",
            },
            "todos": {
                "type": "array",
                "items": {"type": "object"},
                "required": False,
                "description": "Array of implementation todos. Each todo has: id (unique identifier), content (description of task).",
            },
        },
    },
    "ask_question": {
        "description": "Collect structured multiple-choice answers from the user. Provide one or more questions with options, and set allow_multiple when multi-select is appropriate. Use this tool when you need to gather specific information from the user through a structured question format. Each question should have: A unique id (used to match answers), A clear prompt/question text, At least 2 options for the user to choose from, An optional allow_multiple flag (defaults to false for single-select).",
        "parameters": {
            "title": {
                "type": "string",
                "required": False,
                "description": "Optional title for the questions form.",
            },
            "questions": {
                "type": "array",
                "items": {"type": "object"},
                "required": True,
                "description": "Array of questions to present to the user. Each question has: id (unique identifier), prompt (question text), options (array of {id, label} choices), allow_multiple (optional boolean, defaults to false).",
            },
        },
    },
    "delegate_task": {
        "description": "Delegate a research or information-finding task to a specialized sub-agent to save your context window, the more you delegate, more you will live longer. Use this when you need to find specific code, understand how something works, or gather information that may require multiple file reads and searches. The sub-agent will investigate autonomously and return only the final answer, keeping your main context clean. Best for: finding where code is located, understanding implementations, gathering context before making changes. The sub-agent has access to read_file, search_code, list_dir, and semantic_search tools.",
        "parameters": {
            "task": {
                "type": "string",
                "required": True,
                "description": "A detailed description of what information to find or research. Be specific about what you need to know.",
            },
            "purpose": {
                "type": "string",
                "required": False,
                "description": "Brief context about why you need this information (helps sub-agent focus).",
            },
        },
    },
}


def format_tool_description(tool_name: str, tool_def: Dict[str, Any]) -> str:
    """
    Format a tool definition as markdown for inclusion in prompts.
    
    Args:
        tool_name: Name of the tool
        tool_def: Tool definition dict with description and parameters
        
    Returns:
        Formatted markdown string
    """
    lines = [f"## {tool_name}"]
    lines.append(f"**Description**: {tool_def['description']}")
    lines.append("")
    lines.append("**Parameters:**")
    
    params = tool_def.get("parameters", {})
    for param_name, param_info in params.items():
        required = param_info.get("required", False)
        param_type = param_info.get("type", "unknown")
        description = param_info.get("description", "")
        required_marker = "(required)" if required else "(optional)"
        lines.append(f"- {param_name}: {required_marker} {description} (type: {param_type})")
    
    return "\n".join(lines)


def get_tool_definitions_for_mode(
    mode: str,
    set_id: str = "default",
    family: str = "default",
    version: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get tool definitions for a specific mode.
    
    Args:
        mode: Mode name
        set_id: Prompt set ID
        family: Model family
        version: Optional model version
        
    Returns:
        List of tool definition dicts with name, description, and formatted markdown
    """
    tool_registry = get_tool_registry()
    tool_names = tool_registry.get_tools_for_mode(mode, set_id, family, version)
    
    tool_definitions = []
    
    for tool_name in tool_names:
        if tool_name in TOOL_DESCRIPTIONS:
            # System tool - use built-in description
            tool_def = TOOL_DESCRIPTIONS[tool_name].copy()
            tool_def["name"] = tool_name
            tool_def["formatted"] = format_tool_description(tool_name, tool_def)
            tool_definitions.append(tool_def)
        else:
            # Custom tool - try to load TOOL_DESCRIPTOR from module
            tool_def = _load_custom_tool_descriptor(
                tool_name, mode, set_id, family, version
            )
            tool_definitions.append(tool_def)
    
    return tool_definitions


def _load_custom_tool_descriptor(
    tool_name: str,
    mode: str,
    set_id: str,
    family: str,
    version: Optional[str],
) -> Dict[str, Any]:
    """
    Load TOOL_DESCRIPTOR from a custom tool module.
    
    Custom tools should define a TOOL_DESCRIPTOR dict with:
    - description: str - Tool description
    - parameters: Dict[str, Dict] - Parameter definitions
    
    Example:
        TOOL_DESCRIPTOR = {
            "description": "My custom tool that does something useful",
            "parameters": {
                "input": {
                    "type": "string",
                    "required": True,
                    "description": "The input to process",
                },
            },
        }
    
    Args:
        tool_name: Name of the tool
        mode: Mode name (kept for compatibility, but tools are family-level)
        set_id: Prompt set ID
        family: Model family
        version: Optional model version
        
    Returns:
        Tool definition dict with name, description, parameters, and formatted markdown
    """
    tool_registry = get_tool_registry()
    
    try:
        # Tools are stored at family level (shared across modes)
        # Mode parameter is kept for backward compatibility with load_tool_module signature
        tool_module = tool_registry.load_tool_module(
            tool_name, mode, set_id, family, version
        )
        
        if tool_module and hasattr(tool_module, "TOOL_DESCRIPTOR"):
            descriptor = tool_module.TOOL_DESCRIPTOR
            
            if isinstance(descriptor, dict):
                description = descriptor.get("description", f"Custom tool: {tool_name}")
                parameters = descriptor.get("parameters", {})
                
                tool_def = {
                    "name": tool_name,
                    "description": description,
                    "parameters": parameters,
                }
                tool_def["formatted"] = format_tool_description(tool_name, tool_def)
                return tool_def
        
        # Module exists but no TOOL_DESCRIPTOR - log warning
        print(f"Warning: Custom tool '{tool_name}' is missing TOOL_DESCRIPTOR. "
              f"Add TOOL_DESCRIPTOR dict to provide description and parameters.")
        
    except Exception as e:
        print(f"Warning: Failed to load descriptor for custom tool '{tool_name}': {e}")
    
    # Fallback: basic definition with warning indicator
    fallback_def = {
        "name": tool_name,
        "description": f"Custom tool: {tool_name} (No TOOL_DESCRIPTOR provided - add one for better documentation)",
        "parameters": {},
    }
    fallback_def["formatted"] = format_tool_description(tool_name, fallback_def)
    return fallback_def


def convert_tools_to_openai_format(
    tool_definitions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert tool definitions to OpenAI/LiteLLM tools format.

    Args:
        tool_definitions: List of {name, description, parameters} dicts

    Returns:
        List of {"type": "function", "function": {...}} for LiteLLM
    """
    result: List[Dict[str, Any]] = []
    for tool_def in tool_definitions:
        name = tool_def.get("name", "")
        if not name:
            continue
        description = tool_def.get("description", "")
        params = tool_def.get("parameters", {})

        properties: Dict[str, Any] = {}
        required: List[str] = []
        for param_name, param_info in params.items():
            if not isinstance(param_info, dict):
                continue
            ptype = param_info.get("type", "string")
            prop: Dict[str, Any] = {
                "type": ptype,
                "description": param_info.get("description", ""),
            }
            # Gemini/Vertex require array params to have "items"; copy through for API compliance
            if ptype == "array" and "items" in param_info:
                prop["items"] = param_info["items"]
            properties[param_name] = prop
            if param_info.get("required", False):
                required.append(param_name)

        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        result.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema,
            },
        })
    return result


def format_all_tools_markdown(tool_definitions: List[Dict[str, Any]]) -> str:
    """
    Format all tool definitions as a single markdown section.
    
    Args:
        tool_definitions: List of tool definition dicts
        
    Returns:
        Formatted markdown string with all tools
    """
    if not tool_definitions:
        return "No tools available."
    
    sections = []
    for tool_def in tool_definitions:
        formatted = tool_def.get("formatted")
        if formatted:
            sections.append(formatted)
        else:
            # Fallback formatting
            name = tool_def.get("name", "unknown")
            desc = tool_def.get("description", "")
            sections.append(f"## {name}\n**Description**: {desc}")
        sections.append("")  # Empty line between tools
    
    return "\n".join(sections).strip()

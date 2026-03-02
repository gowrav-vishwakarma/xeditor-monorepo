"""Parser for GLM agent mode responses.

This parser supports:
- GLM XML-format tool calls: <tool_call>{function-name}<arg_key>k</arg_key><arg_value>v</arg_value>...</tool_call>
- <think>...</think> internal reasoning
"""

import re
import json
from typing import Dict, Any, Optional, Tuple
from apps.code_editor.parsers.base import ResponseParser, ParsedResponse


class GLMParser(ResponseParser):
    """
    Parser for GLM agent mode responses.
    
    Handles tool calls in the format:
    <tool_call>{function-name}<arg_key>{arg-key-1}</arg_key><arg_value>{arg-value-1}</arg_value>...</tool_call>
    
    Example:
    <tool_call>read_file<arg_key>target_file</arg_key><arg_value>path/to/file.vue</arg_value></tool_call>
    """
    
    family = "glm"
    
    # Patterns for GLM XML format
    THINK_PATTERN = re.compile(r'<think>([\s\S]*?)</think>', re.IGNORECASE)
    TOOL_CALL_PATTERN = re.compile(
        r'<tool_call>([\s\S]*?)</tool_call>',
        re.IGNORECASE
    )
    # Pattern to detect potential tool call start (for buffering)
    # Matches both complete <tool_call> and partial patterns like <tool_call, <tool_c, <tool_
    # This catches partial tool calls early to prevent them from appearing in UI
    # Similar to how GPT parser detects `<|` early
    # Pattern matches: <tool_ (which catches <tool_call, <tool_c, <tool_)
    TOOL_CALL_START = re.compile(r'<tool_', re.IGNORECASE)
    
    def _extract_tool_call(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Extract tool call from GLM XML format.
        
        Args:
            content: Content that may contain a tool call
            
        Returns:
            Dict with 'tool' and 'args' keys, or None if no valid tool call found
        """
        match = self.TOOL_CALL_PATTERN.search(content)
        if not match:
            return None
        
        tool_call_content = match.group(1)
        
        # Extract tool name (text before first <arg_key>)
        arg_key_match = re.search(r'<arg_key>', tool_call_content, re.IGNORECASE)
        if arg_key_match:
            tool_name = tool_call_content[:arg_key_match.start()].strip()
        else:
            # No args, just tool name
            tool_name = tool_call_content.strip()
        
        if not tool_name:
            return None
        
        # Extract arguments: <arg_key>k</arg_key><arg_value>v</arg_value>
        args: Dict[str, Any] = {}
        arg_pattern = re.compile(
            r'<arg_key>([\s\S]*?)</arg_key>\s*<arg_value>([\s\S]*?)</arg_value>',
            re.IGNORECASE
        )
        
        for arg_match in arg_pattern.finditer(tool_call_content):
            key = arg_match.group(1).strip()
            value = arg_match.group(2).strip()
            
            # Try to parse JSON values (arrays, objects, booleans, numbers)
            # If it fails, use as string
            parsed_value = value
            if value:
                # Check if it looks like JSON (starts with {, [, ", or is a number/boolean)
                if value.startswith(('{', '[', '"', "'")) or value.lower() in ('true', 'false', 'null'):
                    try:
                        parsed_value = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        # Not valid JSON, use as string
                        parsed_value = value
                elif value.replace('.', '', 1).replace('-', '', 1).isdigit():
                    # Try to parse as number
                    try:
                        if '.' in value:
                            parsed_value = float(value)
                        else:
                            parsed_value = int(value)
                    except ValueError:
                        parsed_value = value
            
            args[key] = parsed_value
        
        # Normalize tool arguments to match executor expectations
        normalized_args = self._normalize_tool_args(tool_name, args)
        
        return {
            "tool": tool_name,
            "args": normalized_args,
        }
    
    def _normalize_path(self, path: str) -> str:
        """
        Normalize a file path by removing @ prefix and cleaning up.
        
        Args:
            path: Path string that may have @ prefix or other issues
            
        Returns:
            Normalized path string
        """
        if not path:
            return path
        
        # Remove @ prefix if present (common in some path aliases)
        if path.startswith('@'):
            path = path[1:]
        
        # Remove leading/trailing whitespace
        path = path.strip()
        
        return path
    
    def _normalize_tool_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize tool arguments to match what the executor expects.
        
        Maps parameter names from tool descriptions to executor parameter names,
        and normalizes paths.
        
        Args:
            tool_name: Name of the tool
            args: Raw arguments from parsed XML
            
        Returns:
            Normalized arguments dict
        """
        normalized = args.copy()
        
        # Parameter name mappings: description_name -> executor_name
        param_mappings = {
            "read_file": {
                "target_file": "path",
            },
            "write_file": {
                "file_path": "path",
                "contents": "content",
            },
            "delete_file": {
                "target_file": "path",
            },
            "list_dir": {
                "target_directory": "path",
            },
            "search_replace": {
                "file_path": "path",
            },
        }
        
        # Apply parameter name mappings
        if tool_name in param_mappings:
            for desc_name, exec_name in param_mappings[tool_name].items():
                if desc_name in normalized:
                    normalized[exec_name] = normalized.pop(desc_name)
        
        # Normalize path parameters
        path_params = ["path", "target_file", "file_path", "target_directory"]
        for param in path_params:
            if param in normalized and isinstance(normalized[param], str):
                normalized[param] = self._normalize_path(normalized[param])
        
        return normalized
    
    def get_streamable_content(self, content: str) -> Tuple[str, bool]:
        """
        Determine what content is safe to stream vs what should be held in buffer.
        
        This method detects if content contains a potential GLM tool call pattern.
        If we detect a potential tool call start (like `<tool_call>` or partial `<tool_call`), 
        we hold everything from that point forward until we can confirm it's a complete tool call or not.
        
        Args:
            content: Accumulated content from streaming
            
        Returns:
            Tuple of (safe_to_stream, is_tool_pending):
            - safe_to_stream: Content that's definitely safe to stream (no partial XML)
            - is_tool_pending: True if we're potentially in a tool call pattern and should hold content
        """
        # Check if we have a complete tool call - if so, everything before it is safe
        tool_call_match = self.TOOL_CALL_PATTERN.search(content)
        if tool_call_match:
            # Complete tool call detected - everything before it is safe
            safe_end = tool_call_match.start()
            return content[:safe_end], True
        
        # Check if we have a potential tool call start (`<tool_call>`, `<tool_call`, `<tool_c`, or `<tool_`)
        # This catches both complete tags and partial tags during streaming
        # We detect early (at `<tool_` or `<tool_c`) to prevent partial tool calls from appearing in UI
        # If found, hold everything from that point forward
        tool_call_start_match = self.TOOL_CALL_START.search(content)
        if tool_call_start_match:
            # Potential tool call detected - hold everything from this point
            # This prevents "<tool_call", "<tool_c", etc. from appearing in the UI
            safe_end = tool_call_start_match.start()
            return content[:safe_end], True
        
        # No tool call patterns detected - all content is safe to stream
        return content, False
    
    def _remove_complete_tool_calls(self, content: str) -> str:
        """
        Remove complete GLM tool calls from content.
        This is only called after we've confirmed a tool call exists.
        
        Args:
            content: Content that may contain complete GLM tool calls
            
        Returns:
            Content with complete tool calls removed
        """
        result = self.TOOL_CALL_PATTERN.sub('', content)
        
        # Safety: Also remove any incomplete tool call patterns that might have leaked through
        # This handles cases where partial <tool_call...> tags weren't caught by streaming
        # Check if there's an incomplete tool call (has opening tag but no closing tag)
        # Use the same early detection pattern as streaming (<tool_)
        content_lower = result.lower()
        if '<tool_' in content_lower:
            # Count opening and closing tags
            opening_count = len(re.findall(r'<tool_call', content_lower))
            closing_count = len(re.findall(r'</tool_call>', content_lower))
            
            # If we have more opening tags than closing tags, or if we see <tool_ but no complete tag
            # Remove everything from the last <tool_ pattern onward
            if opening_count > closing_count or (opening_count == 0 and '<tool_' in content_lower):
                # Find the last <tool_ pattern and remove everything from there
                # This catches partial patterns like <tool_c, <tool_call, etc.
                last_tool_pattern_match = self.TOOL_CALL_START.search(result)
                if last_tool_pattern_match:
                    # Find all matches and use the last one
                    all_matches = list(self.TOOL_CALL_START.finditer(result))
                    if all_matches:
                        last_match = all_matches[-1]
                        # Check if this has a matching closing tag
                        remaining_content = result[last_match.end():]
                        if '</tool_call>' not in remaining_content.lower():
                            result = result[:last_match.start()]
        
        return result
    
    def parse(self, content: str) -> ParsedResponse:
        """Parse GLM XML format response."""
        # Extract thinking/reasoning
        thinking: Optional[str] = None
        think_match = self.THINK_PATTERN.search(content)
        if think_match:
            thinking = think_match.group(1).strip()
        
        # Extract tool call from GLM XML format
        tool_call: Optional[Dict[str, Any]] = None
        tool_call_data = self._extract_tool_call(content)
        if tool_call_data:
            tool_call = tool_call_data
        
        # Remove complete tool calls from final_text (they're handled separately)
        # Only remove complete tool calls - partial tokens are handled by get_streamable_content()
        final_text = self._remove_complete_tool_calls(content)
        # Also remove thinking tags (internal, shouldn't be displayed)
        final_text = self.strip_tags(final_text)
        
        result = ParsedResponse(
            thinking=thinking,
            tool_call=tool_call,
            final_text=final_text,
        )
        
        return result
    
    def strip_tags(self, content: str) -> str:
        """
        Strip internal tags that shouldn't be displayed to users.
        Only removes <think> tags - these are internal and shouldn't be shown.
        """
        # Only remove thinking tags (internal, shouldn't be displayed)
        result = self.THINK_PATTERN.sub('', content)
        return result
    
    def serialize_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> str:
        """
        Serialize a tool call into GLM XML format for chat context.
        
        Format:
        <tool_call>{tool_name}<arg_key>{k}</arg_key><arg_value>{v}</arg_value>...</tool_call>
        Tool Result: {result}
        """
        # Build the tool call XML
        args_xml = ""
        for key, value in args.items():
            # Convert value to string, handling complex types
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value)
            else:
                value_str = str(value)
            args_xml += f"<arg_key>{key}</arg_key><arg_value>{value_str}</arg_value>"
        
        tool_call_str = f"<tool_call>{tool_name}{args_xml}</tool_call>"
        
        if error:
            out = f"{tool_call_str}\nTool Error: {error}"
        elif result is not None:
            result_str = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            out = f"{tool_call_str}\nTool Result: {result_str}"
        else:
            out = tool_call_str
        if tool_call_id:
            out = f"[{tool_call_id}] {out}"
        return out


parser = GLMParser()

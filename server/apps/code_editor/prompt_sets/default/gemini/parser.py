"""Parser for GPT ask mode responses.

This parser supports:
- Harmony-format tool calls
- <think>...</think> internal reasoning
- <patch file="...">...</patch> blocks for code suggestions (rendered to markdown + extracted)
"""

import re
import json
from typing import Dict, Any, Optional, List, Tuple
from apps.code_editor.parsers.base import ResponseParser, ParsedResponse


class AskModeParser(ResponseParser):
    """
    Parser for GPT ask mode responses.
    
    Handles thinking tags, patch suggestions, and Harmony-format tool calls.
    Tool calls are restricted by the mode's tool allowlist.
    """
    
    
    # Harmony format patterns
    THINK_PATTERN = re.compile(r'<think>([\s\S]*?)</think>', re.IGNORECASE)
    PATCH_PATTERN = re.compile(
        r'<patch(?:\s+file="(?P<file>[^"]+)")?\s*>(?P<body>[\s\S]*?)</patch>',
        re.IGNORECASE,
    )
    # Pattern to find the start of a Harmony tool call
    # Matches any channel type (commentary, analysis, etc.) followed by 'to=' and tool name
    HARMONY_TOOL_CALL_START = re.compile(
        r'<\|channel\|>[\w_]+\s+to=(?:functions\.)?([\w_]+)\s+<\|constrain\|>json<\|message\|>',
        re.IGNORECASE
    )
    
    # Pattern to detect potential Harmony token start (for buffering)
    # Matches `<|` which is the start of any Harmony token
    HARMONY_TOKEN_START = re.compile(r'<\|', re.IGNORECASE)
    
    def _extract_json_object(self, text: str, start_pos: int) -> Optional[str]:
        """
        Extract a JSON object starting at start_pos, handling nested braces.
        Skips optional whitespace before the opening brace.
        
        Args:
            text: The text to search in
            start_pos: Position after <|message|> where JSON should start
            
        Returns:
            JSON string (including any leading whitespace) or None if not found
        """
        if start_pos >= len(text):
            return None
        
        # Skip whitespace to find the opening brace
        json_start = start_pos
        while json_start < len(text) and text[json_start].isspace():
            json_start += 1
        
        # Check if we found an opening brace
        if json_start >= len(text) or text[json_start] != '{':
            return None
        
        brace_count = 0
        i = json_start
        
        while i < len(text):
            char = text[i]
            
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    # Found matching closing brace
                    # Return from original start_pos to include any leading whitespace
                    # This ensures _remove_complete_tool_calls removes the entire sequence
                    return text[start_pos:i+1]
            
            i += 1
        
        # No matching closing brace found
        # If we started an object (brace_count > 0), return what we have to support truncation handling
        if brace_count > 0:
            return text[start_pos:]
            
        return None
    
    def _clean_json(self, json_str: str) -> str:
        """
        Clean JSON string by replacing curly quotes with straight quotes.
        
        Args:
            json_str: JSON string that may contain curly quotes
            
        Returns:
            Cleaned JSON string with straight quotes
        """
        # Replace curly quotes with straight quotes
        # Using unicode escape sequences to ensure proper matching
        replacements = {
            '\u201c': '"',  # Left double quote
            '\u201d': '"',  # Right double quote
            '\u2018': "'",  # Left single quote
            '\u2019': "'",  # Right single quote
        }
        
        cleaned = json_str
        for curly, straight in replacements.items():
            cleaned = cleaned.replace(curly, straight)
        
        return cleaned
    
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
            args: Raw arguments from parsed JSON
            
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
    
    def _extract_patches(self, content: str) -> List[Dict[str, Any]]:
        """
        Extract <patch>...</patch> blocks (code suggestions in Ask mode).

        Returns:
            List of patch dicts in the original order they appear, including raw text
            so debug can replay exactly what the LLM returned.

            Shape:
            {
              "file": str,
              "content": str,   # inner body (no surrounding <patch> tags)
              "raw": str,       # full <patch ...>...</patch> block as returned
              "start": int,     # start offset in the assistant message
              "end": int,       # end offset (exclusive)
            }
        """
        patches: List[Dict[str, Any]] = []
        for m in self.PATCH_PATTERN.finditer(content):
            file_path = (m.group("file") or "").strip()
            body = (m.group("body") or "").strip("\n")
            raw = m.group(0)
            patches.append({
                "file": file_path,
                "content": body,
                "raw": raw,
                "start": m.start(),
                "end": m.end(),
            })
        return patches

    def _has_incomplete_patches(self, content: str) -> bool:
        """
        Check if there are incomplete patch blocks (opening tag without closing tag).
        This helps during streaming to avoid converting incomplete patches prematurely.
        
        Returns:
            True if there are incomplete patches, False otherwise
        """
        # Find all opening <patch> tags
        opening_pattern = re.compile(r'<patch(?:\s+file="[^"]+")?\s*>', re.IGNORECASE)
        closing_pattern = re.compile(r'</patch>', re.IGNORECASE)
        
        opening_matches = list(opening_pattern.finditer(content))
        closing_matches = list(closing_pattern.finditer(content))
        
        # If we have more opening tags than closing tags, there are incomplete patches
        return len(opening_matches) > len(closing_matches)
    
    def _render_patch_tags_to_markdown(self, content: str) -> str:
        """
        Replace <patch>...</patch> blocks with markdown ```diff fences for display.
        Only converts complete patches (those that match the regex pattern).
        Incomplete patches are left as-is.
        """
        def _repl(m: re.Match[str]) -> str:
            file_path = (m.group("file") or "").strip()
            body = (m.group("body") or "").strip("\n")
            header = f"Diff: {file_path}\n" if file_path else ""
            # Always render as a diff code fence for syntax highlighting / UI hooks
            return f"\n```diff\n{header}{body}\n```\n"

        return self.PATCH_PATTERN.sub(_repl, content)
    
    def get_streamable_content(self, content: str) -> Tuple[str, bool]:
        """
        Determine what content is safe to stream vs what should be held in buffer.
        
        This method detects if content contains a potential Harmony tool call pattern.
        If we detect a potential tool call start (like `<|`), we hold everything
        from that point forward until we can confirm it's a tool call or not.
        
        Args:
            content: Accumulated content from streaming
            
        Returns:
            Tuple of (safe_to_stream, is_tool_pending):
            - safe_to_stream: Content that's definitely safe to stream (no partial Harmony tokens)
            - is_tool_pending: True if we're potentially in a tool call pattern and should hold content
        """
        # Check if we have a complete tool call - if so, everything before it is safe
        harmony_match = self.HARMONY_TOOL_CALL_START.search(content)
        if harmony_match:
            # We have a complete tool call pattern - check if JSON is complete too
            message_end_pos = harmony_match.end()
            json_str = self._extract_json_object(content, message_end_pos)
            if json_str:
                # Complete tool call detected - everything before it is safe
                safe_end = harmony_match.start()
                return content[:safe_end], True
        
        # Check if we have a potential Harmony token start (`<|`)
        # If found, hold everything from that point forward
        harmony_start_match = self.HARMONY_TOKEN_START.search(content)
        if harmony_start_match:
            # Potential Harmony token detected - hold everything from this point
            safe_end = harmony_start_match.start()
            return content[:safe_end], True
        
        # No Harmony patterns detected - all content is safe to stream
        return content, False
    
    def _remove_complete_tool_calls(self, content: str) -> str:
        """
        Remove complete Harmony tool calls from content.
        This is only called after we've confirmed a tool call exists.
        Unlike the old _strip_harmony_tokens, this only removes complete tool calls,
        not partial tokens or patterns.
        
        Args:
            content: Content that may contain complete Harmony tool calls
            
        Returns:
            Content with complete tool calls removed
        """
        result = content
        
        # Find and remove complete Harmony tool calls (including JSON)
        harmony_matches = list(self.HARMONY_TOOL_CALL_START.finditer(result))
        for match in reversed(harmony_matches):  # Process in reverse to maintain positions
            start_pos = match.end()
            # Try to extract and remove the JSON object that follows
            json_str = self._extract_json_object(result, start_pos)
            if json_str:
                # Remove the entire tool call including JSON
                full_match_end = start_pos + len(json_str)
                result = result[:match.start()] + result[full_match_end:]
        
        return result
    
    def parse(self, content: str) -> ParsedResponse:
        """Parse Ask mode response."""
        patches = self._extract_patches(content)

        # Extract thinking/reasoning
        thinking: Optional[str] = None
        think_match = self.THINK_PATTERN.search(content)
        if think_match:
            thinking = think_match.group(1).strip()
        
        # Extract tool call from Harmony format
        tool_call: Optional[Dict[str, Any]] = None
        harmony_match = self.HARMONY_TOOL_CALL_START.search(content)
        
        if harmony_match:
            tool_name = harmony_match.group(1).strip()
            # Find the position after <|message|>
            message_end_pos = harmony_match.end()
            
            # Extract JSON object starting from message_end_pos
            json_str = self._extract_json_object(content, message_end_pos)
            
            if json_str:
                try:
                    # Clean JSON string (handle curly quotes)
                    cleaned_json = self._clean_json(json_str)
                    
                    # Parse JSON arguments
                    args = None
                    try:
                        args = json.loads(cleaned_json)
                    except json.JSONDecodeError:
                        # Attempt repair for truncated JSON by appending closing braces
                        for i in range(1, 4):  # Try adding up to 3 braces
                            try:
                                args = json.loads(cleaned_json + "}" * i)
                                break
                            except json.JSONDecodeError:
                                pass
                        
                        # If still failed, raise the error to be caught below
                        if args is None:
                            raise
                    
                    if isinstance(args, dict):
                        # Normalize tool arguments (map parameter names, clean paths)
                        normalized_args = self._normalize_tool_args(tool_name, args)
                        
                        tool_call = {
                            "tool": tool_name,
                            "args": normalized_args,
                        }
                except json.JSONDecodeError as e:
                    # If JSON parsing fails, log but don't fail completely
                    # The tool_call will remain None
                    print(f"Warning: Failed to parse JSON in Harmony tool call: {e}")
                    print(f"JSON string: {json_str[:200]}...")
        
        # Remove complete tool calls from final_text (they're handled separately)
        # Only remove complete tool calls - partial tokens are handled by get_streamable_content()
        final_text = self._remove_complete_tool_calls(content)
        # Also remove thinking tags (internal, shouldn't be displayed)
        final_text = self.strip_tags(final_text)

        # Render patch tags into markdown diff fences for display (keeps message readable)
        # Only convert complete patches - incomplete patches during streaming are left as-is
        # This prevents incomplete patches from appearing as raw text in the UI
        if "<patch" in final_text.lower():
            # Check if there are incomplete patches - if so, don't convert yet
            # This handles streaming scenarios where patch blocks arrive incrementally
            if not self._has_incomplete_patches(final_text):
                # All patches are complete, safe to convert to markdown
                final_text = self._render_patch_tags_to_markdown(final_text)
            # If there are incomplete patches, leave them as-is until they're complete
        
        result = ParsedResponse(
            thinking=thinking,
            tool_call=tool_call,
            patches=patches or None,
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
        Serialize a tool call into Harmony format for chat context.
        
        Format:
        <|channel|>commentary to={tool_name} <|constrain|>json<|message|>{args_json}
        Tool Result: {result}
        """
        args_json = json.dumps(args)
        tool_call_str = f"<|channel|>commentary to={tool_name} <|constrain|>json<|message|>{args_json}"
        
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


parser = AskModeParser()

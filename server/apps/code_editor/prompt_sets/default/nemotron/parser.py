"""Parser for Nvidia Nemotron 3 Nano agent mode responses.

This parser supports:
- Nemotron-format tool calls (<tool_call>/<function=...>/<parameter=...>)
- <think>...</think> internal reasoning
- <patch file="...">...</patch> blocks for diff preview (rendered to markdown + extracted)
"""

import re
import json
import os
from typing import Dict, Any, Optional, List, Tuple
from apps.code_editor.parsers.base import ResponseParser, ParsedResponse


class NemotronParser(ResponseParser):
    """
    Parser for Nvidia Nemotron 3 Nano agent mode responses.
    
    Handles tool calls in the format:
    <tool_call>
    <function=tool_name>
    <parameter=param1>value1</parameter>
    <parameter=param2>value2</parameter>
    </function>
    </tool_call>
    
    Example:
    <tool_call>
    <function=search_code>
    <parameter=query>theme</parameter>
    </function>
    </tool_call>
    """
    
    # Nemotron format patterns
    THINK_PATTERN = re.compile(r'<think>([\s\S]*?)</think>', re.IGNORECASE)
    PATCH_PATTERN = re.compile(
        r'<patch(?:\s+file="(?P<file>[^"]+)")?\s*>(?P<body>[\s\S]*?)</patch>',
        re.IGNORECASE,
    )
    # Pattern to find complete tool_call blocks
    TOOL_CALL_PATTERN = re.compile(
        r'<tool_call>([\s\S]*?)</tool_call>',
        re.IGNORECASE
    )
    # Pattern to find function tag within tool_call
    FUNCTION_PATTERN = re.compile(
        r'<function=([\w_]+)>([\s\S]*?)</function>',
        re.IGNORECASE
    )
    # Pattern to find parameter tags within function
    PARAMETER_PATTERN = re.compile(
        r'<parameter=([\w_]+)>([\s\S]*?)</parameter>',
        re.IGNORECASE
    )
    # Pattern to detect potential tool call start (for buffering)
    # Matches `<tool` which is the start of `<tool_call>` or `<tool` fragment
    TOOL_START_PATTERN = re.compile(r'<tool', re.IGNORECASE)
    
    def _coerce_parameter_value(self, value: str) -> Any:
        """
        Coerce parameter value to appropriate type.
        
        Conservative coercion:
        - If value looks like JSON object/array, try parsing as JSON
        - If value is a scalar token (true/false/null or number), coerce to appropriate type
        - Otherwise keep as string (preserving inner whitespace, only trimming outer)
        
        Args:
            value: Raw parameter value string
            
        Returns:
            Coerced value (bool, None, int, float, dict, list, or str)
        """
        # Trim outer whitespace but preserve inner structure
        trimmed = value.strip()
        
        if not trimmed:
            return ""
        
        # Try JSON parsing for objects/arrays
        if trimmed.startswith('{') or trimmed.startswith('['):
            try:
                return json.loads(trimmed)
            except json.JSONDecodeError:
                # Not valid JSON, keep as string
                pass
        
        # Try boolean/null literals (case-insensitive)
        lower = trimmed.lower()
        if lower == 'true':
            return True
        elif lower == 'false':
            return False
        elif lower == 'null':
            return None
        
        # Try numeric parsing
        try:
            # Try int first
            if '.' not in trimmed and 'e' not in lower and 'E' not in trimmed:
                return int(trimmed)
            # Then float
            return float(trimmed)
        except ValueError:
            # Not a number, keep as string
            pass
        
        # Return trimmed string (outer whitespace removed, inner structure preserved)
        return trimmed
    
    def _extract_tool_call(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Extract tool call from Nemotron format.
        
        Args:
            content: Content that may contain tool calls
            
        Returns:
            Dict with 'tool' and 'args' keys, or None if no valid tool call found
        """
        tool_call_match = self.TOOL_CALL_PATTERN.search(content)
        
        if not tool_call_match:
            return None
        
        tool_call_body = tool_call_match.group(1)
        
        # Extract function name
        function_match = self.FUNCTION_PATTERN.search(tool_call_body)
        
        if not function_match:
            return None
        
        tool_name = function_match.group(1).strip()
        function_body = function_match.group(2)
        
        # Extract parameters
        args: Dict[str, Any] = {}
        param_matches = list(self.PARAMETER_PATTERN.finditer(function_body))
        
        for param_match in param_matches:
            param_name = param_match.group(1).strip()
            param_value_raw = param_match.group(2)
            
            # Coerce parameter value
            param_value = self._coerce_parameter_value(param_value_raw)
            args[param_name] = param_value
        
        if not tool_name:
            return None
        
        return {
            "tool": tool_name,
            "args": args,
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
            args: Raw arguments from parsed tool call
            
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
        Extract <patch>...</patch> blocks.

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
    
    def _normalize_code_block_spacing(self, content: str) -> str:
        """
        Normalize spacing around markdown code blocks to ensure proper rendering.
        
        Ensures that triple backticks (```) are always preceded by a newline.
        
        Args:
            content: Text content that may have code blocks with missing newlines
            
        Returns:
            Content with normalized code block spacing
        """
        # Pattern to match triple backticks that are not preceded by a newline
        # Matches: any non-newline character followed by triple backticks (optionally with language tag)
        # This ensures we only fix cases where newlines are missing
        pattern = re.compile(r'([^\n])```([a-z]*)?', re.IGNORECASE)
        
        def _repl(m: re.Match[str]) -> str:
            preceding_char = m.group(1)
            language_tag = m.group(2) or ""
            # Preserve the preceding character and add newline before code block
            return f"{preceding_char}\n```{language_tag}"
        
        return pattern.sub(_repl, content)
    
    def get_streamable_content(self, content: str) -> Tuple[str, bool]:
        """
        Determine what content is safe to stream vs what should be held in buffer.
        
        This method detects if content contains a potential Nemotron tool call pattern.
        If we detect a potential tool call start (like `<tool`), we hold everything
        from that point forward until we can confirm it's a tool call or not.
        
        Args:
            content: Accumulated content from streaming
            
        Returns:
            Tuple of (safe_to_stream, is_tool_pending):
            - safe_to_stream: Content that's definitely safe to stream (no partial tool call tokens)
            - is_tool_pending: True if we're potentially in a tool call pattern and should hold content
        """
        # Check if we have a complete tool call - if so, everything before it is safe
        tool_call_match = self.TOOL_CALL_PATTERN.search(content)
        if tool_call_match:
            # Complete tool call detected - everything before it is safe
            safe_end = tool_call_match.start()
            return content[:safe_end], True
        
        # Check if we have a potential tool call start (`<tool`)
        # If found, hold everything from that point forward
        tool_start_match = self.TOOL_START_PATTERN.search(content)
        if tool_start_match:
            # Potential tool call detected - hold everything from this point
            safe_end = tool_start_match.start()
            return content[:safe_end], True
        
        # No tool call patterns detected - all content is safe to stream
        return content, False
    
    def _remove_complete_tool_calls(self, content: str) -> str:
        """
        Remove complete Nemotron tool calls from content.
        This is only called after we've confirmed a tool call exists.
        
        Args:
            content: Content that may contain complete tool calls
            
        Returns:
            Content with complete tool calls removed
        """
        # Remove all complete <tool_call>...</tool_call> blocks
        result = self.TOOL_CALL_PATTERN.sub('', content)
        return result
    
    def parse(self, content: str) -> ParsedResponse:
        """Parse Nemotron format response."""
        patches = self._extract_patches(content)

        # Extract thinking/reasoning
        thinking: Optional[str] = None
        think_match = self.THINK_PATTERN.search(content)
        if think_match:
            thinking = think_match.group(1).strip()
        
        # Extract tool call from Nemotron format
        tool_call: Optional[Dict[str, Any]] = None
        raw_tool_call = self._extract_tool_call(content)
        
        if raw_tool_call:
            try:
                tool_name = raw_tool_call["tool"]
                args = raw_tool_call["args"]
                
                # Normalize tool arguments (map parameter names, clean paths)
                normalized_args = self._normalize_tool_args(tool_name, args)
                
                tool_call = {
                    "tool": tool_name,
                    "args": normalized_args,
                }
            except Exception as e:
                # If parsing fails, log but don't fail completely
                # The tool_call will remain None
                print(f"Warning: Failed to parse Nemotron tool call: {e}")
        
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
        
        # Normalize code block spacing to ensure proper markdown rendering
        # This fixes cases where tool call removal strips newlines around code blocks
        final_text = self._normalize_code_block_spacing(final_text)
        
        return ParsedResponse(
            thinking=thinking,
            tool_call=tool_call,
            patches=patches or None,
            final_text=final_text,
        )
    
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
        Serialize a tool call into Nemotron format for chat context.
        
        Format:
        <tool_call>
        <function={tool_name}>
        <parameter={param}>{value}</parameter>
        ...
        </function>
        </tool_call>
        Tool Result: {result}
        """
        # Build parameter tags
        params_str = ""
        for param_name, param_value in args.items():
            if isinstance(param_value, (dict, list)):
                value_str = json.dumps(param_value)
            else:
                value_str = str(param_value)
            params_str += f"<parameter={param_name}>{value_str}</parameter>\n"
        
        tool_call_str = f"<tool_call>\n<function={tool_name}>\n{params_str}</function>\n</tool_call>"
        
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


parser = NemotronParser()

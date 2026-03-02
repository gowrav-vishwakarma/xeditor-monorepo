"""Parser for Kimi family responses (shared across modes).

Kimi K2.* models are trained with a tool-calling format that uses special tokens:

- <|tool_calls_section_begin|> ... <|tool_calls_section_end|>
- <|tool_call_begin|>functions.{tool_name}:{idx}<|tool_call_argument_begin|>{json}<|tool_call_end|>

This parser extracts a single tool call (first one found) and buffers partial
tool-call tokens during streaming to avoid leaking them into the UI.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

from apps.code_editor.parsers.base import ResponseParser, ParsedResponse


class KimiParser(ResponseParser):
    """Parser for Kimi family responses (K2 / K2.5 token tool-calls)."""

    family = "kimi"

    # Thinking tag (Kimi templates commonly wrap reasoning in <think>...</think>)
    THINK_PATTERN = re.compile(r"<think>([\s\S]*?)</think>", re.IGNORECASE)

    # Tool-call tokens (as emitted by Kimi K2.* chat template)
    # Format: <|tool_calls_section_begin|> ... <|tool_calls_section_end|>
    # Note: Uses single angle brackets <|...|>, not double <<|...|>>
    TOOL_CALL_SECTION_PATTERN = re.compile(
        r"<\|tool_calls_section_begin\|>([\s\S]*?)<\|tool_calls_section_end\|>",
        re.IGNORECASE,
    )
    TOOL_CALL_PATTERN = re.compile(
        r"<\|tool_call_begin\|>\s*(?P<tool_call_id>[\s\S]*?)\s*"
        r"<\|tool_call_argument_begin\|>\s*(?P<args>[\s\S]*?)\s*"
        r"<\|tool_call_end\|>",
        re.IGNORECASE,
    )

    # Early detection for streaming buffering. We detect `<|` which is the start of any Kimi token.
    # This catches partial tokens early to prevent them from appearing in UI:
    # - <| (partial token start)
    # - <|tool (partial tool token)
    # - <|tool_calls_section_begin|> (complete token)
    # - <|tool_call_begin|> (complete token)
    # Similar to how GPT/Gemini parsers catch `<|` early for Harmony tokens
    TOOL_TOKEN_START = re.compile(r"<\|", re.IGNORECASE)

    def _extract_json_object(self, text: str, start_pos: int) -> Optional[str]:
        """
        Extract a JSON object starting at start_pos, handling nested braces.
        Skips optional whitespace before the opening brace.
        """
        if start_pos >= len(text):
            return None

        json_start = start_pos
        while json_start < len(text) and text[json_start].isspace():
            json_start += 1

        if json_start >= len(text) or text[json_start] != "{":
            return None

        brace_count = 0
        i = json_start
        while i < len(text):
            char = text[i]
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return text[start_pos : i + 1]
            i += 1

        # Truncated JSON (streaming) – return what we have so callers can attempt repair.
        if brace_count > 0:
            return text[start_pos:]
        return None

    def _normalize_path(self, path: str) -> str:
        if not path:
            return path
        if path.startswith("@"):
            path = path[1:]
        return path.strip()

    def _normalize_tool_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize tool arguments to match what the executor expects.

        The tool descriptions shown to the model may use slightly different parameter
        names; normalize to our executor names (mainly `path`, `content`).
        """
        normalized = args.copy()

        param_mappings: Dict[str, Dict[str, str]] = {
            "read_file": {"target_file": "path"},
            "write_file": {"file_path": "path", "contents": "content"},
            "delete_file": {"target_file": "path"},
            "list_dir": {"target_directory": "path"},
            "search_replace": {"file_path": "path"},
        }

        if tool_name in param_mappings:
            for desc_name, exec_name in param_mappings[tool_name].items():
                if desc_name in normalized:
                    normalized[exec_name] = normalized.pop(desc_name)

        for key in ("path", "target_file", "file_path", "target_directory"):
            if key in normalized and isinstance(normalized[key], str):
                normalized[key] = self._normalize_path(normalized[key])

        return normalized

    def _parse_tool_call_id(self, tool_call_id: str) -> Optional[str]:
        """
        Parse tool name from Kimi tool_call_id.

        Expected: functions.{tool_name}:{idx}
        """
        raw = tool_call_id.strip()
        if not raw:
            return None
        # Example: functions.read_file:0
        if raw.startswith("functions."):
            raw = raw[len("functions.") :]
        if ":" in raw:
            raw = raw.split(":", 1)[0]
        return raw.strip() or None

    def _extract_tool_call(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Extract the first tool call from Kimi token format.

        Returns:
            {"tool": str, "args": dict} or None
        """
        section_match = self.TOOL_CALL_SECTION_PATTERN.search(content)
        if not section_match:
            return None

        section = section_match.group(1) or ""
        call_match = self.TOOL_CALL_PATTERN.search(section)
        if not call_match:
            return None

        tool_call_id = (call_match.group("tool_call_id") or "").strip()
        tool_name = self._parse_tool_call_id(tool_call_id)
        if not tool_name:
            return None

        args_str_raw = call_match.group("args") or ""

        # Kimi templates may emit either a JSON string or already-serialized JSON.
        json_str = self._extract_json_object(args_str_raw, 0) or args_str_raw.strip()
        if not json_str:
            parsed_args: Dict[str, Any] = {}
        else:
            parsed_args = {}
            try:
                loaded = json.loads(json_str)
                if isinstance(loaded, dict):
                    parsed_args = loaded
            except json.JSONDecodeError:
                # Attempt repair for truncated JSON by appending closing braces
                for i in range(1, 5):
                    try:
                        loaded = json.loads(json_str + ("}" * i))
                        if isinstance(loaded, dict):
                            parsed_args = loaded
                            break
                    except json.JSONDecodeError:
                        continue

        normalized_args = self._normalize_tool_args(tool_name, parsed_args)
        return {"tool": tool_name, "args": normalized_args}

    def _remove_complete_tool_call_sections(self, content: str) -> str:
        """
        Remove complete tool-call sections from content.
        """
        result = self.TOOL_CALL_SECTION_PATTERN.sub("", content)

        # Safety: if an incomplete tool section leaked, strip from the last token start onward.
        lowered = result.lower()
        if "<|tool_" in lowered:
            matches = list(self.TOOL_TOKEN_START.finditer(result))
            if matches:
                last = matches[-1]
                # If no closing section end exists after last token, strip trailing fragment
                tail = result[last.start() :].lower()
                if "<|tool_calls_section_end|>" not in tail:
                    result = result[: last.start()]

        return result

    def get_streamable_content(self, content: str) -> Tuple[str, bool]:
        """
        Buffer content from the first `<|` token onward until we have
        a complete tool-call section. This prevents partial Kimi tokens
        (like `<|`, `<|tool`, etc.) from leaking into the UI.
        """
        section_match = self.TOOL_CALL_SECTION_PATTERN.search(content)
        if section_match:
            return content[: section_match.start()], True

        token_start = self.TOOL_TOKEN_START.search(content)
        if token_start:
            return content[: token_start.start()], True

        return content, False

    def parse(self, content: str) -> ParsedResponse:
        # Extract thinking
        thinking: Optional[str] = None
        think_match = self.THINK_PATTERN.search(content)
        if think_match:
            thinking = think_match.group(1).strip()

        tool_call = self._extract_tool_call(content)

        final_text = self._remove_complete_tool_call_sections(content)
        final_text = self.strip_tags(final_text)

        return ParsedResponse(
            thinking=thinking,
            tool_call=tool_call,
            final_text=final_text,
        )

    def strip_tags(self, content: str) -> str:
        # Only remove thinking tags (internal)
        return self.THINK_PATTERN.sub("", content)
    
    def serialize_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> str:
        """
        Serialize a tool call into Kimi token format for chat context.
        
        Format:
        <|tool_calls_section_begin|>
        <|tool_call_begin|>functions.{tool_name}:0<|tool_call_argument_begin|>{args_json}<|tool_call_end|>
        <|tool_calls_section_end|>
        Tool Result: {result}
        """
        args_json = json.dumps(args)
        tool_call_str = (
            f"<|tool_calls_section_begin|>\n"
            f"<|tool_call_begin|>functions.{tool_name}:0<|tool_call_argument_begin|>{args_json}<|tool_call_end|>\n"
            f"<|tool_calls_section_end|>"
        )
        
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


parser = KimiParser()

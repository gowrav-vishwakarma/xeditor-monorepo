"""
Base response parser and parser registry for LLM response handling.

Parsers are responsible for extracting structured data from LLM response content:
- Tool calls (Harmony format, JSON, etc.)
- Patches (<patch> tags for code suggestions)
- Thinking/reasoning (fallback when provider doesn't emit structured thinking events)

The provider layer is the primary source for thinking events. Parsers provide
fallback thinking extraction for models that emit <think> tags in content
rather than structured reasoning fields.
"""

import re
import json
import importlib.util
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Type, Tuple
from pathlib import Path


@dataclass
class ParsedResponse:
    """Result of parsing an LLM response."""
    thinking: Optional[str] = None
    tool_call: Optional[Dict[str, Any]] = None
    # Patch blocks extracted from assistant output (for diff UI + debug replay).
    # Shape is parser-specific but must be JSON-serializable.
    patches: Optional[List[Dict[str, Any]]] = None
    final_text: str = ""
    context_policy: Optional[Dict[str, str]] = None
    
    def __post_init__(self):
        """Set default context policy if not provided."""
        if self.context_policy is None:
            self.context_policy = {
                "thinking": "meta_only",  # Thinking is display-only, not sent to LLM
                "tool_results": "summarize",  # Tool results are summarized for context
            }
    
    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "finalText": self.final_text,
        }
        if self.thinking:
            result["thinking"] = self.thinking
        if self.tool_call:
            result["toolCall"] = self.tool_call
        if self.patches:
            result["patches"] = self.patches
        if self.context_policy:
            result["contextPolicy"] = self.context_policy
        return result


# Utility patterns for thinking extraction fallback
THINK_TAG_PATTERN = re.compile(r'<think>([\s\S]*?)</think>', re.IGNORECASE)
THOUGHT_TAG_PATTERN = re.compile(r'<thought>([\s\S]*?)</thought>', re.IGNORECASE)


def extract_thinking_from_content(content: str) -> Optional[str]:
    """
    Extract thinking/reasoning from content as a fallback.
    
    This is used when the provider doesn't emit structured thinking events.
    Models like DeepSeek via OpenAI-compatible endpoints may emit <think> tags.
    
    Args:
        content: LLM response content
        
    Returns:
        Thinking text if found, None otherwise
    """
    # Try <think> first
    match = THINK_TAG_PATTERN.search(content)
    if match:
        return match.group(1).strip()
    
    # Try <thought>
    match = THOUGHT_TAG_PATTERN.search(content)
    if match:
        return match.group(1).strip()
    
    # Handle incomplete thinking tags during streaming
    for pattern in [r'<think>', r'<thought>']:
        opening_match = re.search(pattern, content, re.IGNORECASE)
        if opening_match:
            # Check if there's no closing tag
            if not re.search(pattern.replace('<', '</'), content, re.IGNORECASE):
                start_pos = opening_match.end()
                return content[start_pos:].strip()
    
    return None


def strip_thinking_tags(content: str) -> str:
    """
    Remove thinking/reasoning tags from content.
    
    This is used to strip <think>...</think> and <thought>...</thought> blocks
    from content when structured thinking events have already been emitted by
    the provider, preventing duplicate display in the UI.
    
    Args:
        content: LLM response content
        
    Returns:
        Content with thinking tags removed
    """
    # Strip complete <think>...</think> blocks
    result = THINK_TAG_PATTERN.sub('', content)
    
    # Strip complete <thought>...</thought> blocks
    result = THOUGHT_TAG_PATTERN.sub('', result)
    
    # Also handle incomplete thinking tags (streaming scenario)
    # Remove opening <think> or <thought> tag and everything after if no closing tag
    for open_tag, close_tag in [('<think>', '</think>'), ('<thought>', '</thought>')]:
        open_match = re.search(open_tag, result, re.IGNORECASE)
        if open_match:
            close_match = re.search(close_tag, result, re.IGNORECASE)
            if not close_match:
                # No closing tag - strip from opening tag to end
                result = result[:open_match.start()]
    
    # Remove standalone closing tags (can appear when model outputs incomplete thinking blocks)
    # This handles cases where we get </think> or </thought> without opening tags
    result = re.sub(r'</think>', '', result, flags=re.IGNORECASE)
    result = re.sub(r'</thought>', '', result, flags=re.IGNORECASE)
    
    # Don't strip whitespace - this preserves spaces in markdown (e.g., "## What" not "##What")
    # The original .strip() was removing spaces at chunk boundaries during streaming
    return result


class ResponseParser(ABC):
    """
    Base class for response parsers.
    
    Parsers focus on extracting structured data from content:
    - Tool calls (primary responsibility)
    - Patches (code suggestions)
    - Thinking (fallback when provider doesn't emit structured events)
    """
    
    # Family identifier (e.g., 'gpt', 'claude', 'llama')
    family: str = "default"
    # Optional version (e.g., '4-turbo')
    version: Optional[str] = None
    
    @abstractmethod
    def parse(self, content: str) -> ParsedResponse:
        """Parse the response content and extract structured data."""
        pass
    
    @abstractmethod
    def strip_tags(self, content: str) -> str:
        """Strip internal tags from content for display."""
        pass
    
    def get_streamable_content(self, content: str) -> Tuple[str, bool]:
        """
        Determine what content is safe to stream vs what should be held in buffer.
        
        Default implementation: all content is safe to stream (no buffering needed).
        Parsers that need to buffer partial tool calls (e.g., Harmony format) should override this.
        
        Args:
            content: Accumulated content from streaming
            
        Returns:
            Tuple of (safe_to_stream, is_tool_pending):
            - safe_to_stream: Content that's safe to stream immediately
            - is_tool_pending: True if we're potentially in a tool call pattern and should hold content
        """
        # Default: all content is safe to stream, no tool pending
        return content, False
    
    def serialize_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> str:
        """
        Serialize a tool call into the family's native format for chat context.
        
        This is used when building LLM context from chat history to ensure
        tool calls are formatted in a way the model recognizes from training.
        
        Args:
            tool_name: Name of the tool that was called
            args: Arguments passed to the tool
            result: Result from the tool execution (if successful)
            error: Error message (if tool failed)
            
        Returns:
            Formatted string representing the tool call and its result
        """
        # Default format using <tool_code> tags (generic fallback)
        tool_call_str = f'<tool_code>{{"tool": "{tool_name}", "args": {json.dumps(args)}}}</tool_code>'
        
        if error:
            return f"{tool_call_str}\nTool Error: {error}"
        elif result is not None:
            result_str = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            return f"{tool_call_str}\nTool Result: {result_str}"
        else:
            return tool_call_str


class DefaultParser(ResponseParser):
    """
    Default response parser supporting common tag formats.
    Supports:
    - <think>...</think> and <thought>...</thought> for thinking
    - <tool_code>...</tool_code> for tool calls
    """
    
    family = "default"
    
    # Regex patterns
    THINK_PATTERN = re.compile(r'<think>([\s\S]*?)</think>', re.IGNORECASE)
    THOUGHT_PATTERN = re.compile(r'<thought>([\s\S]*?)</thought>', re.IGNORECASE)
    TOOL_CODE_PATTERN = re.compile(r'<tool_code>([\s\S]*?)</tool_code>', re.IGNORECASE)
    
    def parse(self, content: str) -> ParsedResponse:
        # Try multiple thinking tag formats
        think_match = self.THINK_PATTERN.search(content)
        if not think_match:
            think_match = self.THOUGHT_PATTERN.search(content)
        
        thinking: Optional[str] = None
        if think_match:
            thinking = think_match.group(1).strip()
        else:
            # Handle incomplete thinking tags during streaming
            # Check if there's an opening <think> or <thought> tag without a closing tag
            opening_think_match = re.search(r'<think>', content, re.IGNORECASE)
            opening_thought_match = re.search(r'<thought>', content, re.IGNORECASE)
            if opening_think_match:
                start_pos = opening_think_match.end()
                thinking = content[start_pos:].strip()
            elif opening_thought_match:
                start_pos = opening_thought_match.end()
                thinking = content[start_pos:].strip()
        
        # Tool calls come from provider events (native API), not from content parsing
        # Final text is content with all tags stripped
        final_text = self.strip_tags(content)
        
        return ParsedResponse(
            thinking=thinking,
            tool_call=None,
            final_text=final_text,
        )
    
    def strip_tags(self, content: str) -> str:
        result = content
        result = self.THINK_PATTERN.sub('', result)
        result = self.THOUGHT_PATTERN.sub('', result)
        result = self.TOOL_CODE_PATTERN.sub('', result)
        return result.strip()
    
    def serialize_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> str:
        """Serialize tool call using <tool_code> format."""
        tool_call_str = f'<tool_code>{{"tool": "{tool_name}", "args": {json.dumps(args)}}}</tool_code>'
        
        if error:
            return f"{tool_call_str}\nTool Error: {error}"
        elif result is not None:
            result_str = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            return f"{tool_call_str}\nTool Result: {result_str}"
        else:
            return tool_call_str


class ClaudeParser(ResponseParser):
    """
    Parser for Claude models.
    Claude uses similar patterns but may have additional formats.
    """
    
    family = "claude"
    
    # Claude may use artifact tags and other formats
    THINK_PATTERN = re.compile(r'<think>([\s\S]*?)</think>', re.IGNORECASE)
    THOUGHT_PATTERN = re.compile(r'<thought>([\s\S]*?)</thought>', re.IGNORECASE)
    TOOL_CODE_PATTERN = re.compile(r'<tool_code>([\s\S]*?)</tool_code>', re.IGNORECASE)
    ARTIFACT_PATTERN = re.compile(r'<artifact[^>]*>([\s\S]*?)</artifact>', re.IGNORECASE)
    
    def parse(self, content: str) -> ParsedResponse:
        # Try thinking patterns
        think_match = self.THINK_PATTERN.search(content)
        if not think_match:
            think_match = self.THOUGHT_PATTERN.search(content)
        
        thinking: Optional[str] = None
        if think_match:
            thinking = think_match.group(1).strip()
        
        # Tool calls come from provider events (native API), not from content parsing
        final_text = self.strip_tags(content)
        
        return ParsedResponse(
            thinking=thinking,
            tool_call=None,
            final_text=final_text,
        )
    
    def strip_tags(self, content: str) -> str:
        result = content
        result = self.THINK_PATTERN.sub('', result)
        result = self.THOUGHT_PATTERN.sub('', result)
        result = self.TOOL_CODE_PATTERN.sub('', result)
        # Keep artifact content but remove tags
        result = re.sub(r'<artifact[^>]*>', '', result)
        result = re.sub(r'</artifact>', '', result)
        return result.strip()
    
    def serialize_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> str:
        """Serialize tool call using <tool_code> format for Claude."""
        tool_call_str = f'<tool_code>{{"tool": "{tool_name}", "args": {json.dumps(args)}}}</tool_code>'
        
        if error:
            return f"{tool_call_str}\nTool Error: {error}"
        elif result is not None:
            result_str = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            return f"{tool_call_str}\nTool Result: {result_str}"
        else:
            return tool_call_str


class GPTParser(ResponseParser):
    """
    Parser for OpenAI GPT models.
    GPT typically uses function calls natively, but may also use text-based tool calls.
    """
    
    family = "gpt"
    
    THINK_PATTERN = re.compile(r'<think>([\s\S]*?)</think>', re.IGNORECASE)
    TOOL_CODE_PATTERN = re.compile(r'<tool_code>([\s\S]*?)</tool_code>', re.IGNORECASE)
    # GPT may use code blocks for tool calls
    JSON_CODE_BLOCK = re.compile(r'```(?:json)?\s*\n([\s\S]*?)\n```', re.IGNORECASE)
    
    def parse(self, content: str) -> ParsedResponse:
        think_match = self.THINK_PATTERN.search(content)
        
        thinking: Optional[str] = None
        if think_match:
            thinking = think_match.group(1).strip()
        
        # Tool calls come from provider events (native API), not from content parsing
        final_text = self.strip_tags(content)
        
        return ParsedResponse(
            thinking=thinking,
            tool_call=None,
            final_text=final_text,
        )
    
    def strip_tags(self, content: str) -> str:
        result = content
        result = self.THINK_PATTERN.sub('', result)
        result = self.TOOL_CODE_PATTERN.sub('', result)
        return result.strip()
    
    def serialize_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> str:
        """Serialize tool call using <tool_code> format for GPT base parser."""
        # Note: The prompt_sets/default/gpt/parser.py uses Harmony format
        # This base parser uses a simpler format
        tool_call_str = f'<tool_code>{{"tool": "{tool_name}", "args": {json.dumps(args)}}}</tool_code>'
        
        if error:
            return f"{tool_call_str}\nTool Error: {error}"
        elif result is not None:
            result_str = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            return f"{tool_call_str}\nTool Result: {result_str}"
        else:
            return tool_call_str


class LlamaParser(ResponseParser):
    """
    Parser for Llama/Meta models.
    """
    
    family = "llama"
    
    THINK_PATTERN = re.compile(r'<think>([\s\S]*?)</think>', re.IGNORECASE)
    THOUGHT_PATTERN = re.compile(r'<thought>([\s\S]*?)</thought>', re.IGNORECASE)
    TOOL_CODE_PATTERN = re.compile(r'<tool_code>([\s\S]*?)</tool_code>', re.IGNORECASE)
    # Llama may use different formats
    FUNCTION_CALL_PATTERN = re.compile(r'<function_call>([\s\S]*?)</function_call>', re.IGNORECASE)
    
    def parse(self, content: str) -> ParsedResponse:
        think_match = self.THINK_PATTERN.search(content)
        if not think_match:
            think_match = self.THOUGHT_PATTERN.search(content)
        
        tool_match = self.TOOL_CODE_PATTERN.search(content)
        if not tool_match:
            tool_match = self.FUNCTION_CALL_PATTERN.search(content)
        
        thinking: Optional[str] = None
        if think_match:
            thinking = think_match.group(1).strip()
        
        tool_call: Optional[Dict[str, Any]] = None
        if tool_match:
            try:
                parsed = json.loads(tool_match.group(1).strip())
                if isinstance(parsed, dict) and "tool" in parsed and "args" in parsed:
                    tool_call = {
                        "tool": parsed["tool"],
                        "args": parsed["args"],
                    }
                elif isinstance(parsed, dict) and "name" in parsed and "parameters" in parsed:
                    # Alternative format
                    tool_call = {
                        "tool": parsed["name"],
                        "args": parsed["parameters"],
                    }
            except (json.JSONDecodeError, KeyError):
                pass
        
        final_text = self.strip_tags(content)
        
        return ParsedResponse(
            thinking=thinking,
            tool_call=tool_call,
            final_text=final_text,
        )
    
    def strip_tags(self, content: str) -> str:
        result = content
        result = self.THINK_PATTERN.sub('', result)
        result = self.THOUGHT_PATTERN.sub('', result)
        result = self.TOOL_CODE_PATTERN.sub('', result)
        result = self.FUNCTION_CALL_PATTERN.sub('', result)
        return result.strip()
    
    def serialize_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> str:
        """Serialize tool call using <function_call> format for Llama."""
        tool_call_str = f'<function_call>{{"name": "{tool_name}", "parameters": {json.dumps(args)}}}</function_call>'
        
        if error:
            return f"{tool_call_str}\nTool Error: {error}"
        elif result is not None:
            result_str = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            return f"{tool_call_str}\nTool Result: {result_str}"
        else:
            return tool_call_str


# Parser registry
_PARSERS: Dict[str, ResponseParser] = {}

def _register_parsers():
    """Register all built-in parsers."""
    global _PARSERS
    parsers = [
        DefaultParser(),
        ClaudeParser(),
        GPTParser(),
        LlamaParser(),
    ]
    for parser in parsers:
        key = parser.family
        if parser.version:
            key = f"{parser.family}:{parser.version}"
        _PARSERS[key] = parser

# Initialize parsers
_register_parsers()


def get_parser_for_model(
    family: str,
    version: Optional[str] = None,
) -> ResponseParser:
    """
    Get the best matching parser for a model.
    
    Priority:
    1. Version-specific parser (family:version)
    2. Family parser (family)
    3. Default parser
    """
    # Try version-specific first
    if version:
        version_key = f"{family}:{version}"
        if version_key in _PARSERS:
            return _PARSERS[version_key]
    
    # Try family
    if family in _PARSERS:
        return _PARSERS[family]
    
    # Fallback to default
    return _PARSERS.get("default", DefaultParser())


def register_parser(parser: ResponseParser) -> None:
    """Register a custom parser."""
    key = parser.family
    if parser.version:
        key = f"{parser.family}:{parser.version}"
    _PARSERS[key] = parser


# Parser module cache (keyed by file path + mtime)
_PARSER_MODULE_CACHE: Dict[str, ResponseParser] = {}


def get_parser_for_request(
    set_id: str,
    family: str,
    version: Optional[str],
    mode: str,
) -> ResponseParser:
    """
    Get parser for a specific request, checking set-specific parsers first.
    
    Lookup order:
    1. Set-specific parser file (server/prompt_sets/{setId}/{family}/{runtime_version}/parser.py)
    2. Set-specific parser file (server/prompt_sets/{setId}/{family}/{set_metadata.modelVersion}/parser.py) if different from runtime_version
    3. Set-specific parser file (server/prompt_sets/{setId}/{family}/parser.py)
    4. Fallback to get_parser_for_model(family, version)
    
    Args:
        set_id: Prompt set ID (e.g., "default", "user/set-name")
        family: Model family (e.g., "gpt", "claude")
        version: Optional model version (e.g., "4-turbo")
        mode: Mode (e.g., "ask", "agent", "plan", "debug") - kept for API compatibility but not used in lookup
        
    Returns:
        ResponseParser instance
    """
    # Try to get set from manager (including "default" set)
    try:
        from apps.code_editor.sets.manager import get_set_manager
        set_manager = get_set_manager()
        set_obj = set_manager.get_set(set_id)
        
        if set_obj:
            # 1. Try runtime version-specific parser first
            if version:
                parser_path = set_obj.get_parser_path(family, version=version)
                if parser_path and parser_path.exists():
                    parser = _load_parser_from_file(parser_path)
                    if parser:
                        return parser
            
            # 2. Try set metadata modelVersion parser (if different from runtime version)
            set_model_version = set_obj.metadata.modelVersion
            if set_model_version and set_model_version != version:
                parser_path = set_obj.get_parser_path(family, version=set_model_version)
                if parser_path and parser_path.exists():
                    parser = _load_parser_from_file(parser_path)
                    if parser:
                        return parser
            
            # 3. Try family-level parser (no version)
            parser_path = set_obj.get_parser_path(family)
            if parser_path and parser_path.exists():
                parser = _load_parser_from_file(parser_path)
                if parser:
                    return parser
    except Exception as e:
        # If set lookup fails, fall back to model parser
        print(f"Warning: Failed to load parser from set {set_id}: {e}")
    
    # Fallback to model-based parser
    return get_parser_for_model(family, version)


def _load_parser_from_file(parser_path: Path) -> Optional[ResponseParser]:
    """
    Load a parser class from a Python file.
    
    Args:
        parser_path: Path to parser.py file
        
    Returns:
        ResponseParser instance or None if loading fails
    """
    try:
        # Check cache key (path + mtime)
        mtime = parser_path.stat().st_mtime
        cache_key = f"{parser_path}:{mtime}"
        
        # Clear old cache entries for this path (in case file was modified)
        keys_to_remove = [k for k in _PARSER_MODULE_CACHE.keys() if k.startswith(f"{parser_path}:")]
        for key in keys_to_remove:
            if key != cache_key:
                del _PARSER_MODULE_CACHE[key]
        
        if cache_key in _PARSER_MODULE_CACHE:
            return _PARSER_MODULE_CACHE[cache_key]
        
        # Load module with unique name to avoid Python import cache issues
        # Include mtime in module name to force reload if file changed
        module_name = f"parser_{hash(str(parser_path))}_{int(mtime * 1000000)}"
        spec = importlib.util.spec_from_file_location(module_name, parser_path)
        if not spec or not spec.loader:
            return None
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Find ResponseParser subclass
        parser_class = None
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, ResponseParser)
                and obj != ResponseParser
            ):
                parser_class = obj
                break
        
        if not parser_class:
            return None
        
        # Instantiate parser
        parser_instance = parser_class()
        
        # Cache it
        _PARSER_MODULE_CACHE[cache_key] = parser_instance
        
        return parser_instance
        
    except Exception as e:
        print(f"Error loading parser from {parser_path}: {e}")
        return None

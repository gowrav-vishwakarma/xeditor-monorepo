"""
Chat management module for XEditor Local Companion.
Handles chat storage at ~/.xeditor/projects/{projectName}/chats/{chatId}.json
"""

import json
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime
from apps.code_editor.project import get_project_manager

if TYPE_CHECKING:
    from apps.code_editor.parsers.base import ResponseParser


def get_chats_directory(project_id: str) -> Path:
    """Get the chats directory for a project."""
    manager = get_project_manager()
    project = manager.get_project(project_id)
    if not project:
        raise ValueError(f"Project not found: {project_id}")
    
    safe_name = project.get("safeName", project.get("name", project_id))
    chats_dir = manager.projects_path / safe_name / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    return chats_dir


def get_chat_path(project_id: str, chat_id: str) -> Path:
    """Get the file path for a chat."""
    return get_chats_directory(project_id) / f"{chat_id}.json"


class ChatManager:
    """
    Manages chat sessions stored in ~/.xeditor/projects/{projectName}/chats/{chatId}.json
    """

    def __init__(self):
        pass

    def create_chat(self, project_id: str, title: Optional[str] = None) -> Dict[str, Any]:
        """Create a new chat session."""
        chat_id = str(uuid.uuid4())
        now = int(datetime.now().timestamp() * 1000)
        
        chat = {
            "id": chat_id,
            "projectId": project_id,
            "title": title or f"Chat {datetime.fromtimestamp(now / 1000).strftime('%Y-%m-%d %H:%M')}",
            "createdAt": now,
            "updatedAt": now,
            "turns": [],
        }
        
        self.save_chat(chat)
        return chat

    def load_chat(self, project_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
        """Load a chat session."""
        chat_path = get_chat_path(project_id, chat_id)
        
        if not chat_path.exists():
            return None
        
        try:
            with open(chat_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Failed to load chat {chat_id}: {e}")
            return None

    def save_chat(self, chat: Dict[str, Any]) -> bool:
        """Save a chat session."""
        try:
            chat_path = get_chat_path(chat["projectId"], chat["id"])
            chat["updatedAt"] = int(datetime.now().timestamp() * 1000)
            
            with open(chat_path, "w", encoding="utf-8") as f:
                json.dump(chat, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Failed to save chat {chat.get('id')}: {e}")
            return False

    def list_chats(self, project_id: str) -> List[Dict[str, Any]]:
        """List all chats for a project."""
        chats_dir = get_chats_directory(project_id)
        
        if not chats_dir.exists():
            return []
        
        chats = []
        for chat_file in chats_dir.glob("*.json"):
            try:
                with open(chat_file, "r", encoding="utf-8") as f:
                    chat = json.load(f)
                    # Create summary
                    chats.append({
                        "id": chat.get("id"),
                        "projectId": chat.get("projectId"),
                        "title": chat.get("title"),
                        "createdAt": chat.get("createdAt"),
                        "updatedAt": chat.get("updatedAt"),
                        "turnCount": len(chat.get("turns", [])),
                    })
            except (json.JSONDecodeError, IOError):
                continue
        
        # Sort by updatedAt descending
        chats.sort(key=lambda c: c.get("updatedAt", 0), reverse=True)
        return chats

    def delete_chat(self, project_id: str, chat_id: str) -> bool:
        """Delete a chat session."""
        chat_path = get_chat_path(project_id, chat_id)
        
        if not chat_path.exists():
            return False
        
        try:
            chat_path.unlink()
            return True
        except Exception as e:
            print(f"Failed to delete chat {chat_id}: {e}")
            return False

    def add_turn(
        self,
        project_id: str,
        chat_id: str,
        turn: Dict[str, Any],
    ) -> bool:
        """Add a turn to a chat."""
        chat = self.load_chat(project_id, chat_id)
        if not chat:
            return False
        
        # Ensure turn has required fields
        if "id" not in turn:
            turn["id"] = str(uuid.uuid4())
        if "timestamp" not in turn:
            turn["timestamp"] = int(datetime.now().timestamp() * 1000)
        
        chat["turns"].append(turn)
        return self.save_chat(chat)

    def build_llm_context(
        self,
        chat: Dict[str, Any],
        new_message: str,
        user_context: List[Dict[str, Any]],
        system_prompt: str,
        family: str = "default",
        set_id: str = "default",
        version: Optional[str] = None,
    ) -> tuple[List[Dict[str, str]], int]:
        """
        Build LLM context from chat history, filtering out meta-only content.
        
        Tool calls from history are serialized using the current family's format,
        ensuring the LLM sees tool calls in a format it recognizes from training.
        This prevents the LLM from learning incorrect tool calling patterns from
        mixed-format history when users switch between model families.
        
        Each tool call is numbered with [tcN] prefix for context compression.
        
        Args:
            chat: Chat data with turns
            new_message: New user message to add
            user_context: Context items to include with the message
            system_prompt: System prompt for the LLM
            family: Current model family (e.g., "gpt", "claude", "kimi")
            set_id: Prompt set ID (e.g., "default")
            version: Optional model version
        
        Returns:
            Tuple of (messages, next_tool_call_counter). Messages are in OpenAI format.
            next_tool_call_counter is the next available tcN for new tool calls in the agent loop.
        """
        # Get parser for current family to serialize tool calls in the correct format
        parser: Optional["ResponseParser"] = None
        try:
            from apps.code_editor.parsers.base import get_parser_for_request
            parser = get_parser_for_request(set_id, family, version, "agent")
        except Exception as e:
            print(f"Warning: Failed to get parser for family {family}: {e}")
        
        messages = [{"role": "system", "content": system_prompt}]
        tool_call_counter = 1
        
        # Process historical turns
        for turn in chat.get("turns", []):
            # Skip turns marked as not included in context
            if not turn.get("includeInContext", True):
                continue
            
            # Skip turns with errors (these shouldn't pollute LLM context)
            if turn.get("meta", {}).get("error"):
                continue
            
            # Add user message
            user_msg = turn.get("userMessage", "")
            if user_context and turn == chat["turns"][-1]:
                # Format context for the last turn if it matches
                user_msg = self._format_message_with_context(user_msg, user_context)
            messages.append({"role": "user", "content": user_msg})
            
            # Build assistant response
            assistant_msg = turn.get("assistantMessage", "")
            
            # Include tool results that are marked for context (numbered with [tcN])
            tool_summary, tool_call_counter = self._summarize_tools(
                turn.get("toolCalls", []),
                parser=parser,
                start_counter=tool_call_counter,
            )
            if tool_summary:
                assistant_msg = f"{tool_summary}\n\n{assistant_msg}"
            
            if assistant_msg:
                messages.append({"role": "assistant", "content": assistant_msg})
        
        # Add new user message with context
        formatted_message = self._format_message_with_context(new_message, user_context)
        messages.append({"role": "user", "content": formatted_message})
        
        return messages, tool_call_counter

    def build_tc_id_map(self, chat: Dict[str, Any]) -> Dict[str, Tuple[int, int]]:
        """
        Build a mapping from tool call IDs (tc1, tc2, ...) to (turn_index, tool_call_index).
        Only includes turns and tool calls that would be included in context.
        Used to resolve _context_updates references for persisting summaries.
        """
        tc_map: Dict[str, Tuple[int, int]] = {}
        counter = 1
        
        for turn_idx, turn in enumerate(chat.get("turns", [])):
            if not turn.get("includeInContext", True):
                continue
            if turn.get("meta", {}).get("error"):
                continue
            
            for tc_idx, tool in enumerate(turn.get("toolCalls", [])):
                if not tool.get("includeInContext", True):
                    continue
                tc_id = f"tc{counter}"
                tc_map[tc_id] = (turn_idx, tc_idx)
                counter += 1
        
        return tc_map

    def update_tool_call_summary(
        self,
        chat: Dict[str, Any],
        turn_index: int,
        tool_call_index: int,
        summary: str,
    ) -> bool:
        """
        Update a specific tool call's contextSummary in the chat data and persist.
        """
        turns = chat.get("turns", [])
        if turn_index < 0 or turn_index >= len(turns):
            return False
        
        tool_calls = turns[turn_index].get("toolCalls", [])
        if tool_call_index < 0 or tool_call_index >= len(tool_calls):
            return False
        
        tool_calls[tool_call_index]["contextSummary"] = summary
        return self.save_chat(chat)

    def _format_message_with_context(
        self,
        message: str,
        context: List[Dict[str, Any]],
    ) -> str:
        """Format a user message with context items."""
        if not context:
            return message
        
        context_sections = []
        for item in context:
            file_path = item.get("metadata", {}).get("filePath", "")
            line_start = item.get("metadata", {}).get("lineStart")
            line_end = item.get("metadata", {}).get("lineEnd")
            symbol_name = item.get("metadata", {}).get("symbolName")
            
            location = ""
            if line_start is not None and line_end is not None:
                location = f" (lines {line_start}-{line_end})"
            elif symbol_name:
                location = f" [{symbol_name}]"
            
            item_type = item.get("type", "file")
            context_sections.append(
                f"### {item_type}: {file_path}{location}\n```\n{item.get('content', '')}\n```"
            )
        
        if context_sections:
            return f"{message}\n\n## Current Context\n\n" + "\n\n".join(context_sections)
        
        return message

    def _summarize_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        parser: Optional["ResponseParser"] = None,
        max_result_chars: int = 5000,
        start_counter: int = 1,
    ) -> Tuple[Optional[str], int]:
        """
        Summarize tool calls that should be included in context.
        
        When a parser is provided, tool calls are serialized using the parser's
        native format (e.g., Harmony tokens for GPT, XML for GLM, etc.).
        This ensures LLMs see tool calls in a format they recognize from training.
        
        Each tool call is prefixed with [tcN] for context compression via _context_updates.
        If contextSummary is set, it is used instead of the full result.
        
        Args:
            tool_calls: List of tool call records
            parser: Optional parser to use for family-specific serialization
            max_result_chars: Maximum characters for tool result string (default 5000)
            start_counter: Starting counter for [tcN] numbering (default 1)
        
        Returns:
            Tuple of (summary string or None, next_counter)
        """
        included_tools = [
            tool for tool in tool_calls
            if tool.get("includeInContext", True)
        ]
        
        if not included_tools:
            return None, start_counter
        
        summaries: List[str] = []
        counter = start_counter
        
        for tool in included_tools:
            tool_name = tool.get("tool", "")
            args = tool.get("args", {})
            result = tool.get("result")
            error = tool.get("error")
            context_summary = tool.get("contextSummary")
            
            # Use contextSummary if set (LLM-provided compression)
            if context_summary is not None and context_summary != "":
                formatted_result = context_summary
            elif error:
                # Error case - result stays None, error is passed to serializer
                formatted_result = None
            elif result:
                # Format result based on tool type
                if tool_name == "read_file" and isinstance(result, dict):
                    # read_file returns structured data with pre-chunked content
                    # Format it nicely for context
                    total_lines = result.get("totalLines", "?")
                    truncated = result.get("truncated", False)
                    strategy = result.get("strategy", "full")
                    content = result.get("content", "")
                    
                    meta_info = f"[{total_lines} lines total"
                    if truncated:
                        meta_info += f", {strategy}"
                    meta_info += "]"
                    
                    # Include metadata and content
                    result_str = f"{meta_info}\n{content}"
                    
                    # Apply cap as safety net
                    if len(result_str) > max_result_chars:
                        result_str = result_str[:max_result_chars] + f"\n... [truncated at {max_result_chars} chars]"
                    
                    formatted_result = result_str
                else:
                    # Other tools: serialize and truncate if needed
                    result_str = json.dumps(result) if isinstance(result, dict) else str(result)
                    if len(result_str) > max_result_chars:
                        result_str = result_str[:max_result_chars] + f"... [truncated at {max_result_chars} chars]"
                    
                    formatted_result = result_str
            else:
                formatted_result = None
            
            # Use parser's serialize_tool_call if available, otherwise fall back to generic format
            tc_id = f"tc{counter}"
            if parser:
                summary = parser.serialize_tool_call(
                    tool_name, args, formatted_result, error, tool_call_id=tc_id
                )
            else:
                # Fallback to generic format (for backwards compatibility)
                summary = f"Tool: {tool_name}({json.dumps(args)})"
                if error:
                    summary += f"\nError: {error}"
                elif formatted_result:
                    summary += f"\nResult: {formatted_result}"
                summary = f"[{tc_id}] {summary}"
            summaries.append(summary)
            counter += 1
        
        return "\n\n".join(summaries), counter


# Singleton instance
_chat_manager: Optional[ChatManager] = None


def get_chat_manager() -> ChatManager:
    """Get the singleton ChatManager instance."""
    global _chat_manager
    if _chat_manager is None:
        _chat_manager = ChatManager()
    return _chat_manager


# RPC Handlers

async def handle_create_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for creating a new chat."""
    manager = get_chat_manager()
    project_id = payload.get("projectId", "")
    title = payload.get("title")
    
    if not project_id:
        return {
            "success": False,
            "error": "Project ID is required",
        }
    
    try:
        chat = manager.create_chat(project_id, title)
        return {
            "success": True,
            "chat": chat,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _strip_debug_from_chat(chat: Dict[str, Any]) -> Dict[str, Any]:
    """Strip debug bundles from chat turns to reduce payload size.
    
    The debug bundles are stored on disk but not sent in normal chat load responses.
    They can be fetched on demand via chat_turn_debug_get.
    """
    stripped_chat = chat.copy()
    stripped_turns = []
    
    for turn in chat.get("turns", []):
        stripped_turn = turn.copy()
        meta = stripped_turn.get("meta", {})
        if isinstance(meta, dict) and "debug" in meta:
            # Create a copy of meta without the debug bundle
            stripped_meta = {k: v for k, v in meta.items() if k != "debug"}
            # Add a flag indicating debug is available
            stripped_meta["hasDebug"] = True
            stripped_turn["meta"] = stripped_meta
        stripped_turns.append(stripped_turn)
    
    stripped_chat["turns"] = stripped_turns
    return stripped_chat


async def handle_load_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for loading a chat."""
    manager = get_chat_manager()
    project_id = payload.get("projectId", "")
    chat_id = payload.get("chatId", "")
    
    if not project_id or not chat_id:
        return {
            "success": False,
            "error": "Project ID and Chat ID are required",
        }
    
    chat = manager.load_chat(project_id, chat_id)
    if chat:
        # Strip debug bundles from response to reduce payload size
        stripped_chat = _strip_debug_from_chat(chat)
        return {
            "success": True,
            "chat": stripped_chat,
        }
    return {
        "success": False,
        "error": f"Chat not found: {chat_id}",
    }


async def handle_list_chats(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for listing chats."""
    manager = get_chat_manager()
    project_id = payload.get("projectId", "")
    
    if not project_id:
        return {
            "success": False,
            "error": "Project ID is required",
        }
    
    try:
        chats = manager.list_chats(project_id)
        return {
            "success": True,
            "chats": chats,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_delete_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for deleting a chat."""
    manager = get_chat_manager()
    project_id = payload.get("projectId", "")
    chat_id = payload.get("chatId", "")
    
    if not project_id or not chat_id:
        return {
            "success": False,
            "error": "Project ID and Chat ID are required",
        }
    
    if manager.delete_chat(project_id, chat_id):
        return {
            "success": True,
        }
    return {
        "success": False,
        "error": f"Failed to delete chat: {chat_id}",
    }


async def handle_rename_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for renaming a chat."""
    manager = get_chat_manager()
    project_id = payload.get("projectId", "")
    chat_id = payload.get("chatId", "")
    title = payload.get("title", "")
    
    if not project_id or not chat_id:
        return {
            "success": False,
            "error": "Project ID and Chat ID are required",
        }
    
    if not title:
        return {
            "success": False,
            "error": "Title is required",
        }
    
    chat = manager.load_chat(project_id, chat_id)
    if not chat:
        return {
            "success": False,
            "error": f"Chat not found: {chat_id}",
        }
    
    chat["title"] = title
    if manager.save_chat(chat):
        return {
            "success": True,
            "chat": chat,
        }
    return {
        "success": False,
        "error": "Failed to rename chat",
    }


async def handle_get_turn_debug(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for fetching debug bundle for a specific turn."""
    manager = get_chat_manager()
    project_id = payload.get("projectId", "")
    chat_id = payload.get("chatId", "")
    turn_id = payload.get("turnId", "")
    
    if not project_id or not chat_id or not turn_id:
        return {
            "success": False,
            "error": "Project ID, Chat ID, and Turn ID are required",
        }
    
    chat = manager.load_chat(project_id, chat_id)
    if not chat:
        return {
            "success": False,
            "error": f"Chat not found: {chat_id}",
        }
    
    # Find the turn by ID
    turns = chat.get("turns", [])
    target_turn = None
    for turn in turns:
        if turn.get("id") == turn_id:
            target_turn = turn
            break
    
    if not target_turn:
        return {
            "success": False,
            "error": f"Turn not found: {turn_id}",
        }
    
    # Get debug bundle from meta
    meta = target_turn.get("meta", {})
    debug_bundle = meta.get("debug")
    
    if not debug_bundle:
        return {
            "success": False,
            "error": "Debug bundle not available for this turn. Debug mode may not have been enabled when this message was sent.",
        }
    
    return {
        "success": True,
        "debug": debug_bundle,
    }

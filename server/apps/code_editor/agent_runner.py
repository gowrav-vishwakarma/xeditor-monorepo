"""
Agent runner for XEditor Local Companion.
Handles agent mode execution with tool calling and streaming events.
"""

import uuid
import json
import re
from typing import Dict, Any, List, Optional, Callable, Awaitable
from datetime import datetime
from pathlib import Path

from apps.code_editor.chat_manager import ChatManager, get_chat_manager
from apps.code_editor.providers import get_provider, LLMRequest, LLMEvent
from apps.code_editor.parsers.base import get_parser_for_request, ParsedResponse, strip_thinking_tags
from apps.code_editor.tools.executor import get_tool_executor
from apps.code_editor.tools.executor import approve_command
from apps.code_editor.tools.registry import get_tool_registry
from apps.code_editor.tools.descriptions import convert_tools_to_openai_format
from apps.code_editor.tools.context import ToolContext
from apps.code_editor.prompts.manager import handle_resolve_prompt
from apps.code_editor.prompts.context_builder import get_context_builder
from apps.code_editor.project import get_project_manager
from apps.code_editor.sets.manager import get_set_manager


# ─────────────────────────────────────────────────────────────────────────────
# Debug Bundle Truncation Limits
# ─────────────────────────────────────────────────────────────────────────────

DEBUG_MAX_CONTENT_LENGTH = 20000  # Max chars per content field
DEBUG_MAX_TRACE_EVENTS = 100  # Max trace events to store
DEBUG_MAX_TOOL_OUTPUT_LENGTH = 10000  # Max chars per tool output

# Markers for command confirmation messages (client-side structured messages)
COMMAND_APPROVED_MARKER = "<!--COMMAND_APPROVED-->"
COMMAND_SKIPPED_MARKER = "<!--COMMAND_SKIPPED-->"


def truncate_string(value: str, max_length: int) -> str:
    """Truncate a string and add indicator if truncated."""
    if len(value) <= max_length:
        return value
    return value[:max_length] + f"\n... [truncated at {max_length} chars]"


# Default limit for tool result strings in LLM context
DEFAULT_TOOL_RESULT_MAX_CHARS = 50000


def format_tool_result_for_llm(
    tool_name: str,
    result: Any,
    max_chars: int = DEFAULT_TOOL_RESULT_MAX_CHARS,
) -> str:
    """
    Format a tool result for inclusion in LLM context.
    
    Handles special formatting for read_file (which returns structured data
    with pre-chunked content and metadata) and generic JSON serialization
    for other tools.
    
    Args:
        tool_name: Name of the tool
        result: Tool result (dict or other)
        max_chars: Maximum characters for the result string
    
    Returns:
        Formatted result string
    """
    if result is None:
        return ""
    
    # Sanitize result - remove large UI-only fields
    if isinstance(result, dict):
        result = {k: v for k, v in result.items() 
                  if k not in ("beforeContent", "afterContent")}
    
    if tool_name == "read_file" and isinstance(result, dict):
        # read_file returns structured data with pre-chunked content and metadata
        total_lines = result.get("totalLines", "?")
        truncated = result.get("truncated", False)
        strategy = result.get("strategy", "full")
        content = result.get("content", "")
        path = result.get("path", "")
        
        # Build metadata header
        meta_parts = [f"{total_lines} lines"]
        if truncated:
            meta_parts.append(f"strategy: {strategy}")
        meta_info = ", ".join(meta_parts)
        
        # Format: path, metadata, then content
        result_str = f"File: {path}\n[{meta_info}]\n\n{content}"
        
        # Apply cap as safety net
        if len(result_str) > max_chars:
            result_str = result_str[:max_chars] + f"\n... [truncated at {max_chars} chars]"
        
        return result_str
    else:
        # Other tools: JSON serialize and truncate if needed
        result_str = json.dumps(result) if isinstance(result, dict) else str(result)
        if len(result_str) > max_chars:
            result_str = result_str[:max_chars] + f"\n... [truncated at {max_chars} chars]"
        return result_str


def build_debug_bundle(
    turn_id: str,
    timestamp: int,
    mode: str,
    model_config: Dict[str, Any],
    set_id: str,
    prompt_template: Dict[str, Any],
    system_prompt: str,
    llm_messages: List[Dict[str, str]],
    trace_events: List[Dict[str, Any]],
    tool_calls: List[Dict[str, Any]],
    assistant_steps: Optional[List[Dict[str, Any]]] = None,
    parser_info: Optional[Dict[str, Any]] = None,
    llm_calls: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build a debug bundle with truncation applied.
    """
    # Helper to truncate a list of messages
    def truncate_messages(msgs: List[Dict[str, str]]) -> List[Dict[str, str]]:
        truncated = []
        for msg in msgs:
            truncated_msg = msg.copy()
            if "content" in truncated_msg and isinstance(truncated_msg["content"], str):
                truncated_msg["content"] = truncate_string(truncated_msg["content"], DEBUG_MAX_CONTENT_LENGTH)
            truncated.append(truncated_msg)
        return truncated

    # Truncate LLM messages content
    truncated_messages = truncate_messages(llm_messages)
    
    # Truncate LLM calls
    truncated_llm_calls = []
    if llm_calls:
        for call in llm_calls:
            call_copy = call.copy()
            if "messages" in call_copy:
                call_copy["messages"] = truncate_messages(call_copy["messages"])
            truncated_llm_calls.append(call_copy)
    
    # Truncate trace events
    truncated_events = trace_events[:DEBUG_MAX_TRACE_EVENTS]
    if len(trace_events) > DEBUG_MAX_TRACE_EVENTS:
        truncated_events.append({
            "type": "truncated",
            "message": f"Showing first {DEBUG_MAX_TRACE_EVENTS} of {len(trace_events)} events"
        })

    # Truncate assistant steps (raw assistant outputs per step)
    truncated_assistant_steps: List[Dict[str, Any]] = []
    if assistant_steps:
        for step in assistant_steps:
            step_copy = step.copy()
            raw_content = step_copy.get("rawAssistant")
            if isinstance(raw_content, str):
                step_copy["rawAssistant"] = truncate_string(raw_content, DEBUG_MAX_CONTENT_LENGTH)
            parsed = step_copy.get("parsed")
            if isinstance(parsed, dict):
                parsed_copy = parsed.copy()
                final_text = parsed_copy.get("finalText")
                if isinstance(final_text, str):
                    parsed_copy["finalText"] = truncate_string(final_text, DEBUG_MAX_CONTENT_LENGTH)
                step_copy["parsed"] = parsed_copy
            truncated_assistant_steps.append(step_copy)
    
    # Truncate tool call outputs
    truncated_tool_calls = []
    for tc in tool_calls:
        truncated_tc = tc.copy()
        if "result" in truncated_tc and truncated_tc["result"]:
            result_str = json.dumps(truncated_tc["result"]) if isinstance(truncated_tc["result"], dict) else str(truncated_tc["result"])
            if len(result_str) > DEBUG_MAX_TOOL_OUTPUT_LENGTH:
                truncated_tc["result"] = truncate_string(result_str, DEBUG_MAX_TOOL_OUTPUT_LENGTH)
                truncated_tc["resultTruncated"] = True
        truncated_tool_calls.append(truncated_tc)
    
    # Get prompt file path
    set_manager = get_set_manager()
    prompt_file_path: Optional[str] = None
    parser_file_path: Optional[str] = None
    
    set_obj = set_manager.get_set(set_id)
    if set_obj:
        family = model_config.get("family", "")
        version = model_config.get("version")
        prompt_path = set_obj.get_prompt_path(family, mode, version)
        if prompt_path:
            prompt_file_path = str(prompt_path)
        parser_path = set_obj.get_parser_path(family, version=version)
        if parser_path:
            parser_file_path = str(parser_path)
    
    return {
        "turnId": turn_id,
        "timestamp": timestamp,
        "model": {
            "id": model_config.get("id", ""),
            "provider": model_config.get("provider", ""),
            "family": model_config.get("family", ""),
            "version": model_config.get("version"),
            "runner": model_config.get("localCompanion", {}).get("runner"),
        },
        "prompt": {
            "setId": set_id,
            "mode": mode,
            "family": model_config.get("family", ""),
            "version": model_config.get("version"),
            "templateId": prompt_template.get("id", ""),
            "promptFilePath": prompt_file_path,
        },
        "parser": {
            "parserId": parser_info.get("id") if parser_info else None,
            "parserFilePath": parser_file_path,
        },
        "resolvedSystemPrompt": truncate_string(system_prompt, DEBUG_MAX_CONTENT_LENGTH),
        "llmMessages": truncated_messages,
        "llmCalls": truncated_llm_calls,
        "traceEvents": truncated_events,
        "toolCalls": truncated_tool_calls,
        "assistantSteps": truncated_assistant_steps,
    }


class AgentRunner:
    """
    Runs agent mode with tool calling and streaming events.
    """

    def __init__(self):
        self.chat_manager = get_chat_manager()
        self.max_steps = 50
    
    def _normalize_tool_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize tool arguments to match what the executor expects.
        
        Maps parameter names from tool descriptions to executor parameter names,
        and normalizes paths. This is the same normalization that HarmonyParser does.
        
        Args:
            tool_name: Name of the tool
            args: Raw arguments from tool call
            
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
        
        # Normalize path parameter (remove @ prefix, strip whitespace)
        # After mapping, the path should be in the "path" key
        if "path" in normalized and isinstance(normalized["path"], str):
            path = normalized["path"]
            # Remove @ prefix if present
            if path.startswith('@'):
                path = path[1:]
            normalized["path"] = path.strip()
        
        return normalized

    async def run_agent_turn(
        self,
        project_id: str,
        chat_id: str,
        user_message: str,
        user_context: List[Dict[str, Any]],
        mode: str,
        model_config: Dict[str, Any],
        on_event: Callable[[str, Dict[str, Any]], Awaitable[None]],
        debug: bool = False,
        # Sub-agent mode parameters
        parent_tool_call_id: Optional[str] = None,
        sub_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run a single agent turn with tool calling support.
        
        Args:
            project_id: Project ID
            chat_id: Chat ID
            user_message: User's message
            user_context: Context items from frontend
            mode: Mode (ask, plan, agent, debug)
            model_config: Model configuration
            on_event: Callback for streaming events
            debug: Whether to capture debug bundle for this turn
            parent_tool_call_id: If set, this is a sub-agent call (skip chat loading/saving)
            sub_agent_id: Unique ID for the sub-agent (used for event parentId linking)
            
        Returns:
            Dict with turn data
        """
        # Check if this is a sub-agent call
        is_sub_agent = parent_tool_call_id is not None
        
        # Load chat (skip for sub-agent mode)
        if is_sub_agent:
            # Sub-agent uses fresh context, not chat history
            chat = {"turns": []}
        else:
            chat = self.chat_manager.load_chat(project_id, chat_id)
            if not chat:
                raise ValueError(f"Chat not found: {chat_id}")

        # If user approved a pending command, we want to execute the pending run_command
        # without going back to LLM to request the tool call again.
        approved_command_id: Optional[str] = None
        skipped_command_user_message: Optional[str] = None
        
        if isinstance(user_message, str) and user_message.startswith(COMMAND_APPROVED_MARKER):
            try:
                payload_str = user_message[len(COMMAND_APPROVED_MARKER):]
                payload = json.loads(payload_str)
                if isinstance(payload, dict):
                    cmd_id = payload.get("id")
                    if isinstance(cmd_id, str) and cmd_id:
                        approved_command_id = cmd_id
            except Exception:
                approved_command_id = None
        
        # If user skipped a pending command, extract their continuation message
        elif isinstance(user_message, str) and user_message.startswith(COMMAND_SKIPPED_MARKER):
            try:
                payload_str = user_message[len(COMMAND_SKIPPED_MARKER):]
                payload = json.loads(payload_str)
                if isinstance(payload, dict):
                    cmd = payload.get("command", "")
                    user_msg = payload.get("user_message", "")
                    # Format a message for the LLM explaining the skip
                    skipped_command_user_message = (
                        f"User skipped the command: {cmd}\n\n"
                        f"User message: {user_msg}" if user_msg else f"User skipped the command: {cmd}"
                    )
            except Exception:
                skipped_command_user_message = None

        # Build prompt context
        context_builder = get_context_builder()
        prompt_context = await context_builder.build_prompt_context(
            project_id=project_id,
            mode=mode,
            set_id=model_config.get("setId", "default"),
            family=model_config.get("family", ""),
            version=model_config.get("version"),
            user_context=user_context,
        )

        # Compute token stats from chat history for prompt template variables
        session_token_stats = {
            "totalTokens": 0,
            "promptTokens": 0,
            "completionTokens": 0,
            "byFamily": {},
        }
        last_context_usage = {
            "usedPromptTokens": 0,
            "contextWindow": model_config.get("contextWindow", 0),
            "fillPercent": 0.0,
        }
        
        # Aggregate token stats from all previous turns in the chat
        for turn in chat.get("turns", []):
            turn_meta = turn.get("meta", {})
            turn_usage = turn_meta.get("usage", {})
            if turn_usage:
                session_token_stats["totalTokens"] += turn_usage.get("totalTokens", 0)
                session_token_stats["promptTokens"] += turn_usage.get("promptTokens", 0)
                session_token_stats["completionTokens"] += turn_usage.get("completionTokens", 0)
            
            # Track per-family usage
            model_snapshot = turn_meta.get("modelSnapshot", {})
            family = model_snapshot.get("family") or turn.get("modelId", "").split("-")[0]
            if family and turn_usage:
                if family not in session_token_stats["byFamily"]:
                    session_token_stats["byFamily"][family] = {
                        "totalTokens": 0,
                        "promptTokens": 0,
                        "completionTokens": 0,
                    }
                session_token_stats["byFamily"][family]["totalTokens"] += turn_usage.get("totalTokens", 0)
                session_token_stats["byFamily"][family]["promptTokens"] += turn_usage.get("promptTokens", 0)
                session_token_stats["byFamily"][family]["completionTokens"] += turn_usage.get("completionTokens", 0)
            
            # Update last context usage from the most recent turn
            context_usage = turn_meta.get("contextUsage", {})
            if context_usage:
                last_context_usage = context_usage

        # Resolve prompt with context
        prompt_response = await handle_resolve_prompt({
            "mode": mode,
            "family": model_config.get("family", ""),
            "version": model_config.get("version"),
            "setId": model_config.get("setId", "default"),
            "context": {
                "system_info": prompt_context.system_info,
                "available_tools": prompt_context.available_tools,
                "project_info": prompt_context.project_info,
                "user_context_summary": prompt_context.user_context_summary,
                "token_stats": session_token_stats,
                "context_usage": last_context_usage,
            },
        })
        
        if not prompt_response.get("success"):
            raise ValueError(f"Failed to resolve prompt: {prompt_response.get('error')}")
        
        prompt_template = prompt_response.get("template", {})
        system_prompt = prompt_template.get("systemPrompt", "")
        
        # Get set-aware parser
        parser = get_parser_for_request(
            set_id=model_config.get("setId", "default"),
            family=model_config.get("family", "default"),
            version=model_config.get("version"),
            mode=mode,
        )

        # We'll build the LLM context a bit later, because in some cases (command approval)
        # we want to execute a pending tool first and then send ONLY the tool output to the LLM.
        # For skipped commands, use the formatted skip message instead of the raw marker.
        if skipped_command_user_message:
            llm_user_message = skipped_command_user_message
        else:
            llm_user_message = user_message
        messages: List[Dict[str, str]] = []
        initial_messages: List[Dict[str, str]] = []
        llm_calls: List[Dict[str, Any]] = []

        turn_id = str(uuid.uuid4())
        turn_timestamp = int(datetime.now().timestamp() * 1000)
        
        accumulated_content = ""  # Raw content with tool call markers (for LLM context)
        thinking_content = ""
        final_text = ""  # Cleaned content without tool call markers (for streaming/saving)
        streamed_safe_content = ""  # Track what we've safely streamed to UI
        tool_calls: List[Dict[str, Any]] = []
        trace_events: List[Dict[str, Any]] = []
        file_changes: List[Dict[str, Any]] = []  # Store file_change events for persistence
        artifacts: List[Dict[str, Any]] = []  # Store artifacts (plans, files) created by tools
        assistant_steps: List[Dict[str, Any]] = [] if debug else []
        all_patches: List[Dict[str, Any]] = []  # Accumulate patches from all steps
        usage = None
        error_message: Optional[str] = None
        
        # Initialize usage aggregation variables for tracking across multiple LLM calls
        turn_usage_total: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        turn_usage_peak_prompt_tokens = 0  # Track peak prompt tokens for context fill calculation
        turn_llm_call_count = 0
        sub_agent_usage_total: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        tool_call_detected = False  # Flag to track if we detected a tool call but need to wait for "end" event
        
        current_step = 0
        last_parsed: Optional[ParsedResponse] = None
        current_thinking_id: Optional[str] = None  # Track current thinking event ID for trace events
        current_assistant_message_id: Optional[str] = None  # Track current assistant_message event ID for trace events

        # Helper to add parentId to trace events for sub-agent mode
        def add_trace_event(event: Dict[str, Any]) -> None:
            """Add a trace event, with parentId if in sub-agent mode."""
            if is_sub_agent and sub_agent_id and "parentId" not in event:
                event["parentId"] = sub_agent_id
            trace_events.append(event)
        
        # Wrapper for on_event that adds parentId for sub-agent mode
        async def emit_event(event_type: str, data: Dict[str, Any]) -> None:
            """Emit an event, adding parentId if in sub-agent mode."""
            if is_sub_agent and sub_agent_id and "parentId" not in data:
                data = {**data, "parentId": sub_agent_id}
            await on_event(event_type, data)

        # Add sub_agent_start event to trace_events if this is a sub-agent call
        # NOTE: For delegate_task, the event is already emitted in executor.py BEFORE calling run_agent_turn
        # to ensure it reaches the frontend during streaming. We still add it to trace_events here
        # for consistency and to ensure it's included in the returned trace_events.
        # We don't emit it again here to avoid duplicates - delegate_task handles the emission.
        if is_sub_agent and sub_agent_id:
            sub_agent_start_event = {
                "type": "sub_agent_start",
                "id": sub_agent_id,
                "timestamp": turn_timestamp,
                "parentId": parent_tool_call_id,  # This links to the delegate_task tool call
                "agentName": "Research Assistant",
                "purpose": user_message[:100] + ("..." if len(user_message) > 100 else ""),
                "input": {"task": user_message},
            }
            trace_events.append(sub_agent_start_event)
            # Don't emit here - delegate_task already emitted it before calling run_agent_turn
            # This prevents duplicate events while ensuring it's in trace_events for persistence

        # If this turn is a COMMAND_APPROVED message, execute the pending run_command immediately,
        # and only then call the LLM with the tool output (avoid an extra LLM round-trip just to re-emit the tool call).
        # Skip for sub-agent mode (sub-agents don't handle command approvals)
        if approved_command_id and not is_sub_agent:
            pending_args: Optional[Dict[str, Any]] = None
            pending_command: Optional[str] = None
            # Find the most recent run_command tool call that requested confirmation for this id
            for turn in reversed(chat.get("turns", [])):
                for tc in reversed(turn.get("toolCalls", [])):
                    if tc.get("tool") != "run_command":
                        continue
                    result = tc.get("result")
                    if not isinstance(result, dict):
                        continue
                    if result.get("action") != "confirm_command":
                        continue
                    if result.get("id") != approved_command_id:
                        continue
                    args = tc.get("args")
                    if isinstance(args, dict):
                        pending_args = args
                    cmd = result.get("command")
                    if isinstance(cmd, str):
                        pending_command = cmd
                    break
                if pending_args:
                    break

            if pending_args:
                # Ensure command is approved (idempotent)
                approve_command(approved_command_id)

                # Compute project root (same logic as tool execution path)
                project_manager = get_project_manager()
                project = project_manager.get_project(project_id)
                project_root = None
                if project:
                    folders = project.get("folders", [])
                    if folders and len(folders) > 0:
                        folder_paths = []
                        for f in folders:
                            folder_path = f.get("systemPath") or f.get("path", "")
                            if folder_path:
                                folder_paths.append(Path(folder_path))
                        if folder_paths:
                            if len(folder_paths) > 1:
                                common_parts = []
                                for parts in zip(*[p.parts for p in folder_paths]):
                                    if len(set(parts)) == 1:
                                        common_parts.append(parts[0])
                                    else:
                                        break
                                if common_parts:
                                    project_root = str(Path(*common_parts))
                                else:
                                    project_root = str(folder_paths[0].parent)
                            else:
                                project_root = str(folder_paths[0])

                set_id = model_config.get("setId", "default")
                family = model_config.get("family", "")
                version = model_config.get("version")
                tool_executor = get_tool_executor(
                    project_root=project_root,
                    mode=mode,
                    set_id=set_id,
                    family=family,
                    version=version,
                    project_id=project_id,
                )

                tool_call_id = f"resume_run_command_{uuid.uuid4()}"
                
                # Execute the command silently (no tool_start/tool_result events, not saved to tool_calls)
                # The user already saw and approved the command, so we don't show the tool card again.
                # The result will be presented by the LLM in its response.
                tool_result = await tool_executor.execute(
                    "run_command",
                    pending_args,
                    # Don't pass on_event to avoid streaming chunks to UI
                    on_event=None,
                    tool_call_id=tool_call_id,
                )
                
                # Don't add to tool_calls - the command was already shown in the previous turn
                # and the result will be presented by the LLM in its response

                result_for_llm: Any = tool_result.result if tool_result.success else {"error": tool_result.error}
                result_str = format_tool_result_for_llm("run_command", result_for_llm)

                cmd_label = pending_command or (pending_args.get("command") if isinstance(pending_args, dict) else None)
                cmd_label = cmd_label if isinstance(cmd_label, str) else ""
                llm_user_message = (
                    f"User approved running the command.\n"
                    f"Command: {cmd_label}\n\n"
                    f"Tool Result: {result_str}\n\n"
                    f"Please present the command output to the user and summarize any important details."
                )

        # Build initial context (after optional pre-execution)
        if is_sub_agent:
            # Sub-agent uses fresh context with just the system prompt and user task
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": llm_user_message},
            ]
        else:
            messages = self.chat_manager.build_llm_context(
                chat,
                llm_user_message,
                user_context,
                system_prompt,
                family=model_config.get("family", "default"),
                set_id=model_config.get("setId", "default"),
                version=model_config.get("version"),
            )
        # Capture initial messages for debug (before any tool calls modify it)
        initial_messages = [msg.copy() for msg in messages] if debug else []

        # Agent loop
        while current_step < self.max_steps:
            current_step += 1
            
            # Emit step_start event for iterations after the first (processing tool results)
            if current_step > 1:
                await emit_event("step_start", {
                    "step": current_step,
                    "reason": "processing_tool_result",
                })
            
            # Stream LLM response
            accumulated_content = ""
            thinking_content = ""
            thinking_started = False
            current_thinking_id = None  # Reset thinking ID for new step
            current_assistant_message_id = None  # Reset assistant message ID for new step
            streamed_safe_content = ""  # Reset safe content tracking for new step
            
            try:
                # Extract prompt parameters (including extra parameters like reasoning.effort)
                prompt_params = prompt_template.get("parameters", {})
                prompt_temperature = prompt_params.get("temperature", 0.7)
                prompt_max_tokens = prompt_params.get("maxTokens")
                # Get all extra parameters (excluding temperature and maxTokens)
                prompt_extra = {k: v for k, v in prompt_params.items() if k not in ("temperature", "maxTokens")}
                
                # Get model extraPayload (if any)
                model_extra_payload = model_config.get("extraPayload") or {}
                
                # Merge: prompt parameters first (defaults), then model extraPayload overrides
                # This allows model-level config to override prompt defaults
                merged_extra_payload = {**prompt_extra, **model_extra_payload}
                
                # Build provider config
                provider_config = {
                    "provider": model_config.get("provider", ""),
                    "id": model_config.get("id", ""),
                    "connection": model_config.get("connection", {}),
                    "auth": model_config.get("connection", {}).get("auth", {}),
                    "localCompanion": model_config.get("localCompanion", {}),
                    "family": model_config.get("family"),
                    "version": model_config.get("version"),
                }
                
                # Capture messages for debug before sending to LLM
                if debug:
                    llm_calls.append({
                        "step": current_step,
                        "timestamp": int(datetime.now().timestamp() * 1000),
                        "messages": [msg.copy() for msg in messages],
                    })

                # Build tools for native LiteLLM tool calling
                tools_openai = convert_tools_to_openai_format(prompt_context.available_tools)

                # Build LLM request
                llm_request = LLMRequest(
                    model_id=model_config.get("id", ""),
                    messages=messages,
                    temperature=prompt_temperature,
                    max_tokens=prompt_max_tokens,
                    extra_payload=merged_extra_payload,
                    tools=tools_openai if tools_openai else None,
                    tool_choice="auto",
                    provider_params=model_config.get("providerParams") or {},
                    provider=model_config.get("provider", ""),
                    connection=model_config.get("connection", {}),
                    auth=model_config.get("connection", {}).get("auth", {}),
                    family=model_config.get("family"),
                    version=model_config.get("version"),
                    mode=mode,
                )
                
                # Get provider and stream
                provider = get_provider(provider_config)
                received_thinking_from_provider = False
                tool_call_detected = False  # Reset flag for this LLM call
                
                async for event in provider.stream(llm_request):
                    if event.type == "thinking":
                        # Provider emits structured thinking events directly
                        received_thinking_from_provider = True
                        if event.content:
                            if not thinking_started:
                                # Create new thinking trace event (only if we don't already have one)
                                if current_thinking_id is None:
                                    current_thinking_id = str(uuid.uuid4())
                                    current_timestamp = int(datetime.now().timestamp() * 1000)
                                    trace_events.append({
                                        "type": "thinking",
                                        "id": current_thinking_id,
                                        "timestamp": current_timestamp,
                                        "content": "",
                                        "includeInContext": False,
                                    })
                                    await emit_event("thinking_start", {})
                                thinking_started = True
                            thinking_content += event.content
                            # Update thinking trace event content
                            if current_thinking_id:
                                for te in trace_events:
                                    if te.get("id") == current_thinking_id and te.get("type") == "thinking":
                                        te["content"] = thinking_content
                                        break
                            await emit_event("thinking_chunk", {"content": event.content})
                    
                    elif event.type == "content":
                        content_chunk = event.content or ""
                        
                        # Guard: if provider already emitted structured thinking events,
                        # strip any thinking tags from content to prevent duplication
                        if received_thinking_from_provider:
                            content_chunk = strip_thinking_tags(content_chunk)
                            if not content_chunk:
                                # Chunk was only thinking content, skip it
                                continue
                        
                        accumulated_content += content_chunk

                        # CRITICAL FIX: Strip thinking tags from accumulated_content BEFORE parsing
                        # This prevents the parser from extracting thinking when provider already emitted structured events
                        # Even if individual chunks were stripped, accumulated_content might still have tags spanning chunks
                        content_to_parse = accumulated_content
                        if received_thinking_from_provider:
                            content_to_parse = strip_thinking_tags(accumulated_content)

                        # CRITICAL FIX: Get streamable content FIRST, before checking for tool calls
                        # This ensures safe content is streamed even if a tool call is detected
                        safe_content, is_tool_pending = parser.get_streamable_content(content_to_parse)
                        
                        # Stream safe content BEFORE checking for tool calls
                        # This prevents Harmony tokens from leaking into the UI
                        if safe_content and not is_tool_pending:
                            # Strip thinking tags from full safe_content before computing delta.
                            # Must strip the full content, not the delta, because <think> can span chunks.
                            # Provider may emit structured thinking (reasoning_content), or parser
                            # may extract from <think> tags (LM Studio, etc.). In both cases we
                            # must not show <think> in the main content area.
                            stripped_safe = strip_thinking_tags(safe_content)
                            if len(stripped_safe) > len(streamed_safe_content):
                                new_safe_content = stripped_safe[len(streamed_safe_content):]
                                if new_safe_content:
                                    
                                    # Create or append to assistant_message trace event
                                    if current_assistant_message_id is None:
                                        current_assistant_message_id = str(uuid.uuid4())
                                        current_timestamp = int(datetime.now().timestamp() * 1000)
                                        trace_events.append({
                                            "type": "assistant_message",
                                            "id": current_assistant_message_id,
                                            "timestamp": current_timestamp,
                                            "content": "",
                                            "step": current_step,
                                        })
                                    # Append content to current assistant_message event
                                    if current_assistant_message_id:
                                        for te in trace_events:
                                            if te.get("id") == current_assistant_message_id and te.get("type") == "assistant_message":
                                                te["content"] = (te.get("content", "") or "") + new_safe_content
                                                break
                                    
                                    await emit_event("content_chunk", {"content": new_safe_content})
                                    streamed_safe_content = stripped_safe
                                    final_text = stripped_safe

                        # Parse incrementally for tool calls and patches
                        parsed = parser.parse(content_to_parse)

                        # Fallback: if provider didn't emit thinking events,
                        # try to extract from content (for models that emit <think> tags)
                        if not received_thinking_from_provider and parsed.thinking:
                            if not thinking_started:
                                # Create new thinking trace event (only if we don't already have one)
                                if current_thinking_id is None:
                                    current_thinking_id = str(uuid.uuid4())
                                    current_timestamp = int(datetime.now().timestamp() * 1000)
                                    trace_events.append({
                                        "type": "thinking",
                                        "id": current_thinking_id,
                                        "timestamp": current_timestamp,
                                        "content": "",
                                        "includeInContext": False,
                                    })
                                    await emit_event("thinking_start", {})
                                thinking_started = True

                            if parsed.thinking != thinking_content:
                                new_thinking = parsed.thinking[len(thinking_content):]
                                thinking_content = parsed.thinking
                                # Update thinking trace event content
                                if current_thinking_id:
                                    for te in trace_events:
                                        if te.get("id") == current_thinking_id and te.get("type") == "thinking":
                                            te["content"] = thinking_content
                                            break
                                if new_thinking:
                                    await emit_event("thinking_chunk", {"content": new_thinking})
                        
                        # Native tool calling: tool calls come from provider events only, not from parsing
                        # Keep last_parsed for patches and final_text
                        last_parsed = parsed
                    
                    elif event.type == "tool_call":
                        # Provider emitted structured tool call event (native LiteLLM tools)
                        if event.tool_call:
                            tool_name = event.tool_call.get("tool")
                            tool_args = event.tool_call.get("args", {})
                            tool_call_id = event.tool_call.get("id") or f"call_{uuid.uuid4().hex[:12]}"
                            normalized_args = self._normalize_tool_args(tool_name, tool_args)
                            last_parsed = ParsedResponse(
                                tool_call={"tool": tool_name, "args": normalized_args, "id": tool_call_id},
                                final_text=final_text,
                            )
                            tool_call_detected = True

                            # Stream any remaining content (native tools: no Harmony tokens in content)
                            if accumulated_content:
                                content_to_parse = strip_thinking_tags(accumulated_content) if received_thinking_from_provider else accumulated_content
                                safe_content, _ = parser.get_streamable_content(content_to_parse)
                                stripped_safe = strip_thinking_tags(safe_content)
                                if stripped_safe and len(stripped_safe) > len(streamed_safe_content):
                                    remaining_content = stripped_safe[len(streamed_safe_content):]
                                    if remaining_content:
                                        if current_assistant_message_id is None:
                                            current_assistant_message_id = str(uuid.uuid4())
                                            current_timestamp = int(datetime.now().timestamp() * 1000)
                                            trace_events.append({
                                                "type": "assistant_message",
                                                "id": current_assistant_message_id,
                                                "timestamp": current_timestamp,
                                                "content": "",
                                                "step": current_step,
                                            })
                                        if current_assistant_message_id:
                                            for te in trace_events:
                                                if te.get("id") == current_assistant_message_id and te.get("type") == "assistant_message":
                                                    te["content"] = (te.get("content", "") or "") + remaining_content
                                                    break
                                        await emit_event("content_chunk", {"content": remaining_content})
                                        streamed_safe_content = stripped_safe
                                        final_text = stripped_safe

                            if thinking_started:
                                await emit_event("thinking_end", {})
                                current_thinking_id = None
                            # Do not break - continue to receive "end" event for usage
                    
                    elif event.type == "end":
                        usage = event.usage
                        
                        # Accumulate usage across all LLM calls in this turn
                        if usage:
                            turn_llm_call_count += 1
                            turn_usage_total["prompt_tokens"] += usage.get("prompt_tokens", 0)
                            turn_usage_total["completion_tokens"] += usage.get("completion_tokens", 0)
                            turn_usage_total["total_tokens"] += usage.get("total_tokens", 0)
                            
                            # Track peak prompt tokens for context fill calculation
                            prompt_tokens = usage.get("prompt_tokens", 0)
                            if prompt_tokens > turn_usage_peak_prompt_tokens:
                                turn_usage_peak_prompt_tokens = prompt_tokens

                        # Final parse for patches and final_text
                        if accumulated_content:
                            content_to_parse_final = strip_thinking_tags(accumulated_content) if received_thinking_from_provider else accumulated_content
                            parsed_final = parser.parse(content_to_parse_final)
                            if tool_call_detected and last_parsed and last_parsed.tool_call:
                                # Preserve tool_call from native event; merge patches and final_text from parser
                                last_parsed = ParsedResponse(
                                    final_text=parsed_final.final_text or last_parsed.final_text,
                                    tool_call=last_parsed.tool_call,
                                    patches=parsed_final.patches,
                                    thinking=parsed_final.thinking or last_parsed.thinking,
                                )
                            else:
                                last_parsed = parsed_final

                        if accumulated_content and last_parsed:
                            # Use parsed.final_text which has tool calls removed (or content as-is for native tools)
                            # This ensures Harmony tokens never leak into the UI
                            if last_parsed.final_text:
                                # parsed.final_text already has tool calls removed by parser._remove_complete_tool_calls()
                                # Always strip thinking tags (parser strips, but defensive for edge cases)
                                final_text = strip_thinking_tags(last_parsed.final_text)
                                
                                # Stream any remaining content that wasn't streamed yet
                                # Use final_text (which is clean) instead of safe_content
                                if len(final_text) > len(streamed_safe_content):
                                    remaining_content = final_text[len(streamed_safe_content):]
                                    if remaining_content:
                                        # Create or append to assistant_message trace event
                                        if current_assistant_message_id is None:
                                            current_assistant_message_id = str(uuid.uuid4())
                                            current_timestamp = int(datetime.now().timestamp() * 1000)
                                            trace_events.append({
                                                "type": "assistant_message",
                                                "id": current_assistant_message_id,
                                                "timestamp": current_timestamp,
                                                "content": "",
                                                "step": current_step,
                                            })
                                        # Append content to current assistant_message event
                                        if current_assistant_message_id:
                                            for te in trace_events:
                                                if te.get("id") == current_assistant_message_id and te.get("type") == "assistant_message":
                                                    te["content"] = (te.get("content", "") or "") + remaining_content
                                                    break
                                        
                                        await emit_event("content_chunk", {"content": remaining_content})
                                        streamed_safe_content = final_text
                                
                                # CRITICAL FIX: Keep accumulated_content unchanged (raw with tool call markers)
                                # This ensures LLM context includes the original tool call markers
                                # final_text is already set correctly for streaming/saving

                            # Fallback thinking extraction if provider didn't emit any
                            if not received_thinking_from_provider and last_parsed.thinking:
                                thinking_content = last_parsed.thinking
                                if not thinking_started:
                                    # Create new thinking trace event (only if we don't already have one)
                                    if current_thinking_id is None:
                                        current_thinking_id = str(uuid.uuid4())
                                        current_timestamp = int(datetime.now().timestamp() * 1000)
                                        trace_events.append({
                                            "type": "thinking",
                                            "id": current_thinking_id,
                                            "timestamp": current_timestamp,
                                            "content": thinking_content,
                                            "includeInContext": False,
                                        })
                                        await emit_event("thinking_start", {})
                                    thinking_started = True
                                else:
                                    # Update existing thinking trace event
                                    if current_thinking_id:
                                        for te in trace_events:
                                            if te.get("id") == current_thinking_id and te.get("type") == "thinking":
                                                te["content"] = thinking_content
                                                break
                                await emit_event("thinking_chunk", {"content": thinking_content})

                            if thinking_started:
                                await emit_event("thinking_end", {})
                                current_thinking_id = None  # Clear current thinking ID

                            # Accumulate patches from this step
                            if last_parsed.patches:
                                all_patches.extend(last_parsed.patches)
                            
                            # Debug: keep the raw assistant output for this step
                            if debug:
                                assistant_steps.append({
                                    "step": current_step,
                                    "rawAssistant": accumulated_content,
                                    "parsed": {
                                        "finalText": last_parsed.final_text,
                                        "toolCall": last_parsed.tool_call,
                                        "patches": last_parsed.patches,
                                        "thinking": last_parsed.thinking or thinking_content,
                                    },
                                })
                        
                        # If we detected a tool call earlier, break now after accumulating usage
                        if tool_call_detected:
                            break
                        
                        break
                    
                    elif event.type == "error":
                        error_message = event.error
                        await emit_event("error", {"message": error_message or "Unknown error"})
                        break
                
            except Exception as e:
                error_message = str(e)
                await emit_event("error", {"message": error_message})

            # If error occurred, break out of agent loop
            if error_message:
                break

            # Check for tool call
            if last_parsed and last_parsed.tool_call:
                try:
                    tool_call = last_parsed.tool_call
                    tool_name = tool_call.get("tool", "")
                    tool_args = tool_call.get("args", {})
                    # Use native tool_call_id from model (required for OpenAI message format)
                    tool_call_id = tool_call.get("id") or str(uuid.uuid4())
                    
                    # Resolve tool name (handle malformed names with token artifacts like <|channel|>)
                    tool_registry = get_tool_registry()
                    set_id = model_config.get("setId", "default")
                    family = model_config.get("family", "")
                    version = model_config.get("version")
                    resolved_name = tool_registry.resolve_tool_name(tool_name, mode, set_id, family, version)
                    if resolved_name:
                        tool_name = resolved_name
                    
                    # Reset assistant message ID when tool starts - next text will be a new segment
                    current_assistant_message_id = None
                    
                    # Emit tool start event
                    tool_start_timestamp = int(datetime.now().timestamp() * 1000)
                    # Add tool_call trace event with proper timestamp
                    trace_events.append({
                        "type": "tool_call",
                        "id": tool_call_id,
                        "timestamp": tool_start_timestamp,
                        "toolName": tool_name,
                        "arguments": tool_args,
                        "output": "",  # Initialize output for streaming
                    })
                    await emit_event("tool_start", {
                        "tool": tool_name,
                        "args": tool_args,
                        "id": tool_call_id,
                    })
                except Exception as tool_error:
                    error_message = f"Error processing tool call: {str(tool_error)}"
                    await emit_event("error", {"message": error_message})
                    break
                
                # Get project root for tool execution
                project_manager = get_project_manager()
                project = project_manager.get_project(project_id)
                project_root = None
                if project:
                    # Get project root from folders (this is the actual project being edited, not the IDE workspace)
                    folders = project.get("folders", [])
                    if folders and len(folders) > 0:
                        # Try both 'path' and 'systemPath' fields (folders may have either)
                        folder_paths = []
                        for f in folders:
                            folder_path = f.get("systemPath") or f.get("path", "")
                            if folder_path:
                                folder_paths.append(Path(folder_path))
                        
                        if folder_paths:
                            if len(folder_paths) > 1:
                                # Multi-folder project: find common root
                                common_parts = []
                                for parts in zip(*[p.parts for p in folder_paths]):
                                    if len(set(parts)) == 1:
                                        common_parts.append(parts[0])
                                    else:
                                        break
                                if common_parts:
                                    project_root = str(Path(*common_parts))
                                else:
                                    # No common root, use first folder's parent
                                    project_root = str(folder_paths[0].parent)
                            else:
                                    # Single folder: use the folder itself as root (paths are relative to project root)
                                    project_root = str(folder_paths[0])
                
                # Check if tool is allowed for this set/mode (tool_name is already resolved above)
                
                if not tool_registry.is_tool_allowed(tool_name, mode, set_id, family, version):
                    # Tool is not in the allowlist
                    tool_result_data = {
                        "success": False,
                        "error": f"Tool '{tool_name}' is not allowed for this prompt set/mode. Available tools: {tool_registry.get_tools_for_mode(mode, set_id, family, version)}",
                    }
                    
                    # Store the blocked tool call
                    tool_call_data = {
                        "id": tool_call_id,
                        "tool": tool_name,
                        "args": tool_args,
                        "result": None,
                        "error": tool_result_data["error"],
                        "includeInContext": True,
                    }
                    tool_calls.append(tool_call_data)
                    
                    # Update tool_call trace event output with error
                    for te in trace_events:
                        if te.get("id") == tool_call_id and te.get("type") == "tool_call":
                            te["output"] = f"Error: {tool_result_data['error']}"
                            break
                    
                    # Emit tool result event with error
                    tool_result_event_data = {
                        "tool": tool_name,
                        "result": None,
                        "error": tool_result_data["error"],
                        "id": tool_call_id,
                    }
                    await emit_event("tool_result", tool_result_event_data)
                    # Persist tool_result trace event (needed for nested/sub-agent replay after reload)
                    trace_events.append({
                        "type": "tool_result",
                        "id": f"result-{tool_call_id}",
                        "timestamp": int(datetime.now().timestamp() * 1000),
                        "toolCallId": tool_call_id,
                        "result": None,
                        "error": tool_result_data["error"],
                        **({"parentId": sub_agent_id} if is_sub_agent and sub_agent_id else {}),
                    })
                    
                    # Add error to messages for next iteration (native tool format)
                    messages.append({
                        "role": "assistant",
                        "content": final_text or "",
                        "tool_calls": [{
                            "id": tool_call_id,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": json.dumps(tool_args)},
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": f"Tool Error: {tool_result_data['error']}",
                    })
                    
                    continue
                
                # Execute tool based on type (system vs custom)
                if tool_registry.is_system_tool(tool_name):
                    # System tool - use ToolExecutor
                    tool_executor = get_tool_executor(
                        project_root=project_root,
                        mode=mode,
                        set_id=set_id,
                        family=model_config.get("family"),
                        version=model_config.get("version"),
                        project_id=project_id,
                    )
                    # Use emit_event for tool execution to ensure sub-agent events get parentId
                    # For delegate_task, we also pass the original on_event so it can emit sub_agent_start
                    # directly (bypassing the wrapper) to ensure it reaches the frontend immediately
                    tool_result = await tool_executor.execute(
                        tool_name,
                        tool_args,
                        on_event=emit_event,
                        tool_call_id=tool_call_id,
                        model_config=model_config,  # Pass model_config for delegate_task
                        original_on_event=on_event if tool_name == "delegate_task" else None,  # Pass original for delegate_task
                    )
                else:
                    # Custom tool - load module and execute
                    tool_module = tool_registry.load_tool_module(
                        tool_name,
                        mode,
                        set_id,
                        family,
                        version,
                    )
                    
                    if tool_module and hasattr(tool_module, tool_name):
                        tool_func = getattr(tool_module, tool_name)
                        try:
                            # Create ToolContext for custom tool
                            tool_context = ToolContext(
                                project_root=Path(project_root) if project_root else Path.cwd(),
                                project_id=project_id,
                                llm_config=model_config,
                                chat_id=chat_id,
                                tool_call_id=tool_call_id,
                                emit_event=on_event,
                            )
                            
                            # Call custom tool
                            result = await tool_func(tool_args, tool_context)
                            
                            # Convert to ToolResult-like object
                            from apps.code_editor.tools.executor import ToolResult
                            tool_result = ToolResult(
                                success=result.get("success", False),
                                result=result.get("result"),
                                error=result.get("error"),
                            )
                        except Exception as e:
                            from apps.code_editor.tools.executor import ToolResult
                            tool_result = ToolResult(
                                success=False,
                                error=f"Custom tool execution failed: {str(e)}",
                            )
                    else:
                        from apps.code_editor.tools.executor import ToolResult
                        tool_result = ToolResult(
                            success=False,
                            error=f"Custom tool module not found or missing function: {tool_name}",
                        )
                
                # Store tool call
                raw_tool_result: Any = tool_result.result if tool_result.success else None
                merged_subagent_trace_events: Optional[List[Dict[str, Any]]] = None

                # Special handling for delegate_task: keep UI/LLM context clean and merge sub-agent trace events
                tool_result_for_ui: Any = raw_tool_result
                tool_result_for_llm: Any = raw_tool_result
                if tool_name == "delegate_task" and tool_result.success and isinstance(raw_tool_result, dict):
                    tool_result_for_ui = raw_tool_result.get("answer", "")
                    tool_result_for_llm = tool_result_for_ui
                    sub_trace_events = raw_tool_result.get("traceEvents")
                    if isinstance(sub_trace_events, list):
                        merged_subagent_trace_events = sub_trace_events

                tool_call_data = {
                    "id": tool_call_id,
                    "tool": tool_name,
                    "args": tool_args,
                    "result": tool_result_for_ui if tool_result.success else None,
                    "error": tool_result.error,
                    "includeInContext": True,  # Default: include in context
                }
                tool_calls.append(tool_call_data)

                # Merge sub-agent trace events into parent trace_events so they persist after reload
                if merged_subagent_trace_events:
                    trace_events.extend(merged_subagent_trace_events)
                    
                    # Extract sub-agent usage from sub_agent_end events and accumulate
                    # Note: sub_agent_end event has usage in camelCase format
                    for event in merged_subagent_trace_events:
                        if event.get("type") == "sub_agent_end" and event.get("usage"):
                            sub_usage = event.get("usage", {})
                            # Convert camelCase to snake_case for accumulation
                            sub_agent_usage_total["prompt_tokens"] += sub_usage.get("promptTokens", sub_usage.get("prompt_tokens", 0))
                            sub_agent_usage_total["completion_tokens"] += sub_usage.get("completionTokens", sub_usage.get("completion_tokens", 0))
                            sub_agent_usage_total["total_tokens"] += sub_usage.get("totalTokens", sub_usage.get("total_tokens", 0))
                
                # Update tool_call trace event output with final result/error
                for te in trace_events:
                    if te.get("id") == tool_call_id and te.get("type") == "tool_call":
                        if tool_result.success and tool_result.result is not None:
                            # Format result as string for output field
                            if tool_name == "delegate_task" and isinstance(raw_tool_result, dict):
                                te["output"] = str(tool_result_for_ui or "")
                            elif isinstance(tool_result.result, str):
                                te["output"] = tool_result.result
                            elif isinstance(tool_result.result, dict):
                                te["output"] = json.dumps(tool_result.result, indent=2)
                            else:
                                te["output"] = str(tool_result.result)
                        elif tool_result.error:
                            # Include error message in output
                            te["output"] = f"Error: {tool_result.error}"
                        break
                
                # Emit tool result event
                tool_result_event_data = {
                    "tool": tool_name,
                    "result": tool_result_for_ui if tool_result.success else None,
                    "error": tool_result.error,
                    "id": tool_call_id,
                }
                await emit_event("tool_result", tool_result_event_data)
                # Persist tool_result trace event (needed for nested/sub-agent replay after reload)
                trace_events.append({
                    "type": "tool_result",
                    "id": f"result-{tool_call_id}",
                    "timestamp": int(datetime.now().timestamp() * 1000),
                    "toolCallId": tool_call_id,
                    "result": tool_result_event_data.get("result"),
                    **({"error": tool_result.error} if tool_result.error else {}),
                    **({"parentId": sub_agent_id} if is_sub_agent and sub_agent_id else {}),
                })
                
                # Emit file_change event if tool modified/created a file with content for diff preview
                if tool_result.success and tool_result.result:
                    result_dict = tool_result.result if isinstance(tool_result.result, dict) else {}
                    change_type = result_dict.get("changeType", "modified")
                    # For modified files: emit when beforeContent is present (can show diff)
                    # For created files: emit when afterContent is present (can show new file content)
                    should_emit = False
                    if change_type == "modified" and result_dict.get("beforeContent") is not None:
                        should_emit = True
                    elif change_type == "created" and result_dict.get("afterContent") is not None:
                        should_emit = True
                    
                    if should_emit:
                        file_change_data = {
                            "path": result_dict.get("path", ""),
                            "changeType": change_type,
                            "beforeContent": result_dict.get("beforeContent"),
                            "afterContent": result_dict.get("afterContent"),
                            "toolCallId": tool_call_id,
                        }
                        # Store file_change for persistence
                        file_changes.append(file_change_data)
                        # Add to trace_events for turn meta (use current timestamp)
                        current_timestamp = int(datetime.now().timestamp() * 1000)
                        trace_events.append({
                            "type": "file_change",
                            "id": f"file_change_{tool_call_id}",
                            "timestamp": current_timestamp,
                            "toolCallId": tool_call_id,
                            "path": file_change_data["path"],
                            "changeType": file_change_data["changeType"],
                            "beforeContent": file_change_data.get("beforeContent"),
                            "afterContent": file_change_data.get("afterContent"),
                        })
                        await emit_event("file_change", file_change_data)
                    
                    # Extract artifacts from tool result (e.g., plan files)
                    if result_dict.get("action") == "open_in_editor":
                        artifact_path = result_dict.get("plan_file_path") or result_dict.get("file_path")
                        if artifact_path:
                            # Determine artifact type based on tool or file extension
                            artifact_type = "plan" if tool_name == "create_plan" else "file"
                            # Extract display name from path or result
                            artifact_name = result_dict.get("filename") or artifact_path.split("/")[-1]
                            
                            artifacts.append({
                                "path": artifact_path,
                                "type": artifact_type,
                                "name": artifact_name,
                                "toolCallId": tool_call_id,
                            })
                
                # Append tool result to messages for next iteration (native OpenAI tool format)
                if tool_result.success:
                    result_str = format_tool_result_for_llm(tool_name, tool_result_for_llm)
                    messages.append({
                        "role": "assistant",
                        "content": final_text or "",
                        "tool_calls": [{
                            "id": tool_call_id,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": json.dumps(tool_args)},
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result_str,
                    })
                else:
                    messages.append({
                        "role": "assistant",
                        "content": final_text or "",
                        "tool_calls": [{
                            "id": tool_call_id,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": json.dumps(tool_args)},
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": f"Tool Error: {tool_result.error}",
                    })
                
                # Special handling for ask_question: stop agent loop and wait for user response
                # The frontend will display the question form and user response will come as a new user message
                if tool_name == "ask_question" and tool_result.success:
                    # Break out of agent loop - don't continue iterating
                    break

                # Special handling for confirm_command: stop agent loop and wait for user approval/skip
                # Avoid an extra LLM call that would just ask for confirmation in text.
                if tool_result.success and tool_result.result and isinstance(tool_result.result, dict):
                    if tool_result.result.get("action") == "confirm_command":
                        break
                
                # Continue loop for other tools
                continue
            
            # No tool call - final answer
            break

        # Create turn data
        # If there's an error, don't include in context and store error in meta
        has_error = error_message is not None
        
        # Build usage breakdown: main agent vs sub-agents
        # Convert to camelCase for client compatibility
        main_usage = {
            "promptTokens": turn_usage_total["prompt_tokens"],
            "completionTokens": turn_usage_total["completion_tokens"],
            "totalTokens": turn_usage_total["total_tokens"],
        }
        sub_agents_usage = {
            "promptTokens": sub_agent_usage_total["prompt_tokens"],
            "completionTokens": sub_agent_usage_total["completion_tokens"],
            "totalTokens": sub_agent_usage_total["total_tokens"],
        }
        total_usage = {
            "promptTokens": main_usage["promptTokens"] + sub_agents_usage["promptTokens"],
            "completionTokens": main_usage["completionTokens"] + sub_agents_usage["completionTokens"],
            "totalTokens": main_usage["totalTokens"] + sub_agents_usage["totalTokens"],
        }
        
        usage_breakdown = {
            "main": main_usage,
            "subAgents": sub_agents_usage,
            "total": total_usage,
            "llmCallCount": turn_llm_call_count if turn_llm_call_count > 0 else None,
        }
        
        # Build context usage info (based on peak prompt tokens)
        context_window = model_config.get("contextWindow", 0)
        context_usage = None
            # Show context usage if we have peak prompt tokens
        if turn_usage_peak_prompt_tokens > 0:
            if context_window > 0:
                # Model has a known context window - calculate percentage
                fill_percent = (turn_usage_peak_prompt_tokens / context_window) * 100.0
                context_usage = {
                    "usedPromptTokens": turn_usage_peak_prompt_tokens,
                    "contextWindow": context_window,
                    "fillPercent": fill_percent,
                }
            else:
                # Model context window unknown - show used tokens only (no percentage)
                context_usage = {
                    "usedPromptTokens": turn_usage_peak_prompt_tokens,
                    "contextWindow": 0,  # 0 indicates unknown/not set
                    "fillPercent": 0.0,  # 0 indicates no percentage available
                }
        
        # Build model snapshot for stable per-family tracking
        model_snapshot = {
            "id": model_config.get("id", ""),
            "provider": model_config.get("provider", ""),
            "family": model_config.get("family", ""),
            "version": model_config.get("version"),
            "contextWindow": context_window,
        }
        
        # Convert last usage to camelCase if present (for backward compatibility)
        usage_camel_case = None
        if usage:
            usage_camel_case = {
                "promptTokens": usage.get("prompt_tokens", 0),
                "completionTokens": usage.get("completion_tokens", 0),
                "totalTokens": usage.get("total_tokens", 0),
            }
        
        # Build meta dict
        # Use total_usage for backward compatibility with existing "usage" field
        meta: Dict[str, Any] = {
            "thinking": thinking_content,
            "systemPrompt": system_prompt,
            "usage": total_usage if total_usage["totalTokens"] > 0 else usage_camel_case,  # Backward compat: use aggregated total or last usage (camelCase)
            "usageBreakdown": usage_breakdown,
            "contextUsage": context_usage,
            "modelSnapshot": model_snapshot,
            "traceEvents": trace_events,
            "error": error_message,
        }
        
        # Persist patches to turn meta (for UI to render diff previews)
        if all_patches:
            meta["patches"] = all_patches
        
        # Persist artifacts to turn meta (for UI to display clickable artifact links)
        if artifacts:
            meta["artifacts"] = artifacts
        
        # Add debug bundle if debug mode is enabled
        if debug:
            meta["debug"] = build_debug_bundle(
                turn_id=turn_id,
                timestamp=turn_timestamp,
                mode=mode,
                model_config=model_config,
                set_id=model_config.get("setId", "default"),
                prompt_template=prompt_template,
                system_prompt=system_prompt,
                llm_messages=initial_messages,
                trace_events=trace_events,
                tool_calls=tool_calls,
                assistant_steps=assistant_steps,
                llm_calls=llm_calls,
            )
        
        # Compute assistantMessage from assistant_message trace events if available
        # Otherwise fall back to final_text (for backward compatibility)
        assistant_message_events = [te for te in trace_events if te.get("type") == "assistant_message"]
        if assistant_message_events:
            # Concatenate all assistant_message segments
            clean_assistant_message = "".join(te.get("content", "") or "" for te in assistant_message_events)
        else:
            # Fallback to final_text for backward compatibility
            clean_assistant_message = final_text
        
        # CRITICAL FIX: Ensure clean_assistant_message doesn't contain Harmony tokens before saving
        # This is a safety check - parsed.final_text should already be clean, but verify
        if "<|channel|>" in clean_assistant_message or "<|" in clean_assistant_message:
            # If clean_assistant_message somehow contains Harmony tokens, use parsed.final_text if available
            if last_parsed and last_parsed.final_text:
                clean_assistant_message = last_parsed.final_text
            else:
                # Fallback: try to remove Harmony tokens manually
                clean_assistant_message = re.sub(r'<\|[^|]*\|>', '', clean_assistant_message)
        
        # For sub-agent mode, add parentId to all trace_events that don't have it
        if is_sub_agent and sub_agent_id:
            for te in trace_events:
                if "parentId" not in te:
                    te["parentId"] = sub_agent_id
        
        turn_data: Dict[str, Any] = {
            "id": turn_id,
            "timestamp": turn_timestamp,
            "mode": mode,
            "modelId": model_config.get("id", ""),
            "userMessage": user_message,
            "userContext": user_context,
            "assistantMessage": "" if has_error else clean_assistant_message,
            "includeInContext": not has_error,
            "meta": meta,
            "toolCalls": tool_calls,
        }

        # Emit sub_agent_end event if this is a sub-agent call
        if is_sub_agent and sub_agent_id:
            sub_agent_end_event = {
                "type": "sub_agent_end",
                "id": f"{sub_agent_id}-end",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "parentId": parent_tool_call_id,
                "agentStartId": sub_agent_id,
                "result": clean_assistant_message if not has_error else None,
                "error": error_message,
                "usage": main_usage if main_usage["totalTokens"] > 0 else None,  # Sub-agent's own usage (not including nested sub-agents) - camelCase
                "modelSnapshot": model_snapshot,
            }
            trace_events.append(sub_agent_end_event)
            await on_event("sub_agent_end", sub_agent_end_event)
            
            # For sub-agents, return turn_data without saving to chat
            # The parent turn will include all sub-agent trace_events
            return turn_data

        # Save turn to chat (only for main agent, not sub-agents)
        self.chat_manager.add_turn(project_id, chat_id, turn_data)

        # Emit turn complete event
        await on_event("turn_complete", {
            "turnId": turn_id,
            "usage": usage,
        })

        return turn_data

# Singleton instance
_agent_runner: Optional[AgentRunner] = None


def get_agent_runner() -> AgentRunner:
    """Get the singleton AgentRunner instance."""
    global _agent_runner
    if _agent_runner is None:
        _agent_runner = AgentRunner()
    return _agent_runner

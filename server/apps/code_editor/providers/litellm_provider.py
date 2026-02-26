"""
Unified LiteLLM provider for all model routing.

Routes all requests through LiteLLM with runtime model prefix normalization.
Handles tools, thinking/reasoning, usage, and tool_calls from LiteLLM responses.
"""

import json
import uuid
from typing import AsyncGenerator, Dict, Any, List, Optional, Set

import litellm

from .base import LLMProvider
from .events import LLMEvent, LLMRequest, TokenUsage
from .normalize import (
    normalize_model_name,
    build_litellm_kwargs_from_connection,
    gemini_model_id_from_path,
)


class LiteLLMProvider(LLMProvider):
    """
    Unified provider for all models via LiteLLM.

    Uses provider prefix + model_id for routing. Supports:
    - All LiteLLM providers (openai, anthropic, ollama, lm_studio, etc.)
    - OpenAI-compatible endpoints (openai/ with api_base)
    - local_companion/vllm (routes to vllm_manager)
    - Native tool_calls, reasoning_content, and usage
    """

    _REASONING_EFFORT_VALUES: Set[str] = {"none", "low", "medium", "high"}

    def _normalize_reasoning_effort(self, effort: Any) -> Optional[str]:
        """Normalize UI/provider-specific reasoning levels to LiteLLM reasoning_effort."""
        if effort is None:
            return None
        value = str(effort).strip().lower()
        if not value:
            return None
        # Map provider-specific level names to common reasoning_effort
        if value == "minimal":
            return "low"
        if value in self._REASONING_EFFORT_VALUES:
            return value
        return None

    def _mapped_reasoning_effort_from_provider_params(self, request: LLMRequest) -> Optional[str]:
        """
        Map providerParams to LiteLLM common reasoning_effort.

        We intentionally map only to common params, not provider-native payload keys.
        """
        provider_params = request.provider_params or {}

        # LM Studio style schema: reasoning.enabled + reasoning.effort
        reasoning_cfg = provider_params.get("reasoning")
        if isinstance(reasoning_cfg, dict) and reasoning_cfg.get("enabled"):
            return self._normalize_reasoning_effort(reasoning_cfg.get("effort") or "medium")

        # Google/Ollama style schema: thinking.enabled + thinking.thinkingLevel
        thinking_cfg = provider_params.get("thinking")
        if isinstance(thinking_cfg, dict) and thinking_cfg.get("enabled"):
            thinking_level = thinking_cfg.get("thinkingLevel")
            # If level isn't specified, default to medium when thinking is enabled.
            return self._normalize_reasoning_effort(thinking_level or "medium")

        return None

    def _mapped_chat_template_kwargs_from_provider_params(self, request: LLMRequest) -> Optional[Dict[str, Any]]:
        """
        Map providerParams to vLLM chat_template_kwargs when requested by UI.

        This is primarily for vLLM/local_companion reasoning models that require
        chat-template toggles like `thinking` / `enable_thinking`.
        """
        provider_params = request.provider_params or {}
        result: Dict[str, Any] = {}

        # Power-user passthrough (exact shape expected by vLLM)
        explicit_kwargs = provider_params.get("chatTemplateKwargs")
        if isinstance(explicit_kwargs, dict):
            result.update(explicit_kwargs)

        reasoning_cfg = provider_params.get("reasoning")
        if isinstance(reasoning_cfg, dict):
            enabled = bool(reasoning_cfg.get("enabled"))
            mode_raw = reasoning_cfg.get("chatTemplateThinking")
            mode = str(mode_raw).strip().lower() if mode_raw is not None else "auto"

            if mode == "enable":
                result.setdefault("thinking", True)
                result.setdefault("enable_thinking", True)
            elif mode == "disable":
                result.setdefault("thinking", False)
                result.setdefault("enable_thinking", False)
            elif enabled and mode == "auto":
                # Auto mode intentionally does not force chat-template toggles.
                # This avoids overriding model/server defaults and prevents
                # routing all output into reasoning for some vLLM setups.
                pass

        return result or None

    def _get_supported_openai_params(self, model: str, provider_prefix: str) -> Set[str]:
        """Best-effort supported params lookup from LiteLLM."""
        try:
            params = litellm.get_supported_openai_params(
                model=model,
                custom_llm_provider=provider_prefix,
            )
            if isinstance(params, list):
                return {str(param).strip().lower() for param in params if str(param).strip()}
        except Exception:
            pass

        try:
            params = litellm.get_supported_openai_params(model=model)
            if isinstance(params, list):
                return {str(param).strip().lower() for param in params if str(param).strip()}
        except Exception:
            pass

        return set()

    def _supports_reasoning(self, model: str) -> bool:
        """Best-effort reasoning support check."""
        try:
            return bool(litellm.supports_reasoning(model=model))
        except Exception:
            # Fail open to avoid breaking providers where capability lookup is incomplete.
            return True

    def _supports_function_calling(self, model: str) -> bool:
        """Best-effort function-calling support check."""
        try:
            return bool(litellm.supports_function_calling(model=model))
        except Exception:
            # Fail open to avoid accidental tool disablement.
            return True

    @staticmethod
    def _tools_for_gemini(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Ensure tool schemas are Gemini/Vertex compliant: array parameters must have "items".
        Mutates and returns the same list (with nested dicts updated in place).
        """
        for tool in tools:
            func = (tool or {}).get("function") if isinstance(tool, dict) else None
            if not isinstance(func, dict):
                continue
            params = func.get("parameters")
            if not isinstance(params, dict):
                continue
            props = params.get("properties")
            if not isinstance(props, dict):
                continue
            for key, prop in list(props.items()):
                if not isinstance(prop, dict) or prop.get("type") != "array":
                    continue
                if "items" not in prop:
                    prop["items"] = {"type": "string"}
        return tools

    def _extract_thinking_text_from_blocks(self, blocks: Any) -> str:
        """
        Extract reasoning text from thinking_blocks-like structures.

        Expected block item shapes include:
        - {"type": "thinking", "thinking": "..."}
        - {"thinking": "..."}
        """
        if not isinstance(blocks, list):
            return ""
        parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            thinking = block.get("thinking")
            if isinstance(thinking, str) and thinking:
                parts.append(thinking)
        return "\n".join(parts).strip()

    def _get_new_reasoning_text(self, accumulated: str, incoming: str) -> tuple[str, str]:
        """
        Return (new_accumulated, delta_to_emit) for reasoning text.

        Handles both incremental chunks and cumulative full-text updates.
        """
        if not incoming:
            return accumulated, ""

        if accumulated and incoming.startswith(accumulated):
            # Cumulative text, emit only the suffix.
            delta = incoming[len(accumulated):]
            return incoming, delta

        if accumulated and incoming in accumulated:
            # Duplicate chunk; emit nothing.
            return accumulated, ""

        # Independent/new chunk.
        return accumulated + incoming, incoming

    async def stream(self, request: LLMRequest) -> AsyncGenerator[LLMEvent, None]:
        """Stream response using LiteLLM."""
        provider = request.provider or self.config.get("provider", "")
        model_id = request.model_id or ""
        connection = request.connection or self.connection
        auth = request.auth or self.auth

        # For Gemini, use model id from connection path when present so LiteLLM gets the
        # correct API name (e.g. gemini-3-pro-preview) and doesn't 404 then fall back to Vertex.
        if provider.strip().lower() in ("google", "gemini") and connection:
            path_model = gemini_model_id_from_path((connection or {}).get("path") or "")
            if path_model:
                model_id = path_model

        # Build LiteLLM kwargs from connection/auth first to get api_base
        conn_kwargs = build_litellm_kwargs_from_connection(
            provider,
            connection,
            auth,
            local_companion=self.config.get("localCompanion"),
        )

        # Normalize model name - pass api_base so it knows to skip prefix for custom endpoints
        litellm_model = normalize_model_name(
            provider,
            model_id,
            family=request.family,
            base_url=connection.get("baseUrl") if connection else None,
            api_base=conn_kwargs.get("api_base"),
        )

        if not litellm_model:
            yield LLMEvent(
                type="error",
                error="Invalid model configuration: provider and model ID are required.",
            )
            return

        litellm_kwargs: Dict[str, Any] = {
            "model": litellm_model,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},  # Request usage in final stream chunk
            "drop_params": True,  # Drop unsupported common OpenAI params safely per provider/model
            **conn_kwargs,
        }

        if request.max_tokens:
            litellm_kwargs["max_tokens"] = request.max_tokens

        provider_prefix = litellm_model.split("/", 1)[0].lower() if "/" in litellm_model else provider.lower()
        supported_params = self._get_supported_openai_params(litellm_model, provider_prefix)

        # Map UI providerParams -> LiteLLM common params (reasoning_effort)
        reasoning_effort = self._mapped_reasoning_effort_from_provider_params(request)
        if reasoning_effort and self._supports_reasoning(litellm_model):
            litellm_kwargs["reasoning_effort"] = reasoning_effort

        # Optional vLLM chat-template controls for reasoning behavior.
        chat_template_kwargs = self._mapped_chat_template_kwargs_from_provider_params(request)
        if chat_template_kwargs:
            litellm_kwargs["chat_template_kwargs"] = chat_template_kwargs

        # Capability-aware native tools passing
        supports_tools_param = (not supported_params) or ("tools" in supported_params)
        supports_tool_choice_param = (not supported_params) or ("tool_choice" in supported_params)
        provider_lower = (provider or "").lower()
        supports_fn_calling = self._supports_function_calling(litellm_model)
        force_tools_for_vllm = provider_lower in {"vllm", "local_companion"}
        force_tools_for_lmstudio = provider_lower in {"lmstudio", "lm_studio"}

        if request.tools and (
            force_tools_for_vllm
            or force_tools_for_lmstudio
            or (supports_tools_param and supports_fn_calling)
        ):
            tools = list(request.tools)
            if litellm_model.startswith("gemini/"):
                tools = self._tools_for_gemini(tools)
            litellm_kwargs["tools"] = tools
            if force_tools_for_vllm or force_tools_for_lmstudio or supports_tool_choice_param:
                litellm_kwargs["tool_choice"] = request.tool_choice

        if request.extra_payload:
            litellm_kwargs.update(request.extra_payload)

        try:
            finish_reason = None
            usage = None
            tool_calls_acc: Dict[int, Dict[str, Any]] = {}
            emitted_reasoning_text = ""
            tool_calls_seen = False

            response = await litellm.acompletion(**litellm_kwargs)

            async for chunk in response:
                # Usage can arrive on dedicated stream chunks with empty choices.
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = self._usage_from_chunk(chunk.usage)

                if not hasattr(chunk, "choices") or not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                if not delta:
                    continue

                # Content
                content_value = getattr(delta, "content", None)
                reasoning_value = getattr(delta, "reasoning_content", None)
                
                # vLLM workaround: If content is None but reasoning_content exists,
                # vLLM may be putting main content in reasoning_content.
                # We need to accumulate and detect tool calls, then emit content appropriately.
                if content_value:
                    # Normal case: content exists
                    yield LLMEvent(type="content", content=content_value)
                elif reasoning_value and not content_value:
                    # No-op here: reasoning is emitted via structured thinking events below.
                    pass

                # Reasoning/thinking (LiteLLM standardized)
                # Only treat as thinking if we also have content (normal case, not vLLM workaround)
                reasoning_from_delta = ""
                if hasattr(delta, "reasoning") and getattr(delta, "reasoning"):
                    reasoning_from_delta = str(getattr(delta, "reasoning"))
                elif hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_from_delta = str(delta.reasoning_content)

                # Fallback: some providers expose thinking as thinking_blocks.
                # Try both delta and full message to maximize compatibility.
                thinking_blocks_text = ""
                if hasattr(delta, "thinking_blocks") and getattr(delta, "thinking_blocks"):
                    thinking_blocks_text = self._extract_thinking_text_from_blocks(getattr(delta, "thinking_blocks"))
                elif hasattr(choice, "message") and getattr(choice, "message") is not None:
                    msg = getattr(choice, "message")
                    if hasattr(msg, "thinking_blocks") and getattr(msg, "thinking_blocks"):
                        thinking_blocks_text = self._extract_thinking_text_from_blocks(getattr(msg, "thinking_blocks"))

                reasoning_candidate = reasoning_from_delta or thinking_blocks_text
                if reasoning_candidate:
                    emitted_reasoning_text, reasoning_delta = self._get_new_reasoning_text(
                        emitted_reasoning_text,
                        reasoning_candidate,
                    )
                    if reasoning_delta:
                        yield LLMEvent(type="thinking", content=reasoning_delta)

                # Tool calls (streaming) - accumulate by index
                tcs = getattr(delta, "tool_calls", None) or []
                for tc in tcs:
                    tc_dict = tc if isinstance(tc, dict) else None
                    if tc_dict is None and hasattr(tc, "__dict__"):
                        tc_dict = {
                            "index": getattr(tc, "index", None),
                            "id": getattr(tc, "id", None),
                            "function": getattr(tc, "function", None),
                        }
                    if not tc_dict:
                        continue
                    idx = tc_dict.get("index")
                    if idx is None:
                        continue
                    fn = tc_dict.get("function")
                    if fn is not None and not isinstance(fn, dict) and hasattr(fn, "name"):
                        fn = {"name": getattr(fn, "name", None), "arguments": getattr(fn, "arguments", None) or ""}
                    fn = fn or {}
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"name": "", "arguments": "", "id": tc_dict.get("id", ""), "emitted": False}
                    acc = tool_calls_acc[idx]
                    if acc.get("emitted"):
                        continue
                    if fn.get("name"):
                        acc["name"] = fn["name"]
                    if fn.get("arguments") is not None:
                        acc["arguments"] = acc.get("arguments", "") + str(fn["arguments"])
                    if tc_dict.get("id"):
                        acc["id"] = tc_dict["id"]
                    name = acc.get("name", "")
                    args_str = acc.get("arguments", "")
                    if name and args_str:
                        try:
                            args = json.loads(args_str)
                            tool_call_id = acc.get("id") or f"call_{idx}_{uuid.uuid4().hex[:8]}"
                            yield LLMEvent(
                                type="tool_call",
                                tool_call={"tool": name, "args": args, "id": tool_call_id},
                            )
                            acc["emitted"] = True
                            tool_calls_seen = True
                        except json.JSONDecodeError:
                            pass

                if hasattr(choice, "finish_reason") and choice.finish_reason:
                    finish_reason = choice.finish_reason

            yield LLMEvent(
                type="end",
                usage=usage,
                finish_reason=finish_reason,
            )

        except Exception as e:
            error_str = str(e)
            error_lower = error_str.lower()
            is_auth_error = (
                "api_key" in error_lower
                or "api key" in error_lower
                or "authentication" in error_lower
                or "unauthorized" in error_lower
                or "invalid api" in error_lower
                or "google.auth" in error_lower
                or "defaultcredentialserror" in error_lower
                or "application default credentials" in error_lower
            )
            if is_auth_error:
                api_key_provided = (
                    (auth.get("type") == "bearer" and bool(auth.get("apiKey")))
                    or (auth.get("type") == "header" and bool(auth.get("value")))
                )
                if not api_key_provided:
                    if provider.lower() in {"google", "gemini", "vertex_ai"}:
                        error_message = (
                            "Google authentication is required. Configure an API key "
                            "(x-goog-api-key) or ADC credentials."
                        )
                    else:
                        error_message = "API key is required. Please configure your API key in the model settings."
                elif "google.auth" in error_lower or "defaultcredentialserror" in error_lower:
                    error_message = (
                        "Google auth setup is incomplete. Install `google-auth` and configure "
                        "Application Default Credentials (ADC) or a valid Gemini API key."
                    )
                else:
                    error_message = f"Authentication failed: {error_str}"
            else:
                error_message = f"LiteLLM error: {error_str}"
            yield LLMEvent(type="error", error=error_message)

    def _usage_from_chunk(self, usage: Any) -> Optional[Dict[str, Any]]:
        """
        Extract usage dict from LiteLLM chunk.usage.
        Handles OpenAI-style, Anthropic, Gemini, LMStudio, and other LiteLLM variants.
        """
        if not usage:
            return None

        # Already a dict (e.g. from some providers)
        if isinstance(usage, dict):
            parsed = TokenUsage.from_auto(usage)
            return parsed.to_dict() if parsed else None

        # Object with attributes
        result: Dict[str, Any] = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }

        # completion_tokens_details - reasoning_tokens (OpenAI o1, Anthropic extended thinking)
        details = getattr(usage, "completion_tokens_details", None)
        if details:
            if isinstance(details, dict):
                reasoning = details.get("reasoning_tokens")
                if reasoning is not None:
                    result["reasoning_tokens"] = reasoning
            elif hasattr(details, "reasoning_tokens") and details.reasoning_tokens is not None:
                result["reasoning_tokens"] = details.reasoning_tokens

        # input_tokens_details - cached_tokens
        input_details = getattr(usage, "input_tokens_details", None)
        if input_details:
            if isinstance(input_details, dict):
                cached = input_details.get("cached_tokens")
                if cached is not None:
                    result["cached_tokens"] = cached
            elif hasattr(input_details, "cached_tokens") and input_details.cached_tokens is not None:
                result["cached_tokens"] = input_details.cached_tokens

        # Ensure total_tokens if missing
        if not result["total_tokens"] and (result["prompt_tokens"] or result["completion_tokens"]):
            result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]

        return result

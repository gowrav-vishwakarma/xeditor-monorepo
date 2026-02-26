"""
Model name normalization for LiteLLM routing.

Maps provider + model_id to LiteLLM model string (provider_prefix/model_name).
Handles provider aliases and runtime auto-prefixing.
"""

from typing import Tuple
from urllib.parse import urlparse
import re


# Provider ID -> LiteLLM route prefix
# See https://docs.litellm.ai/docs/providers
# For Google AI Studio (GEMINI_API_KEY), LiteLLM route is gemini/ not google/
PROVIDER_TO_PREFIX: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "ollama": "ollama",
    "lmstudio": "lm_studio",
    "lm_studio": "lm_studio",
    "openai_compatible": "openai",
    "openrouter": "openrouter",
    "sglang": "openai",  # OpenAI-compatible
    "vllm": "openai",  # OpenAI-compatible
    "local_companion": "openai",  # Routes to vLLM, OpenAI-compatible
    "kimi": "openai",  # OpenAI-compatible (Moonshot)
    "moonshot": "openai",  # Alias for Kimi
    "google": "gemini",  # Google AI Studio: LiteLLM expects gemini/ prefix
    "gemini": "gemini",  # Google AI Studio
    "vertex_ai": "vertex_ai",
    "deepseek": "deepseek",
    "groq": "groq",
    "mistral": "mistral",
    "xai": "xai",
}


def gemini_model_id_from_path(path: str) -> str | None:
    """
    Extract Gemini API model id from connection path (e.g. /v1beta/models/gemini-3-pro-preview:generateContent).
    Returns None if path is empty or doesn't match. Used so LiteLLM gets the correct model name
    and doesn't fall back to Vertex AI on 404.
    """
    if not path or not isinstance(path, str):
        return None
    path = path.strip()
    # Match /v1beta/models/MODEL_ID:generateContent or /v1/models/MODEL_ID
    m = re.match(r"/v1(?:beta)?/models/([^/:]+)(?::generateContent)?", path)
    return m.group(1) if m else None


def _is_already_prefixed(model_id: str) -> bool:
    """Check if model_id already contains a provider prefix (e.g. openai/gpt-4, ollama_chat/llama3)."""
    if not model_id or "/" not in model_id:
        return False
    prefix = model_id.split("/", 1)[0].lower()
    known_prefixes = set(PROVIDER_TO_PREFIX.values()) | set(PROVIDER_TO_PREFIX.keys())
    # Also recognize ollama_chat/ as a valid prefix (special case for Ollama tool calling)
    known_prefixes.add("ollama_chat")
    return prefix in known_prefixes


def _resolve_prefix_from_base_url(base_url: str) -> str | None:
    """
    Resolve LiteLLM prefix from base URL when provider is openai_compatible.
    Used for known endpoints that need a specific prefix (e.g. Gemini).
    """
    if not base_url:
        return None
    try:
        parsed = urlparse(base_url)
        host = (parsed.netloc or "").lower()
        if "generativelanguage.googleapis.com" in host:
            return "gemini"
        if "openrouter.ai" in host:
            return "openrouter"
    except Exception:
        pass
    return None


def normalize_model_name(
    provider: str,
    model_id: str,
    *,
    family: str | None = None,
    base_url: str | None = None,
    api_base: str | None = None,
) -> str:
    """
    Build LiteLLM model string from provider and model_id.

    - If model_id is already prefixed (e.g. openai/gpt-4), return as-is.
    - When using custom api_base (e.g. vLLM), return raw model_id (no prefix).
    - Else prefix with provider's LiteLLM prefix at runtime.
    - For openai_compatible, may resolve prefix from base_url (e.g. Gemini -> gemini/).

    Args:
        provider: Provider ID from model config
        model_id: Raw model ID (e.g. gpt-4-turbo, llama3.1)
        family: Optional model family (e.g. gemini) for hinting
        base_url: Optional connection baseUrl for prefix resolution
        api_base: Optional resolved api_base (if set, don't prefix model name)

    Returns:
        LiteLLM model string (e.g. openai/gpt-4-turbo, ollama/llama3.1, or raw gpt-oss-20b for custom api_base)
    """
    provider = (provider or "").strip().lower()
    model_id = (model_id or "").strip()

    if not model_id:
        return ""

    # OpenRouter uses provider/model format - always prefix with openrouter unless already has it
    if provider == "openrouter":
        if model_id.lower().startswith("openrouter/"):
            return model_id
        return f"openrouter/{model_id}"

    # When using custom api_base (e.g. vLLM, OpenAI-compatible endpoints),
    # LiteLLM strips the first provider prefix from model names.
    # For vLLM, we need to use double prefix trick: "openai/openai/model-name"
    # LiteLLM strips the first "openai/" leaving "openai/model-name" which vLLM expects.
    if api_base:
        # For Ollama, always use ollama_chat/ prefix (even with custom api_base)
        # This routes to /api/chat endpoint which supports tool calling
        if provider == "ollama":
            # Extract base model name (remove any existing prefix)
            if "/" in model_id:
                parts = model_id.split("/", 1)
                base_model = parts[1] if len(parts) > 1 else model_id
            else:
                base_model = model_id
            # Use ollama_chat/ prefix for tool calling support
            result = f"ollama_chat/{base_model}"
            return result
        
        if provider in ("vllm", "local_companion"):
            # Extract base model name (remove any existing prefix)
            if "/" in model_id:
                parts = model_id.split("/", 1)
                base_model = parts[1] if len(parts) > 1 else model_id
            else:
                base_model = model_id
            # Use double prefix: openai/openai/model-name
            # LiteLLM strips first "openai/" -> "openai/model-name" (what vLLM expects)
            result = f"openai/openai/{base_model}"
            return result
        # For other providers with custom api_base, we need to ensure they have the correct prefix
        # LM Studio and other OpenAI-compatible providers need "openai/" prefix
        # However, LiteLLM strips the first prefix when using custom api_base, so we need double prefix
        # Same trick as vLLM: use "openai/openai/model-name" so LiteLLM strips to "openai/model-name"
        if provider in ("lmstudio", "lm_studio", "sglang", "openai_compatible"):
            # Extract base model name (remove any existing prefix first)
            if "/" in model_id:
                parts = model_id.split("/", 1)
                base_model = parts[1] if len(parts) > 1 else model_id
            else:
                base_model = model_id
            # Use double prefix: openai/openai/model-name
            # LiteLLM strips first "openai/" -> "openai/model-name" (what LM Studio expects)
            result = f"openai/openai/{base_model}"
            return result

        # Google/Gemini: LiteLLM expects gemini/ prefix for Google AI Studio (not google/)
        if provider in ("google", "gemini"):
            if "/" in model_id:
                parts = model_id.split("/", 1)
                base_model = parts[1] if len(parts) > 1 else model_id
            else:
                base_model = model_id
            return f"gemini/{base_model}"

        # For other providers with custom api_base, strip prefix if present
        # (Some providers don't need prefix when using custom api_base)
        if "/" in model_id:
            parts = model_id.split("/", 1)
            raw_model = parts[1] if len(parts) > 1 else model_id
            return raw_model
        return model_id

    if _is_already_prefixed(model_id):
        return model_id

    # For Ollama, use ollama_chat/ prefix instead of ollama/ to enable native tool calling
    # ollama_chat/ routes to /api/chat endpoint which supports tool calling
    # ollama/ routes to /api/generate which doesn't support tool calling
    if provider == "ollama":
        # Check if model_id already has ollama_chat/ prefix
        if model_id.lower().startswith("ollama_chat/"):
            return model_id
        # Use ollama_chat/ prefix for tool calling support
        result = f"ollama_chat/{model_id}"
        return result

    # For vLLM and local_companion without custom api_base, prefix with openai/
    if provider in ("vllm", "local_companion"):
        prefix = PROVIDER_TO_PREFIX.get(provider, "openai")
        result = f"{prefix}/{model_id}"
        return result

    # For openai_compatible, try to resolve prefix from base_url or family
    if provider == "openai_compatible":
        if base_url:
            resolved = _resolve_prefix_from_base_url(base_url)
            if resolved:
                return f"{resolved}/{model_id}"
        if family and family.lower() == "gemini":
            return f"gemini/{model_id}"
        if family and family.lower() == "kimi":
            pass  # Keep openai/ with api_base
        prefix = PROVIDER_TO_PREFIX.get(provider, "openai")
    else:
        prefix = PROVIDER_TO_PREFIX.get(provider, "openai")

    result = f"{prefix}/{model_id}"
    return result


def get_api_base_for_provider(
    provider: str,
    connection: dict,
    *,
    local_companion: dict | None = None,
) -> str | None:
    """
    Get api_base for LiteLLM kwargs.

    For local_companion/vllm, resolves from vllm_manager.
    For others, uses connection.baseUrl. LiteLLM handles path construction automatically.
    For OpenAI-compatible endpoints (vLLM, etc.), ensures /v1 is included in api_base.
    """
    provider = (provider or "").strip().lower()

    if provider in ("local_companion", "vllm"):
        try:
            from apps.code_editor.vllm_manager import get_vllm_manager
            manager = get_vllm_manager()
            status = manager.get_status()
            if status.get("running") and status.get("port"):
                # Return base URL without /v1 - LiteLLM will append /v1/chat/completions
                return f"http://127.0.0.1:{status['port']}"
        except ImportError:
            pass
        # Fallback to connection.baseUrl if vllm_manager is not available
        # For vLLM, baseUrl should include /v1 (e.g., http://localhost:8000/v1)
        # LiteLLM will append /chat/completions automatically for OpenAI-compatible endpoints
        base_url = (connection or {}).get("baseUrl", "")
        if base_url:
            base = base_url.rstrip("/")
            # If baseUrl doesn't end with /v1, append it for vLLM OpenAI-compatible endpoints
            if not base.endswith("/v1"):
                base = f"{base}/v1"
            return base
        return None

    base_url = (connection or {}).get("baseUrl", "")

    if not base_url:
        # Default api_base for known providers when not configured
        if provider in ("google", "gemini"):
            return "https://generativelanguage.googleapis.com"
        return None

    base = base_url.rstrip("/")
    
    # Ollama does NOT use /v1 - it uses /api/chat directly
    # Strip /v1 if present in baseUrl (user might have added it by mistake)
    if provider == "ollama":
        if base.endswith("/v1"):
            base = base[:-3]  # Remove trailing /v1
        return base
    
    # For OpenAI-compatible providers (LM Studio, sglang, etc.), ensure /v1 is included
    # LiteLLM will append /chat/completions to /v1
    if provider in ("lmstudio", "lm_studio", "sglang", "openai_compatible"):
        if not base.endswith("/v1"):
            base = f"{base}/v1"
    
    # LiteLLM expects base URL (e.g. https://api.openai.com or https://host/v1)
    return base if base else None


def build_litellm_kwargs_from_connection(
    provider: str,
    connection: dict,
    auth: dict,
    *,
    local_companion: dict | None = None,
) -> dict:
    """
    Build LiteLLM kwargs for api_key, api_base, and provider-specific config.

    Returns dict to merge into litellm.acompletion() kwargs.
    """
    result: dict = {}

    api_base = get_api_base_for_provider(provider, connection, local_companion=local_companion)
    # For Google AI Studio (gemini/), do not pass api_base so LiteLLM uses its native
    # gemini/ route with api_key only. Passing api_base can trigger Vertex AI fallback
    # on errors and cause Vertex_ai_betaException.
    if api_base and not (
        provider.strip().lower() in ("google", "gemini")
        and "generativelanguage.googleapis.com" in (api_base or "")
    ):
        result["api_base"] = api_base

    auth_type = (auth or {}).get("type", "none")
    if auth_type == "bearer" and auth.get("apiKey"):
        result["api_key"] = auth["apiKey"]
    elif auth_type == "header" and auth.get("headerName"):
        # LiteLLM supports api_key for most; for custom headers use extra_headers
        value = auth.get("value", "")
        if value:
            result["api_key"] = value
        # Custom header name (e.g. x-goog-api-key) - use headers
        header_name = auth.get("headerName", "")
        if header_name and value:
            result.setdefault("extra_headers", {})[header_name] = value

    # Merge connection headers (non-auth)
    headers = (connection or {}).get("headers", {})
    if isinstance(headers, dict) and headers:
        result.setdefault("extra_headers", {}).update(headers)

    return result

"""Tests for LiteLLM model normalization and provider prefix resolution."""

import pytest

from apps.code_editor.providers.normalize import (
    normalize_model_name,
    PROVIDER_TO_PREFIX,
)


class TestNormalizeModelName:
    """Tests for normalize_model_name."""

    def test_openai_unprefixed(self):
        assert normalize_model_name("openai", "gpt-4o") == "openai/gpt-4o"

    def test_anthropic_unprefixed(self):
        assert normalize_model_name("anthropic", "claude-3-5-sonnet") == "anthropic/claude-3-5-sonnet"

    def test_ollama_unprefixed(self):
        assert normalize_model_name("ollama", "llama3.1") == "ollama/llama3.1"

    def test_lmstudio_maps_to_lm_studio(self):
        assert normalize_model_name("lmstudio", "local-model") == "lm_studio/local-model"

    def test_google_provider(self):
        # LiteLLM expects gemini/ prefix for Google AI Studio (GEMINI_API_KEY)
        assert normalize_model_name("google", "gemini-2.0-flash") == "gemini/gemini-2.0-flash"

    def test_gemini_provider(self):
        assert normalize_model_name("gemini", "gemini-2.0-flash") == "gemini/gemini-2.0-flash"

    def test_kimi_provider(self):
        assert normalize_model_name("kimi", "kimi-k2") == "openai/kimi-k2"

    def test_openai_compatible_with_gemini_family(self):
        assert (
            normalize_model_name("openai_compatible", "gemini-2.0", family="gemini")
            == "gemini/gemini-2.0"
        )

    def test_already_prefixed_passthrough(self):
        assert normalize_model_name("openai", "openai/gpt-4o") == "openai/gpt-4o"
        assert normalize_model_name("anthropic", "anthropic/claude-3") == "anthropic/claude-3"

    def test_empty_model_id(self):
        assert normalize_model_name("openai", "") == ""

    def test_openrouter(self):
        assert normalize_model_name("openrouter", "anthropic/claude-3") == "openrouter/anthropic/claude-3"

"""Shared configuration for the application language model."""

from __future__ import annotations

import os
from typing import Any

from langsmith.wrappers import wrap_openai
from openai import OpenAI


DEFAULT_MODEL = os.getenv("LLM_MODEL_NAME", "gemini-2.5-flash")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:1234/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "google/gemma-4-12b")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "lm-studio")

llm_client = wrap_openai(
    OpenAI(
        api_key=os.getenv("GEMINI_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
)

_local_llm_client: OpenAI | None = None


def get_local_llm_client() -> Any:
    """Return the cached local OpenAI-compatible client for LM Studio / local LLMs."""
    global _local_llm_client
    if _local_llm_client is None:
        _local_llm_client = wrap_openai(
            OpenAI(
                api_key=LOCAL_LLM_API_KEY,
                base_url=LOCAL_LLM_URL,
            )
        )
    return _local_llm_client


def is_local_model(model_name: str | None) -> bool:
    """Return True if the requested model indicates a locally hosted engine."""
    if not model_name:
        return False
    lowered = model_name.strip().lower()
    return any(
        cue in lowered
        for cue in ("local", "gemma", "lmstudio", "1234", "localhost", "morpheus-local")
    )


def get_llm_client(model_name: str | None = None) -> Any:
    """Return the appropriate LLM client based on the requested model name."""
    if is_local_model(model_name):
        return get_local_llm_client()
    return llm_client


def get_llm_model_name(model_name: str | None = None) -> str:
    """Return the concrete model string for the chosen backend."""
    if is_local_model(model_name):
        return LOCAL_LLM_MODEL
    return DEFAULT_MODEL


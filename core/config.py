"""Shared configuration for the application language model."""

import os

from langsmith.wrappers import wrap_openai
from openai import OpenAI


DEFAULT_MODEL = os.getenv("LLM_MODEL_NAME", "gemini-3.5-flash-lite")

llm_client = wrap_openai(
    OpenAI(
        api_key=os.getenv("GEMINI_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
)

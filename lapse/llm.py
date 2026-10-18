from __future__ import annotations

import os
from urllib.parse import urlsplit
from uuid import uuid4

from openai import AsyncOpenAI, OpenAI, OpenAIError

from lapse.config import settings

_SESSION = f"lapse-{uuid4()}"


def client(*, asynchronous=False, base_url=None, api_key=None):
    config = settings()
    base_url = config.llm_base_url if base_url is None else base_url
    api_key = config.llm_api_key if api_key is None else api_key
    headers = {"x-opencode-session": _SESSION} if urlsplit(base_url).hostname == "opencode.ai" else {}
    factory = AsyncOpenAI if asynchronous else OpenAI
    return factory(
        api_key=api_key,
        base_url=base_url,
        default_headers=headers,
        timeout=30.0,
        max_retries=1,
    )


def _models(model, fallback_models):
    if fallback_models is None:
        fallback_models = os.getenv("LLM_FALLBACK_MODELS", "glm-5.3-flash,qwen3.8-flash")
    return list(
        dict.fromkeys(
            [
                model or settings().llm_model,
                *filter(None, (m.strip() for m in fallback_models.split(","))),
            ]
        )
    )


def _attempt(diagnostics, index):
    if diagnostics is not None:
        diagnostics["llm_attempts"] = diagnostics.get("llm_attempts", 0) + 1
        diagnostics["model_fallback_used"] = diagnostics.get("model_fallback_used", False) or index > 0


def complete(connection, *, model=None, fallback_models=None, diagnostics=None, **kwargs):
    models = _models(model, fallback_models)
    for index, candidate in enumerate(models):
        _attempt(diagnostics, index)
        try:
            return connection.chat.completions.create(model=candidate, **kwargs)
        except OpenAIError:
            if index == len(models) - 1:
                raise


async def acomplete(connection, *, model=None, fallback_models=None, diagnostics=None, **kwargs):
    models = _models(model, fallback_models)
    for index, candidate in enumerate(models):
        _attempt(diagnostics, index)
        try:
            return await connection.chat.completions.create(model=candidate, **kwargs)
        except OpenAIError:
            if index == len(models) - 1:
                raise

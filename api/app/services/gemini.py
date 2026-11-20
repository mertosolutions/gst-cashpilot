"""Thin wrapper over the Google GenAI SDK (Gemini). Every call is optional: callers fall back to local engines."""
from __future__ import annotations

import json
import time
from functools import lru_cache

from app.core.config import get_settings


class GeminiUnavailable(RuntimeError):
    pass


_cooldown_until = 0.0
COOLDOWN_SECONDS = 600


def is_quota_error(exc: BaseException) -> bool:
    t = f"{type(exc).__name__} {exc}"
    return "429" in t or "RESOURCE_EXHAUSTED" in t or "ResourceExhausted" in t or "quota" in t.lower()


def mark_quota_hit() -> None:
    """After a quota error, skip Gemini for a while so the app answers fast with its local engines instead of waiting on retries."""
    global _cooldown_until
    _cooldown_until = time.time() + COOLDOWN_SECONDS


def available() -> bool:
    return get_settings().gemini_enabled and time.time() >= _cooldown_until


@lru_cache
def _client():
    s = get_settings()
    if not s.gemini_api_key:
        raise GeminiUnavailable("GEMINI_API_KEY is not set")
    from google import genai
    from google.genai import types
    # one attempt and a timeout: waiting through long retries is worse than falling back to the local engine
    return genai.Client(api_key=s.gemini_api_key, http_options=types.HttpOptions(timeout=45_000, retry_options=types.HttpRetryOptions(attempts=1)))


def enabled() -> bool:
    return get_settings().gemini_enabled


def embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    from google.genai import types
    resp = _client().models.embed_content(model=s.gemini_embed_model, contents=texts,
                                          config=types.EmbedContentConfig(output_dimensionality=768))
    return [list(e.values) for e in resp.embeddings]


def generate_text(prompt: str) -> str:
    s = get_settings()
    resp = _client().models.generate_content(model=s.gemini_model, contents=prompt)
    return (resp.text or "").strip()


def generate_json_from_file(data: bytes, mime_type: str, prompt: str) -> dict:
    """Multimodal call used by the extraction layer (invoice scan -> JSON fields)."""
    from google.genai import types
    s = get_settings()
    resp = _client().models.generate_content(
        model=s.gemini_model,
        contents=[types.Part.from_bytes(data=data, mime_type=mime_type), prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
    )
    return json.loads(resp.text)

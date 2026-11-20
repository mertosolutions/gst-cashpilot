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
    if not s.gemini_enabled:
        raise GeminiUnavailable("No Gemini credentials are configured")
    from google import genai
    from google.genai import types
    # one attempt and a timeout: waiting through long retries is worse than falling back to the local engine
    http = types.HttpOptions(timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1))
    if s.genai_backend == "vertex":
        if s.vertex_api_key:  # Vertex AI express mode
            return genai.Client(vertexai=True, api_key=s.vertex_api_key, http_options=http)
        return genai.Client(vertexai=True, project=s.google_cloud_project, location=s.google_cloud_location, http_options=http)
    return genai.Client(api_key=s.gemini_api_key, http_options=http)


def enabled() -> bool:
    return get_settings().gemini_enabled


def embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    from google.genai import types
    resp = _client().models.embed_content(model=s.gemini_embed_model, contents=texts,
                                          config=types.EmbedContentConfig(output_dimensionality=768))
    return [list(e.values) for e in resp.embeddings]


FALLBACK_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]
_SKIP_UNTIL: dict[str, float] = {}  # a model that was overloaded is skipped for a few minutes so later calls are not slow
LAST_MODEL = {"name": ""}  # the model that really answered the last call, so the UI can say which one it was


def _generate(contents, config=None) -> str:
    """Calls the configured model; when it is overloaded (503/504), over its quota (429) or unknown (404) the next model in the list is tried."""
    s = get_settings()
    last: Exception | None = None
    models = [m for m in dict.fromkeys([s.gemini_model, *FALLBACK_MODELS]) if _SKIP_UNTIL.get(m, 0) < time.time()] or [s.gemini_model]
    for model in models:
        try:
            resp = _client().models.generate_content(model=model, contents=contents, config=config)
            LAST_MODEL["name"] = model
            return (resp.text or "").strip()
        except Exception as exc:  # noqa: BLE001
            last = exc
            t = f"{type(exc).__name__} {exc}"
            if is_quota_error(exc):
                # the quota is per model: skip this one (a day limit for long, a per-minute limit briefly) and try the next model
                _SKIP_UNTIL[model] = time.time() + (3600 if "PerDay" in t or "per day" in t.lower() else 90)
                continue
            if not any(k in t for k in ("503", "504", "UNAVAILABLE", "DEADLINE", "404", "NOT_FOUND", "overloaded", "high demand", "Timeout", "timed out")):
                raise
            _SKIP_UNTIL[model] = time.time() + 300
    raise last  # type: ignore[misc]


def generate_text(prompt: str, system: str | None = None) -> str:
    from google.genai import types
    cfg = types.GenerateContentConfig(system_instruction=system, temperature=0.2) if system else None
    return _generate(prompt, cfg)


def generate_json(prompt: str, system: str | None = None) -> dict:
    """Gemini answers with JSON only (response_mime_type), which the caller validates before using."""
    from google.genai import types
    cfg = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json", temperature=0.1)
    text = _generate(prompt, cfg)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return json.loads(text)


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

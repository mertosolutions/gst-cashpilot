"""Vertex AI Search (Google Cloud Discovery Engine) as the rule search for the RAG layer.
The GST rule passages are imported once into a Vertex AI Search data store (scripts/vertex_search_setup.py). At decision time the same query
the local engine would use is sent to the data store and the top passages come back with their citations. If anything fails
(no credentials, no data store, quota) the caller falls back to the local engine, so the app never stops working."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
HOST = "https://discoveryengine.googleapis.com/v1"


class VertexSearchUnavailable(RuntimeError):
    pass


@lru_cache
def _session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    creds, project = google.auth.default(scopes=SCOPES)
    return AuthorizedSession(creds), project


def project_id() -> str:
    s = get_settings()
    if s.google_cloud_project:
        return s.google_cloud_project
    import os
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return os.environ["GOOGLE_CLOUD_PROJECT"]
    return ""


def data_store_path() -> str:
    s = get_settings()
    ds = s.vertex_search_data_store
    if ds.startswith("projects/"):
        return ds
    return f"projects/{project_id()}/locations/{s.vertex_search_location}/collections/default_collection/dataStores/{ds}"


def enabled() -> bool:
    s = get_settings()
    return s.rag_backend == "vertex_search" and bool(project_id())


def parse_results(payload: dict, top_k: int) -> list[dict]:
    """Discovery Engine search response -> the passage dicts the RAG layer uses. Documents carry citation/topic/body as structured data."""
    out = []
    for rank, r in enumerate(payload.get("results", [])[:top_k]):
        doc = r.get("document", {})
        d = doc.get("structData") or {}
        if not d.get("citation"):
            continue
        out.append({"id": doc.get("id") or d.get("id", ""), "citation": d["citation"], "topic": d.get("topic", ""), "body": d.get("body", ""),
                    "score": round(max(0.05, 1.0 - 0.15 * rank), 4), "cosine": None, "engine": "vertex-ai-search"})
    return out


def search(query: str, top_k: int = 3, http=None) -> list[dict]:
    """Searches the data store. `http` can be given in tests; otherwise Application Default Credentials are used."""
    sess = http or _session()[0]
    url = f"{HOST}/{data_store_path()}/servingConfigs/default_search:search"
    body = {"query": query, "pageSize": top_k, "queryExpansionSpec": {"condition": "AUTO"}, "spellCorrectionSpec": {"mode": "AUTO"}}
    resp = sess.post(url, json=body, timeout=15)
    if resp.status_code != 200:
        raise VertexSearchUnavailable(f"Vertex AI Search returned {resp.status_code}: {resp.text[:200]}")
    return parse_results(resp.json(), top_k)

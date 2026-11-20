"""Vertex AI Search adapter (no network: a fake HTTP session stands in for Google)."""
from app.services import rag, vertex_search

PAYLOAD = {"results": [
    {"document": {"id": "s16_2_aa", "structData": {"citation": "Section 16(2)(aa), CGST Act, 2017", "topic": "Invoice must appear in GSTR-2B", "body": "ITC can be taken only if..."}}},
    {"document": {"id": "s16_4", "structData": {"citation": "Section 16(4), CGST Act, 2017", "topic": "Time limit", "body": "Not after 30 November..."}}},
    {"document": {"id": "junk", "structData": {}}}]}


class FakeResp:
    def __init__(self, status, data): self.status_code, self._d, self.text = status, data, str(data)
    def json(self): return self._d


class FakeHttp:
    def __init__(self, status=200): self.status, self.calls = status, []
    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json)); return FakeResp(self.status, PAYLOAD)


def test_parse_keeps_citations_and_ranks():
    got = vertex_search.parse_results(PAYLOAD, 3)
    assert [g["citation"] for g in got] == ["Section 16(2)(aa), CGST Act, 2017", "Section 16(4), CGST Act, 2017"]
    assert got[0]["score"] > got[1]["score"] and got[0]["engine"] == "vertex-ai-search"


def test_search_calls_the_data_store_serving_config(monkeypatch):
    monkeypatch.setattr(vertex_search, "project_id", lambda: "demo-proj")
    http = FakeHttp()
    got = vertex_search.search("invoice not in GSTR-2B", 2, http=http)
    url, body = http.calls[0]
    assert url.endswith("/projects/demo-proj/locations/global/collections/default_collection/dataStores/gst-rules/servingConfigs/default_search:search")
    assert body["query"] == "invoice not in GSTR-2B" and body["pageSize"] == 2 and len(got) == 2


def test_rag_uses_vertex_search_and_falls_back_to_local(client, monkeypatch):
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        monkeypatch.setattr(vertex_search, "enabled", lambda: True)
        monkeypatch.setattr(vertex_search, "search", lambda q, k, http=None: vertex_search.parse_results(PAYLOAD, k))
        rag._VCACHE.clear()
        hit = rag.search_many(db, [{"text": "not in gstr-2b", "tags": ["not_in_2b"]}])[0]
        assert hit[0]["engine"] == "vertex-ai-search"
        def boom(q, k, http=None): raise vertex_search.VertexSearchUnavailable("no credentials")
        rag._VCACHE.clear()  # results are cached per query text, so start clean to see the failure
        monkeypatch.setattr(vertex_search, "search", boom)
        local = rag.search_many(db, [{"text": "not in gstr-2b", "tags": ["not_in_2b"]}])[0]
        assert local and local[0]["engine"] != "vertex-ai-search"  # the app keeps working

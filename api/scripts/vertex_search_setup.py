"""One-time setup of Vertex AI Search for the GST rule passages.
Run after: billing is linked to the project, the Discovery Engine API is enabled and `gcloud auth application-default login` is done.

  python scripts/vertex_search_setup.py --project YOUR_PROJECT [--data-store gst-rules] [--location global]

It creates a generic search data store and imports the passages from app/data/rules/passages.json as structured documents.
Then set in api/.env:  RAG_BACKEND=vertex_search  GOOGLE_CLOUD_PROJECT=YOUR_PROJECT"""
import argparse
import json
import sys
import time
from pathlib import Path

import google.auth
from google.auth.transport.requests import AuthorizedSession

HOST = "https://discoveryengine.googleapis.com/v1"
PASSAGES = Path(__file__).resolve().parents[1] / "app/data/rules/passages.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--data-store", default="gst-rules")
    ap.add_argument("--location", default="global")
    a = ap.parse_args()
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    http = AuthorizedSession(creds)
    parent = f"projects/{a.project}/locations/{a.location}/collections/default_collection"

    r = http.post(f"{HOST}/{parent}/dataStores?dataStoreId={a.data_store}", json={
        "displayName": "GST rule passages", "industryVertical": "GENERIC", "solutionTypes": ["SOLUTION_TYPE_SEARCH"], "contentConfig": "NO_CONTENT"})
    if r.status_code not in (200, 409):  # 409 = it already exists
        print("Could not create the data store:", r.status_code, r.text[:400]); return 1
    print("data store:", "created" if r.status_code == 200 else "already exists")
    if r.status_code == 200:
        time.sleep(10)

    docs = [{"id": p["id"], "structData": {"id": p["id"], "citation": p["citation"], "topic": p["topic"], "body": p["body"], "tags": p["tags"]}}
            for p in json.loads(PASSAGES.read_text())["passages"]]
    r = http.post(f"{HOST}/{parent}/dataStores/{a.data_store}/branches/default_branch/documents:import",
                  json={"inlineSource": {"documents": docs}, "reconciliationMode": "INCREMENTAL"})
    if r.status_code != 200:
        print("Import failed:", r.status_code, r.text[:400]); return 1
    op = r.json()["name"]
    for _ in range(30):
        s = http.get(f"{HOST}/{op}").json()
        if s.get("done"):
            print("import finished:", json.dumps(s.get("response", s.get("error", {})))[:200]); break
        time.sleep(5)
    print(f"Done. Set RAG_BACKEND=vertex_search and GOOGLE_CLOUD_PROJECT={a.project} in api/.env")
    return 0


if __name__ == "__main__":
    sys.exit(main())

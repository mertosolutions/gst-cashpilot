import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["AUTO_SEED"] = "true"
os.environ["AUTH_MODE"] = "dev"
os.environ["GEMINI_API_KEY"] = ""  # tests run offline even if api/.env has a key
os.environ["GOOGLE_API_KEY"] = ""
os.environ["DOCUMENT_AI_ENABLED"] = "false"  # tests never call Google Cloud
os.environ["RAG_BACKEND"] = "local"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c

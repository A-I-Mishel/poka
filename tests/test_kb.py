"""Knowledge-base tests: chunking, cosine math, ingest/search, isolation.

All embeddings are stubbed (deterministic, no network, no quota). The
fake embedder uses fixed vectors chosen to share NO words with the
query, proving ranking is by vector similarity rather than keywords.
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from services import kb as kb_svc
from services import kb_embeddings


MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 51>>stream\n"
    b"BT /F1 12 Tf 10 100 Td (hello knowledge base) Tj ET\n"
    b"endstream\nendobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"startxref\n0\n%%EOF\n"
)


class FakeEmbedder:
    """Fixed vectors by exact text: ranking proves vector math, not keywords."""

    def __init__(self, mapping, default=(1.0, 0.0)):
        self.mapping = dict(mapping)
        self.default = tuple(default)

    def __call__(self, texts):
        return [list(self.mapping.get(str(t), self.default)) for t in texts]


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def open_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    return tmp_path


@pytest.fixture()
def stubbed_embedder():
    kb_embeddings.configure_embedder(kb_embeddings.stub_embed)
    try:
        yield kb_embeddings.stub_embed
    finally:
        kb_embeddings.configure_embedder(None)


def test_chunk_text_bounds_and_overlap():
    text = " ".join("word%d" % i for i in range(200))
    chunks = kb_svc.chunk_text(text, chunk_chars=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks)
    # Overlap: adjacent chunks share words.
    assert set(chunks[0].split()) & set(chunks[1].split())
    # Deterministic.
    assert chunks == kb_svc.chunk_text(text, chunk_chars=300, overlap=50)
    assert kb_svc.chunk_text("") == []
    assert kb_svc.chunk_text("   ") == []


def test_cosine_math():
    assert kb_svc.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert kb_svc.cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert kb_svc.cosine([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)
    assert kb_svc.cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0
    assert kb_svc.cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert kb_svc.cosine([], []) == 0.0
    assert kb_svc.cosine(None, [1.0]) == 0.0


def test_extract_text_txt_and_csv():
    text, reason = kb_svc.extract_text(b"hello world", "note.csv")
    assert reason == "" and text == "hello world"
    text, reason = kb_svc.extract_text(b"a,b\n1,2\n", "d.csv")
    assert reason == "" and "a,b" in text


def test_extract_text_pdf():
    text, reason = kb_svc.extract_text(MINIMAL_PDF, "doc.pdf")
    assert reason == "", reason
    assert "knowledge" in text


def test_extract_text_unsupported_and_empty():
    text, reason = kb_svc.extract_text(b"\x89PNG\r\n\x1a\n", "photo.png")
    assert text == "" and reason.startswith("unsupported-type")
    text, reason = kb_svc.extract_text(b"   ", "empty.csv")
    assert text == "" and reason == "empty"


def test_ingest_search_ranks_by_vector_not_keywords(open_env, stubbed_embedder):
    fake = FakeEmbedder({
        "apple banana cherry": (1.0, 0.0),
        "quantum physics entanglement": (0.0, 1.0),
        "french cuisine recipes": (0.1, 0.99),
    })
    kb_embeddings.configure_embedder(fake)
    try:
        r1 = kb_svc.ingest_document("u1", "doc1", "fruit.csv", b"apple banana cherry")
        r2 = kb_svc.ingest_document("u1", "doc2", "physics.csv", b"quantum physics entanglement")
        assert r1["ingested"] and r1["chunks"] == 1
        assert r2["ingested"] and r2["chunks"] == 1
        hits = kb_svc.search("u1", "french cuisine recipes")
        assert len(hits) == 2
        # Zero shared words with the query, yet ranked first by vector.
        assert hits[0]["upload_id"] == "doc2"
        assert hits[0]["name"] == "physics.csv"
        assert hits[0]["score"] > hits[1]["score"]
    finally:
        kb_embeddings.configure_embedder(None)


def test_search_is_per_user(open_env, stubbed_embedder):
    kb_svc.ingest_document("alice", "d1", "a.csv", b"secret alice content here")
    assert kb_svc.search("alice", "secret alice content") != []
    assert kb_svc.search("bob", "secret alice content") == []


def test_search_skips_dim_mismatch(open_env):
    kb_embeddings.configure_embedder(FakeEmbedder({"doc text here": (1.0, 0.0)}))
    try:
        assert kb_svc.ingest_document("u", "d", "a.csv", b"doc text here")["ingested"]
    finally:
        kb_embeddings.configure_embedder(None)
    kb_embeddings.configure_embedder(FakeEmbedder({"query words": (0.0, 1.0, 0.0)}))
    try:
        assert kb_svc.search("u", "query words") == []
    finally:
        kb_embeddings.configure_embedder(None)


def test_search_respects_valid_ids(open_env, stubbed_embedder):
    kb_svc.ingest_document("u", "keep", "k.csv", b"keep this document content")
    kb_svc.ingest_document("u", "drop", "d.csv", b"drop this document content")
    hits = kb_svc.search("u", "document content", valid_ids={"keep"})
    assert [h["upload_id"] for h in hits] == ["keep"]


def test_ingest_embed_failure_degrades(open_env):
    def _boom(texts):
        raise RuntimeError("no network")

    kb_embeddings.configure_embedder(_boom)
    try:
        res = kb_svc.ingest_document("u", "d", "a.csv", b"some text here")
        assert res["ingested"] is False and res["reason"] == "embed-failed"
        assert kb_svc.search("u", "some text") == []
    finally:
        kb_embeddings.configure_embedder(None)


def test_drop_document(open_env, stubbed_embedder):
    kb_svc.ingest_document("u", "d", "a.csv", b"forget this text")
    assert kb_svc.search("u", "forget this") != []
    assert kb_svc.drop_document("u", "d") is True
    assert kb_svc.search("u", "forget this") == []
    assert kb_svc.drop_document("u", "d") is False


def test_kb_persists_in_vault(open_env, stubbed_embedder):
    kb_svc.ingest_document("u", "d", "a.csv", b"persistent text here")
    kb = kb_svc.load_kb("u")
    assert set(kb["docs"]) == {"d"}
    assert kb["docs"]["d"]["chunks"][0]["vector"] != []
    assert (open_env / "data" / "users" / "u" / "kb.json").exists()


def test_upload_ingests_into_kb(open_env):
    from backend.main import app

    kb_embeddings.configure_embedder(kb_embeddings.stub_embed)
    try:
        with TestClient(app) as client:
            res = client.post(
                "/api/uploads",
                files={"file": ("report.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            )
            assert res.status_code == 200, res.text
            # Ephemeral open-mode upload: find whichever vault got the doc.
            found = []
            users = open_env / "data" / "users"
            for vault in users.iterdir():
                kb = kb_svc.load_kb(vault.name)
                if kb.get("docs"):
                    found.append(kb)
            assert len(found) == 1
            doc = list(found[0]["docs"].values())[0]
            assert doc["name"] == "report.pdf" and len(doc["chunks"]) >= 1
    finally:
        kb_embeddings.configure_embedder(None)


def test_upload_unsupported_type_skips_kb(open_env):
    from backend.main import app

    with TestClient(app) as client:
        res = client.post(
            "/api/uploads",
            files={"file": ("note.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        )
        assert res.status_code == 200, res.text
    res = kb_svc.ingest_document("u", "img1", "photo.png", b"\x89PNG\r\n\x1a\n")
    assert res["ingested"] is False


def test_search_documents_tool(open_env, stubbed_embedder):
    from services import context as ctx
    from services.files import FileStore
    from tools.kb_search_tool import search_documents

    ctx.set_current_user_id("tool-user")
    ctx.set_limit_key("tool-user")
    try:
        out = search_documents.invoke({"query": "nothing anywhere"})
        assert out.startswith("STATUS=EMPTY")
        # Mirror the upload endpoint: registry entry first, then ingest.
        csv_bytes = b"step,action\n1,deploy with render\n2,blueprint publish\n"
        meta = FileStore("tool-user").save_upload(csv_bytes, "guide.csv")
        kb_svc.ingest_document("tool-user", meta.id, "guide.csv", csv_bytes)
        out = search_documents.invoke({"query": "deploy with render blueprint"})
        assert "guide.csv" in out
    finally:
        ctx.set_current_user_id(None)
        ctx.set_limit_key(None)

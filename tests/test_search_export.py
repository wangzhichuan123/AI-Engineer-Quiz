"""HTTP acceptance tests, real auth, FTS5 and the same demo generator as manual QA."""
import csv
import io
import sqlite3
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from keepstack import app as http, audit, auth, db, ingest, search, search_demo
from keepstack.config import config


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    for name, path in (("data_dir", tmp_path), ("db_path", tmp_path / "catalog.db"),
                       ("blob_dir", tmp_path / "blobs"), ("thumb_dir", tmp_path / "thumbs"),
                       ("cache_dir", tmp_path / "cache")):
        monkeypatch.setattr(config, name, path)
    monkeypatch.setattr(config, "ai_enabled", False)
    monkeypatch.setattr(config, "ocr_enabled", False)
    conn = sqlite3.connect(config.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for module in (db, http, audit, auth, ingest, search, search_demo):
        monkeypatch.setattr(module, "get_conn", lambda: conn)
    data = search_demo.populate()
    with TestClient(http.app) as client:
        login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        assert login.status_code == 200
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        yield client, data
    conn.close()


def filters(**changes):
    result = dict(q="harbor", collection_id=1, include_tags=["approved", "campaign"],
                  exclude_tags=["internal"], media_type="document", sort="oldest")
    result.update(changes)
    return result


def get_list(client, **params):
    response = client.get("/api/assets", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def get_csv(client, **params):
    response = client.get("/api/assets/export.csv", params=params)
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "attachment" in response.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"), newline="")))


def test_combined_filters_and_exact_tags(catalog):
    client, data = catalog
    result = get_list(client, **filters(include_tags=["APPROVED", "approved", "campaign"]))
    assert result["total"] == 66
    assert [a["uuid"] for a in result["items"]] == data["document_matches"][:60]
    assert get_list(client, **filters(exclude_tags=["internal", "approved"]))["total"] == 0
    assert get_list(client, **filters(include_tags=["does-not-exist"]))["total"] == 0
    assert get_list(client, **filters(include_tags=['客户, "甲"']))["total"] == 1
    assert get_list(client, **filters(collection_id=999))["total"] == 0
    assert get_list(client, **filters(media_type="image"))["total"] == 1
    # Regression: legacy tag + collection + FTS had SQL binding order wrong.
    assert get_list(client, **filters(tag="approved"))["total"] == 66


@pytest.mark.parametrize("sort", ["oldest", "newest"])
def test_pages_tied_dates_and_export_order(catalog, sort):
    client, data = catalog
    expected = data["document_matches"][::1 if sort == "oldest" else -1]
    found = []
    for offset in range(0, 80, 7):
        result = get_list(client, **filters(sort=sort), limit=7, offset=offset)
        assert result["total"] == 66
        found.extend(a["uuid"] for a in result["items"])
    assert found == expected
    assert len(set(found)) == 66
    # Export ignores page parameters and includes all matches in exactly the same order.
    assert [r["uuid"] for r in get_csv(client, **filters(sort=sort), limit=7, offset=14)] == expected


def test_csv_roundtrip_and_empty_header(catalog):
    import json
    client, _ = catalog
    rows = get_csv(client, **filters())
    assert rows[0]["description"] == '中文港口, "宣传"\n第二行'
    assert json.loads(rows[-1]["tags"]) == ["approved", "campaign", "internal-only", '客户, "甲"']
    assert set(rows[0]) == {"uuid", "title", "description", "filename", "media_type", "tags", "created_at"}
    response = client.get("/api/assets/export.csv", params=filters(q="missingneedle"))
    assert response.content.decode("utf-8-sig").strip() == "uuid,title,description,filename,media_type,tags,created_at"


@pytest.mark.parametrize("q", ["   ", '"harbor" OR (harbor*) --', "!!!", "中文", "'; DROP TABLE assets; --"])
def test_special_queries_never_fail(catalog, q):
    client, _ = catalog
    result = get_list(client, **filters(q=q))
    rows = get_csv(client, **filters(q=q))
    assert len(rows) == result["total"]
    if not q.strip():
        assert result["total"] == 67
    if q == "!!!":
        assert result["total"] == 0


@pytest.mark.parametrize("params", [dict(limit=0), dict(limit=-1), dict(limit=201), dict(offset=-1),
    dict(offset="bad"), dict(offset=2**63), dict(collection_id=0), dict(collection_id=2**63), dict(sort="oops"),
    dict(status="deleted"), dict(mode="semantic")])
def test_invalid_parameters(catalog, params):
    client, _ = catalog
    assert client.get("/api/assets", params=params).status_code == 422


def test_auth_and_export_validation(catalog):
    client, _ = catalog
    for params in (dict(collection_id=-1), dict(sort="invalid"), dict(status="deleted")):
        assert client.get("/api/assets/export.csv", params=params).status_code == 422
    client.headers.pop("Authorization")
    for path in ("/api/assets", "/api/assets/export.csv"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_edits_reindex_title_description_and_tags(catalog):
    client, data = catalog
    uuid = data["uuids"][0]
    path = "/api/assets/" + uuid
    assert client.patch(path, json={"title": '新标题, "修订"\nnext', "description": "freshneedle"}).status_code == 200
    assert get_list(client, q="freshneedle")["total"] == 1
    assert get_list(client, **filters())["total"] == 65
    assert get_csv(client, q="freshneedle")[0]["title"] == '新标题, "修订"\nnext'
    assert client.post(path + "/tags", json={"name": "NewNeedle"}).status_code == 200
    assert get_list(client, q="newneedle")["total"] == 1
    assert len(get_csv(client, include_tags=["newneedle"])) == 1
    assert client.delete(path + "/tags/newneedle").status_code == 200
    assert get_list(client, q="newneedle")["total"] == 0
    assert get_csv(client, include_tags=["newneedle"]) == []
    assert client.post(path + "/tags", json={"name": "internal"}).status_code == 200
    assert get_csv(client, exclude_tags=["internal"], q="freshneedle") == []


def test_remove_tag_with_slash_updates_query_and_export(catalog):
    client, data = catalog
    path = "/api/assets/" + data["uuids"][0]
    name = '客户/外宣, "甲" #1?'
    assert client.post(path + "/tags", json={"name": name}).status_code == 200
    assert get_list(client, include_tags=[name])["total"] == 1
    assert len(get_csv(client, include_tags=[name])) == 1
    assert client.delete(path + "/tags/" + quote(name, safe="")).status_code == 200
    assert get_list(client, include_tags=[name])["total"] == 0
    assert get_csv(client, include_tags=[name]) == []


def test_large_export_batches_tags_without_skipping_rows(catalog):
    import json
    client, _ = catalog
    conn = db.get_conn()
    # No blobs are needed for metadata-only export. Span multiple export batches.
    for index in range(450):
        cur = conn.execute(
            "INSERT INTO assets (uuid, sha256, filename, title, storage_key, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (f"batch-{index}", "synthetic", "batch.txt", "batchneedle", "unused",
             "2026-02-01T00:00:00Z", "2026-02-01T00:00:00Z"))
        if index % 2 == 0:
            conn.execute("INSERT INTO asset_tags (asset_id, tag_id) "
                         "SELECT ?, id FROM tags WHERE name IN ('approved', 'campaign')", (cur.lastrowid,))
        conn.execute("INSERT INTO asset_fts (rowid, title) VALUES (?,?)", (cur.lastrowid, "batchneedle"))
    conn.commit()
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        rows = get_csv(client, q="batchneedle", sort="oldest")
    finally:
        conn.set_trace_callback(None)
    assert [row["uuid"] for row in rows] == [f"batch-{i}" for i in range(450)]
    assert all(json.loads(row["tags"]) == (["approved", "campaign"] if i % 2 == 0 else [])
               for i, row in enumerate(rows))
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 8, f"Export performed {len(selects)} SELECTs for 450 rows"

"""Reproducible search acceptance catalog: python -m keepstack.search_demo.

Use a fresh KEEPSTACK_DATA_DIR. Creates real synthetic files, never downloads media.
"""
from __future__ import annotations

import io
import json

from PIL import Image

from . import ingest
from .db import get_conn, init_db


def populate() -> dict:
    init_db()
    conn = get_conn()
    if conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]:
        raise ValueError("Search demo requires an empty asset catalog; use a fresh KEEPSTACK_DATA_DIR")
    for cid, name in ((1, "Harbor campaign"), (2, "Other collection")):
        conn.execute("INSERT INTO collections (id, uuid, name, created_at) VALUES (?,?,?,?)",
                     (cid, f"search-demo-collection-{cid}", name, "2026-01-01T00:00:00Z"))
    conn.commit()
    ids, matching = [], []
    # 65 base matches, then controls; the exact-tag control at 72 also matches.
    for index in range(73):
        title = f"Harbor asset {index:03d}"
        description = '中文港口, "宣传"\n第二行' if index == 0 else "Campaign description"
        tags, collection, status = ["approved", "campaign"], 1, "active"
        if index == 65:
            tags.append("internal")
        elif index == 66:
            tags = ["approved"]
        elif index == 67:
            collection = 2
        elif index == 68:
            status = "deleted"
        elif index == 70:
            title = "Mountain asset"
        elif index == 71:
            tags = ["approved-extra", "campaign"]
        elif index == 72:
            tags += ['客户, "甲"', "internal-only"]
        if index == 69:
            data = io.BytesIO()
            Image.new("RGB", (32, 32), (80, 140, 200)).save(data, format="PNG")
            data.seek(0)
            filename = "sample.png"
        else:
            data = io.BytesIO(f"Synthetic search fixture {index}".encode())
            filename = f"sample-{index:03d}.txt"
        asset = ingest.ingest_stream(data, filename, title=title, run_ai=False)
        aid = asset["id"]
        ids.append(asset["uuid"])
        if index < 65 or index == 72:
            matching.append(asset["uuid"])
        # Five consecutive assets share a timestamp, including page boundaries.
        created = f"2026-01-{1 + index // 5:02d}T00:00:00Z"
        conn.execute("UPDATE assets SET description=?, status=?, created_at=? WHERE id=?",
                     (description, status, created, aid))
        ingest._set_tags(conn, aid, [(tag, 1.0) for tag in tags], "manual")
        conn.execute("INSERT INTO collection_assets (collection_id, asset_id) VALUES (?,?)",
                     (collection, aid))
        conn.commit()
        ingest.reindex_fts(aid)
    return {"uuids": ids, "document_matches": matching, "collection_id": 1}


if __name__ == "__main__":
    print(json.dumps(populate(), indent=2))

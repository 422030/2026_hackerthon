"""LLM 응답 캐시. [담당: B]

DB 와 snapshots/*.json 양쪽에 쓴다.
DB 가 깨져도 파일이 남고, 파일은 git 에 커밋되어 다른 노트북에서도 데모가 된다.
현장 네트워크가 막혔을 때의 폴백이 이 파일 하나에 걸려 있다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.db import connect
from app.schema import PageAnalysis, content_hash

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "snapshots"


def cache_key(task: str, content_sig: str, prompt_version: str, model_id: str) -> str:
    """task 는 'page_analysis'. 장래에 다른 작업이 붙어도 키가 섞이지 않게 네임스페이스를 둔다."""
    return content_hash(task, content_sig, prompt_version, model_id)


def _snapshot_path(key: str) -> Path:
    return SNAPSHOT_DIR / f"{key}.json"


def cache_get(key: str) -> PageAnalysis | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT analysis_json FROM llm_cache WHERE key = ?", (key,)
        ).fetchone()
    if row:
        pa = PageAnalysis.model_validate_json(row["analysis_json"])
        pa.source = "cache"
        return pa

    path = _snapshot_path(key)
    if path.exists():
        pa = PageAnalysis.model_validate_json(path.read_text(encoding="utf-8"))
        pa.source = "snapshot"
        return pa
    return None


def cache_put(key: str, pa: PageAnalysis, task: str = "page_analysis") -> None:
    payload = pa.model_dump_json()
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache"
            "(key, task, content_sig, prompt_version, model_id, analysis_json, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                key,
                task,
                pa.page_sha1,
                pa.prompt_version,
                pa.model_id,
                payload,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    _snapshot_path(key).write_text(payload, encoding="utf-8")


def count() -> int:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM llm_cache").fetchone()
    return int(row["n"]) if row else 0

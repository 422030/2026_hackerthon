"""파이프라인 오케스트레이션. [담당: C]

반복문 하나가 제품의 본체다.
어떤 페이지가 실패해도 예외로 전체를 죽이지 않고 끝까지 간다.
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

from app import assemble, ingest, ocr as ocr_mod
from app.db import connect
from app.llm import adapter, guard
from app.schema import AccessDoc, JobStatus, PageAnalysis, PageImage, RenderOptions

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
RETRY_SOURCES = {"degraded", "snapshot"}
PAGE_WORKERS = 2  # Limit concurrent OCR/Gemini calls to avoid API bursts.

_jobs: dict[str, JobStatus] = {}
_docs: dict[str, AccessDoc] = {}
_cancelled: set[str] = set()
_lock = threading.Lock()


def cancel(job_id: str) -> bool:
    """중단을 요청한다. 돌고 있는 쪽은 끝까지 가고 그 다음 쪽부터 멈춘다.

    AI 호출 한가운데를 끊을 수단이 없다. 한 쪽을 버리느니 기다린다.
    """
    st = _jobs.get(job_id)
    if st is None or st.status not in {"queued", "running"}:
        return False
    with _lock:
        _cancelled.add(job_id)
    return True


def new_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = JobStatus(job_id=job_id, status="queued")
    return job_id


def get_status(job_id: str) -> JobStatus | None:
    return _jobs.get(job_id)


def get_doc(job_id: str) -> AccessDoc | None:
    """메모리에 없으면 DB 에서 꺼낸다. 서버를 재시작해도 결과가 살아 있어야 한다."""
    doc = _docs.get(job_id)
    if doc is not None:
        return doc
    with connect() as conn:
        row = conn.execute(
            "SELECT doc_json FROM jobs WHERE id = ? AND doc_json IS NOT NULL", (job_id,)
        ).fetchone()
    if not row:
        return None
    doc = AccessDoc.model_validate_json(row["doc_json"])
    _docs[job_id] = doc
    return doc


def list_jobs(limit: int = 50) -> list[dict]:
    """보관함 목록. 변환이 끝난 것만 최신순으로."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, filename, pages_total, degraded_json, created_at, doc_json"
            " FROM jobs WHERE doc_json IS NOT NULL"
            " ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    out = []
    for row in rows:
        try:
            doc = AccessDoc.model_validate_json(row["doc_json"])
            stats = doc.stats.model_dump()
            title = doc.title
            page_range = list(doc.page_range)
        except Exception:  # noqa: BLE001 - 스키마가 바뀐 옛 기록은 건너뛰지 않고 최소 정보만
            stats, title, page_range = {}, row["filename"], [1, 1]
        out.append(
            {
                "job_id": row["id"],
                "title": title,
                "filename": row["filename"],
                "pages": row["pages_total"],
                "page_range": page_range,
                "created_at": row["created_at"],
                "degraded": json.loads(row["degraded_json"] or "[]"),
                "stats": stats,
            }
        )
    return out


def delete_job(job_id: str) -> bool:
    """보관함에서 지운다. llm_cache 와 snapshots 는 남긴다.

    캐시 키는 페이지 내용 해시라 여러 job 이 같은 항목을 공유한다.
    여기서 같이 지우면 다른 job 의 재생과 오프라인 경로가 깨진다.
    """
    with connect() as conn:
        cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.execute("DELETE FROM pages WHERE job_id = ?", (job_id,))
        removed = cur.rowcount > 0

    with _lock:
        _jobs.pop(job_id, None)
        _docs.pop(job_id, None)
    return removed


def failed_pages(job_id: str) -> list[int]:
    """다시 돌릴 쪽 번호. pages 테이블의 page_no 는 PDF 순번이다."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT page_no FROM pages WHERE job_id = ? AND source IN (?,?)"
            " ORDER BY page_no",
            (job_id, *sorted(RETRY_SOURCES)),
        ).fetchall()
    return [r["page_no"] for r in rows]


def retry(job_id: str, opts: RenderOptions | None = None) -> None:
    """실패한 쪽만 다시 돌린다. 성공한 쪽은 그대로 두고 문서를 다시 조립한다."""
    opts = opts or RenderOptions()
    st = _jobs.get(job_id) or JobStatus(job_id=job_id, status="queued")
    with _lock:
        _jobs[job_id] = st
    st.status = "running"
    st.error = None
    st.degraded_pages = []

    try:
        with connect() as conn:
            saved = conn.execute(
                "SELECT page_no, analysis_json, source, image_path FROM pages"
                " WHERE job_id = ? ORDER BY page_no",
                (job_id,),
            ).fetchall()
            job_row = conn.execute(
                "SELECT filename FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()

        if not saved or not job_row:
            raise RuntimeError("이 변환의 페이지 기록이 없다")

        # 원본 PDF 는 처음 변환할 때 지웠다. 뽑아둔 PNG 로 다시 돌린다.
        cached = {r["page_no"]: r["image_path"] for r in saved}

        targets = [r["page_no"] for r in saved if r["source"] in RETRY_SOURCES]
        st.pages_total = len(targets)
        st.pages_done = 0
        if not targets:
            st.stage = "render"
            st.status = "done"
            return

        fixed: dict[int, PageAnalysis] = {}
        for page_no in targets:
            if job_id in _cancelled:
                break
            st.current_page = page_no

            st.stage = "ingest"
            page = ingest.load_cached_page(cached.get(page_no, ""))
            if page is None:
                st.degraded_pages.append(page_no)
                st.pages_done += 1
                continue

            st.stage = "ocr"
            ocr_result = ocr_mod.run_ocr(page)

            st.stage = "analyze"
            pa = adapter.analyze_page(page, ocr_result)
            pa = guard.cross_check(pa, ocr_result)

            if pa.source in RETRY_SOURCES:
                st.degraded_pages.append(page_no)
            fixed[page_no] = pa
            st.pages_done += 1
            _save_page(job_id, page, pa)

        analyses = [
            fixed.get(r["page_no"])
            or PageAnalysis.model_validate_json(r["analysis_json"])
            for r in saved
        ]

        st.stage = "assemble"
        doc = assemble.assemble(
            analyses,
            {"job_id": job_id, "source_filename": job_row["filename"]},
            opts,
        )
        doc.degraded_pages = sorted(set(doc.degraded_pages))

        with _lock:
            _docs[job_id] = doc
        _save_job(job_id, job_row["filename"], doc, st)

        st.stage = "render"
        st.status = "done"
        st.degraded_pages = doc.degraded_pages
    except Exception as exc:  # noqa: BLE001 - 상태로 보고하고 죽지 않는다
        st.status = "error"
        st.error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()


def _discard_source(path: str, pages: list[PageImage]) -> None:
    """쪽을 다 뽑은 원본 업로드 파일을 지운다.

    이미지를 올린 경우 그 파일이 곧 쪽 이미지다. 지우면 변환할 것이 없어지므로
    건너뛴다. 업로드 폴더 밖의 파일도 건드리지 않는다.
    지우지 못해도 변환은 그대로 간다.
    """
    src = Path(path).resolve()
    if any(Path(p.image_path).resolve() == src for p in pages):
        return
    if src.parent != UPLOAD_DIR.resolve():
        return
    try:
        src.unlink(missing_ok=True)
    except OSError:
        pass


def run(
    job_id: str,
    path: str,
    page_from: int,
    page_to: int,
    opts: RenderOptions | None = None,
) -> None:
    """백그라운드 스레드에서 돌린다."""
    st = _jobs[job_id]
    st.status = "running"
    opts = opts or RenderOptions()

    try:
        st.stage = "ingest"
        pages = ingest.load_pages(path, page_range=(page_from, page_to))
        if not pages:
            # 읽은 쪽이 없으면 여기서 끝낸다. 가짜 데이터로 메우면
            # 원문에 없는 내용이 사용자 문서로 나간다.
            total = ingest.page_count(path)
            if total is None:
                raise RuntimeError(
                    "파일을 열지 못했습니다. PDF 가 손상되었거나 암호가 걸려 있을 수 있습니다."
                )
            raise RuntimeError(
                f"{page_from}쪽을 찾을 수 없습니다. 이 문서는 {total}쪽까지 있습니다."
            )

        # 쪽을 다 뽑았으면 원본은 더 쓰지 않는다. 교재 한 권이 수백 MB 라
        # 남겨 두면 변환할 때마다 디스크에 그대로 쌓인다.
        _discard_source(path, pages)

        st.pages_total = len(pages)
        # Keep at most two pages in flight. Submit the next only when one finishes,
        # so cancellation does not queue the entire document.
        results: dict[int, PageAnalysis] = {}

        def process_page(page: PageImage) -> PageAnalysis:
            ocr_result = ocr_mod.run_ocr(page)
            pa = adapter.analyze_page(page, ocr_result)
            return guard.cross_check(pa, ocr_result)

        st.stage = "analyze"
        with ThreadPoolExecutor(max_workers=PAGE_WORKERS) as pool:
            remaining = iter(pages)
            pending = {}

            def submit_next() -> bool:
                if job_id in _cancelled:
                    return False
                page = next(remaining, None)
                if page is None:
                    return False
                pending[pool.submit(process_page, page)] = page
                st.current_page = page.page_no
                return True

            for _ in range(PAGE_WORKERS):
                if not submit_next():
                    break

            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    page = pending.pop(future)
                    pa = future.result()
                    results[page.page_no] = pa
                    if pa.source in {"degraded", "snapshot"}:
                        st.degraded_pages.append(page.page_no)
                    st.pages_done += 1
                    _save_page(job_id, page, pa)
                for _ in done:
                    submit_next()

        # Concurrent completion order differs from PDF reading order.
        analyses = [results[p.page_no] for p in pages if p.page_no in results]

        stopped = job_id in _cancelled
        if stopped and not analyses:
            st.status = "cancelled"
            st.stage = "idle"
            return

        st.stage = "assemble"
        doc = assemble.assemble(
            analyses,
            {"job_id": job_id, "source_filename": Path(path).name},
            opts,
        )
        doc.degraded_pages = sorted(set(doc.degraded_pages))

        _docs[job_id] = doc
        _save_job(job_id, path, doc, st)

        # 중단해도 여기까지 변환한 쪽은 버리지 않는다.
        st.stage = "render"
        st.status = "cancelled" if stopped else "done"
        st.degraded_pages = doc.degraded_pages
    except Exception as exc:  # noqa: BLE001 - 상태로 보고하고 죽지 않는다
        st.status = "error"
        st.error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        with _lock:
            _cancelled.discard(job_id)


def _save_page(job_id: str, page, pa: PageAnalysis) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pages"
            "(job_id, page_no, sha1, image_path, analysis_json, source, elapsed_ms)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                job_id,
                page.page_no,
                page.sha1,
                page.image_path,
                pa.model_dump_json(),
                pa.source,
                pa.elapsed_ms,
            ),
        )


def _save_job(job_id: str, path: str, doc: AccessDoc, st: JobStatus) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO jobs"
            "(id, filename, status, stage, pages_total, pages_done, doc_json,"
            " degraded_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                Path(path).name,
                "done",
                "render",
                st.pages_total,
                st.pages_done,
                doc.model_dump_json(),
                json.dumps(doc.degraded_pages),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

"""FastAPI 앱. 로컬에서만 돈다. 배포하지 않는다. [담당: C]

실행:  uv run uvicorn app.main:app --reload --port 8000
열기:  http://localhost:8000
"""

from __future__ import annotations

import html
import re
import shutil
import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import db, jobs
from app.llm import adapter
from app.render import html as html_render
from app.render import markdown as md_render
from app.render import speech as speech_render
from app.schema import RenderOptions

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = jobs.UPLOAD_DIR
WEB_DIR = ROOT / "web"

# 한 번에 변환할 수 있는 쪽 수. 쪽당 1분 안팎이 걸린다.
MAX_PAGES = 20

app = FastAPI(title="전공 교재 접근성 변환기")
db.init()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/result.html")
def result_page() -> FileResponse:
    return FileResponse(WEB_DIR / "result.html")


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse(adapter.backend_status())


@app.post("/api/jobs")
async def create_job(
    file: UploadFile,
    page_from: int = Form(1),
    page_to: int = Form(3),
    footnote_mode: str = Form("end"),
) -> JSONResponse:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / (file.filename or "upload.pdf")
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # 범위를 서버에서 다시 자른다. 화면의 안내만으로는 막지 못하고,
    # 범위가 넓으면 되돌릴 방법 없이 몇 시간짜리 작업이 돈다.
    page_from = max(1, page_from)
    page_to = max(page_from, page_to)
    capped = min(page_to, page_from + MAX_PAGES - 1)

    job_id = jobs.new_job()
    opts = RenderOptions(footnote_mode=footnote_mode)  # type: ignore[arg-type]
    threading.Thread(
        target=jobs.run,
        args=(job_id, str(dest), page_from, capped, opts),
        daemon=True,
    ).start()
    return JSONResponse(
        {
            "job_id": job_id,
            "page_from": page_from,
            "page_to": capped,
            "capped": capped < page_to,
            "max_pages": MAX_PAGES,
        }
    )


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> JSONResponse:
    """변환 중단. 돌고 있는 쪽까지만 끝내고 멈춘다."""
    if not jobs.cancel(job_id):
        return JSONResponse({"error": "멈출 수 있는 작업이 아닙니다."}, status_code=400)
    return JSONResponse({"job_id": job_id, "cancelling": True})


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, footnote_mode: str = Form("end")) -> JSONResponse:
    """실패한 쪽만 다시 돌린다. 전체를 다시 올리지 않게 한다."""
    pages = jobs.failed_pages(job_id)
    if not pages:
        return JSONResponse({"error": "다시 돌릴 쪽이 없습니다."}, status_code=400)

    opts = RenderOptions(footnote_mode=footnote_mode)  # type: ignore[arg-type]
    threading.Thread(target=jobs.retry, args=(job_id, opts), daemon=True).start()
    return JSONResponse({"job_id": job_id, "pages": pages})


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    st = jobs.get_status(job_id)
    if st is None:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return JSONResponse(st.model_dump())


@app.get("/api/jobs/{job_id}/doc")
def job_doc(job_id: str) -> JSONResponse:
    doc = jobs.get_doc(job_id)
    if doc is None:
        return JSONResponse({"error": "not ready"}, status_code=404)
    return JSONResponse(doc.model_dump())


@app.get("/api/jobs/{job_id}/html", response_class=HTMLResponse)
def job_html(job_id: str, footnote_mode: str = "end") -> HTMLResponse:
    doc = jobs.get_doc(job_id)
    if doc is None:
        return HTMLResponse("<p>아직 준비되지 않았습니다.</p>", status_code=404)
    opts = RenderOptions(footnote_mode=footnote_mode)  # type: ignore[arg-type]
    return HTMLResponse(html_render.to_html(doc, opts))


@app.get("/api/jobs/{job_id}/download.html", response_class=HTMLResponse)
def job_html_file(job_id: str, footnote_mode: str = "end") -> HTMLResponse:
    """내려받는 HTML. 혼자서 열리는 완성된 문서다.

    화면용 조각과 달리 문자 인코딩 선언과 스타일을 안에 담는다.
    받은 파일을 그대로 스크린리더로 열기 때문에 바깥에 기대는 것이 없어야 한다.
    """
    doc = jobs.get_doc(job_id)
    if doc is None:
        return HTMLResponse("<p>아직 준비되지 않았습니다.</p>", status_code=404)

    opts = RenderOptions(footnote_mode=footnote_mode)  # type: ignore[arg-type]
    css = (WEB_DIR / "a11y.css").read_text(encoding="utf-8")
    body = html_render.to_html(doc, opts)
    title = doc.title or Path(doc.source_filename).stem

    page = (
        "<!doctype html>\n"
        '<html lang="ko">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>\n{css}\n</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )
    return HTMLResponse(page, headers=_disposition(download_name(doc, "html")))


@app.get("/api/jobs/{job_id}/speech")
def job_speech(job_id: str) -> JSONResponse:
    doc = jobs.get_doc(job_id)
    if doc is None:
        return JSONResponse({"error": "not ready"}, status_code=404)
    return JSONResponse([s.model_dump() for s in speech_render.to_speech_text(doc)])


def download_name(doc, ext: str) -> str:
    """내려받는 파일 이름. 책이름_시작쪽-끝쪽.

    여러 범위를 내려받아도 서로 구분되어야 한다.
    파일 이름에 쓸 수 없는 글자는 밑줄로 바꾼다.
    """
    stem = Path(doc.source_filename or "교재").stem
    while Path(stem).suffix:  # '....pdf.pdf' 처럼 확장자가 겹친 경우
        stem = Path(stem).stem
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip() or "교재"
    first, last = doc.page_range
    return f"{stem}_{first}-{last}.{ext}"


def _disposition(name: str) -> dict[str, str]:
    """한글 파일 이름은 그대로 못 싣는다. RFC 5987 형식을 같이 보낸다."""
    quoted = quote(name, safe="")
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"}


@app.get("/api/jobs/{job_id}/markdown", response_class=PlainTextResponse)
def job_markdown(job_id: str) -> PlainTextResponse:
    doc = jobs.get_doc(job_id)
    if doc is None:
        return PlainTextResponse("아직 준비되지 않았습니다.", status_code=404)
    return PlainTextResponse(
        md_render.to_markdown(doc), headers=_disposition(download_name(doc, "md"))
    )


@app.get("/api/jobs/{job_id}/baseline", response_class=PlainTextResponse)
def job_baseline(job_id: str) -> PlainTextResponse:
    """좌우 비교 화면용. 일반 OCR 결과 평문."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT analysis_json FROM pages WHERE job_id = ? ORDER BY page_no", (job_id,)
        ).fetchall()
    if not rows:
        return PlainTextResponse("(OCR 결과 없음. fixtures 모드로 실행 중일 수 있습니다.)")

    import json

    chunks = []
    for row in rows:
        data = json.loads(row["analysis_json"])
        chunks.append(" ".join(b.get("text", "") for b in data.get("blocks", [])))
    return PlainTextResponse("\n\n".join(chunks))


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")

"""LLM 호출 경로. [담당: B]

경로 네 개: 캐시 -> 온라인 -> 교정 재요청 -> degraded.
어떤 실패도 예외로 파이프라인을 죽이지 않는다.

백엔드는 환경변수로 고른다.
  GEMINI_API_KEY 또는 GOOGLE_API_KEY  -> Gemini
  ANTHROPIC_API_KEY                    -> Claude
둘 다 없으면 degraded 경로로만 동작한다.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from app import cache, heuristics
from app.llm import backend_gemini, prompts
from app.ocr import line_table
from app.schema import OcrResult, PageAnalysis, PageImage

FORCE_OFFLINE = False
TIMEOUT_S = 90
RAW_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw"


def set_offline(flag: bool) -> None:
    global FORCE_OFFLINE
    FORCE_OFFLINE = flag


def active_backend() -> str:
    if FORCE_OFFLINE:
        return "offline"
    if backend_gemini.available():
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return "offline"


def model_id() -> str:
    backend = active_backend()
    if backend == "gemini":
        return backend_gemini.DEFAULT_MODEL
    if backend == "claude":
        return os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
    return "none"


def backend_status() -> dict:
    backend = active_backend()
    return {
        "llm_online": backend not in {"offline"},
        "backend": backend,
        "model": model_id(),
        "prompt_version": prompts.PROMPT_VERSION,
        "cache_entries": cache.count(),
        "offline_forced": FORCE_OFFLINE,
    }


def analyze_page(
    page: PageImage, ocr: OcrResult, mode: str = "auto", timeout_s: int = TIMEOUT_S
) -> PageAnalysis:
    key = cache.cache_key("page_analysis", page.sha1, prompts.PROMPT_VERSION, model_id())

    hit = cache.cache_get(key)
    if hit is not None:
        hit.page_no = page.page_no
        return hit

    if mode == "offline" or active_backend() == "offline":
        return heuristics.blocks_from_ocr(page, ocr)

    try:
        pa = _call_llm(page, ocr)
        cache.cache_put(key, pa)
        return pa
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 degraded 로 넘긴다
        pa = heuristics.blocks_from_ocr(page, ocr)
        pa.warnings.append(f"LLM 호출 실패: {type(exc).__name__}: {exc}")
        return pa


def _call_llm(page: PageImage, ocr: OcrResult) -> PageAnalysis:
    started = time.time()
    user_text = prompts.build_user_message(
        page_no=page.page_no,
        ocr_text=ocr.text,
        ocr_line_table=line_table(ocr),
        column_count=ocr.column_count,
        mean_conf=ocr.mean_conf,
        is_native=(ocr.engine == "native"),
    )

    raw = _generate(prompts.SYSTEM_PROMPT, user_text, page.image_path)
    _save_raw(page, raw)

    try:
        data = _parse(raw)
    except Exception as exc:  # noqa: BLE001 - 형식이 깨지면 1회만 교정 재요청
        repair = prompts.REPAIR_TEMPLATE.format(errors=str(exc), previous=raw[:4000])
        raw = _generate(prompts.SYSTEM_PROMPT, repair, None)
        _save_raw(page, raw, suffix="repair")
        data = _parse(raw)

    pa = _to_analysis(data, page)
    pa.elapsed_ms = int((time.time() - started) * 1000)
    return pa


def _generate(system: str, user_text: str, image_path: str | None) -> str:
    backend = active_backend()
    if backend == "gemini":
        return backend_gemini.generate(system, user_text, image_path)
    if backend == "claude":
        return _generate_claude(system, user_text, image_path)
    raise RuntimeError("사용 가능한 LLM 백엔드가 없다")


def _generate_claude(system: str, user_text: str, image_path: str | None) -> str:
    import base64

    import anthropic

    content: list[dict] = []
    if image_path:
        img = Path(image_path)
        if img.exists() and img.stat().st_size < 5_000_000:
            media = "image/png" if img.suffix.lower() == ".png" else "image/jpeg"
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media,
                        "data": base64.standard_b64encode(img.read_bytes()).decode(),
                    },
                }
            )
    content.append({"type": "text", "text": user_text})

    resp = anthropic.Anthropic(timeout=TIMEOUT_S).messages.create(
        model=model_id(),
        max_tokens=8000,
        system=system,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _parse(raw: str) -> dict:
    return backend_gemini.parse_json(raw)


def _save_raw(page: PageImage, raw: str, suffix: str = "") -> None:
    """원문 응답을 남긴다. 프롬프트를 고칠 때 무엇이 달라졌는지 보려면 필요하다."""
    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        name = f"p{page.page_no:03d}{('_' + suffix) if suffix else ''}.json"
        (RAW_DIR / name).write_text(raw, encoding="utf-8")
    except Exception:  # noqa: BLE001 - 디버그용이라 실패해도 무시
        pass


def _to_analysis(data: dict, page: PageImage) -> PageAnalysis:
    for i, b in enumerate(data.get("blocks", [])):
        b.setdefault("page_no", page.page_no)
        b.setdefault("order", i)
        b.setdefault("id", f"p{page.page_no}-b{i:02d}")
    for i, t in enumerate(data.get("terms", [])):
        t.setdefault("page_no", page.page_no)
        t.setdefault("order", i)
        t.setdefault("type", "term")
        t.setdefault("id", f"p{page.page_no}-t{i:02d}")

    return PageAnalysis(
        page_no=page.page_no,
        page_sha1=page.sha1,
        source="llm_vision",
        model_id=model_id(),
        prompt_version=prompts.PROMPT_VERSION,
        blocks=data.get("blocks", []),
        terms=data.get("terms", []),
        column_count=data.get("column_count", 1),
        page_kind=data.get("page_kind", "body"),
        warnings=data.get("warnings", []),
    )

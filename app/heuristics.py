"""LLM 없이 OCR 만으로 최소 결과를 만든다. [담당: A]

네트워크가 막히거나 LLM 이 계속 실패할 때 쓰는 경로.
도표 설명은 포기하고 본문만 살린다. 빈칸을 지어내지 않는 것이 이 모듈의 목적이다.
"""

from __future__ import annotations

from app.schema import Block, OcrResult, PageAnalysis, PageImage


def blocks_from_ocr(page: PageImage, ocr: OcrResult) -> PageAnalysis:
    blocks: list[Block] = []
    order = 0

    lines = ocr.lines or _fake_lines(ocr.text)
    heights = [line.bbox[3] - line.bbox[1] for line in lines] or [0.02]
    median_h = sorted(heights)[len(heights) // 2]

    for line in lines:
        y0 = line.bbox[1]
        height = line.bbox[3] - line.bbox[1]
        text = line.text.strip()
        if not text:
            continue

        if y0 < 0.07:
            btype = "running_head"
        elif y0 > 0.95 and len(text) <= 5:
            btype = "page_number"
        elif height > median_h * 1.35 and len(text) < 60:
            btype = "heading"
        else:
            btype = "paragraph"

        blocks.append(
            Block(
                id=f"p{page.page_no}-b{order:02d}",
                type=btype,
                page_no=page.page_no,
                order=order,
                bbox=line.bbox,
                text=text,
                text_source="ocr",
                level=3 if btype == "heading" else None,
                confidence=min(1.0, max(0.2, line.conf / 100)),
                flags=["llm_degraded"],
            )
        )
        order += 1

    return PageAnalysis(
        page_no=page.page_no,
        page_sha1=page.sha1,
        source="degraded",
        model_id="none",
        prompt_version="none",
        blocks=blocks,
        column_count=ocr.column_count,
        reading_order_source="geometric",
        warnings=["LLM 없이 OCR 만으로 생성. 도표·수식 설명이 없음"],
    )


def _fake_lines(text: str):
    """lines 가 없는 native 텍스트층용. 줄 단위로 가짜 좌표를 만든다."""
    from app.schema import OcrLine

    rows = [r for r in (text or "").splitlines() if r.strip()]
    out = []
    for i, row in enumerate(rows):
        y = min(0.98, 0.05 + i * 0.03)
        out.append(OcrLine(bbox=(0.1, y, 0.9, y + 0.02), text=row, conf=90.0))
    return out

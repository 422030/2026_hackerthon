"""Tesseract 래퍼. [담당: A]

OCR 결과는 완성품이 아니라 세 가지 용도로 쓴다.
  1. 본문 텍스트의 기준  2. LLM 그라운딩  3. 할루시네이션 대조
PaddleOCR 을 쓰지 않는 이유는 윈도우 설치 충돌 때문이다.
"""

from __future__ import annotations

import time

from app.schema import OcrLine, OcrResult, PageImage


def run_ocr(page: PageImage, langs: str = "kor+eng") -> OcrResult:
    """네이티브 텍스트층이 있으면 그것을 쓰고, 없으면 Tesseract 를 돌린다."""
    started = time.time()

    if page.native_text:
        return OcrResult(
            engine="native",
            text=page.native_text,
            lines=[],
            mean_conf=100.0,
            elapsed_ms=int((time.time() - started) * 1000),
        )

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return OcrResult(engine="none", text="", elapsed_ms=0)

    src = page.preprocessed_path or page.image_path
    try:
        with Image.open(src) as im:
            data = pytesseract.image_to_data(
                im, lang=langs, output_type=pytesseract.Output.DICT
            )
            width, height = im.size
    except Exception:
        return OcrResult(engine="none", text="", elapsed_ms=0)

    lines = _group_lines(data, width, height)
    text = "\n".join(line.text for line in lines)
    confs = [line.conf for line in lines if line.conf >= 0]

    return OcrResult(
        engine="tesseract",
        text=text,
        lines=lines,
        mean_conf=sum(confs) / len(confs) if confs else 0.0,
        column_count=_estimate_columns(lines),
        elapsed_ms=int((time.time() - started) * 1000),
    )


def _group_lines(data: dict, width: int, height: int) -> list[OcrLine]:
    """Tesseract 의 단어 단위 출력을 줄 단위로 묶는다."""
    buckets: dict[tuple, list[int]] = {}
    for i, word in enumerate(data.get("text", [])):
        if not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        buckets.setdefault(key, []).append(i)

    lines: list[OcrLine] = []
    for idxs in buckets.values():
        words = [data["text"][i] for i in idxs]
        x0 = min(data["left"][i] for i in idxs)
        y0 = min(data["top"][i] for i in idxs)
        x1 = max(data["left"][i] + data["width"][i] for i in idxs)
        y1 = max(data["top"][i] + data["height"][i] for i in idxs)
        confs = [float(data["conf"][i]) for i in idxs if float(data["conf"][i]) >= 0]
        lines.append(
            OcrLine(
                bbox=(x0 / width, y0 / height, x1 / width, y1 / height),
                text=" ".join(words),
                conf=sum(confs) / len(confs) if confs else 0.0,
            )
        )

    lines.sort(key=lambda line: (round(line.bbox[1], 3), line.bbox[0]))
    return lines


def _estimate_columns(lines: list[OcrLine]) -> int:
    """x 중심의 분포로 단 수를 추정한다. 정확할 필요는 없고 LLM 에 힌트로만 준다."""
    if len(lines) < 8:
        return 1
    centers = sorted((line.bbox[0] + line.bbox[2]) / 2 for line in lines)
    left = sum(1 for c in centers if c < 0.45)
    right = sum(1 for c in centers if c > 0.55)
    middle = len(centers) - left - right
    if left > 3 and right > 3 and middle < len(centers) * 0.25:
        return 2
    return 1


def line_table(ocr: OcrResult, limit: int = 120) -> str:
    """LLM 에 넘길 라인 좌표표. 토큰을 아끼려고 한 줄에 하나씩 쓴다."""
    rows = []
    for line in ocr.lines[:limit]:
        x0, y0, x1, _ = line.bbox
        rows.append(f"y0={y0:.3f} x={x0:.2f}-{x1:.2f} conf={line.conf:.0f} | {line.text}")
    return "\n".join(rows)

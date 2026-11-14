"""LLM 출력 검증. [담당: B]

세 가지를 본다.
  1. LLM 이 본문을 요약하거나 늘렸는가
  2. 도표 설명에 원본에 없는 숫자가 들어갔는가
  3. OCR 신뢰도가 낮은 영역인가
판정하지 않고 표시만 한다. 틀렸다고 블록을 버리지 않는다.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from app.schema import OcrResult, PageAnalysis

BODY_TYPES = {"heading", "paragraph", "list", "caption"}
# 숫자가 앞서는 하이픈은 범위·복합 번호의 구분자다(`#300-366`, `그림 3-2`).
# 음수 부호로 보는 하이픈은 앞에 숫자가 없을 때로 한정한다.
NUMBER_RE = re.compile(r"(?<![\d.,])-?\d+(?:[.,]\d+)?")
MIN_OCR_CHARS = 50
SHRINK_LIMIT = 0.70
EXPAND_LIMIT = 1.40
BLOCK_MATCH_LIMIT = 0.60

# 누락 의심 구간 기준. 짧은 줄은 쪽번호·머리글과 겹쳐 오탐이 잦으므로 세지 않는다.
MISSING_LINE_MIN = 8
MISSING_MIN_CHARS = 40
MISSING_RATIO_LIMIT = 0.15
MISSING_COVER_LIMIT = 0.50


def norm(s: str) -> str:
    """비교용 정규화. 공백과 구두점을 날리고 각주 표기를 제거한다."""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"\[\^[^\]]*\]", "", s)
    return re.sub(r"[^0-9a-z가-힣]", "", s)


def extract_numbers(s: str) -> set[str]:
    out = set()
    for m in NUMBER_RE.finditer(s or ""):
        out.add(m.group().replace(",", "").lstrip("0") or "0")
    return out


def _tolerated(n: str, evidence: set[str]) -> bool:
    """7.2 와 7.23 처럼 반올림 차이는 같은 값으로 본다."""
    try:
        v = float(n)
    except ValueError:
        return False
    for e in evidence:
        try:
            ev = float(e)
        except ValueError:
            continue
        if abs(v - ev) <= max(0.05, 0.01 * abs(ev)):
            return True
    return False


def cross_check(pa: PageAnalysis, ocr: OcrResult) -> PageAnalysis:
    ocr_body = norm(ocr.text)
    if len(ocr_body) < MIN_OCR_CHARS:
        pa.warnings.append("ocr_too_short_to_verify")
        return pa

    body_blocks = [b for b in pa.blocks if b.type in BODY_TYPES]
    llm_body = norm("".join(b.text for b in body_blocks))
    if not llm_body:
        return pa

    # 길이 비교에는 본문뿐 아니라 머리글·쪽번호·각주처럼 AI 가 다른 타입으로
    # 분류한 텍스트도 포함한다. OCR 텍스트에는 그것들이 다 섞여 있으므로,
    # 본문만 세면 정상 분류를 요약으로 오인한다.
    llm_all = norm("".join(b.text for b in pa.blocks))
    len_ratio = len(llm_all) / len(ocr_body)
    shrink_limit = 0.85 if ocr.engine == "native" else SHRINK_LIMIT

    if len_ratio < shrink_limit:
        pa.warnings.append(f"body_shrunk len_ratio={len_ratio:.2f}")
        for b in body_blocks:
            if "suspected_summary" not in b.flags:
                b.flags.append("suspected_summary")
            b.confidence = round(b.confidence * 0.6, 3)
    elif len_ratio > EXPAND_LIMIT:
        pa.warnings.append(f"body_expanded len_ratio={len_ratio:.2f}")
        for b in body_blocks:
            b.confidence = round(b.confidence * 0.7, 3)

    ratio = SequenceMatcher(None, ocr_body, llm_body).ratio()
    if ratio < 0.85:
        _mark_mismatched_blocks(body_blocks, ocr_body)
        if ratio < 0.65:
            pa.warnings.append(f"body_mismatch ratio={ratio:.2f}")

    _check_numbers(pa, ocr)
    _check_ocr_conf(pa, ocr)
    _check_missing(pa, ocr)

    if pa.source == "degraded":
        for b in pa.blocks:
            if b.type in {"figure", "formula"} and "llm_degraded" not in b.flags:
                b.flags.append("llm_degraded")
    return pa


def _mark_mismatched_blocks(body_blocks, ocr_body: str) -> None:
    """전수 탐색은 느리다. 블록 앞부분으로 후보 위치를 잡고 그 주변만 비교한다."""
    for b in body_blocks:
        nb = norm(b.text)
        if len(nb) < 10:
            continue
        head = nb[:12]
        start = ocr_body.find(head)
        if start < 0:
            best = 0.0
        else:
            window = ocr_body[start : start + int(len(nb) * 1.25)]
            best = SequenceMatcher(None, window, nb).ratio()
        if best < BLOCK_MATCH_LIMIT:
            if "ocr_mismatch" not in b.flags:
                b.flags.append("ocr_mismatch")
            b.confidence = min(b.confidence, 0.4)


def _evidence_reaches_figure(grounded: set[str], caption: set[str]) -> bool:
    """근거 텍스트가 그림 내부의 글자까지 담고 있는지 추정한다.

    캡션에 적힌 수치는 그림 밖에서 읽히므로 내부가 읽혔다는 증거가 아니다.
    한 자리 수는 쪽번호·절 번호와 우연히 겹치므로 접촉으로 세지 않는다.
    """
    return any(len(n.lstrip("-")) >= 2 for n in grounded - caption)


def _check_numbers(pa: PageAnalysis, ocr: OcrResult) -> None:
    evidence = extract_numbers(ocr.text)
    for b in pa.blocks:
        if b.type != "figure":
            continue
        claimed = extract_numbers((b.alt_long or "") + " " + (b.alt_short or ""))
        for dp in b.data_points:
            claimed |= extract_numbers(str(dp.get("value", "")))
        unverified = sorted(
            n for n in claimed if n not in evidence and not _tolerated(n, evidence)
        )
        if not unverified:
            continue

        # 반올림 허용으로 넘어간 값은 접촉의 증거가 아니다. 가까운 다른 수치와
        # 겹쳤을 뿐 그 수치가 읽혔다는 뜻이 아니다.
        grounded = claimed & evidence

        # 대조할 근거가 닿지 않은 그림과, 근거가 닿았는데도 어긋난 수치는 다른
        # 상태다. 둘 다 경고하되 구분해서 표시한다.
        if _evidence_reaches_figure(grounded, extract_numbers(b.text)):
            if "unverified_number" not in b.flags:
                b.flags.append("unverified_number")
            b.confidence = min(b.confidence, 0.5)
            b.note = f"근거 없는 수치: {unverified[:5]}"
        else:
            if "unverifiable_number" not in b.flags:
                b.flags.append("unverifiable_number")
            b.confidence = min(b.confidence, 0.8)
            b.note = f"대조 근거가 없는 수치: {unverified[:5]}"


def _haystack(pa: PageAnalysis) -> str:
    """LLM 이 내놓은 모든 글자. 표는 셀에, 그림은 설명에 들어 있다."""
    parts: list[str] = []
    for b in pa.blocks:
        parts += [b.text, b.alt_short or "", b.alt_long or "", b.speech or ""]
        parts += b.list_items
        for row in b.table_grid or []:
            parts += [c.text for c in row]
    for t in pa.terms:
        parts += [t.surface or "", t.gloss or ""]
    return norm("".join(parts))


def _covered(nl: str, hay: str) -> float:
    """한 줄이 결과 안에 얼마나 들어 있는지. 0.0~1.0.

    줄 전체를 통째로 찾지 않는다. 수식 기호는 원문 글리프와 결과 표기가
    달라서, 본문이 멀쩡히 있어도 줄 단위 대조는 실패한다.
    """
    if nl in hay:
        return 1.0
    w = MISSING_LINE_MIN
    windows = [nl[k : k + w] for k in range(len(nl) - w + 1)]
    if not windows:
        return 0.0
    return sum(1 for x in windows if x in hay) / len(windows)


def _check_missing(pa: PageAnalysis, ocr: OcrResult) -> None:
    """OCR 에는 있는데 어느 블록에도 담기지 않은 구간을 찾는다.

    bbox 로 덮개를 계산하지 않는다. LLM 이 bbox 를 비워 보내는 경우가 많아
    기하학적 판정이 성립하지 않는다. 정규화한 글자가 들어 있는지로 본다.
    """
    # 네이티브 텍스트층 경로는 lines 를 채우지 않는다. 줄바꿈으로 나눠 쓴다.
    raw_lines = [ln.text for ln in ocr.lines] or (ocr.text or "").splitlines()
    if not raw_lines:
        return

    hay = _haystack(pa)
    if not hay:
        return

    missing: list[str] = []
    missing_chars = 0
    total_chars = 0

    for raw in raw_lines:
        nl = norm(raw)
        total_chars += len(nl)
        if len(nl) < MISSING_LINE_MIN or _covered(nl, hay) >= MISSING_COVER_LIMIT:
            continue
        missing_chars += len(nl)
        if len(missing) < 3:
            missing.append(raw.strip()[:40])

    if not total_chars or missing_chars < MISSING_MIN_CHARS:
        return
    if missing_chars / total_chars < MISSING_RATIO_LIMIT:
        return

    sample = " / ".join(missing)
    pa.warnings.append(
        f"missing_text chars={missing_chars} ratio="
        f"{missing_chars / total_chars:.2f} sample={sample}"
    )


def _check_ocr_conf(pa: PageAnalysis, ocr: OcrResult) -> None:
    if not ocr.lines:
        return
    for b in pa.blocks:
        if not b.bbox:
            continue
        overlap = [line for line in ocr.lines if _iou(line.bbox, b.bbox) > 0.3]
        if overlap:
            mean = sum(line.conf for line in overlap) / len(overlap)
            if mean < 60 and "low_ocr_conf" not in b.flags:
                b.flags.append("low_ocr_conf")


def _iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union else 0.0

"""TTS 세그먼트 생성기. [담당: C]

HTML 을 그대로 읽히지 않고 문장 단위 배열을 따로 만든다.
Web Speech API 는 조각을 하나씩 넣어야 중단·재개·이동이 된다.
"""

from __future__ import annotations

import re

from app.schema import AccessDoc, RenderOptions, SpeechSegment

LEXICON = {
    "≤": "작거나 같다",
    "≥": "크거나 같다",
    "±": "플러스 마이너스",
    "×": "곱하기",
    "÷": "나누기",
    "%": "퍼센트",
    "Σ": "시그마",
    "α": "알파",
    "β": "베타",
    "θ": "세타",
    "μ": "뮤",
    "σ": "시그마",
    "Ω": "오메가",
    "→": "에서",
    "cf.": "참고",
    "etc.": "등",
    "e.g.": "예를 들어",
}

FOOTNOTE_RE = re.compile(r"\[\^(\d+)\]")


def speak_text(s: str) -> str:
    out = FOOTNOTE_RE.sub("", s or "")
    for k, v in LEXICON.items():
        out = out.replace(k, f" {v} ")
    return re.sub(r"\s+", " ", out).strip()


def to_speech_text(
    doc: AccessDoc, opts: RenderOptions | None = None
) -> list[SpeechSegment]:
    opts = opts or RenderOptions()
    fn_by_num = {f.global_number: f for f in doc.footnotes if f.global_number}
    segs: list[SpeechSegment] = []

    def add(block_id: str, kind: str, text: str, pause: int = 0, lang: str = "ko-KR"):
        text = speak_text(text)
        if text:
            segs.append(
                SpeechSegment(
                    index=len(segs),
                    block_id=block_id,
                    kind=kind,
                    text=text,
                    lang=lang,
                    pause_ms_after=pause,
                )
            )

    add("doc", "nav", doc.title, 400)
    s = doc.stats
    add(
        "doc",
        "nav",
        f"총 {s.pages}쪽. 그림 {s.figures}개, 표 {s.tables}개, 수식 {s.formulas}개.",
        400,
    )

    # PDF 실제 쪽 번호를 각 페이지의 첫 읽기 블록 앞에 한 번 안내한다.
    # page_break 블록 자체는 읽지 않아 중복 안내를 피한다.
    last_page_no = None
    for b in doc.blocks:
        if b.type == "page_break":
            continue
        if b.page_no != last_page_no:
            add(b.id, "page", f"{b.page_no}페이지입니다.", 200)
            last_page_no = b.page_no
        if b.type == "heading":
            add(b.id, "heading", f"제목 레벨 {b.level}. {b.text}", 400)
        elif b.type in {"paragraph", "caption", "marginalia", "unknown"}:
            add(b.id, "body", b.text, 150)
        elif b.type == "list":
            for i, item in enumerate(b.list_items, start=1):
                add(b.id, "body", f"{i}. {item}", 100)
        elif b.type == "formula":
            add(b.id, "formula", f"수식. {b.speech}", 300)
        elif b.type == "figure":
            add(b.id, "figure", f"그림. {b.alt_short}", 200)
            if b.alt_long:
                add(b.id, "figure", f"AI 설명 시작. {b.alt_long} AI 설명 끝.", 300)
            if "unverified_number" in b.flags:
                add(b.id, "figure", "주의. 원문에서 확인되지 않는 수치가 있습니다.", 300)
            elif "unverifiable_number" in b.flags:
                add(
                    b.id,
                    "figure",
                    "주의. 그림 안의 글자가 원문 텍스트에 없어 수치를 대조하지 못했습니다.",
                    300,
                )
        elif b.type == "table":
            add(b.id, "table", f"표. {b.alt_short or b.text or '표의 내용을 설명합니다.'}", 200)
            if b.alt_long:
                add(b.id, "table", b.alt_long, 300)
            else:
                add(b.id, "table", "표의 핵심 내용을 분석하지 못했습니다.", 300)

    return segs

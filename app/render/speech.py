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
    "➔": "따라서",
    "ω": "오메가",
    "−": "빼기",
    "–": ",",
    "cf.": "참고",
    "etc.": "등",
    "e.g.": "예를 들어",
}

FOOTNOTE_RE = re.compile(r"\[\^(\d+)\]")

# Read common inline math notation aloud without changing the displayed textbook.
# Keep transformations conservative: complex expressions remain for the AI reader.
LETTER_NAMES = {
    "a": "에이", "b": "비", "c": "씨", "d": "디", "e": "이",
    "f": "에프", "g": "지", "h": "에이치", "i": "아이", "j": "제이",
    "k": "케이", "l": "엘", "m": "엠", "n": "엔", "o": "오",
    "p": "피", "q": "큐", "r": "알", "s": "에스", "t": "티",
    "u": "유", "v": "브이", "w": "더블유", "x": "엑스",
    "y": "와이", "z": "제트",
}
SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹ⁿᵏ", "0123456789nk")
SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
MATH_BASE = r"[A-Za-z]"
MATH_EXP = r"(?:\{[A-Za-z0-9]+\}|[A-Za-z0-9]+)"
POWER_RE = re.compile(rf"(?<![A-Za-z])({MATH_BASE})\s*\^\s*({MATH_EXP})")
UNICODE_POWER_RE = re.compile(r"(?<![A-Za-z])([A-Za-z0-9])([⁰¹²³⁴⁵⁶⁷⁸⁹ⁿᵏ]+)")
SUB_RE = re.compile(r"(?<![A-Za-z])([A-Za-z])_({[A-Za-z0-9]+}|[A-Za-z0-9]+)")
UNICODE_SUB_RE = re.compile(r"(?<![A-Za-z])([A-Za-z])([₀₁₂₃₄₅₆₇₈₉]+)")
FRAC_RE = re.compile(r"\\frac\s*\{([A-Za-z0-9]+)\}\s*\{([A-Za-z0-9]+)\}")
SQRT_RE = re.compile(r"(?:\\sqrt\s*\{([A-Za-z0-9]+)\}|√\s*([A-Za-z0-9]+))")


def _math_atom(value: str) -> str:
    value = value.strip("{}")
    if value.isdigit():
        return value
    return " ".join(LETTER_NAMES.get(ch.lower(), ch) for ch in value)


def _power(base: str, exponent: str) -> str:
    exp = exponent.strip("{}")
    suffix = "제곱" if exp == "2" else "세제곱" if exp == "3" else f"{_math_atom(exp)}승"
    return f" {_math_atom(base)}의 {suffix} "


ASYMPTOTIC_RE = re.compile(
    r"(?<![A-Za-z])(?P<kind>O|Ο|Ω|Θ|\\Omega|\\Theta|\\mathcal\{O\})\s*"
    r"\(\s*(?P<expr>[0-9A-Za-z^{}()_⁰¹²³⁴⁵⁶⁷⁸⁹ⁿᵏ\s]+)\s*\)"
)
INLINE_MONOMIAL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<coefficient>[0-9]+)\s*(?P<variable>[nNxX])"
    r"(?=(?:은|는|이|가|을|를|과|와|보다|에|도|만|의|[ ,.;:)]|$))"
)
MATH_N_PARTICLE_RE = re.compile(r"(?<![A-Za-z])([nNxX])(?=\s?(?:은|는|이|가|을|를|과|와|보다|에|도|만|의))")


def _read_asymptotic(match: re.Match[str]) -> str:
    names = {
        "O": "빅오", "Ο": "빅오", "Ω": "빅오메가", "Θ": "빅세타",
        r"\Omega": "빅오메가", r"\Theta": "빅세타",
        r"\mathcal{O}": "빅오",
    }
    inner = normalize_math_speech(match.group("expr"))
    inner = re.sub(r"(?<![A-Za-z])([A-Za-z])(?![A-Za-z])", lambda m: _math_atom(m[1]), inner)
    inner = INLINE_MONOMIAL_RE.sub(
        lambda m: f"{m['coefficient']} {_math_atom(m['variable'])}", inner
    )
    return f" {names[match.group('kind')]} {inner.strip()} "


FUNC_RE = re.compile(r"(?<![A-Za-z])([A-Za-z])\s*\(\s*([A-Za-z](?:\s*_\s*[0-9]+)?)\s*\)")


def _read_func(match: re.Match[str]) -> str:
    """f(n) 은 '에프 엔'. 한 글자 함수에 한 글자 변수일 때만 바꾼다."""
    arg = match[2].replace(" ", "")
    if "_" in arg:
        base, idx = arg.split("_", 1)
        return f" {_math_atom(match[1])} {_math_atom(base)} 아래첨자 {idx} "
    return f" {_math_atom(match[1])} {_math_atom(arg)} "


def normalize_math_speech(text: str) -> str:
    """Convert unambiguous simple math notation to Korean speech."""
    text = ASYMPTOTIC_RE.sub(_read_asymptotic, text)
    text = FUNC_RE.sub(_read_func, text)
    text = text.replace(r"\in", " ∈ ").replace("∈", " 에 속한다 ")
    text = text.replace("→", " 따라서 ")
    text = INLINE_MONOMIAL_RE.sub(
        lambda m: f" {m['coefficient']} {_math_atom(m['variable'])} ", text
    )
    text = MATH_N_PARTICLE_RE.sub(lambda m: f"{_math_atom(m[1])}", text)
    text = FRAC_RE.sub(lambda m: f" {_math_atom(m[2])}분의 {_math_atom(m[1])} ", text)
    text = SQRT_RE.sub(lambda m: f" 루트 {_math_atom(m[1] or m[2])} ", text)
    text = POWER_RE.sub(lambda m: _power(m[1], m[2]), text)
    text = UNICODE_POWER_RE.sub(lambda m: _power(m[1], m[2].translate(SUPERSCRIPT)), text)
    text = SUB_RE.sub(lambda m: f" {_math_atom(m[1])} 아래첨자 {_math_atom(m[2])} ", text)
    text = UNICODE_SUB_RE.sub(
        lambda m: f" {_math_atom(m[1])} 아래첨자 {_math_atom(m[2].translate(SUBSCRIPT))} ", text
    )
    return text




def speak_text(s: str) -> str:
    out = normalize_math_speech(FOOTNOTE_RE.sub("", s or ""))
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

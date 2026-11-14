"""전 모듈 공통 데이터 계약.

이 파일을 고치면 팀 채널에 알리고 fixtures/*.json 을 같이 고친다.
필드 추가는 자유, 삭제와 의미 변경은 3명 합의 후에만.

bbox 는 페이지 기준 정규화 좌표 (0.0~1.0), 원점 좌상단, (x0, y0, x1, y1).

LLM 은 한 페이지 안에서 알 수 있는 것만 채운다.
페이지를 넘나드는 연결(문단 병합, 각주 전역 번호)은 assemble.py 가 채운다.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0.0"

BBox = tuple[float, float, float, float]

BlockType = Literal[
    "heading",
    "paragraph",
    "list",
    "figure",
    "table",
    "formula",
    "footnote",
    "caption",
    "term",
    "running_head",
    "page_number",
    "marginalia",
    "page_break",
    "unknown",
]

TextSource = Literal["native", "ocr", "llm", "mixed", "none"]

AnalysisSource = Literal["llm_vision", "llm_text", "cache", "snapshot", "degraded"]

BlockFlag = Literal[
    "ocr_mismatch",
    "low_ocr_conf",
    "llm_degraded",
    "unverified_number",
    "unverifiable_number",
    "truncated",
    "unanchored_footnote",
    "suspected_summary",
    "merged_across_page",
    "moved_after_merge",
]


class PageImage(BaseModel):
    """ingest.load_pages() 산출물. 한 페이지 = 한 PNG."""

    model_config = ConfigDict(extra="forbid")

    page_no: int = Field(..., ge=1)
    label: str | None = Field(None, description="원본에 인쇄된 쪽번호 문자열")
    image_path: str
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    dpi: int = 300
    sha1: str = Field(..., description="PNG 바이트 SHA1. 캐시 키 재료")
    native_text: str | None = Field(None, description="born-digital PDF 의 텍스트층")
    is_scanned: bool = True
    preprocessed_path: str | None = Field(
        None, description="보정 PNG. OCR 에만 쓰고 LLM 에는 원본을 보낸다"
    )


class OcrLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bbox: BBox
    text: str
    conf: float = Field(..., ge=0, le=100)
    column: int | None = None


class OcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["tesseract", "native", "none"]
    text: str = Field("", description="읽기 순서로 이어붙인 전체 텍스트")
    lines: list[OcrLine] = Field(default_factory=list)
    mean_conf: float = Field(0.0, ge=0, le=100)
    column_count: int = Field(1, ge=1, le=3)
    elapsed_ms: int = 0

    @property
    def char_count(self) -> int:
        return len(self.text.replace(" ", ""))


class TableCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    is_header: bool = False
    header_axis: Literal["col", "row", "both", "none"] = "none"
    row_span: int = Field(1, ge=1)
    col_span: int = Field(1, ge=1)
    footnote_markers: list[str] = Field(default_factory=list)


class Block(BaseModel):
    """페이지 안의 의미 단위 하나.

    2단 조판은 column 과 order 로, 페이지 걸친 문단은
    starts_mid_sentence / ends_mid_sentence 로, 표 안 각주는
    footnote_scope 와 container_block_id 로 표현한다.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="'p{page_no}-b{nn}' 형식")
    type: BlockType
    page_no: int = Field(..., ge=1)
    order: int = Field(0, ge=0, description="페이지 내 읽기 순서(0-base)")
    bbox: BBox | None = None
    column: int | None = None

    text: str = Field("", description="인라인 각주 표기는 '[^1]' 형태로 남긴다")
    text_source: TextSource = "llm"
    level: int | None = Field(None, ge=1, le=6)
    list_ordered: bool | None = None
    list_items: list[str] = Field(default_factory=list)

    starts_mid_sentence: bool = False
    ends_mid_sentence: bool = False
    continues_from: str | None = None
    continues_to: str | None = None

    alt_short: str | None = Field(None, max_length=160)
    alt_long: str | None = Field(None, max_length=600)
    figure_kind: (
        Literal[
            "bar", "line", "scatter", "pie", "flow", "schematic",
            "photo", "map", "screenshot", "other", "unreadable",
        ]
        | None
    ) = None
    crop_path: str | None = None
    table_grid: list[list[TableCell]] | None = None
    data_points: list[dict] = Field(
        default_factory=list, description="도표에서 확실히 읽히는 값만. 추정값 금지"
    )

    latex: str | None = None
    speech: str | None = Field(None, max_length=600, description="한국어 구어 읽기문")
    formula_label: str | None = None

    marker: str | None = Field(None, description="원본 각주 표기 그대로")
    global_number: int | None = Field(None, description="assemble 이 채운다")
    footnote_scope: Literal["page", "table", "figure"] = "page"
    container_block_id: str | None = None
    ref_block_ids: list[str] = Field(default_factory=list)
    ref_char_offset: int | None = None

    surface: str | None = None
    reading: str | None = None
    gloss: str | None = Field(None, max_length=300)
    lang: str | None = None

    confidence: float = Field(1.0, ge=0.0, le=1.0)
    flags: list[BlockFlag] = Field(default_factory=list)
    note: str | None = Field(None, description="디버그 메모. 출력에는 쓰지 않는다")

    @field_validator("alt_short")
    @classmethod
    def _no_banned_prefix(cls, v: str | None) -> str | None:
        if v is None:
            return v
        banned = ("이미지", "그림 파일", "사진입니다", "image of", "picture of")
        s = v.strip()
        for b in banned:
            if s.startswith(b):
                raise ValueError(f"alt_short 는 '{b}' 로 시작할 수 없다: {s[:30]}")
        return s

    @model_validator(mode="after")
    def _type_requirements(self) -> "Block":
        if self.type == "heading" and self.level is None:
            self.level = 3
        if self.type == "figure" and not self.alt_short:
            self.alt_short = "설명을 생성하지 못한 그림"
            self.figure_kind = self.figure_kind or "unreadable"
            if "llm_degraded" not in self.flags:
                self.flags.append("llm_degraded")
        if self.type == "formula" and not self.speech:
            self.speech = self.latex or self.text or "읽을 수 없는 수식"
        if self.type == "footnote" and self.footnote_scope != "page":
            if not self.container_block_id:
                raise ValueError("표/그림 각주는 container_block_id 가 필요하다")
        if self.type == "term" and not self.surface:
            raise ValueError("term 블록은 surface 가 필요하다")
        return self


class PageAnalysis(BaseModel):
    """LLM 호출 1회의 결과. 캐시 단위이기도 하다."""

    model_config = ConfigDict(extra="forbid")

    page_no: int = Field(..., ge=1)
    page_sha1: str = ""
    source: AnalysisSource
    model_id: str = ""
    prompt_version: str = ""
    schema_version: str = SCHEMA_VERSION

    blocks: list[Block] = Field(default_factory=list)
    terms: list[Block] = Field(default_factory=list)

    column_count: int = Field(1, ge=1, le=3)
    reading_order_source: Literal["llm", "geometric", "fallback"] = "llm"
    page_kind: Literal["body", "toc", "index", "cover", "blank", "exercise"] = "body"

    @field_validator("page_kind", mode="before")
    @classmethod
    def _normalize_page_kind(cls, value: str) -> str:
        # Gemini may label a title/cover page as "title"; normalize to the schema value.
        if isinstance(value, str) and value.strip().lower() == "title":
            return "cover"
        return value

    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0
    raw_response_path: str | None = None

    @model_validator(mode="after")
    def _unique_ids(self) -> "PageAnalysis":
        ids = [b.id for b in self.blocks] + [b.id for b in self.terms]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"블록 id 중복: {dup}")
        self.blocks.sort(key=lambda b: b.order)
        for i, b in enumerate(self.blocks):
            b.order = i
        return self


class DocStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pages: int = 0
    headings: int = 0
    paragraphs: int = 0
    figures: int = 0
    figures_described: int = 0
    tables: int = 0
    formulas: int = 0
    footnotes: int = 0
    table_footnotes: int = 0
    terms: int = 0
    flagged_blocks: int = 0
    total_elapsed_ms: int = 0


class AccessDoc(BaseModel):
    """렌더러 입력. 전역 연결이 모두 끝난 상태."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    schema_version: str = SCHEMA_VERSION
    title: str = ""
    source_filename: str = ""
    page_range: tuple[int, int] = (1, 1)

    blocks: list[Block] = Field(default_factory=list)
    footnotes: list[Block] = Field(default_factory=list)
    table_footnotes: list[Block] = Field(default_factory=list)
    glossary: list[Block] = Field(default_factory=list)

    stats: DocStats = Field(default_factory=DocStats)
    degraded_pages: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )


class RenderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    footnote_mode: Literal["end", "inline"] = "end"
    include_latex: bool = True
    include_confidence: bool = False
    heading_base: int = Field(2, ge=1, le=3)
    include_page_breaks: bool = True
    include_glossary: bool = True


class SpeechSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    block_id: str
    kind: Literal[
        "nav", "body", "heading", "figure", "table", "formula", "footnote", "page"
    ]
    text: str
    lang: str = "ko-KR"
    pause_ms_after: int = 0


class JobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Literal["queued", "running", "done", "error", "cancelled"] = "queued"
    stage: Literal["ingest", "ocr", "analyze", "assemble", "render", "idle"] = "idle"
    pages_total: int = 0
    pages_done: int = 0
    current_page: int | None = None
    degraded_pages: list[int] = Field(default_factory=list)
    llm_online: bool = True
    error: str | None = None


def content_hash(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p.encode("utf-8"))
    return h.hexdigest()

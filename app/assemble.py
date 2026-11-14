"""페이지별 결과를 문서 하나로 합친다. [담당: C]

AI 호출이 없다. 전부 규칙이다.
단계 순서를 바꾸면 깨진다: 평탄화 -> 분리 -> 문단 병합 -> heading 정규화 -> 각주 번호.
병합이 블록 id 를 없애므로 각주 앵커가 먼저 돌면 안 되고,
heading 정규화 전에는 문서 제목을 정할 수 없다.
"""

from __future__ import annotations

import re
from collections import Counter

from app.schema import AccessDoc, Block, DocStats, PageAnalysis, RenderOptions

DROP_TYPES = {"running_head", "page_number"}
BODY_MERGE_LIMIT = 3000

# 끊긴 문장 사이에 끼어들 수 있다고 보는 블록과 그 개수 상한.
SKIPPABLE_BETWEEN = {"figure", "table", "formula", "caption"}
MAX_SKIP_FOR_MERGE = 3


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def assemble(
    pages: list[PageAnalysis], meta: dict, opts: RenderOptions | None = None
) -> AccessDoc:
    opts = opts or RenderOptions()
    pages = sorted(pages, key=lambda p: p.page_no)

    doc = AccessDoc(
        job_id=meta.get("job_id", ""),
        source_filename=meta.get("source_filename", ""),
        page_range=(pages[0].page_no, pages[-1].page_no) if pages else (1, 1),
    )

    flat: list[Block] = []
    for pa in pages:
        for b in pa.blocks:
            if b.type in DROP_TYPES:
                continue
            if b.type == "unknown" and not _norm(b.text):
                continue
            flat.append(b)
        if pa.source in {"degraded", "snapshot"}:
            doc.degraded_pages.append(pa.page_no)
        doc.warnings.extend(pa.warnings)

    _drop_repeated_headings(flat)

    page_fns = [b for b in flat if b.type == "footnote" and b.footnote_scope == "page"]
    cont_fns = [b for b in flat if b.type == "footnote" and b.footnote_scope != "page"]
    body = [b for b in flat if b.type != "footnote"]

    _merge_across_pages(body, page_fns)
    _normalize_headings(body, opts.heading_base, doc, meta)
    _renumber_footnotes(body, page_fns)
    _letter_footnotes(cont_fns)

    doc.blocks = _insert_page_breaks(body) if opts.include_page_breaks else body
    doc.footnotes = page_fns
    doc.table_footnotes = cont_fns
    doc.glossary = []  # No generated glossary, including legacy cached analyses.
    doc.stats = _stats(doc, pages)
    return doc


def _drop_repeated_headings(flat: list[Block]) -> None:
    """같은 텍스트가 3쪽 이상 최상단에 반복되면 머리글로 보고 버린다."""
    counts = Counter(_norm(b.text) for b in flat if b.type == "heading")
    doomed = []
    for b in flat:
        if b.type != "heading":
            continue
        top = b.order == 0 or (b.bbox and b.bbox[1] < 0.12)
        if counts[_norm(b.text)] >= 3 and top:
            doomed.append(b)
    for b in doomed:
        flat.remove(b)


def _find_continuation(body: list[Block], i: int) -> int | None:
    """끊긴 문단의 뒷부분 위치를 찾는다.

    쪽 경계에 그림·표가 끼어 있어도 본문을 먼저 잇는다. 끼어든 블록은
    제자리에 두므로 이어붙인 문단 뒤로 밀린다.
    heading 과 list 는 넘지 않는다. 절이 바뀌면 같은 문장이 아니다.
    """
    cur = body[i]
    skipped = 0
    last = min(i + 2 + MAX_SKIP_FOR_MERGE, len(body))

    for j in range(i + 1, last):
        b = body[j]
        if b.page_no not in (cur.page_no, cur.page_no + 1):
            return None
        if b.type == "paragraph":
            if b.page_no == cur.page_no + 1 and b.starts_mid_sentence:
                return j
            return None
        if b.type not in SKIPPABLE_BETWEEN:
            return None
        skipped += 1
        if skipped > MAX_SKIP_FOR_MERGE:
            return None
    return None


def _merge_across_pages(body: list[Block], footnotes: list[Block]) -> None:
    i = 0
    while i < len(body) - 1:
        cur = body[i]
        if (
            cur.type != "paragraph"
            or not cur.ends_mid_sentence
            or len(cur.text) >= BODY_MERGE_LIMIT
        ):
            i += 1
            continue

        j = _find_continuation(body, i)
        if j is None:
            i += 1
            continue

        nxt = body[j]
        for b in body[i + 1 : j]:
            if "moved_after_merge" not in b.flags:
                b.flags.append("moved_after_merge")

        before = len(cur.text)
        left, right = cur.text.rstrip(), nxt.text.lstrip()
        if left.endswith("-") and right[:1].isascii():
            merged = left[:-1] + right
        elif left and right and ord(left[-1]) > 0x3000 and ord(right[0]) > 0x3000:
            merged = left + right
        else:
            merged = left + " " + right

        cur.text = merged
        cur.ends_mid_sentence = nxt.ends_mid_sentence
        cur.continues_to = nxt.id
        nxt.continues_from = cur.id
        if "merged_across_page" not in cur.flags:
            cur.flags.append("merged_across_page")

        shift = before
        for fn in footnotes:
            if nxt.id in fn.ref_block_ids:
                fn.ref_block_ids = [cur.id if r == nxt.id else r for r in fn.ref_block_ids]
                if fn.ref_char_offset is not None:
                    fn.ref_char_offset += shift
        del body[j]


def _normalize_headings(
    body: list[Block], base: int, doc: AccessDoc, meta: dict
) -> None:
    heads = [b for b in body if b.type == "heading"]
    if not heads:
        doc.title = meta.get("source_filename", "제목 없음")
        return

    for h in heads:
        m = re.match(r"^\s*(\d+(?:\.\d+)*)\s", h.text)
        if m:
            h.level = min(6, m.group(1).count(".") + 1)
        elif re.match(r"^\s*제?\s*\d+\s*[장편부]", h.text):
            h.level = 1

    min_lv = min(h.level or base for h in heads)
    shift = base - min_lv
    for h in heads:
        h.level = max(1, min(6, (h.level or base) + shift))

    prev = base - 1
    for h in heads:
        if h.level > prev + 1:
            h.level = prev + 1
        if h.level < base:
            h.level = base
        prev = h.level

    doc.title = heads[0].text if heads[0].level == base else meta.get("source_filename", "")


def _renumber_footnotes(body: list[Block], footnotes: list[Block]) -> None:
    index = {b.id: i for i, b in enumerate(body)}

    def sort_key(fn: Block):
        if fn.ref_block_ids and fn.ref_block_ids[0] in index:
            return (0, index[fn.ref_block_ids[0]], fn.ref_char_offset or 0)
        return (1, fn.page_no * 10000, fn.marker or "")

    footnotes.sort(key=sort_key)

    for n, fn in enumerate(footnotes, start=1):
        fn.global_number = n
        if not fn.ref_block_ids or fn.ref_block_ids[0] not in index:
            if "unanchored_footnote" not in fn.flags:
                fn.flags.append("unanchored_footnote")
            tail = [b for b in body if b.page_no == fn.page_no]
            if tail:
                fn.ref_block_ids = [tail[-1].id]
                fn.ref_char_offset = len(tail[-1].text)

        for bid in fn.ref_block_ids:
            b = body[index[bid]] if bid in index else None
            if b is None:
                continue
            placeholder = f"[^{fn.marker}]"
            if placeholder in b.text:
                b.text = b.text.replace(placeholder, f"[^{n}]", 1)
            elif fn.ref_char_offset is not None and fn.ref_char_offset <= len(b.text):
                pos = fn.ref_char_offset
                b.text = b.text[:pos] + f"[^{n}]" + b.text[pos:]
            else:
                b.text = b.text.rstrip() + f"[^{n}]"


def _letter_footnotes(cont: list[Block]) -> None:
    groups: dict[str, list[Block]] = {}
    for fn in cont:
        groups.setdefault(fn.container_block_id or "", []).append(fn)
    for group in groups.values():
        for i, fn in enumerate(sorted(group, key=lambda f: f.marker or "")):
            fn.marker = chr(ord("a") + i)
            fn.global_number = None


def _insert_page_breaks(body: list[Block]) -> list[Block]:
    out: list[Block] = []
    last_page = None
    for b in body:
        if last_page is not None and b.page_no != last_page and not b.continues_from:
            out.append(
                Block(
                    id=f"p{b.page_no}-pb",
                    type="page_break",
                    page_no=b.page_no,
                    order=0,
                    text=f"{b.page_no}쪽",
                )
            )
        out.append(b)
        last_page = b.page_no
    return out


def _dedupe_terms(terms: list[Block]) -> list[Block]:
    seen: dict[str, Block] = {}
    for t in sorted(terms, key=lambda x: (x.page_no, x.order)):
        key = _norm((t.surface or "").lower())
        if key and key not in seen:
            seen[key] = t
    return sorted(seen.values(), key=lambda t: (t.surface or "").lower())


def _stats(doc: AccessDoc, pages: list[PageAnalysis]) -> DocStats:
    s = DocStats(pages=len(pages))
    for b in doc.blocks:
        if b.type == "heading":
            s.headings += 1
        elif b.type == "paragraph":
            s.paragraphs += 1
        elif b.type == "figure":
            s.figures += 1
            if b.alt_long:
                s.figures_described += 1
        elif b.type == "table":
            s.tables += 1
        elif b.type == "formula":
            s.formulas += 1
        if b.flags:
            s.flagged_blocks += 1
    s.footnotes = len(doc.footnotes)
    s.table_footnotes = len(doc.table_footnotes)
    s.terms = len(doc.glossary)
    s.total_elapsed_ms = sum(p.elapsed_ms for p in pages)
    return s

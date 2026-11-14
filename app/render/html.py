"""시맨틱 HTML 렌더러. [담당: C]

이 파일의 태그 선택이 곧 제품의 탐색 기능이다.
제목 레벨을 건너뛰지 않고, 표는 진짜 table 로, 그림은 figure 로,
각주는 왕복 링크로 낸다. 눈으로만 보이는 표시는 쓰지 않는다.
"""

from __future__ import annotations

import html
import re

from app.schema import AccessDoc, Block, RenderOptions

FOOTNOTE_RE = re.compile(r"\[\^(\d+)\]")


def esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def to_html(doc: AccessDoc, opts: RenderOptions | None = None) -> str:
    opts = opts or RenderOptions()
    fn_by_num = {f.global_number: f for f in doc.footnotes if f.global_number}

    parts: list[str] = []
    parts.append('<a class="skip" href="#body-start">본문 바로가기</a>')
    parts.append(f"<h1>{esc(doc.title)}</h1>")
    parts.append(_summary(doc))
    parts.append(_missing_notice(doc))
    parts.append(_outline(doc, opts))
    parts.append('<div id="body-start"></div>')

    for b in doc.blocks:
        parts.append(_block_html(b, opts, fn_by_num))

    if opts.footnote_mode == "end" and doc.footnotes:
        parts.append(_footnote_section(doc))
    if doc.table_footnotes:
        parts.append(_table_footnote_section(doc))
    if opts.include_glossary and doc.glossary:
        parts.append(_glossary(doc))

    return "\n".join(p for p in parts if p)


def _summary(doc: AccessDoc) -> str:
    s = doc.stats
    text = (
        f"총 {s.pages}쪽. 그림 {s.figures}개, 표 {s.tables}개, "
        f"수식 {s.formulas}개, 각주 {s.footnotes}개."
    )
    if doc.degraded_pages:
        pages = ", ".join(str(p) for p in sorted(set(doc.degraded_pages)))
        text += f" {pages}쪽은 오프라인으로 처리되어 그림 설명이 없습니다."
    return f'<p class="doc-summary">{esc(text)}</p>'


def _missing_notice(doc: AccessDoc) -> str:
    """원문에 있는데 결과에 담기지 않은 구간. 숨기면 학생이 모른 채 지나간다."""
    samples = []
    for w in doc.warnings:
        if w.startswith("missing_text") and "sample=" in w:
            samples.append(w.split("sample=", 1)[1])
    if not samples:
        return ""

    items = "".join(f"<li>{esc(s)}</li>" for s in samples[:3])
    return (
        '<section class="verify" aria-labelledby="miss-h">'
        '<h2 id="miss-h">확인이 필요한 구간</h2>'
        "<p>원문에는 있으나 결과에 담기지 않은 글자가 있습니다. "
        "아래 부분은 직접 확인해 주세요.</p>"
        f"<ul>{items}</ul></section>"
    )


def _outline(doc: AccessDoc, opts: RenderOptions) -> str:
    heads = [b for b in doc.blocks if b.type == "heading"]
    if not heads:
        return ""
    items = "".join(
        f'<li><a href="#{esc(h.id)}">{esc(h.text)}</a></li>' for h in heads
    )
    return f'<nav aria-label="문서 개요"><ul>{items}</ul></nav>'


def _inline(text: str, fn_by_num: dict, opts: RenderOptions) -> str:
    """본문 안의 [^n] 을 각주 링크나 인라인 aside 로 바꾼다."""
    out = esc(text)

    def repl(m: re.Match) -> str:
        n = int(m.group(1))
        if opts.footnote_mode == "inline":
            fn = fn_by_num.get(n)
            body = esc(fn.text) if fn else ""
            return (
                f'</p><aside role="note">각주 {n}. {body}</aside><p>'
            )
        return (
            f'<sup><a href="#fn{n}" id="fnref{n}" '
            f'aria-label="각주 {n}">[각주 {n}]</a></sup>'
        )

    return FOOTNOTE_RE.sub(repl, out)


def _block_html(b: Block, opts: RenderOptions, fn_by_num: dict) -> str:
    flag_note = ""
    if opts.include_confidence and ("ocr_mismatch" in b.flags or "low_ocr_conf" in b.flags):
        flag_note = '<span class="sr-only">인식 신뢰도가 낮은 부분입니다.</span>'

    if b.type == "heading":
        lv = max(2, min(6, b.level or 2))
        return f'<h{lv} id="{esc(b.id)}">{esc(b.text)}</h{lv}>'

    if b.type == "paragraph":
        flag = ' data-flag="verify"' if "ocr_mismatch" in b.flags else ""
        return f'<p id="{esc(b.id)}"{flag}>{flag_note}{_inline(b.text, fn_by_num, opts)}</p>'

    if b.type == "list":
        tag = "ol" if b.list_ordered else "ul"
        items = "".join(f"<li>{esc(i)}</li>" for i in b.list_items)
        return f'<{tag} id="{esc(b.id)}">{items}</{tag}>'

    if b.type == "page_break":
        return f'<hr class="pagebreak" aria-label="{esc(b.text)} 시작">'

    if b.type == "formula":
        label = f" {esc(b.formula_label)}" if b.formula_label else ""
        latex = (
            f"<details><summary>LaTeX 표기</summary><code>{esc(b.latex)}</code></details>"
            if (opts.include_latex and b.latex)
            else ""
        )
        return (
            f'<div id="{esc(b.id)}" role="math" aria-label="{esc(b.speech)}">'
            f'<span aria-hidden="true">{esc(b.latex or b.text)}{label}</span>'
            f"{latex}</div>"
        )

    if b.type == "figure":
        img = (
            f'<img src="{esc(b.crop_path)}" alt="{esc(b.alt_short)}">'
            if b.crop_path
            else f'<div role="img" aria-label="{esc(b.alt_short)}" class="figure-placeholder"></div>'
        )
        cap = f"<figcaption>{esc(b.text)}</figcaption>" if b.text else ""
        if b.alt_long:
            desc = (
                f'<div id="{esc(b.id)}-desc" class="long-desc">'
                f'<span class="sr-only">AI 설명 시작.</span> {esc(b.alt_long)} '
                f'<span class="sr-only">AI 설명 끝.</span></div>'
            )
            described = f' aria-describedby="{esc(b.id)}-desc"'
        else:
            desc = (
                '<div class="long-desc"><strong>설명을 생성하지 못했습니다.</strong> '
                "이 부분은 직접 확인하거나 다른 사람에게 보여 주세요.</div>"
            )
            described = ""
        warn = ""
        if "unverified_number" in b.flags:
            warn = (
                '<p class="verify"><span class="sr-only">주의. </span>'
                "원문에서 확인되지 않는 수치가 포함되어 있습니다. 확인이 필요합니다.</p>"
            )
        elif "unverifiable_number" in b.flags:
            warn = (
                '<p class="verify"><span class="sr-only">주의. </span>'
                "그림 안의 글자가 원문 텍스트에 없어 이 설명의 수치를 대조하지 "
                "못했습니다. 확인이 필요합니다.</p>"
            )
        return f'<figure id="{esc(b.id)}"{described}>{img}{cap}{desc}{warn}</figure>'

    if b.type == "table":
        return _table_html(b)

    if b.type == "caption":
        return f'<p class="caption" id="{esc(b.id)}">{esc(b.text)}</p>'

    if b.type == "marginalia":
        return f'<aside id="{esc(b.id)}">{esc(b.text)}</aside>'

    return f'<p id="{esc(b.id)}">{esc(b.text)}</p>'


def _table_html(b: Block) -> str:
    if not b.table_grid:
        return f'<p id="{esc(b.id)}">{esc(b.alt_short or b.text)}</p>'

    rows = []
    for row in b.table_grid:
        cells = []
        for c in row:
            span = ""
            if c.row_span > 1:
                span += f' rowspan="{c.row_span}"'
            if c.col_span > 1:
                span += f' colspan="{c.col_span}"'
            if c.is_header:
                scope = c.header_axis if c.header_axis != "none" else "col"
                cells.append(f'<th scope="{scope}"{span}>{esc(c.text)}</th>')
            else:
                cells.append(f"<td{span}>{esc(c.text)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")

    cap = f"<caption>{esc(b.text or b.alt_short)}</caption>" if (b.text or b.alt_short) else ""
    return f'<table id="{esc(b.id)}">{cap}{"".join(rows)}</table>'


def _footnote_section(doc: AccessDoc) -> str:
    items = []
    for fn in doc.footnotes:
        n = fn.global_number
        back = f'<a href="#fnref{n}" aria-label="각주 {n} 참조 위치로 돌아가기">↩ 본문으로</a>'
        items.append(f'<li id="fn{n}">{esc(fn.text)} {back}</li>')
    return (
        '<section id="footnotes" aria-labelledby="fn-h">'
        '<h2 id="fn-h">각주</h2><ol>' + "".join(items) + "</ol></section>"
    )


def _table_footnote_section(doc: AccessDoc) -> str:
    items = "".join(
        f"<li>{esc(fn.marker)}) {esc(fn.text)}</li>" for fn in doc.table_footnotes
    )
    return (
        '<section aria-labelledby="tfn-h"><h2 id="tfn-h">표 각주</h2>'
        f"<ul>{items}</ul></section>"
    )


def _glossary(doc: AccessDoc) -> str:
    rows = []
    for t in doc.glossary:
        lang = f' lang="{esc(t.lang)}"' if t.lang else ""
        reading = f" ({esc(t.reading)})" if t.reading else ""
        rows.append(
            f"<dt><span{lang}>{esc(t.surface)}</span>{reading}</dt>"
            f"<dd>{esc(t.gloss)}</dd>"
        )
    return (
        '<section id="glossary" aria-labelledby="gl-h">'
        '<h2 id="gl-h">용어·외국어 표기</h2><dl>' + "".join(rows) + "</dl></section>"
    )

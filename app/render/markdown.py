"""마크다운 렌더러. 저장·공유용. [담당: C]"""

from __future__ import annotations

import re

from app.schema import AccessDoc, RenderOptions


def to_markdown(doc: AccessDoc, opts: RenderOptions | None = None) -> str:
    opts = opts or RenderOptions()
    out: list[str] = [f"# {doc.title}", ""]

    s = doc.stats
    out.append(
        f"> 총 {s.pages}쪽. 그림 {s.figures}개, 표 {s.tables}개, "
        f"수식 {s.formulas}개."
    )
    out.append("")

    for b in doc.blocks:
        if b.type == "heading":
            out += ["#" * max(2, b.level or 2) + f" {b.text}", ""]
        elif b.type == "paragraph":
            out += [re.sub(r"\[\^\d+\]", "", b.text), ""]
        elif b.type == "list":
            mark = "1." if b.list_ordered else "-"
            out += [f"{mark} {re.sub(r'\[\^\d+\]', '', i)}" for i in b.list_items] + [""]
        elif b.type == "page_break":
            out += [f"<!-- {b.text} -->", ""]
        elif b.type == "formula":
            out += [f"$$ {b.latex or b.text} $$", f"> 읽기: {b.speech}", ""]
        elif b.type == "figure":
            out += [f"![{b.alt_short}]({b.crop_path or ''})"]
            if b.text:
                out.append(f"*{b.text}*")
            out += [f"> {b.alt_long}" if b.alt_long else "> 설명을 생성하지 못했습니다.", ""]
        elif b.type == "table":
            out += _table_md(b) + [""]
        else:
            out += [re.sub(r"\[\^\d+\]", "", b.text), ""]

    return "\n".join(out)


def _table_md(b) -> list[str]:
    if not b.table_grid:
        return [b.alt_short or b.text or ""]
    rows = []
    for i, row in enumerate(b.table_grid):
        rows.append("| " + " | ".join(c.text for c in row) + " |")
        if i == 0:
            rows.append("|" + "---|" * len(row))
    if b.text:
        rows.insert(0, f"*{b.text}*")
    return rows

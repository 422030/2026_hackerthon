"""가짜 데이터로 전 구간이 도는지 확인한다.

서버와 OCR 없이 assemble -> render 경로만 본다.
1일차 게이트의 최소 조건이 이 스크립트다.

실행: .venv\\Scripts\\python smoke_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from app import assemble  # noqa: E402
from app.render import html as html_render  # noqa: E402
from app.render import markdown as md_render  # noqa: E402
from app.render import speech as speech_render  # noqa: E402
from app.schema import PageAnalysis, RenderOptions  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def main() -> int:
    paths = sorted(FIXTURES.glob("page_fake_*.json"))
    if not paths:
        print("FAIL: fixtures 가 없다")
        return 1

    pages = [PageAnalysis.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]
    print(f"[1] fixtures {len(pages)}장 로드")

    doc = assemble.assemble(pages, {"job_id": "smoke", "source_filename": "fake.pdf"})
    print(f"[2] assemble 완료 — 제목 '{doc.title}', 블록 {len(doc.blocks)}개")
    print(f"    통계: {doc.stats.model_dump()}")

    checks: list[tuple[str, bool, str]] = []

    # 머리글이 버려졌는가
    checks.append(
        ("머리글 제거", all(b.type != "running_head" for b in doc.blocks), "")
    )

    # 페이지 걸친 문단이 병합됐는가
    merged = [b for b in doc.blocks if "merged_across_page" in b.flags]
    checks.append(("페이지 걸친 문단 병합", len(merged) == 1, f"{len(merged)}건"))

    # 각주가 전역 번호를 받았는가
    nums = [f.global_number for f in doc.footnotes]
    checks.append(("각주 전역 번호", nums == [1, 2], f"{nums}"))

    # 본문에 [^n] 이 전역 번호로 치환됐는가
    body = " ".join(b.text for b in doc.blocks)
    checks.append(("각주 표기 치환", "[^1]" in body and "[^2]" in body, ""))

    # 제목 레벨이 건너뛰지 않는가
    levels = [b.level for b in doc.blocks if b.type == "heading"]
    ok_levels = all(lv == 2 for lv in levels)
    checks.append(("제목 레벨 정규화", ok_levels, f"{levels}"))

    html = html_render.to_html(doc, RenderOptions())
    for tag in ["<h2", "<figure", "<table", 'role="math"', 'id="fn1"', "AI 설명 시작"]:
        checks.append((f"HTML {tag}", tag in html, ""))

    segs = speech_render.to_speech_text(doc)
    checks.append(("음성 조각 생성", len(segs) > 8, f"{len(segs)}개"))
    kinds = {s.kind for s in segs}
    checks.append(("figure 조각 존재", "figure" in kinds, f"{sorted(kinds)}"))

    md = md_render.to_markdown(doc)
    checks.append(("마크다운 생성", len(md) > 200, f"{len(md)}자"))

    out = Path(__file__).resolve().parent / "data" / "smoke.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<title>스모크 테스트 결과</title>'
        '<link rel="stylesheet" href="../web/a11y.css"></head><body>'
        + html
        + "</body></html>",
        encoding="utf-8",
    )

    print("\n[3] 검사")
    failed = 0
    for name, ok, extra in checks:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"    {mark}  {name}{(' — ' + extra) if extra else ''}")

    print(f"\n[4] 결과 HTML: {out}")
    print(f"\n{'전부 통과' if failed == 0 else str(failed) + '건 실패'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

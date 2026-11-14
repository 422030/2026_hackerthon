"""테스트용 가상 교재 PDF 를 만든다.

저작권 문제가 없는 자체 제작 샘플이다. 실제 데모에는 OpenStax 교재를 쓴다.
실행: .venv\\Scripts\\python make_sample.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).resolve().parent / "samples" / "sample_textbook.pdf"
FONT = "malgun.ttf"
FONT_PATH = Path("C:/Windows/Fonts/malgun.ttf")


def main() -> None:
    doc = fitz.open()
    fontfile = str(FONT_PATH) if FONT_PATH.exists() else None

    # ── 12쪽 ────────────────────────────────────────────
    p = doc.new_page(width=595, height=842)
    _text(p, 60, 60, "제3장 확률변수", 9, fontfile)          # 머리글
    _text(p, 60, 110, "3.1 확률변수의 정의", 16, fontfile)    # 제목
    _text(
        p, 60, 150,
        "확률변수(random variable)1)란 표본공간의 각 원소에 실수를\n"
        "대응시키는 함수이다. 변수라는 이름과 달리 실제로는 함수이며,\n"
        "이 점이 초심자에게 흔한 혼동의 원인이 된다.",
        11, fontfile,
    )
    _text(p, 160, 240, "X : Ω → R          (3.1)", 13, fontfile)

    _chart(p, 60, 280, 420, 200)
    _text(p, 60, 500, "그림 3-2. 연도별 청년 실업률", 10, fontfile)

    _text(
        p, 60, 540,
        "확률변수는 치역의 성질에 따라 이산확률변수와 연속확률변수로\n"
        "구분한다. 이산확률변수는 치역이 가산집합인 경우이고,",
        11, fontfile,
    )
    p.draw_line(fitz.Point(60, 740), fitz.Point(300, 740))
    _text(p, 60, 755, "1) 김철수(2019), 통계학의 기초, 한빛출판, 42쪽.", 9, fontfile)
    _text(p, 520, 800, "12", 9, fontfile)

    # ── 13쪽 ────────────────────────────────────────────
    p = doc.new_page(width=595, height=842)
    _text(p, 60, 60, "제3장 확률변수", 9, fontfile)
    _text(p, 60, 110, "연속확률변수는 치역이 실수 구간인 경우이다.", 11, fontfile)
    _text(p, 60, 160, "3.2 표본의 구성", 16, fontfile)
    _text(
        p, 60, 200,
        "조사에 사용된 표본은 지역별로 다음과 같이 배분되었다.1)",
        11, fontfile,
    )
    _table(p, 60, 240, fontfile)
    _text(p, 60, 380, "표 3-1. 지역별 표본 수", 10, fontfile)

    p.draw_rect(fitz.Rect(60, 420, 480, 560))
    _text(p, 200, 490, "(조사 절차 도식)", 11, fontfile)
    _text(p, 60, 580, "그림 3-3. 조사 절차", 10, fontfile)

    p.draw_line(fitz.Point(60, 740), fitz.Point(300, 740))
    _text(p, 60, 755, "1) 표본 추출은 2024년 3월에 이루어졌다.", 9, fontfile)
    _text(p, 520, 800, "13", 9, fontfile)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    doc.close()
    print(f"생성: {OUT}")


def _text(page, x, y, body, size, fontfile):
    page.insert_text(
        fitz.Point(x, y), body, fontsize=size,
        fontname="kor" if fontfile else "helv", fontfile=fontfile,
    )


def _chart(page, x, y, w, h):
    """간단한 꺾은선그래프. 축 눈금과 라벨을 실제로 그린다."""
    page.draw_line(fitz.Point(x, y + h), fitz.Point(x + w, y + h))
    page.draw_line(fitz.Point(x, y), fitz.Point(x, y + h))

    values = [2.0, 2.5, 7.0, 4.0, 3.5, 8.0, 6.0, 5.0, 9.0]
    step = w / (len(values) - 1)
    pts = [fitz.Point(x + i * step, y + h - (v / 12) * h) for i, v in enumerate(values)]
    for a, b in zip(pts, pts[1:]):
        page.draw_line(a, b)

    for i, label in enumerate(["0", "4", "8", "12"]):
        yy = y + h - (int(label) / 12) * h
        page.insert_text(fitz.Point(x - 22, yy + 3), label, fontsize=8)
    for i, label in enumerate(["1990", "2000", "2010", "2020"]):
        xx = x + (i / 3) * w
        page.insert_text(fitz.Point(xx - 10, y + h + 14), label, fontsize=8)


def _table(page, x, y, fontfile):
    rows = [["지역", "표본 수", "비율"], ["서울", "412", "34.3%"],
            ["경기", "388", "32.3%"], ["그 외", "400", "33.3%"]]
    cw, rh = 110, 30
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            rect = fitz.Rect(x + c * cw, y + r * rh, x + (c + 1) * cw, y + (r + 1) * rh)
            page.draw_rect(rect)
            page.insert_text(
                fitz.Point(rect.x0 + 8, rect.y0 + 20), cell, fontsize=10,
                fontname="kor" if fontfile else "helv", fontfile=fontfile,
            )


if __name__ == "__main__":
    main()

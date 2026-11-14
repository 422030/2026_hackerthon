"""PDF·이미지를 페이지 단위 PNG 로 바꾼다. [담당: A]

PyMuPDF 를 쓴다. pdf2image 는 poppler 바이너리가 필요해서 윈도우에서 시간을 먹는다.
PyMuPDF 가 없으면 ImportError 대신 빈 목록을 돌려주고 호출부가 fixtures 로 넘어간다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.schema import PageImage

WORK_DIR = Path(__file__).resolve().parent.parent / "data" / "pages"


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    h.update(path.read_bytes())
    return h.hexdigest()


def page_count(path: str) -> int | None:
    """문서의 쪽 수. 읽지 못하면 None."""
    src = Path(path)
    if src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        return 1
    try:
        import fitz

        with fitz.open(src) as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001 - 호출부가 안내 문구를 만든다
        return None


def load_pages(
    path: str, dpi: int = 300, page_range: tuple[int, int] | None = None
) -> list[PageImage]:
    """PDF 또는 이미지 파일을 PageImage 목록으로 바꾼다."""
    src = Path(path)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    if src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        return [_single_image(src)]

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []

    doc = fitz.open(src)
    first, last = page_range or (1, doc.page_count)
    last = min(last, doc.page_count)

    out: list[PageImage] = []
    zoom = dpi / 72.0
    for idx in range(first - 1, last):
        page = doc[idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        png_path = WORK_DIR / f"{src.stem}_p{idx + 1:03d}.png"
        pix.save(png_path)

        native = page.get_text("text") or ""
        img = PageImage(
            page_no=idx + 1,
            image_path=str(png_path),
            width=pix.width,
            height=pix.height,
            dpi=dpi,
            sha1=_sha1_file(png_path),
            native_text=native if len(native.strip()) > 40 else None,
            is_scanned=len(native.strip()) <= 40,
        )
        _write_sidecar(img, png_path)
        out.append(img)
    doc.close()
    return out


def _sidecar_path(png_path: Path) -> Path:
    return png_path.with_suffix(".page.json")


def _write_sidecar(img: PageImage, png_path: Path) -> None:
    """PNG 옆에 쪽 정보를 적어 둔다.

    원본 PDF 는 쪽을 다 뽑은 직후 지운다. 텍스트층과 해상도는 PNG 만 봐서는
    되살릴 수 없으므로 여기 남겨 둔다. 실패해도 변환 자체는 계속 간다.
    """
    try:
        _sidecar_path(png_path).write_text(img.model_dump_json(), encoding="utf-8")
    except OSError:
        pass


def load_cached_page(image_path: str) -> PageImage | None:
    """이미 뽑아둔 PNG 로 PageImage 를 되살린다. 없으면 None.

    다시 변환할 때 쓴다. 원본 PDF 가 이미 없어도 쪽을 다시 돌릴 수 있다.
    """
    png = Path(image_path)
    meta = _sidecar_path(png)
    if not png.exists() or not meta.exists():
        return None
    try:
        return PageImage.model_validate_json(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _single_image(src: Path) -> PageImage:
    try:
        from PIL import Image

        with Image.open(src) as im:
            w, h = im.size
    except Exception:
        w = h = 0

    return PageImage(
        page_no=1,
        image_path=str(src),
        width=w or 1,
        height=h or 1,
        sha1=_sha1_file(src),
        native_text=None,
        is_scanned=True,
    )

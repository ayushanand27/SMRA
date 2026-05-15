"""
Extract text from PDFs page-by-page: native text, tables (pdfplumber), optional OCR (Tesseract).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import pdfplumber

_MAX_PAGES = 100
_MAX_OUTPUT_CHARS = 120_000
_MIN_IMAGE_SIDE = 40
_MAX_IMAGE_PIXELS = 2_500_000


@dataclass
class PdfExtractResult:
    chapter_text: str
    notes: str
    page_count: int
    table_count: int
    ocr_page_runs: int = 0
    ocr_image_runs: int = 0
    warnings: list[str] = field(default_factory=list)


def _truncate(s: str, limit: int) -> tuple[str, bool]:
    s = s.strip()
    if len(s) <= limit:
        return s, False
    return s[: limit - 20].rsplit("\n", 1)[0] + "\n\n[…truncated for model context…]", True


def _format_table(table: list[list[str | None]]) -> str:
    if not table:
        return ""
    rows: list[str] = []
    for row in table:
        cells = [re.sub(r"\s+", " ", str(c or "").strip()) for c in row]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def _ocr_image(pil_img) -> str | None:
    try:
        import pytesseract
    except ImportError:
        return None
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return None
    try:
        # eng + hin when available
        return pytesseract.image_to_string(pil_img, lang="eng+hin").strip()
    except Exception:
        try:
            return pytesseract.image_to_string(pil_img, lang="eng").strip()
        except Exception:
            return None


def _ocr_from_pixmap(pix: fitz.Pixmap) -> str | None:
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return _ocr_image(img)
    except Exception:
        return None


def extract_pdf_to_text(
    pdf_bytes: bytes,
    *,
    ocr_pages: bool = True,
    ocr_images: bool = True,
) -> PdfExtractResult:
    if not pdf_bytes or len(pdf_bytes) < 8 or not pdf_bytes[:5].startswith(b"%PDF"):
        raise ValueError("Invalid or empty PDF file.")

    warnings: list[str] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n_pages = len(doc)
    if n_pages == 0:
        doc.close()
        raise ValueError("PDF has no pages.")
    if n_pages > _MAX_PAGES:
        warnings.append(f"Only first {_MAX_PAGES} of {n_pages} pages were processed.")
    effective_pages = min(n_pages, _MAX_PAGES)

    ocr_page_runs = 0
    ocr_image_runs = 0
    table_count = 0
    parts: list[str] = []

    plumber = pdfplumber.open(io.BytesIO(pdf_bytes))
    try:
        for i in range(effective_pages):
            page = doc[i]
            page_num = i + 1
            block_lines: list[str] = []

            native = (page.get_text("text") or "").strip()
            if native:
                block_lines.append(native)

            # Tables via pdfplumber (same page index)
            try:
                p_page = plumber.pages[i]
                tables = p_page.extract_tables() or []
                for ti, table in enumerate(tables):
                    if not table:
                        continue
                    formatted = _format_table(table)
                    if formatted.strip():
                        table_count += 1
                        block_lines.append(f"\n[Table {ti + 1} on page {page_num}]\n{formatted}\n")
            except Exception:
                warnings.append(f"Table extraction skipped on page {page_num}.")

            # Embedded images (figures, scans inside page)
            if ocr_images:
                try:
                    for img in page.get_images(full=True):
                        xref = img[0]
                        try:
                            base = doc.extract_image(xref)
                        except Exception:
                            continue
                        w, h = int(base.get("width", 0)), int(base.get("height", 0))
                        if w < _MIN_IMAGE_SIDE or h < _MIN_IMAGE_SIDE:
                            continue
                        if w * h > _MAX_IMAGE_PIXELS:
                            continue
                        from PIL import Image

                        try:
                            pil_img = Image.open(io.BytesIO(base["image"]))
                            if pil_img.mode not in ("RGB", "L"):
                                pil_img = pil_img.convert("RGB")
                        except Exception:
                            continue
                        ocr_t = _ocr_image(pil_img)
                        if ocr_t and len(ocr_t) > 15:
                            ocr_image_runs += 1
                            block_lines.append(f"\n[Text from image on page {page_num}]\n{ocr_t}\n")
                except Exception:
                    pass

            # Full-page OCR when little native text or scans
            if ocr_pages:
                sparse = len(re.sub(r"\s+", "", native)) < 80
                if sparse or not native:
                    try:
                        mat = fitz.Matrix(1.8, 1.8)
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        ocr_t = _ocr_from_pixmap(pix)
                        if ocr_t and len(ocr_t) > 20:
                            ocr_page_runs += 1
                            block_lines.append(f"\n[Page {page_num} — OCR from page image]\n{ocr_t}\n")
                    except Exception:
                        pass

            page_body = "\n".join(block_lines).strip()
            if page_body:
                parts.append(f"=== Page {page_num} ===\n{page_body}")
    finally:
        plumber.close()

    doc.close()

    merged = "\n\n".join(parts).strip()
    if not merged:
        raise ValueError("No text could be extracted from this PDF. Try OCR with Tesseract installed.")

    truncated, was_trunc = _truncate(merged, _MAX_OUTPUT_CHARS)
    if was_trunc:
        warnings.append(f"Extracted content truncated to {_MAX_OUTPUT_CHARS} characters.")

    ocr_note = []
    if ocr_page_runs or ocr_image_runs:
        ocr_note.append(f"OCR: {ocr_page_runs} page(s), {ocr_image_runs} embedded image(s).")
    else:
        if ocr_pages or ocr_images:
            ocr_note.append(
                "OCR did not add text (install Tesseract + pytesseract for text inside images/scanned pages)."
            )

    notes = (
        f"PDF: {effective_pages} page(s), {table_count} table(s). " + " ".join(ocr_note + warnings[:3])
    ).strip()

    return PdfExtractResult(
        chapter_text=truncated,
        notes=notes,
        page_count=effective_pages,
        table_count=table_count,
        ocr_page_runs=ocr_page_runs,
        ocr_image_runs=ocr_image_runs,
        warnings=warnings,
    )

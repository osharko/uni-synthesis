#!/usr/bin/env python3
"""
ocr_to_text.py — Pipeline OCR per scansioni / fotocopie:
  1. split delle doppie pagine in pagine singole
  2. image enhancement (contrasto, nitidezza, luminosità, grayscale)
  3. OCR via ocrmypdf + tesseract → PDF cercabile
  4. estrazione testo via PyMuPDF → markdown

Configurazione via .env (vedi .env.example). CLI sovrascrive INPUT_PDF.

Esempi:
  python scripts/ocr_to_text.py                              # usa .env
  python scripts/ocr_to_text.py books/Scan.pdf
  python scripts/ocr_to_text.py books/Scan.pdf --no-split    # già pagina singola
  python scripts/ocr_to_text.py books/Scan.pdf --skip-ocr    # solo split+enhance
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import fitz  # PyMuPDF
    import numpy as np
    from PIL import Image, ImageEnhance
    from dotenv import dotenv_values
except ImportError as e:
    sys.exit(f"Errore: dipendenza mancante ({e}). pip install -r requirements.txt")

REPO_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_DIR / ".env"


def load_config(env_path: Path = ENV_PATH) -> dict:
    raw = dotenv_values(env_path) if env_path.exists() else {}

    def f(key, default):
        v = raw.get(key, "")
        return float(v) if v else default

    def i(key, default):
        v = raw.get(key, "")
        return int(v) if v else default

    def b(key, default):
        v = raw.get(key, "")
        if not v:
            return default
        return v.lower() in ("true", "1", "yes")

    input_pdf = raw.get("INPUT_PDF", "")
    if input_pdf and not os.path.isabs(input_pdf):
        input_pdf = str(REPO_DIR / input_pdf)

    work_dir = raw.get("WORK_DIR", "")
    if work_dir and not os.path.isabs(work_dir):
        work_dir = str(REPO_DIR / work_dir)

    return {
        "input_pdf": input_pdf,
        "work_dir": work_dir,
        "auto_split": b("AUTO_SPLIT", True),
        "auto_split_range": f("AUTO_SPLIT_RANGE", 0.15),
        "split_position": f("SPLIT_POSITION", 0.50),
        "center_crop_margin": f("CENTER_CROP_MARGIN", 0.02),
        "outer_crop_margin": f("OUTER_CROP_MARGIN", 0.01),
        "vertical_crop_margin": f("VERTICAL_CROP_MARGIN", 0.01),
        "page_start": i("PAGE_START", 0),
        "page_end": i("PAGE_END", 0),
        "render_dpi": i("RENDER_DPI", 300),
        "jpeg_quality": i("JPEG_QUALITY", 85),
        "enhance_contrast": b("ENHANCE_CONTRAST", True),
        "contrast_factor": f("CONTRAST_FACTOR", 1.3),
        "sharpen": b("SHARPEN", True),
        "sharpness_factor": f("SHARPNESS_FACTOR", 1.5),
        "adjust_brightness": b("ADJUST_BRIGHTNESS", True),
        "brightness_factor": f("BRIGHTNESS_FACTOR", 1.05),
        "grayscale": b("GRAYSCALE", True),
        "ocr_enabled": b("OCR_ENABLED", True),
        "ocr_language": raw.get("OCR_LANGUAGE", "") or "ita",
        "ocr_dpi": i("OCR_DPI", 300),
        "ocr_skip_text": b("OCR_SKIP_TEXT", True),
        "ocr_deskew": b("OCR_DESKEW", True),
    }


def enhance_image(img: Image.Image, cfg: dict) -> Image.Image:
    if cfg["grayscale"]:
        img = img.convert("L")
    if cfg["adjust_brightness"]:
        img = ImageEnhance.Brightness(img).enhance(cfg["brightness_factor"])
    if cfg["enhance_contrast"]:
        img = ImageEnhance.Contrast(img).enhance(cfg["contrast_factor"])
    if cfg["sharpen"]:
        img = ImageEnhance.Sharpness(img).enhance(cfg["sharpness_factor"])
    return img


def detect_split_position(img: Image.Image, nominal: float, search_range: float) -> int:
    """Trova la colonna più luminosa vicino al centro per lo split doppia pagina."""
    w, h = img.size
    gray = np.array(img.convert("L"))
    center_x = int(w * nominal)
    half = int(w * search_range)
    x0, x1 = max(0, center_x - half), min(w, center_x + half)
    region = gray[int(h * 0.2):int(h * 0.8), x0:x1]
    col_brightness = region.mean(axis=0).astype(float)
    kernel_size = max(5, int(w * 0.005))
    kernel = np.ones(kernel_size) / kernel_size
    smoothed = np.convolve(col_brightness, kernel, mode="same")
    bright = np.where(smoothed >= 200.0)[0]
    zone_center = (x1 - x0) / 2.0
    if len(bright):
        best = int(bright[np.argmin(np.abs(bright - zone_center))])
    else:
        positions = np.arange(x1 - x0, dtype=float)
        sigma = (x1 - x0) * 0.3
        proximity = np.exp(-0.5 * ((positions - zone_center) / sigma) ** 2)
        best = int(np.argmax(smoothed * proximity))
    return x0 + best


def split_and_enhance(cfg: dict, input_pdf: Path, do_split: bool) -> Path:
    """Restituisce un PDF temporaneo con pagine singole + enhancement."""
    doc = fitz.open(input_pdf)
    total = len(doc)
    p_start = cfg["page_start"] if cfg["page_start"] > 0 else 1
    p_end = cfg["page_end"] if cfg["page_end"] > 0 else total

    print(f"  Pagine: {p_start}-{p_end} di {total}  |  DPI {cfg['render_dpi']}  |  "
          f"split={'on' if do_split else 'off'}")

    out = fitz.open()
    zoom = cfg["render_dpi"] / 72.0
    mat = fitz.Matrix(zoom, zoom)

    widths = [doc[i].rect.width for i in range(p_start - 1, p_end)]
    if widths and max(widths) > min(widths) * 1.3:
        width_threshold = (min(widths) + max(widths)) / 2
    else:
        width_threshold = 0

    pages_out = 0
    for i in range(p_start - 1, p_end):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        w, h = img.size
        is_double = do_split and (page.rect.width > width_threshold if width_threshold else True)

        vert = int(h * cfg["vertical_crop_margin"])
        outer = int(w * cfg["outer_crop_margin"])

        boxes = []
        if not is_double:
            boxes.append((outer, vert, w - outer, h - vert))
        else:
            if cfg["auto_split"]:
                sx = detect_split_position(img, cfg["split_position"], cfg["auto_split_range"])
            else:
                sx = int(w * cfg["split_position"])
            center = int(w * cfg["center_crop_margin"])
            boxes.append((outer, vert, sx - center, h - vert))
            boxes.append((sx + center, vert, w - outer, h - vert))

        for box in boxes:
            cropped = img.crop(box)
            cropped = enhance_image(cropped, cfg)
            if cropped.mode == "L":
                cropped = cropped.convert("RGB")
            buf = io.BytesIO()
            cropped.save(buf, format="JPEG", quality=cfg["jpeg_quality"], optimize=True)
            buf.seek(0)
            cw, ch = cropped.size
            page_out = out.new_page(width=cw * 72 / cfg["render_dpi"],
                                    height=ch * 72 / cfg["render_dpi"])
            page_out.insert_image(page_out.rect, stream=buf.getvalue())
            pages_out += 1

        print(f"\r  Processing: {i - p_start + 2}/{p_end - p_start + 1}  "
              f"({pages_out} pagine output)", end="", flush=True)
    print()
    doc.close()

    tmp_fd, tmp_path = tempfile.mkstemp(suffix="_split.pdf", prefix="uni-synth_")
    os.close(tmp_fd)
    out.save(tmp_path, deflate=True, garbage=4)
    out.close()
    return Path(tmp_path)


def run_ocr(input_pdf: Path, output_pdf: Path, cfg: dict) -> bool:
    """Ritorna True se OCR riuscito (anche con --skip-text), False se fallback."""
    if shutil.which("ocrmypdf") is None:
        print("  ATTENZIONE: ocrmypdf non installato. "
              "Su Arch: sudo pacman -S tesseract tesseract-data-ita && pip install ocrmypdf")
        shutil.copy2(input_pdf, output_pdf)
        return False

    cmd = ["ocrmypdf", "--language", cfg["ocr_language"],
           "--image-dpi", str(cfg["ocr_dpi"]), "--optimize", "1", "--output-type", "pdf"]
    if cfg["ocr_skip_text"]:
        cmd.append("--skip-text")
    if cfg["ocr_deskew"]:
        cmd.append("--deskew")
    cmd += [str(input_pdf), str(output_pdf)]

    print(f"  OCR ({cfg['ocr_language']})...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode in (0, 6):
        if not output_pdf.exists() or output_pdf.stat().st_size == 0:
            shutil.copy2(input_pdf, output_pdf)
        return True
    print(f"  OCR warning (exit {result.returncode}): {result.stderr.strip()[:300]}")
    shutil.copy2(input_pdf, output_pdf)
    return False


def extract_text_from_pdf(pdf_path: Path, md_path: Path) -> dict:
    doc = fitz.open(pdf_path)
    chunks, chars = [], 0
    for i, page in enumerate(doc):
        text = page.get_text("text")
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        chunks.append(f"<!-- page {i + 1} -->\n\n{text}\n")
        chars += len(text)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(chunks), encoding="utf-8")
    doc.close()
    return {"pages": len(chunks), "chars": chars, "out": str(md_path)}


def resolve_work_dir(cfg: dict, input_pdf: Path) -> Path:
    if cfg["work_dir"]:
        wd = Path(cfg["work_dir"])
    else:
        wd = input_pdf.parent / input_pdf.stem
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def main() -> None:
    ap = argparse.ArgumentParser(description="OCR + estrazione per PDF scansionati.")
    ap.add_argument("pdf", nargs="?", type=Path, default=None,
                    help="PDF di input (override INPUT_PDF in .env)")
    ap.add_argument("--no-split", action="store_true",
                    help="Salta lo split doppia pagina (PDF già pagina singola)")
    ap.add_argument("--skip-ocr", action="store_true",
                    help="Salta OCR (solo split + enhancement)")
    ap.add_argument("--env", type=Path, default=ENV_PATH, help="Path al file .env")
    args = ap.parse_args()

    cfg = load_config(args.env)
    if args.skip_ocr:
        cfg["ocr_enabled"] = False
    input_pdf = args.pdf if args.pdf else (Path(cfg["input_pdf"]) if cfg["input_pdf"] else None)
    if not input_pdf or not input_pdf.exists():
        sys.exit(f"Errore: PDF non trovato. Specifica via CLI o INPUT_PDF in .env. "
                 f"(provato: {input_pdf})")

    print("=" * 60)
    print(f"  OCR pipeline: {input_pdf.name}")
    print("=" * 60)

    work_dir = resolve_work_dir(cfg, input_pdf)
    enhanced_pdf = work_dir / f"{input_pdf.stem} - ocr.pdf"
    md_out = work_dir / f"{input_pdf.stem} - estratto.md"

    tmp_pdf = split_and_enhance(cfg, input_pdf, do_split=not args.no_split)

    if cfg["ocr_enabled"]:
        run_ocr(tmp_pdf, enhanced_pdf, cfg)
        tmp_pdf.unlink(missing_ok=True)
    else:
        shutil.move(tmp_pdf, enhanced_pdf)

    print(f"  PDF processato:    {enhanced_pdf}")
    print(f"  Estrazione testo → {md_out}")
    result = extract_text_from_pdf(enhanced_pdf, md_out)
    print(f"  Pagine estratte:   {result['pages']}")
    print(f"  Caratteri:         {result['chars']:,}")
    print(f"  Markdown:          {result['out']}")


if __name__ == "__main__":
    main()

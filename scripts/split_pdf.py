#!/usr/bin/env python3
r"""
split_pdf.py — Divide un PDF con doppie pagine (due fogli per pagina) in pagine
singole, in modo VETTORIALE: il layer di testo/l'immagine originale vengono
conservati (nessuna rasterizzazione), così il PDF risultante è pronto per
full_to_text.py senza dover rifare l'OCR.

Esempi:
  python scripts/split_pdf.py books/Foucault.pdf
  python scripts/split_pdf.py books/Foucault.pdf --pages 1-10
  python scripts/split_pdf.py books/Foucault.pdf --out books/Foucault/split.pdf
  python scripts/split_pdf.py books/Foucault.pdf --no-auto   # split a metà esatta

Comportamento:
  - Per ogni pagina di input crea due pagine di output (metà sinistra e metà destra).
  - La posizione del taglio è rilevata automaticamente (colonna più chiara vicino
    al centro) oppure forzata a metà con --no-auto.
  - Con --pages START-END limita il range di pagine di input (1-indexed).
  - Le pagine vengono ritagliate ai margini (--margin) per rimuovere la fascia
    bianca esterna, opzionale.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import pymupdf  # PyMuPDF
except ImportError:
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        sys.exit("Errore: PyMuPDF mancante. Installa con: pip install PyMuPDF")

try:
    import numpy as np
except ImportError:
    np = None


def detect_gutter(doc, pno: int, nominal: float = 0.5, search_range: float = 0.15,
                  dpi: int = 72) -> float:
    """Trova la x del taglio (in punti PDF) come colonna più chiara vicino al centro."""
    page = doc[pno]
    r = page.rect
    if np is None:
        return r.x0 + r.width * nominal

    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)

    center_x = int(pix.width * nominal)
    half = int(pix.width * search_range)
    x0, x1 = max(0, center_x - half), min(pix.width, center_x + half)
    region = gray[int(pix.height * 0.2):int(pix.height * 0.8), x0:x1].astype(float)
    col = region.mean(axis=0)
    k = max(5, int(pix.width * 0.005))
    smoothed = np.convolve(col, np.ones(k) / k, mode="same")
    bright = np.where(smoothed >= 200.0)[0]
    zone_center = (x1 - x0) / 2.0
    if len(bright):
        best = int(bright[np.argmin(np.abs(bright - zone_center))])
    else:
        pos = np.arange(x1 - x0, dtype=float)
        prox = np.exp(-0.5 * ((pos - zone_center) / ((x1 - x0) * 0.3)) ** 2)
        best = int(np.argmax(smoothed * prox))
    px = x0 + best
    return r.x0 + px / zoom


def split_pdf(input_pdf: Path, output_pdf: Path, start: int, end: int,
              auto: bool, margin: float, nominal: float) -> dict:
    src = pymupdf.open(input_pdf)
    total = len(src)
    start = max(1, start) if start else 1
    end = min(total, end) if end else total

    out = pymupdf.open()
    pages_out = 0
    for i in range(start - 1, end):
        page = src[i]
        r = page.rect
        sx = detect_gutter(src, i, nominal) if auto else r.x0 + r.width * nominal
        m = margin
        left = pymupdf.Rect(r.x0 + m, r.y0 + m, sx, r.y1 - m)
        right = pymupdf.Rect(sx, r.y0 + m, r.x1 - m, r.y1 - m)

        for clip in (left, right):
            w, h = clip.width, clip.height
            new = out.new_page(width=w, height=h)
            new.show_pdf_page(new.rect, src, i, clip=clip)
            pages_out += 1

        print(f"\r  {i - start + 2}/{end - start + 1} pagine input "
              f"→ {pages_out} pagine output", end="", flush=True)
    print()

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    out.save(output_pdf, deflate=True, garbage=4)
    out.close()
    src.close()
    return {"pages_in": end - start + 1, "pages_out": pages_out, "out": str(output_pdf)}


def parse_range(spec: str) -> tuple[int, int]:
    spec = spec.strip()
    if not spec:
        return 0, 0
    if "-" in spec:
        a, b = spec.split("-", 1)
        return int(a), int(b)
    n = int(spec)
    return n, n


def default_output(input_pdf: Path) -> Path:
    work = input_pdf.parent / input_pdf.stem
    work.mkdir(parents=True, exist_ok=True)
    return work / f"{input_pdf.stem} - split.pdf"


def main() -> None:
    ap = argparse.ArgumentParser(description="Split vettoriale doppie pagine → pagine singole.")
    ap.add_argument("pdf", type=Path, help="PDF di input (doppie pagine)")
    ap.add_argument("--out", type=Path, default=None, help="PDF di output")
    ap.add_argument("--pages", type=str, default="", help="Range pagine input, es. '1-10'")
    ap.add_argument("--no-auto", action="store_true",
                    help="Taglio a metà esatta (disabilita auto-detect del gutter)")
    ap.add_argument("--margin", type=float, default=0.0,
                    help="Margine esterno da rimuovere, in punti (default 0)")
    ap.add_argument("--position", type=float, default=0.5,
                    help="Posizione nominale del taglio (0-1, default 0.5)")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"Errore: PDF non trovato: {args.pdf}")

    start, end = parse_range(args.pages)
    out = args.out or default_output(args.pdf)

    print(f"Split: {args.pdf}")
    result = split_pdf(args.pdf, out, start, end,
                       auto=not args.no_auto, margin=args.margin, nominal=args.position)
    print(f"  Pagine input:  {result['pages_in']}")
    print(f"  Pagine output: {result['pages_out']}")
    print(f"  Output:        {result['out']}")


if __name__ == "__main__":
    main()

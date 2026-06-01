#!/usr/bin/env python3
r"""
full_to_text.py — Estrae il testo di un PDF nativo (con layer testo già presente)
in un unico markdown, pronto per essere splittato in capitoli.

Esempi:
  python scripts/full_to_text.py books/MioLibro.pdf
  python scripts/full_to_text.py books/MioLibro.pdf --out books/MioLibro/MioLibro\ -\ estratto.md
  python scripts/full_to_text.py books/MioLibro.pdf --start 5 --end 250 --skip-empty

Pre-requisiti: PyMuPDF (`pip install PyMuPDF`).

Comportamento:
  - Estrae con `page.get_text("text")` (preserva ordine di lettura).
  - Inserisce un separatore "<!-- page N -->" tra le pagine, utile a quality_check.
  - Salta pagine vuote (< MIN_CHARS_PER_PAGE caratteri non-whitespace) se --skip-empty.
  - Se --out non è specificato, scrive in books/<basename>/<basename> - estratto.md.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("Errore: PyMuPDF mancante. Installa con: pip install PyMuPDF")

MIN_CHARS_PER_PAGE = 30


def default_output_path(pdf_path: Path) -> Path:
    base = pdf_path.stem
    work_dir = pdf_path.parent / base
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir / f"{base} - estratto.md"


def clean_text(text: str) -> str:
    # rimuove sillabazione di fine riga "paro-\nla" → "parola"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # normalizza spazi multipli (ma preserva newline)
    text = re.sub(r"[ \t]+", " ", text)
    # rimuove righe completamente vuote multiple
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(pdf_path: Path, out_path: Path, start: int, end: int,
            skip_empty: bool, exclude: set[int]) -> dict:
    doc = fitz.open(pdf_path)
    total = len(doc)
    start = max(1, start) if start else 1
    end = min(total, end) if end else total

    chunks = []
    skipped = []
    char_count = 0
    page_count = 0
    for i in range(start - 1, end):
        page_num = i + 1
        if page_num in exclude:
            skipped.append(page_num)
            continue
        text = doc[i].get_text("text")
        cleaned = clean_text(text)
        if skip_empty and len(re.sub(r"\s", "", cleaned)) < MIN_CHARS_PER_PAGE:
            skipped.append(page_num)
            continue
        chunks.append(f"<!-- page {page_num} -->\n\n{cleaned}\n")
        char_count += len(cleaned)
        page_count += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(chunks), encoding="utf-8")
    doc.close()

    return {
        "pages_total": total,
        "pages_extracted": page_count,
        "pages_skipped": skipped,
        "chars": char_count,
        "out": str(out_path),
    }


def parse_exclude(spec: str) -> set[int]:
    out: set[int] = set()
    if not spec:
        return out
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Estrai testo da PDF nativo in markdown.")
    ap.add_argument("pdf", type=Path, help="PDF di input (deve avere layer testo)")
    ap.add_argument("--out", type=Path, default=None, help="Markdown di output")
    ap.add_argument("--start", type=int, default=0, help="Prima pagina (1-indexed, 0=tutte)")
    ap.add_argument("--end", type=int, default=0, help="Ultima pagina (1-indexed, 0=tutte)")
    ap.add_argument("--skip-empty", action="store_true",
                    help="Salta pagine quasi vuote (<30 caratteri non-whitespace)")
    ap.add_argument("--exclude", type=str, default="",
                    help="Pagine da escludere, es. '1,2,10-15,250'")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"Errore: PDF non trovato: {args.pdf}")

    out = args.out or default_output_path(args.pdf)
    exclude = parse_exclude(args.exclude)

    print(f"Estrazione: {args.pdf}")
    result = extract(args.pdf, out, args.start, args.end, args.skip_empty, exclude)
    print(f"  Pagine totali:      {result['pages_total']}")
    print(f"  Pagine estratte:    {result['pages_extracted']}")
    print(f"  Pagine saltate:     {len(result['pages_skipped'])}"
          + (f"  → {result['pages_skipped']}" if result["pages_skipped"] else ""))
    print(f"  Caratteri:          {result['chars']:,}")
    print(f"  Output:             {result['out']}")


if __name__ == "__main__":
    main()

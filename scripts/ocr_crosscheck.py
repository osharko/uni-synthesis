#!/usr/bin/env python3
r"""
ocr_crosscheck.py — Seconda lettura OCR in CPU (tesseract) e confronto con il
markdown già estratto/corretto, per validazione incrociata SENZA usare LLM.

Idee:
  - Il PDF splittato ha un layer OCR (spesso tesseract) con errori.
  - Qui si produce una lettura INDIPENDENTE della pagina con tesseract (ita),
    poi si confronta con il testo attuale per:
      * `fragments`: recuperare i passi marcati [illeggibile];
      * `full`     : elencare le divergenze pagina per pagina (candidati refusi).

Nessuna dipendenza Python extra: usa il binario `tesseract` + PyMuPDF.

Esempi:
  python scripts/ocr_crosscheck.py --mode fragments \
      --pdf "books/Foucault/Foucault - split.pdf" \
      --current "books/Foucault/revisione/Le parole e le cose - revisionato.md" \
      --fragments books/Foucault/revisione2/frag_cases.json \
      --out /tmp/opencode/cross_fragments.md

  python scripts/ocr_crosscheck.py --mode full --pages 1-20 --dpi 400 \
      --pdf "books/Foucault/Foucault - split.pdf" \
      --estratto "books/Foucault/Foucault - estratto.md" \
      --out /tmp/opencode/cross_pages.md

Nota (full): il confronto è PAGINA per PAGINA tra la lettura tesseract e il
layer dell'`estratto` (stessa pagina, nessun allineamento). Serve `--estratto`
con i marker `<!-- page N -->`.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        sys.exit("Errore: PyMuPDF mancante (pip install PyMuPDF)")

TOK = re.compile(r"[a-zA-ZàèéìòùÀÈÉÌÒÙ']+")


def tokens(s: str) -> list[str]:
    return [t.lower() for t in TOK.findall(s)]


def ocr_page(doc, pno: int, dpi: int, lang: str, psm: int) -> str:
    """OCR di una pagina (0-based) via tesseract su immagine temporanea."""
    page = doc[pno]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72.0, dpi / 72.0))
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = Path(f.name)
    pix.save(tmp)
    try:
        res = subprocess.run(
            ["tesseract", str(tmp), "stdout", "-l", lang, "--oem", "1", "--psm", str(psm)],
            capture_output=True, text=True, timeout=300,
        )
        return res.stdout
    finally:
        tmp.unlink(missing_ok=True)


def parse_pages(spec: str, total: int) -> list[int]:
    if not spec:
        return list(range(total))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a) - 1, int(b)))
        else:
            out.append(int(part) - 1)
    return [p for p in out if 0 <= p < total]


def best_window(ocr_tokens: list[str], anchor: list[str]) -> int:
    """Indice (in token) della finestra OCR più simile all'anchor (overlap)."""
    aset = set(anchor)
    best, best_i = -1, 0
    n = len(anchor)
    for i in range(0, max(1, len(ocr_tokens) - n)):
        ov = len(aset & set(ocr_tokens[i:i + n + 4]))
        if ov > best:
            best, best_i = ov, i
    return best_i


def run_fragments(doc, current: str, fragments: list[dict], dpi: int, lang: str, psm: int) -> str:
    lines = current.split("\n")
    out = ["# Cross-check OCR — frammenti [illeggibile]\n"]
    for fr in fragments:
        pg = fr.get("page")
        out.append(f"\n## #{fr.get('n')}  (riga {fr.get('line')}, pagina split {pg})\n")
        if not pg:
            out.append("_pagina non individuata_\n")
            continue
        ocr = ocr_page(doc, pg - 1, dpi, lang, psm)
        ot = tokens(ocr)
        anchor = tokens(fr.get("before", "") + " " + fr.get("after", ""))
        i = best_window(ot, anchor)
        # riporta una finestra di testo OCR attorno alla posizione trovata
        # ricostruiamo dal testo OCR grezzo tramite gli stessi token non è banale:
        # mostriamo invece +/- 60 token dell'OCR normalizzato.
        win = ot[max(0, i - 10): i + 45]
        out.append("**Lettera OCR (tesseract), finestra:**\n")
        out.append("> " + " ".join(win) + "\n")
        out.append(f"\n**Testo attuale (riga {fr.get('line')}):**\n")
        out.append("> " + lines[fr["line"] - 1][:400] + "\n")
    return "\n".join(out)


def build_page_text_map(doc, current_lines: list[str], dpi: int, lang: str, psm: int) -> None:
    """(placeholder) mapping pagina→testo attuale, non usato nella modalità frammenti."""
    return None


PAGE_MARK = re.compile(r"<!--\s*page\s+(\d+)\s*-->")


def load_estratto_pages(path: Path) -> dict[int, str]:
    """Legge un estratto con marker `<!-- page N -->` e restituisce {N: testo}."""
    txt = path.read_text(encoding="utf-8")
    parts = PAGE_MARK.split(txt)
    out: dict[int, str] = {}
    for i in range(1, len(parts), 2):
        out[int(parts[i])] = parts[i + 1] if i + 1 < len(parts) else ""
    return out


def run_full(doc, estratto_pages: dict[int, str], pages: list[int],
             dpi: int, lang: str, psm: int, top: int = 40) -> str:
    """Seconda lettura (tesseract) vs layer OCR dell'estratto, PAGINA per PAGINA.

    Nessun allineamento: si confrontano le due letture della STESSA pagina
    (il layer dell'estratto contiene i marker `<!-- page N -->`).
    """
    rows = []
    for pno in sorted(pages):
        ref = set(tokens(estratto_pages.get(pno + 1, ""))) - STOP
        ocr = set(tokens(ocr_page(doc, pno, dpi, lang, psm))) - STOP
        if not ref and not ocr:
            continue
        only_ocr = sorted(t for t in (ocr - ref) if len(t) >= 5)
        only_ref = sorted(t for t in (ref - ocr) if len(t) >= 5)
        div = len(only_ocr) + len(only_ref)
        union = len(ocr | ref) or 1
        ratio = 1.0 - div / union
        rows.append((ratio, pno + 1, div, len(ocr), len(ref), only_ocr, only_ref))

    valid = [r for r in rows if r[3] > 0 and r[4] > 0]
    low = [r for r in valid if r[0] < 0.5]
    avg_ratio = sum(r[0] for r in valid) / max(1, len(valid))
    out = ["# Cross-check OCR (CPU) — report completo\n"]
    out.append(f"- Pagine confrontate: {len(rows)} (con testo da entrambe le letture: {len(valid)})")
    out.append(f"- Similarità media tesseract↔layer: {avg_ratio:.3f}")
    out.append(f"- Pagine a bassa concordanza (<0.5): {len(low)}")
    out.append("\n## Pagine a bassa concordanza (da rivedere: figure, degradate, o errori)\n")
    for ratio, pg, div, no, nr, oo, orf in sorted(valid, key=lambda r: r[0])[:top]:
        out.append(f"\n### pagina {pg} (similarità {ratio:.2f}, divergenze {div}; {no} vs {nr} token)\n")
        out.append(f"- solo in tesseract: {', '.join(oo[:25]) or '—'}\n")
        out.append(f"- solo nel layer: {', '.join(orf[:25]) or '—'}\n")
    return "\n".join(out)


STOP = {"della", "delle", "degli", "dello", "nella", "nelle", "negli", "nello", "questo",
        "questa", "questi", "queste", "sono", "essere", "come", "anche", "loro", "suo",
        "sua", "suoi", "sue", "che", "non", "per", "con", "una", "uno", "gli", "del",
        "dei", "dal", "dai", "alla", "alle", "allo", "agli", "più", "già", "tra", "fra",
        "sul", "sui", "sullo", "sulla", "sulle", "sugli", "dell", "nell"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Cross-check OCR CPU (tesseract).")
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--current", type=Path, default=None,
                    help="markdown di riferimento (per mostrare il testo attuale in modalità fragments)")
    ap.add_argument("--mode", choices=["fragments", "full"], default="fragments")
    ap.add_argument("--fragments", type=Path, default=None, help="JSON lista frammenti (modalità fragments)")
    ap.add_argument("--pages", default="", help="pagine 1-based, es. '1-20,44' (modalità full)")
    ap.add_argument("--estratto", type=Path, default=None,
                    help="estratto con marker '<!-- page N -->' (ponte pagina→testo, consigliato in full)")
    ap.add_argument("--dpi", type=int, default=400)
    ap.add_argument("--lang", default="ita")
    ap.add_argument("--psm", type=int, default=6)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if subprocess.run(["which", "tesseract"], capture_output=True).returncode != 0:
        sys.exit("Errore: tesseract non installato.")
    doc = pymupdf.open(args.pdf)
    current = args.current.read_text(encoding="utf-8") if args.current else ""

    if args.mode == "fragments":
        if not args.fragments:
            sys.exit("Errore: --fragments richiesto in modalità fragments.")
        frags = json.loads(args.fragments.read_text(encoding="utf-8"))
        report = run_fragments(doc, current, frags, args.dpi, args.lang, args.psm)
    else:
        if not args.estratto:
            sys.exit("Errore: modalità full richiede --estratto (markdown con marker '<!-- page N -->').")
        estratto_pages = load_estratto_pages(args.estratto)
        pages = parse_pages(args.pages, len(doc))
        report = run_full(doc, estratto_pages, pages, args.dpi, args.lang, args.psm)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    doc.close()
    print(f"Report → {args.out}")


if __name__ == "__main__":
    main()

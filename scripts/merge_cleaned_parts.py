#!/usr/bin/env python3
r"""
merge_cleaned_parts.py — Unisce in un unico markdown i blocchi di testo già
ripuliti dall'OCR (es. output di `prompts/normalize_ocr.md` eseguito su blocchi
paralleli), producendo il file di studio finale.

Fa:
  - concatena i blocchi nell'ordine dato (o alfabetico);
  - raccoglie le sezioni `## Da verificare` in un'unica appendice finale;
  - raccoglie le definizioni `[^n]: …` in un'unica sezione `## Note` finale
    (riportando i riferimenti `[^n]` nel corpo al posto giusto);
  - aggiunge frontespizio e indice con ancore **compatibili con pandoc**
    (stesso algoritmo di `auto_identifiers`, così i link interni funzionano
    anche nel PDF esportato con `export_pdf.py`).

Esempi:
  python scripts/merge_cleaned_parts.py \
      --dir "books/MioLibro/puliti" \
      --out "books/MioLibro.md" \
      --title "Elementi di Management Aziendale" \
      --authors "Pierluigi Lizza, Paola Giansante" \
      --note "Testo ricavato da re-OCR (tesseract) con correzione dei refusi."

L'ordine è alfabetico; per forzarlo, prefissa i file con `00`, `01`, … oppure
passa `--order` con l'elenco dei prefissi.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def pandoc_anchor(title: str) -> str:
    """Stesso algoritmo di `auto_identifiers` di pandoc (per link interni)."""
    s = re.sub(r"[^\w\s\-\.]", "", title.lower(), flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s)
    while s and not s[0].isalpha():
        s = s[1:]
    return s or "section"


def clean_part(t: str) -> str:
    # completa i titoli di capitolo senza sottotitolo: "## CAPITOLO Quarto"
    def fix_chap(m):
        return m.group(0)
    # demote heading che sono evidentemente frasi (titolo troppo lungo/segno di continuazione)
    def demote(m):
        title = m.group(2)
        if len(title) > 62 or title.rstrip().endswith(("-", ",", ";")):
            return title
        return m.group(0)
    t = re.sub(r"^(#{3,5}) (.+)$", demote, t, flags=re.M)
    # "64 Titolo" → "6.4 Titolo"
    t = re.sub(r"^(#{3,5}) (\d)([1-9]) ([\"“']?[A-ZÀ-Ý])", r"\1 \2.\3 \4", t, flags=re.M)
    return t.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Unisce blocchi puliti in un markdown finale.")
    ap.add_argument("--dir", type=Path, required=True, help="cartella dei blocchi puliti")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--authors", default=None)
    ap.add_argument("--note", default=None, help="nota in testa al documento (opzionale)")
    ap.add_argument("--order", nargs="*", default=None,
                    help="prefissi/nomi dei file nell'ordine desiderato")
    args = ap.parse_args()

    if not args.dir.is_dir():
        sys.exit(f"Errore: cartella non trovata: {args.dir}")

    def natkey(p: Path):
        m = re.match(r"(\d+)", p.name)
        return (0, int(m.group(1)), p.name) if m else (1, 0, p.name)

    files = sorted(args.dir.glob("*.md"), key=natkey)
    if args.order:
        def key(p: Path) -> int:
            for i, o in enumerate(args.order):
                if p.name.startswith(o):
                    return i
            return len(args.order)
        files = sorted(files, key=key)
    if not files:
        sys.exit(f"Errore: nessun .md in {args.dir}")

    notes: dict[int, str] = {}
    verify: list[str] = []
    texts: list[str] = []
    for f in files:
        t = f.read_text(encoding="utf-8")
        m = re.split(r"\n##\s+Da verificare\s*\n", t)
        if len(m) > 1:
            if m[1].strip():
                verify.append(f"**{f.name}**\n\n{m[1].strip()}")
            t = m[0]
        t = re.sub(r"^\[\^(\d+)\]:\s*(.*)$",
                   lambda mm: (notes.__setitem__(int(mm.group(1)), mm.group(2).rstrip())
                               or ""), t, flags=re.M)
        t = re.sub(r"\n---\n\n##\s+Note\s*\n", "\n", t)
        texts.append(clean_part(t))
    body = "\n\n".join(x for x in texts if x)

    toc = []
    for line in body.splitlines():
        m = re.match(r"^(#{2,3})\s+(.*)$", line)
        if not m:
            continue
        lvl, title = len(m.group(1)), m.group(2).strip()
        if not (title.upper().startswith(("CAPITOLO", "PARTE", "CHAPTER"))
                or re.match(r"^\d+(\.\d+)*[\.\s]", title)):
            continue
        if len(title) > 75:
            continue
        toc.append(f"{'  ' * (lvl - 2)}- [{title}](#{pandoc_anchor(title)})")

    head = []
    if args.title:
        head.append(f"# {args.title}\n")
    if args.authors:
        head.append(f"*{args.authors}*\n")
    if args.note:
        head.append("> " + args.note.replace("\n", "\n> ") + "\n")
    if toc:
        head.append("## Indice\n\n" + "\n".join(toc) + "\n")
    header = "\n".join(head) + "\n---\n\n" if head else ""

    tail = ""
    if notes:
        tail += ("\n\n---\n\n## Note\n\n"
                 + "\n\n".join(f"[^{n}]: {notes[n]}" for n in sorted(notes)))
    if verify:
        tail += ("\n\n---\n\n# Da verificare\n\n"
                 "> Punti in cui l'OCR era troppo degradato per una correzione "
                 "sicura.\n\n" + "\n\n".join(verify))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(header + body + tail + "\n", encoding="utf-8")
    words = len(re.sub(r"^\[\^\d+\]:.*$", "", body, flags=re.M).split())
    print(f"Output: {args.out}")
    print(f"  blocchi: {len(files)}  voci indice: {len(toc)}  note: {len(notes)}  "
          f"'Da verificare': {len(verify)}")
    print(f"  parole (corpo): {words:,}  caratteri: {len(args.out.read_text(encoding='utf-8')):,}")


if __name__ == "__main__":
    main()

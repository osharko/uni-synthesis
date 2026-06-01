#!/usr/bin/env python3
r"""
split_chapters.py — Divide un estratto markdown in un file per capitolo.

Strategie (in ordine di preferenza):
  1. --anchors  →  divide su righe esatte fornite dall'utente (più affidabile)
  2. --pattern  →  regex personalizzata (default: detection automatica titoli "Capitolo N", "CAPITOLO N", "Cap. N")
  3. --by-pages →  blocchi di N pagine (usa i marker <!-- page N --> inseriti da full_to_text/ocr_to_text)

Esempi:
  python scripts/split_chapters.py books/MioLibro/MioLibro\ -\ estratto.md
  python scripts/split_chapters.py books/MioLibro/MioLibro\ -\ estratto.md --pattern '^Capitolo\s+\d+'
  python scripts/split_chapters.py books/MioLibro/MioLibro\ -\ estratto.md --anchors anchors.txt
  python scripts/split_chapters.py books/MioLibro/MioLibro\ -\ estratto.md --by-pages 25

Output: nella stessa cartella dell'estratto, file "<libro> - cap_NN_<slug> - estratto.md".

Suggerimento: usa --dry-run per vedere i tagli prima di scrivere i file.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

DEFAULT_PATTERN = r"^\s*(?:CAPITOLO|Capitolo|CAP\.?|Cap\.?)\s+([IVXLCDM]+|\d+)\b[\s\.\-—:]*(.*)$"
PAGE_MARKER = re.compile(r"<!--\s*page\s+(\d+)\s*-->")


def slugify(text: str, maxlen: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "_", text)
    return text[:maxlen].strip("_") or "senza_titolo"


def roman_to_int(s: str) -> int | None:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    try:
        total, prev = 0, 0
        for c in reversed(s.upper()):
            v = vals[c]
            total += -v if v < prev else v
            prev = v
        return total
    except KeyError:
        return None


def split_by_pattern(text: str, pattern: str) -> list[tuple[int, str, str]]:
    """Restituisce lista di (numero, titolo, contenuto)."""
    regex = re.compile(pattern, re.MULTILINE)
    matches = list(regex.finditer(text))
    if not matches:
        return []

    chapters: list[tuple[int, str, str]] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        groups = m.groups()
        num_raw = groups[0] if groups else str(idx + 1)
        title = (groups[1] if len(groups) > 1 else "").strip() if groups else ""
        num = roman_to_int(num_raw) if num_raw and not num_raw.isdigit() else (
            int(num_raw) if num_raw and num_raw.isdigit() else idx + 1
        )
        chapters.append((num or idx + 1, title, body))
    return chapters


def split_by_pages(text: str, pages_per_chapter: int) -> list[tuple[int, str, str]]:
    parts = PAGE_MARKER.split(text)
    if len(parts) <= 1:
        sys.exit("Errore: nessun marker '<!-- page N -->' trovato; usa --pattern o --anchors.")
    # parts: [prefix, pageN, content, pageN, content, ...]
    pages: list[tuple[int, str]] = []
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ""
        pages.append((page_num, body))

    chapters: list[tuple[int, str, str]] = []
    for ci, start in enumerate(range(0, len(pages), pages_per_chapter), start=1):
        block = pages[start:start + pages_per_chapter]
        if not block:
            continue
        first_page, last_page = block[0][0], block[-1][0]
        body = "\n\n".join(f"<!-- page {p} -->\n\n{b.strip()}" for p, b in block)
        title = f"pp. {first_page}-{last_page}"
        chapters.append((ci, title, body))
    return chapters


def split_by_anchors(text: str, anchors: list[str]) -> list[tuple[int, str, str]]:
    """anchors è una lista di stringhe (titoli esatti) presenti nel testo."""
    positions = []
    for a in anchors:
        idx = text.find(a)
        if idx == -1:
            print(f"  ⚠ anchor non trovato: {a!r}", file=sys.stderr)
            continue
        positions.append((idx, a))
    positions.sort()
    if not positions:
        sys.exit("Errore: nessun anchor trovato nel testo.")
    chapters = []
    for i, (start, title) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chapters.append((i + 1, title.strip(), text[start:end].strip()))
    return chapters


def write_chapters(chapters: list[tuple[int, str, str]], base: Path, dry_run: bool) -> list[Path]:
    out_paths = []
    stem = base.stem.replace(" - estratto", "")
    parent = base.parent
    for num, title, body in chapters:
        slug = slugify(title) if title else f"cap_{num:02d}"
        fname = f"{stem} - cap_{num:02d}_{slug} - estratto.md"
        path = parent / fname
        out_paths.append(path)
        if dry_run:
            print(f"  [dry-run] cap_{num:02d}  {len(body):>7,} chars  →  {fname}"
                  + (f"   ({title[:60]})" if title else ""))
        else:
            path.write_text(body + "\n", encoding="utf-8")
    return out_paths


def main() -> None:
    ap = argparse.ArgumentParser(description="Divide un estratto markdown in capitoli.")
    ap.add_argument("estratto", type=Path, help="File markdown estratto")
    ap.add_argument("--pattern", default=DEFAULT_PATTERN,
                    help="Regex per detection titoli capitolo (default: 'Capitolo N')")
    ap.add_argument("--by-pages", type=int, default=0,
                    help="Spezza in blocchi di N pagine (fallback)")
    ap.add_argument("--anchors", type=Path, default=None,
                    help="File con un titolo esatto per riga (più affidabile di regex)")
    ap.add_argument("--dry-run", action="store_true", help="Mostra i tagli senza scrivere")
    args = ap.parse_args()

    if not args.estratto.exists():
        sys.exit(f"Errore: file non trovato: {args.estratto}")
    text = args.estratto.read_text(encoding="utf-8")

    if args.anchors:
        anchors = [l.strip() for l in args.anchors.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.startswith("#")]
        chapters = split_by_anchors(text, anchors)
        strategy = f"anchors ({len(anchors)} righe)"
    elif args.by_pages:
        chapters = split_by_pages(text, args.by_pages)
        strategy = f"pagine ({args.by_pages}/capitolo)"
    else:
        chapters = split_by_pattern(text, args.pattern)
        strategy = f"pattern {args.pattern!r}"
        if not chapters:
            sys.exit(f"Errore: nessun capitolo trovato col pattern. "
                     f"Prova --anchors o --by-pages N. Estratto: {args.estratto}")

    print(f"Strategia: {strategy}")
    print(f"Capitoli trovati: {len(chapters)}")
    write_chapters(chapters, args.estratto, args.dry_run)
    if not args.dry_run:
        print(f"Output in: {args.estratto.parent}")


if __name__ == "__main__":
    main()

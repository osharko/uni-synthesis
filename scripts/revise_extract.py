#!/usr/bin/env python3
r"""
revise_extract.py — Da un PDF a doppia pagina (con layer testo, già splittato in
pagine singole) produce UN UNICO markdown "rivisto":
  - rimuove i marker/righe di servizio: numeri di pagina, il "nome della pagina"
    (running header col titolo del libro/sezione), righe di rumore;
  - ricostruisce i paragrafi usando la rientranza della prima riga (x0);
  - toglie i trattini di sillabazione a fine riga (dehyphenation);
  - formatta la struttura per PARTI / CAPITOLI / SEZIONI.

Esempi:
  python scripts/revise_extract.py "books/Foucault/Foucault - split.pdf" \
      --out "Le parole e le cose.md"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import pymupdf  # PyMuPDF
except ImportError:
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        sys.exit("Errore: PyMuPDF mancante. Installa con: pip install PyMuPDF")

# --- geometria pagina (dal PDF splittato) ---
FOOTER_Y = 545.0        # sotto questa y: running header ("nome della pagina")
PAGENUM_Y = 500.0       # fascia numeri di pagina
INDENT_MIN = 8.0        # scostamento x0 che identifica l'inizio di un paragrafo
FOOTNOTE_GAP = 14.0     # salto verticale che separa il corpo dalle note
FOOTNOTE_MIN_Y = 455.0  # le note stanno nella fascia bassa della pagina

TITLE = "Le parole e le cose"
SUBTITLE = "Un'archeologia delle scienze umane"

# titolo normalizzato (upper, apostrofi uniformati) -> (livello, titolo pulito)
HEADINGS = {
    "PREFAZIONE": (2, "Prefazione"),
    "PARTE PRIMA": (2, "Parte prima"),
    "PARTE SECONDA": (2, "Parte seconda"),
    "LE DAMIGELLE D'ONORE": (3, "Le damigelle d'onore"),
    "LA PROSA DEL MONDO": (3, "La prosa del mondo"),
    "RAPPRESENTARE": (3, "Rappresentare"),
    "PARLARE": (3, "Parlare"),
    "CLASSIFICARE": (3, "Classificare"),
    "SCAMBIARE": (3, "Scambiare"),
    "I LIMITI DELLA RAPPRESENTAZIONE": (3, "I limiti della rappresentazione"),
    "1 LIMITI DELLA RAPPRESENTAZIONE": (3, "I limiti della rappresentazione"),
    "LAVORO, VITA, LINGUAGGIO": (3, "Lavoro, vita, linguaggio"),
    "L'UOMO E I SUOI DUPLICATI": (3, "L'uomo e i suoi duplicati"),
    "L'UOMAO E I SUOI DUPLICATI": (3, "L'uomo e i suoi duplicati"),
    "LE SCIENZE UMANE": (3, "Le scienze umane"),
    "LE RCIENZE UMANE": (3, "Le scienze umane"),
    "APPENDICE": (2, "Appendice"),
}

PAGENUM_RE = re.compile(r"^[\dIVXLCDMivxlcdm\s.,:;'’‘\-]{1,7}$")
SECTION_RE = re.compile(r"^[0-9ÎS DIl]{1,3}[.,]\s+\S")
GARBAGE_RE = re.compile(r"[\\|_~^<>]|\u00c3[\u0080-\u00bf]")


def norm(s: str) -> str:
    return s.strip().upper().replace("’", "'").replace("‘", "'")


def is_upper_line(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    return sum(c.isupper() for c in letters) / len(letters) >= 0.85


def clean_paragraph(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\s+([,;:\.\!\?»])", r"\1", s)
    s = re.sub(r"(«)\s+", r"\1", s)
    s = re.sub(r"\s-\s", " — ", s)   # trattino lungo (OCR: " - ")
    return s


def join_line(para: str, nxt: str) -> str:
    """Unisce una riga di continuazione, togliendo il trattino di sillabazione."""
    p = para.rstrip()
    attached = p.endswith(("-", "‐", "\u00ad")) and len(p) > 1 and not p[-2].isspace()
    if attached:
        base = p[:-1]
        m = re.match(r"^[-\u2010\u00ad]\s*", nxt)
        if m:
            return base + "-" + nxt[m.end():]
        return base + nxt
    return p + " " + nxt


def page_lines(page) -> list[dict]:
    raw = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            t = "".join(sp["text"] for sp in l["spans"]).strip()
            if not t:
                continue
            raw.append({
                "text": t,
                "x0": l["bbox"][0],
                "y0": l["bbox"][1],
                "size": max(sp["size"] for sp in l["spans"]),
            })
    # unisce i segmenti che stanno sulla stessa riga (stesso y, x crescenti)
    raw.sort(key=lambda d: (round(d["y0"], 1), d["x0"]))
    out: list[dict] = []
    for ln in raw:
        if out and abs(ln["y0"] - out[-1]["y0"]) < 4.0:
            prev = out[-1]
            prev["text"] = (prev["text"].rstrip() + " " + ln["text"].lstrip()).strip()
            prev["size"] = max(prev["size"], ln["size"])
        else:
            out.append(dict(ln))
    return out


def build(pdf_path: Path) -> list[str]:
    doc = pymupdf.open(pdf_path)
    out: list[str] = []            # blocchi markdown
    para = ""                      # paragrafo in costruzione
    note_buf = ""                  # nota della pagina in corso
    pending_notes: list[str] = []  # note da emettere dopo il paragrafo corrente
    started = False                # salta il front-matter prima del primo titolo

    def flush():
        nonlocal para, pending_notes
        if para.strip():
            out.append(clean_paragraph(para))
            para = ""
        for nt in pending_notes:
            out.append(("Q", nt))
        pending_notes = []

    stop = False
    for page in doc:
        if stop:
            break
        lines = page_lines(page)
        # filtra righe di servizio
        body = []
        for ln in lines:
            if ln["y0"] >= FOOTER_Y:
                continue
            if ln["y0"] >= PAGENUM_Y and PAGENUM_RE.match(ln["text"]):
                continue
            if GARBAGE_RE.search(ln["text"]) and not is_upper_line(ln["text"]):
                continue
            # etichette/rumore di figure: maiuscolo, corto, senza senso di frase
            # (ma non scartare titoli di capitolo/parte né la parola INDICE)
            if (is_upper_line(ln["text"]) and len(ln["text"]) <= 12
                    and " " not in ln["text"].strip()
                    and norm(ln["text"]) not in HEADINGS and norm(ln["text"]) != "INDICE"):
                continue
            body.append(ln)
        if not body:
            continue

        left = min(ln["x0"] for ln in body)

        # individua l'eventuale regione delle note a piè di pagina (in fondo,
        # preceduta da un salto verticale più grande del normale)
        foot_from = len(body)
        for idx in range(1, len(body)):
            if (body[idx]["y0"] - body[idx - 1]["y0"]) > FOOTNOTE_GAP \
                    and body[idx]["y0"] > FOOTNOTE_MIN_Y:
                foot_from = idx
                break

        for idx, ln in enumerate(body):
            t = ln["text"]
            n = norm(t)
            if n == "INDICE":          # fine del corpo: l'indice si omette
                stop = True
                break
            # 1) titolo di capitolo/parte
            if n in HEADINGS:
                flush()
                lvl, title = HEADINGS[n]
                out.append(("H", lvl, title))
                started = True
                continue
            if not started:
                continue               # front-matter: scarta finché non c'è un titolo
            # 2) intestazione di sezione (maiuscolo, numerata)
            if is_upper_line(t) and len(t) >= 6 and SECTION_RE.match(t) and not PAGENUM_RE.match(t):
                flush()
                out.append(("H", 4, t.rstrip()))
                continue

            if idx >= foot_from:        # nota: accantonata, non spezza il corpo
                note_buf = (note_buf + " " + t) if note_buf else t
                continue
            if (ln["x0"] - left) > INDENT_MIN:
                flush()
            para = join_line(para, t) if para else t

        # fine pagina: accumula le note e chiudi il corpo se è concluso
        if note_buf.strip():
            pending_notes.append(clean_paragraph(note_buf))
            note_buf = ""
        if not para.strip() or para.rstrip().endswith((".", "»", "!", "?", ":")):
            flush()

    flush()
    doc.close()
    return out


def render(blocks: list) -> str:
    parts = [f"# {TITLE}", "", f"*{SUBTITLE}* — Michel Foucault", "", "---", ""]
    for b in blocks:
        if isinstance(b, tuple) and b and b[0] == "H":
            lvl, title = b[1], b[2]
            parts.append("#" * lvl + " " + title)
            parts.append("")
        elif isinstance(b, tuple) and b and b[0] == "Q":
            parts.append("> " + b[1])
            parts.append("")
        else:
            parts.append(b)
            parts.append("")
    return "\n".join(parts).strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Revisiona un estratto splittato in un unico markdown.")
    ap.add_argument("pdf", type=Path, help="PDF splittato (pagine singole, con layer testo)")
    ap.add_argument("--out", type=Path, required=True, help="Markdown di output")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"Errore: PDF non trovato: {args.pdf}")

    blocks = build(args.pdf)
    md = render(blocks)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    n_head = sum(1 for b in blocks if isinstance(b, tuple) and b[0] == "H")
    n_note = sum(1 for b in blocks if isinstance(b, tuple) and b[0] == "Q")
    print(f"Output: {args.out}")
    print(f"  Paragrafi: {len(blocks) - n_head - n_note}   Intestazioni: {n_head}   "
          f"Note: {n_note}   Caratteri: {len(md):,}")


if __name__ == "__main__":
    main()

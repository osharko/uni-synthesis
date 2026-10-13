#!/usr/bin/env python3
r"""
ocr_to_markdown.py — Da PDF scannerizzato (spesso con OCR già presente ma
inutilizzabile) a markdown strutturato, con **re-OCR in CPU** (tesseract).

Nasce dal caso "CamScanner + OCRmyPDF": su un volume con **pagine doppie**
(spread) l'OCR originale legge le due pagine come un'unica colonna, producendo
righe interlacciate e testo illeggibile. Inoltre la risoluzione nativa (~150
dpi) è spesso troppo bassa perché tesseract lavori bene. La soluzione:

  1. ogni pagina è divisa in **unità**: la pagina intera, oppure le due metà
     se la pagina è in orizzontale (spread a due facciate);
  2. si estrae l'**immagine incorporata** (spesso 1:1 con la pagina, molto più
     veloce di un render) e la si ingrandisce (--upscale, default 2×);
  3. OCR tesseract (`-l <lang>`, TSV) in parallelo, con **cache** su disco;
  4. strutturazione: rimozione di running header/footer (rilevati per
     **ripetizione** sulle pagine + pattern), ricostruzione dei paragrafi
     (rientro di prima riga + riga corta), de-sillabazione, titoli di
     capitolo/sezione, note a piè di pagina numerate → note markdown `[^n]`.

Il testo prodotto è una **trascrizione fedele** (nessuna sintesi): va poi
ripulito dai refusi con `prompts/normalize_ocr.md` (un blocco per volta).

Esempi:
  python scripts/ocr_to_markdown.py --pdf books/MioLibro.pdf \
      --out "books/MioLibro/MioLibro - strutturato.md" \
      --config "books/MioLibro/_config.json"

Config JSON (tutte le chiavi opzionali):
  {
    "lang": "ita",
    "psm": 4,
    "upscale": 2,
    "skip_pages": [1, 2, 3, 4, 5],
    "running_head_re": "regex aggiuntiva per testatine",
    "chapters": [{"num": 1, "ordinal": "Primo",
                  "title": "Elementi propedeutici allo studio del management"}]
  }

Dipendenze: PyMuPDF, Pillow, tesseract + lingua (`tesseract-data-ita`).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pymupdf
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        sys.exit("Errore: PyMuPDF mancante. Installa con: pip install PyMuPDF")

try:
    from PIL import Image
except ImportError:
    sys.exit("Errore: Pillow mancante. Installa con: pip install Pillow")

# --------------------------------------------------------------- geometria
HEADER_ZONE = 74.0          # fascia alta (punti) per le pagine singole
HEADER_ZONE_LAND = 62.0     # fascia alta per gli spread
FOOTER_ZONE = 42.0          # fascia bassa (watermark/piè di pagina)
INDENT_MIN = 9.0            # rientro che apre un paragrafo
SHORT_LINE = 28.0            # riga "corta" ⇒ probabile fine paragrafo
SAME_LINE_Y = 4.0
FOOTNOTE_GAP = 12.0
RUNHEAD_MIN_PAGES = 3       # una riga ripetuta su ≥ N pagine = testatina

# --------------------------------------------------------------- pattern
PAGENUM_RE = re.compile(r"^[\s.,:;'’‘\-|_\W]*\d{1,3}[\s.,:;'’‘\-|_\W]*$")
FOOTER_RE = re.compile(r"Cams\s*can\w*|Cam\s*\$?\s*[Ss]?canner|Scanned\s*with",
                       re.I)
ORDINALS = {"PRIMO": 1, "SECONDO": 2, "TERZO": 3, "QUARTO": 4, "QUINTO": 5,
            "SESTO": 6, "SETTIMO": 7}
ORDINAL_RE = re.compile(
    r"\b(PRIMO|SECONDO|TERZO|QUARTO|QUINTO|SESTO|SETTIMO|PRIM\w*|SECOND\w*|"
    r"TERZ\w*|QUART\w*|QUINT\w*|SEST\w*|SETTIM\w*)\b")
CHAPTER_RE = re.compile(r"^[^\w]{0,3}(?:CAPITOLO|CAP\.?|PARTE|CHAPTER)\s+[IVXLCDM\d\w]{1,12}$",
                        re.I)
SECTION_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-ZÀ-Ý][^\n]{2,70})$")
FOOTNOTE_START_RE = re.compile(r"^(\d{1,3})\s*[\.\)]?\s*(.*)$")
ALNUM_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]")
CURA_RE = re.compile(r"^\(?\s*a cura di\b", re.I)

DEFAULT_CONFIG = {"lang": "ita", "psm": 4, "upscale": 2, "skip_pages": [],
                  "running_head_re": None, "chapters": []}


def norm(s: str) -> str:
    return (s.replace("’", "'").replace("‘", "'").replace("“", '"')
            .replace("”", '"').strip())


def _alnum_lower(s: str) -> str:
    return re.sub(r"[^a-zà-ÿ ]", "", norm(s).lower()).strip()


def ordinal_name(n: int) -> str:
    for k, v in ORDINALS.items():
        if v == n:
            return k.capitalize()
    return str(n)


# ------------------------------------------------------------------ OCR (CPU)
def page_units(pdf: Path) -> list[dict]:
    """Una pagina → 1 unità (pagina intera) o 2 (metà sinistra/destra)."""
    doc = pymupdf.open(pdf)
    units = []
    for pno in range(len(doc)):
        r = doc[pno].rect
        if r.width > r.height:                       # spread: due facciate
            mid = r.x0 + r.width / 2
            for col, clip in enumerate((pymupdf.Rect(r.x0, r.y0, mid, r.y1),
                                        pymupdf.Rect(mid, r.y0, r.x1, r.y1))):
                units.append({"page": pno + 1, "col": col, "rect": clip,
                              "portrait": False, "height": clip.height})
        else:
            units.append({"page": pno + 1, "col": 0, "rect": pymupdf.Rect(r),
                          "portrait": True, "height": r.height})
    doc.close()
    return units


def unit_image(doc, page, rect, upscale: float):
    """Immagine della porzione `rect` (immagine incorporata se 1:1, altrimenti
    render) ingrandita di `upscale`. Ritorna (PIL.Image, scale pt/pixel)."""
    imgs = page.get_images(full=True)
    if len(imgs) == 1:
        try:
            info = doc.extract_image(imgs[0][0])
            im = Image.open(io.BytesIO(info["image"])).convert("L")
            r = page.rect
            W, H = im.size
            box = (int(round((rect.x0 - r.x0) / r.width * W)),
                   int(round((rect.y0 - r.y0) / r.height * H)),
                   int(round((rect.x1 - r.x0) / r.width * W)),
                   int(round((rect.y1 - r.y0) / r.height * H)))
            im = im.crop(box)
            if upscale and upscale != 1:
                im = im.resize((int(im.width * upscale),
                                int(im.height * upscale)), Image.LANCZOS)
            return im, rect.width / im.width
        except Exception:
            pass
    dpi = 200 * (upscale or 1)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), clip=rect)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), 72.0 / dpi


def _tsv_lines(tsv: str, scale: float) -> list[dict]:
    rows = [l.split("\t") for l in tsv.splitlines()[1:] if l.count("\t") >= 11]
    groups: dict[tuple, list] = {}
    for r in rows:
        if r[0] == "5" and r[11].strip():
            groups.setdefault((r[2], r[3], r[4]), []).append(r)
    lines = []
    for key in sorted(groups, key=lambda k: (int(k[0]), int(k[2]))):
        ws = sorted(groups[key], key=lambda r: int(r[6]))
        left = min(int(r[6]) for r in ws)
        top = min(int(r[7]) for r in ws)
        right = max(int(r[6]) + int(r[8]) for r in ws)
        bottom = max(int(r[7]) + int(r[9]) for r in ws)
        lines.append({"text": " ".join(r[11].strip() for r in ws),
                      "x0": left * scale, "x1": right * scale,
                      "y0": top * scale, "y1": bottom * scale,
                      "size": (bottom - top) * scale})
    return lines


def ocr_units(pdf: Path, cfg: dict, cache_path: Path, workers: int = 0) -> list[dict]:
    units = page_units(pdf)
    cache: dict[str, list] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    todo = [u for u in units if f"{u['page']}:{u['col']}" not in cache]
    if todo:
        doc = pymupdf.open(pdf)
        tmp = Path(tempfile.mkdtemp(prefix="ocrmd_"))
        jobs = []
        for u in todo:
            try:
                im, scale = unit_image(doc, doc[u["page"] - 1], u["rect"],
                                       cfg.get("upscale", 2))
            except Exception as exc:  # pragma: no cover
                print(f"\n  render fallito {u['page']}:{u['col']}: {exc}",
                      file=sys.stderr)
                continue
            img = tmp / f"{u['page']:04d}_{u['col']}.jpg"
            im.save(img, "JPEG", quality=92)
            jobs.append((f"{u['page']}:{u['col']}", img, scale))
        doc.close()
        nw = workers or max(1, min(8, os.cpu_count() or 4))
        env = dict(os.environ, OMP_THREAD_LIMIT="1")
        lang, psm = cfg.get("lang", "ita"), str(cfg.get("psm", 4))

        def run(job):
            key, img, scale = job
            try:
                res = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", lang, "--psm", psm, "tsv"],
                    capture_output=True, text=True, timeout=180, env=env)
                return key, _tsv_lines(res.stdout, scale)
            except Exception as exc:  # pragma: no cover
                print(f"\n  OCR fallito {key}: {exc}", file=sys.stderr)
                return key, []

        done = 0
        with cf.ThreadPoolExecutor(max_workers=nw) as ex:
            for key, lines in ex.map(run, jobs):
                cache[key] = lines
                done += 1
                print(f"\r  OCR {done}/{len(jobs)} unità", end="", flush=True)
                if done % 20 == 0:
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False),
                                          encoding="utf-8")
        print()
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(tmp, ignore_errors=True)
    for u in units:
        u["lines"] = cache.get(f"{u['page']}:{u['col']}", [])
    return units


# ------------------------------------------------------ running head/footer
def detect_running_heads(units: list[dict], cfg: dict) -> tuple[set[str], set[str]]:
    """Righe che ricorrono in testa/piè pagina su più pagine = testatina/piè."""
    heads: dict[str, set[int]] = {}
    feet: dict[str, set[int]] = {}
    for u in units:
        zone = (HEADER_ZONE if u["portrait"] else HEADER_ZONE_LAND)
        for ln in u["lines"]:
            key = _alnum_lower(ln["text"])
            if len(key) < 4:
                continue
            if ln["y0"] <= zone:
                heads.setdefault(key, set()).add(u["page"])
            elif ln["y0"] >= u["height"] - FOOTER_ZONE:
                feet.setdefault(key, set()).add(u["page"])
    minp = cfg.get("runhead_min_pages", RUNHEAD_MIN_PAGES)
    return ({k for k, v in heads.items() if len(v) >= minp},
            {k for k, v in feet.items() if len(v) >= minp})


# ------------------------------------------------------------- strutturazione
def is_noise(t: str) -> bool:
    t = t.strip()
    return not t or (len(t) <= 30 and sum(c.isalnum() for c in t) < 0.45 * len(t))


def clean_para(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\s+([,;:\.\!\?»])", r"\1", s)
    s = re.sub(r"«\s+", "«", s)
    s = re.sub(r"\s+»", "»", s)
    return re.sub(r"^[#|_~^*=\\ ]+", "", s)


def join_line(para: str, nxt: str) -> str:
    p = para.rstrip()
    if p.endswith(("-", "‐", "\u00ad")) and len(p) > 1 and not p[-2].isspace():
        return p[:-1] + nxt.lstrip()
    return p + " " + nxt


def structure(units: list[dict], cfg: dict) -> list[dict]:
    chapters = {c["num"]: c for c in cfg.get("chapters", [])}
    title_to_num = {_alnum_lower(c["title"]): c["num"] for c in cfg.get("chapters", [])
                    if c.get("title")}
    heads, feet = detect_running_heads(units, cfg)
    extra_re = re.compile(cfg["running_head_re"], re.I) if cfg.get("running_head_re") else None
    skip_pages = set(cfg.get("skip_pages", []))

    def looks_repeat(t: str) -> bool:
        k = _alnum_lower(t)
        return k in heads or k in feet

    def chapter_of(t: str) -> int | None:
        n = _alnum_lower(t)
        if 12 <= len(n) <= 55:
            for tn, num in title_to_num.items():
                words = n.split()
                n1 = " ".join(words[1:]) if len(words) > 1 else n
                tw = tn.split()
                tn1 = " ".join(tw[1:]) if len(tw) > 1 else tn
                if n == tn or (n1 == tn1 and len(n1) >= 12) \
                        or (tn.startswith(n) and len(n) >= 0.4 * len(tn)):
                    return num
        m = ORDINAL_RE.search(t.upper())
        if m and "TOLO" in t.upper() and len(t) <= 34:
            w = m.group(1)
            for k in ORDINALS:
                if w == k or w.startswith(k[:4]):
                    return ORDINALS[k]
        if CHAPTER_RE.match(t.strip()):
            mc = re.search(r"\d+", t)
            if mc:
                return int(mc.group(0))
        return None

    def section_of(t: str) -> tuple[int, str] | None:
        m = SECTION_RE.match(t)
        if not m:
            return None
        num, title = m.group(1), m.group(2).strip()
        if t.rstrip().endswith(",") or sum(c.isalpha() for c in title) < 4:
            return None
        if re.search(r"op\.\s?cit|Cfr\.|pag\.|\bsegg\b|Ibidem", title, re.I):
            return None
        return min(3 + num.count("."), 5), f"{num} {title}"

    items: list[dict] = []
    next_note, last_chapter = 1, 0
    for u in units:
        if u["page"] in skip_pages:
            continue
        lines = sorted(u["lines"], key=lambda d: d["y0"])
        zone_top = HEADER_ZONE if u["portrait"] else HEADER_ZONE_LAND
        kept = []
        for ln in lines:
            t = ln["text"]
            in_top = ln["y0"] <= zone_top
            in_bottom = ln["y0"] >= u["height"] - FOOTER_ZONE
            if FOOTER_RE.search(t) or is_noise(t):
                continue
            if (in_top or in_bottom):
                if looks_repeat(t) or (extra_re and extra_re.search(t)):
                    continue
                if len(t) <= 4 or PAGENUM_RE.match(t):
                    continue
            kept.append(ln)
        lines = kept
        if not lines:
            continue
        if u["col"] == 0:
            items.append({"kind": "page", "n": u["page"]})

        def note_num(ln: dict) -> int | None:
            t = ln["text"]
            if not t or not t[0].isdigit():
                return None
            m = FOOTNOTE_START_RE.match(t)
            return int(m.group(1)) if (m and len(m.group(1)) <= 3) else None

        foot_from = len(lines)
        for i in range(1, len(lines)):
            gap = lines[i]["y0"] - lines[i - 1]["y0"]
            n = note_num(lines[i])
            if gap > FOOTNOTE_GAP and lines[i]["y0"] > u["height"] * 0.55 \
                    and n is not None and next_note - 2 <= n <= next_note + 20:
                foot_from = i
                break
        body = lines[:foot_from]
        left = min((ln["x0"] for ln in body), default=0.0)
        right = max((ln["x1"] for ln in body), default=0.0)

        para, prev_short = "", True
        notes: list[tuple[int, str]] = []
        pending, pending_num = "", 0
        skip_title_left, skip_flag = "", False
        for i, ln in enumerate(lines):
            t = ln["text"]
            if i >= foot_from:                      # note a piè di pagina
                n = note_num(ln)
                if n is not None and next_note - 2 <= n <= next_note + 20:
                    if pending:
                        notes.append((pending_num, pending))
                    pending_num, next_note = n, n + 1
                    pending = re.sub(r"^\d{1,3}\s*[\.\)]?\s*", "", t)
                else:
                    pending = (pending + " " + t).strip() if pending else t
                continue
            if skip_flag:                            # salta titolo + "(a cura di …)"
                tl = norm(t).lower()
                if CURA_RE.match(tl):
                    continue
                if skip_title_left and (skip_title_left.startswith(tl)
                                        or tl in skip_title_left):
                    skip_title_left = skip_title_left[len(tl):].lstrip()
                    skip_flag = bool(skip_title_left)
                    continue
                skip_flag = False
            h, ci = None, None
            top_area = ln["y0"] < u["height"] * 0.42
            if prev_short:
                if top_area:
                    ci = chapter_of(t)
                    if ci:
                        h = (2, f"CAPITOLO {ordinal_name(ci)}"
                               + (f" — {chapters[ci]['title']}"
                                  if chapters.get(ci, {}).get("title") else ""))
                if h is None:
                    h = section_of(t)
            if h:
                if h[0] == 2 and ci and ci <= last_chapter:
                    continue                             # testatina/duplicato
                if para:
                    items.append({"kind": "para", "text": clean_para(para)})
                    para = ""
                items.append({"kind": "heading", "level": h[0], "text": h[1]})
                prev_short = True
                if h[0] == 2 and ci:
                    last_chapter = ci
                    skip_title_left = _alnum_lower(chapters.get(ci, {}).get("title", ""))
                    skip_flag = bool(skip_title_left)
                continue
            if not ALNUM_RE.search(t) or (len(t) <= 2 and not t.rstrip().endswith(".")):
                prev_short = True
                continue
            if para and ((ln["x0"] - left) > INDENT_MIN or prev_short):
                items.append({"kind": "para", "text": clean_para(para)})
                para = ""
            para = join_line(para, t) if para else t
            prev_short = (right - ln["x1"]) > SHORT_LINE
        if para:
            items.append({"kind": "para", "text": clean_para(para)})
        if pending:
            notes.append((pending_num, pending))
        for num, nt in notes:
            items.append({"kind": "note", "n": num, "text": clean_para(nt)})
    return items


def render(items: list[dict]) -> str:
    out: list[str] = []
    note_defs: list[str] = []
    for it in items:
        if it["kind"] == "page":
            out.append(f"<!-- page {it['n']} -->")
        elif it["kind"] == "heading":
            out.append("#" * it["level"] + " " + it["text"])
        elif it["kind"] == "para":
            out.append(it["text"])
        elif it["kind"] == "note":
            for j in range(len(out) - 1, -1, -1):
                if out[j] and not out[j].startswith(("#", "<!--")):
                    out[j] += f"[^{it['n']}]"
                    break
            note_defs.append(f"[^{it['n']}]: {it['text']}")
    text = "\n\n".join(out)
    if note_defs:
        text += "\n\n---\n\n## Note\n\n" + "\n\n".join(note_defs)
    return text.strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="PDF scannerizzato → markdown (re-OCR CPU).")
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=None,
                    help="JSON con parametri libro-specifici (opzionale)")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--no-cache", action="store_true",
                    help="Ignora/azzera la cache OCR (<pdf>_-ocr_cache.json)")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"Errore: PDF non trovato: {args.pdf}")
    cfg = dict(DEFAULT_CONFIG)
    if args.config:
        if not args.config.exists():
            sys.exit(f"Errore: config non trovata: {args.config}")
        cfg.update(json.loads(args.config.read_text(encoding="utf-8")))

    cache = args.pdf.with_name(args.pdf.stem + "_-ocr_cache.json")
    if args.no_cache:
        cache.unlink(missing_ok=True)
    print("1/2  OCR (tesseract, CPU)…")
    units = ocr_units(args.pdf, cfg, cache, args.workers)
    print("2/2  strutturazione markdown…")
    items = structure(units, cfg)
    md = render(items)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    n_h = sum(1 for i in items if i["kind"] == "heading")
    n_p = sum(1 for i in items if i["kind"] == "para")
    n_n = sum(1 for i in items if i["kind"] == "note")
    print(f"Output: {args.out}")
    print(f"  Paragrafi: {n_p}   Heading: {n_h}   Note: {n_n}   Caratteri: {len(md):,}")


if __name__ == "__main__":
    main()

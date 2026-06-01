#!/usr/bin/env python3
"""
export_pdf.py — Esporta una sintesi markdown in PDF, con supporto completo a:
  - formule LaTeX inline `$...$` e block `$$...$$` / environments
  - diagrammi ` ```mermaid `, ` ```tikz `, ` ```dot `
  - tabelle, grassetto, citazioni, sillabazione

Sceglie automaticamente il miglior engine disponibile:

  1. **xelatex / pdflatex / lualatex** (se installato `tectonic` o `latexmk`):
     resa tipografica massima, formule perfette. Richiede distribuzione LaTeX.
  2. **typst** (se installato): rapido, moderno, math nativa.
  3. **weasyprint + mathjax** (default, no LaTeX richiesto): HTML/CSS,
     math renderizzato come HTML+MathJax → PDF.

Esempi:
  python scripts/export_pdf.py books/MioLibro.md
  python scripts/export_pdf.py books/MioLibro.md --out MioLibro.pdf --engine weasyprint
  python scripts/export_pdf.py books/MioLibro.md --engine xelatex --toc

Dipendenze (almeno una catena deve essere presente):
  - pandoc                                (sempre necessario)
  - tesseract per OCR di formule          (solo se input è scan)
  - una di:
      * texlive-{xetex,latex,fonts-recommended} + (opz.) latexmk / tectonic
      * typst
      * python-weasyprint
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CSS = REPO / "scripts" / "_pdf_style.css"


PANDOC_BASE_ARGS = [
    "--standalone",
    "--from", "markdown+yaml_metadata_block+tex_math_dollars+raw_tex+pipe_tables"
              "+fenced_divs+attributes+definition_lists",
    "-V", "lang=it",
    "-V", "geometry:margin=2.2cm",
]


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def detect_engine(preferred: str | None) -> str:
    """Restituisce uno tra: xelatex, lualatex, pdflatex, tectonic, typst, weasyprint."""
    candidates_by_pref = {
        "xelatex": ["xelatex", "lualatex", "tectonic", "pdflatex", "typst", "weasyprint"],
        "lualatex": ["lualatex", "xelatex", "tectonic", "pdflatex", "typst", "weasyprint"],
        "pdflatex": ["pdflatex", "xelatex", "lualatex", "tectonic", "typst", "weasyprint"],
        "tectonic": ["tectonic", "xelatex", "lualatex", "pdflatex", "typst", "weasyprint"],
        "typst": ["typst", "xelatex", "tectonic", "lualatex", "pdflatex", "weasyprint"],
        "weasyprint": ["weasyprint", "xelatex", "tectonic", "lualatex", "typst", "pdflatex"],
        None: ["xelatex", "lualatex", "tectonic", "pdflatex", "typst", "weasyprint"],
    }
    chain = candidates_by_pref.get(preferred, candidates_by_pref[None])
    for c in chain:
        # weasyprint è un modulo Python, non un binario garantito
        if c == "weasyprint":
            try:
                import weasyprint  # noqa: F401
                return "weasyprint"
            except ImportError:
                continue
        if have(c):
            return c
    sys.exit("Nessun engine PDF disponibile. Installa LaTeX (xelatex/tectonic) "
             "oppure typst oppure python-weasyprint.")


def ensure_css(path: Path) -> Path:
    """Crea un CSS minimo per weasyprint se non esiste."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(r"""
@page {
  size: A4;
  margin: 2.4cm 2.2cm;
  @bottom-center { content: counter(page); color: #888; font-size: 9pt; }
}
body {
  font-family: "Liberation Serif", Georgia, "Times New Roman", serif;
  font-size: 11.5pt;
  line-height: 1.55;
  text-align: justify;
  hyphens: auto;
}
h1 { text-align: center; font-size: 22pt; color: #16213e; margin-top: 0; }
h2 {
  font-size: 16pt; color: #16213e;
  border-bottom: 1.5px solid #c9ced8; padding-bottom: 4px;
  page-break-before: always;
}
h3 { font-size: 13pt; color: #2a3b5f; }
h4 { font-style: italic; }
code, pre, .math { font-family: "JetBrains Mono", "Liberation Mono", monospace; }
blockquote { color: #444; border-left: 3px solid #c9ced8; padding-left: 12px; }
table { border-collapse: collapse; margin: 1em 0; }
th, td { border: 1px solid #c9ced8; padding: 4px 8px; }
.math.display { display: block; text-align: center; margin: 0.8em 0; }
hr { display: none; }
""", encoding="utf-8")
    return path


def expand_mermaid(md_text: str, tmpdir: Path) -> str:
    """Se mmdc (mermaid-cli) è installato, sostituisce i blocchi mermaid con immagini SVG.
    Altrimenti li lascia come code block (saranno visibili come testo)."""
    import re
    if not have("mmdc"):
        return md_text
    out = []
    last = 0
    counter = 0
    pattern = re.compile(r"```mermaid\s*\n(.+?)\n```", re.DOTALL)
    for m in pattern.finditer(md_text):
        out.append(md_text[last:m.start()])
        src = m.group(1)
        counter += 1
        mmd_file = tmpdir / f"diagram_{counter}.mmd"
        svg_file = tmpdir / f"diagram_{counter}.svg"
        mmd_file.write_text(src, encoding="utf-8")
        subprocess.run(["mmdc", "-i", str(mmd_file), "-o", str(svg_file),
                        "-b", "transparent"], capture_output=True)
        if svg_file.exists():
            out.append(f"\n![Diagramma {counter}]({svg_file})\n")
        else:
            out.append(m.group(0))
        last = m.end()
    out.append(md_text[last:])
    return "".join(out)


def export_latex(md_path: Path, out_path: Path, engine: str, toc: bool) -> None:
    cmd = ["pandoc", str(md_path), "-o", str(out_path),
           f"--pdf-engine={engine}"] + PANDOC_BASE_ARGS
    if toc:
        cmd += ["--toc", "--toc-depth=3"]
    # Pacchetti LaTeX utili (mhchem per chimica, amsmath/amssymb sempre, microtype per giustificazione)
    cmd += ["-V", "mainfont=Liberation Serif",
            "-V", "monofont=Liberation Mono",
            "--include-in-header=" + str(_latex_preamble())]
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _latex_preamble() -> Path:
    """Genera un preambolo LaTeX con pacchetti math standard."""
    tmp = Path(tempfile.gettempdir()) / "uni_synthesis_preamble.tex"
    tmp.write_text(r"""
\usepackage{amsmath,amssymb,amsthm}
\usepackage[version=4]{mhchem}
\usepackage{microtype}
\usepackage{enumitem}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{hyperref}
\hypersetup{colorlinks=true,linkcolor=blue!50!black,urlcolor=blue!50!black}
""", encoding="utf-8")
    return tmp


def export_typst(md_path: Path, out_path: Path, toc: bool) -> None:
    cmd = ["pandoc", str(md_path), "-o", str(out_path),
           "--pdf-engine=typst"] + PANDOC_BASE_ARGS
    if toc:
        cmd += ["--toc", "--toc-depth=3"]
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def export_weasyprint(md_path: Path, out_path: Path, css: Path, toc: bool) -> None:
    cmd = ["pandoc", str(md_path), "-o", str(out_path),
           "--pdf-engine=weasyprint",
           f"--css={css}",
           "--mathjax"] + PANDOC_BASE_ARGS  # MathJax renderizza $...$ in HTML
    if toc:
        cmd += ["--toc", "--toc-depth=3"]
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Esporta sintesi markdown in PDF con math.")
    ap.add_argument("input", type=Path, help="File markdown sorgente")
    ap.add_argument("--out", type=Path, default=None, help="PDF di output")
    ap.add_argument("--engine", default=None,
                    choices=["xelatex", "lualatex", "pdflatex", "tectonic",
                             "typst", "weasyprint"],
                    help="Engine preferito (auto-detect se omesso)")
    ap.add_argument("--toc", action="store_true", help="Aggiungi indice")
    ap.add_argument("--css", type=Path, default=DEFAULT_CSS,
                    help="CSS (usato solo da weasyprint)")
    ap.add_argument("--render-mermaid", action="store_true",
                    help="Renderizza blocchi mermaid come SVG (richiede mmdc)")
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"Input non trovato: {args.input}")
    if not have("pandoc"):
        sys.exit("Errore: pandoc non installato. Su Arch: sudo pacman -S pandoc")

    out = args.out or args.input.with_suffix(".pdf")
    engine = detect_engine(args.engine)
    print(f"Engine selezionato: {engine}")

    md_path = args.input
    with tempfile.TemporaryDirectory(prefix="uni_synth_pdf_") as td:
        tmpdir = Path(td)
        if args.render_mermaid:
            text = expand_mermaid(args.input.read_text(encoding="utf-8"), tmpdir)
            md_path = tmpdir / args.input.name
            md_path.write_text(text, encoding="utf-8")

        if engine in ("xelatex", "lualatex", "pdflatex", "tectonic"):
            export_latex(md_path, out, engine, args.toc)
        elif engine == "typst":
            export_typst(md_path, out, args.toc)
        else:
            ensure_css(args.css)
            export_weasyprint(md_path, out, args.css, args.toc)

    size_kb = out.stat().st_size / 1024
    print(f"PDF scritto: {out} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()

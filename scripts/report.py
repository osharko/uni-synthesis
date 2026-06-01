#!/usr/bin/env python3
"""
report.py — Report di fine lavorazione per un libro processato dalla suite.

Raccoglie:
  - dimensione PDF originale
  - dimensione estratto (md, righe, parole, caratteri)
  - dimensione sintesi (idem)
  - capitoli presenti (sia file estratto sia file sintesi)
  - ratio di compressione
  - se presenti, integra metriche di quality_check (passa --qc-json)
  - tempo di lavorazione complessivo se invocato da pipeline.py

Esempio:
  python scripts/report.py --book "books/MioLibro" --out "books/MioLibro/REPORT.md"
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


def fmt_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def stats(text: str) -> dict:
    words = len(re.findall(r"\S+", text))
    lines = text.count("\n") + 1
    return {"chars": len(text), "words": words, "lines": lines}


def find_one(book_dir: Path, suffix: str) -> Path | None:
    matches = sorted(book_dir.glob(f"*{suffix}"))
    return matches[0] if matches else None


def collect(book_dir: Path) -> dict:
    book_dir = book_dir.resolve()
    name = book_dir.name
    parent = book_dir.parent

    pdf = next(iter(sorted(parent.glob(f"{name}.pdf"))), None) or next(
        iter(sorted(book_dir.glob("*.pdf"))), None
    )
    extracted = find_one(book_dir, " - estratto.md")
    synthesis = (parent / f"{name}.md")
    if not synthesis.exists():
        synthesis = find_one(book_dir, ".md") or None

    chapters_estratti = sorted(book_dir.glob("* - cap_*_*- estratto.md"))
    chapters_sintesi = sorted(book_dir.glob("* - cap*- sintesi.md"))

    info: dict = {"book_dir": str(book_dir), "name": name, "generated_at": datetime.now().isoformat(timespec="seconds")}

    if pdf and pdf.exists():
        info["pdf"] = {"path": str(pdf), "size_bytes": pdf.stat().st_size,
                       "size_human": fmt_size(pdf.stat().st_size)}
    if extracted and extracted.exists():
        info["extracted"] = {"path": str(extracted),
                             "size_bytes": extracted.stat().st_size,
                             **stats(extracted.read_text(encoding="utf-8"))}
    if synthesis and synthesis.exists() and synthesis != extracted:
        info["synthesis"] = {"path": str(synthesis),
                             "size_bytes": synthesis.stat().st_size,
                             **stats(synthesis.read_text(encoding="utf-8"))}

    info["chapters"] = {
        "extracted_count": len(chapters_estratti),
        "synthesis_count": len(chapters_sintesi),
        "extracted_files": [p.name for p in chapters_estratti],
        "synthesis_files": [p.name for p in chapters_sintesi],
    }

    if "extracted" in info and "synthesis" in info:
        info["ratio"] = round(info["extracted"]["words"] /
                              max(1, info["synthesis"]["words"]), 2)

    # Conteggio formule LaTeX e diagrammi nella sintesi (best-effort)
    if "synthesis" in info:
        s = (synthesis if synthesis and synthesis.exists() else None)
        if s:
            text = s.read_text(encoding="utf-8")
            inline = len(re.findall(r"(?<!\$)\$(?!\$)[^\$\n]{2,400}?(?<!\$)\$(?!\$)", text))
            block = len(re.findall(r"\$\$[^\$]{2,2000}?\$\$", text, re.DOTALL))
            env = len(re.findall(r"\\begin\{(?:equation|align|gather|multline|cases|"
                                 r"[bpvBPV]?matrix)\*?\}", text))
            diagrams = len(re.findall(r"```(?:mermaid|tikz|dot|plantuml)\b", text))
            info["math_diagrams"] = {
                "latex_inline": inline,
                "latex_block": block + env,
                "diagrams": diagrams,
            }

    return info


def render(info: dict, qc: dict | None, duration_s: float | None) -> str:
    lines = [
        f"# Report di lavorazione — {info['name']}",
        "",
        f"_Generato: {info['generated_at']}_",
        "",
        "## File principali",
        "",
    ]
    rows = []
    if "pdf" in info:
        rows.append(("PDF originale", info["pdf"]["path"], info["pdf"]["size_human"]))
    if "extracted" in info:
        ext = info["extracted"]
        rows.append(("Estratto markdown", ext["path"],
                     f"{fmt_size(ext['size_bytes'])} · {ext['words']:,} parole · "
                     f"{ext['lines']:,} righe"))
    if "synthesis" in info:
        syn = info["synthesis"]
        rows.append(("Sintesi amalgama", syn["path"],
                     f"{fmt_size(syn['size_bytes'])} · {syn['words']:,} parole · "
                     f"{syn['lines']:,} righe"))
    if rows:
        lines += ["| Tipo | Path | Dimensione |", "|---|---|---|"]
        for t, p, s in rows:
            lines.append(f"| {t} | `{p}` | {s} |")
        lines.append("")

    if "ratio" in info:
        lines += [f"**Ratio di compressione:** 1/{info['ratio']}  "
                  f"(target ideale: 1/5 – 1/8)", ""]

    if "math_diagrams" in info:
        md = info["math_diagrams"]
        if md["latex_inline"] + md["latex_block"] + md["diagrams"] > 0:
            lines += [
                "## Notazione tecnica preservata",
                "",
                f"- Formule LaTeX inline (`$…$`): **{md['latex_inline']}**",
                f"- Formule LaTeX block (`$$…$$` / environments): **{md['latex_block']}**",
                f"- Diagrammi (mermaid/tikz): **{md['diagrams']}**",
                "",
            ]

    ch = info["chapters"]
    lines += [
        "## Capitoli",
        "",
        f"- Capitoli estratti: **{ch['extracted_count']}**",
        f"- Capitoli sintetizzati: **{ch['synthesis_count']}**",
        "",
    ]
    if ch["extracted_count"] != ch["synthesis_count"]:
        diff = ch["extracted_count"] - ch["synthesis_count"]
        lines.append(f"⚠️ **Disallineamento di {diff} capitoli** — verifica.\n")

    if qc:
        cov = qc["coverage"]
        lines += [
            "## Quality check (deterministico)",
            "",
            f"- Score complessivo: **{qc['score']:.1%}**",
            f"- Esito: {'✅ PASSED' if qc['passed'] else '❌ FAILED'}",
            f"- Ratio rilevato: 1/{qc['ratio']:.2f} (target {qc['ratio_target']})",
            "",
            "| Aspetto | Copertura |",
            "|---|---:|",
            f"| Keyword (top-50) | {cov['keywords']:.1%} |",
            f"| Nomi propri | {cov['proper_names']:.1%} |",
            f"| Citazioni letterali | {cov['quotes']:.1%} |",
            f"| Riferimenti bibliografici | {cov['bib_refs']:.1%} |",
            f"| Capitoli | {cov['chapters']:.1%} |",
            f"| Anni/date | {cov['years']:.1%} |",
            "",
        ]
        miss_chap = qc["missing"]["chapters"]
        if miss_chap:
            lines += [f"**Capitoli mancanti nella sintesi:** {', '.join(miss_chap)}", ""]

    if duration_s is not None:
        h, rem = divmod(int(duration_s), 3600)
        m, s = divmod(rem, 60)
        lines += [f"## Tempo di lavorazione", "",
                  f"{h}h {m}m {s}s ({duration_s:.0f} secondi)", ""]

    if ch["synthesis_files"]:
        lines += ["## File sintesi per capitolo", ""]
        for f in ch["synthesis_files"]:
            lines.append(f"- `{f}`")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Report di fine lavorazione.")
    ap.add_argument("--book", required=True, type=Path,
                    help="Cartella del libro (es. books/MioLibro)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Path del report (default: <book>/REPORT.md)")
    ap.add_argument("--qc-json", type=Path, default=None,
                    help="Integra metriche da output JSON di quality_check.py")
    ap.add_argument("--duration", type=float, default=None,
                    help="Durata lavorazione in secondi")
    args = ap.parse_args()

    if not args.book.exists() or not args.book.is_dir():
        raise SystemExit(f"Errore: cartella libro non trovata: {args.book}")

    info = collect(args.book)
    qc = json.loads(args.qc_json.read_text(encoding="utf-8")) if args.qc_json else None
    text = render(info, qc, args.duration)
    out = args.out or (args.book / "REPORT.md")
    out.write_text(text, encoding="utf-8")
    print(f"Report scritto: {out}")
    print()
    print(text)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
pipeline.py — Orchestratore end-to-end della suite uni-synthesis.

Fa, in sequenza:
  1. Estrazione testo (full_to_text.py se --native, ocr_to_text.py se --scan)
  2. Split capitoli (split_chapters.py)
  3. Stop e attesa: gli agenti AI (Claude/opencode/altro) producono le sintesi
     in books/<libro>/<libro> - capNN - sintesi.md + l'amalgama books/<libro>.md
  4. (su comando --resume) quality_check.py + report.py

Esempi:
  # passo 1: dal PDF al set di capitoli pronti per gli agenti
  python scripts/pipeline.py prepare books/MioLibro.pdf --native
  python scripts/pipeline.py prepare books/Scan.pdf --scan

  # ... ora gli agenti AI producono le sintesi (vedi prompts/) ...

  # passo 2: a sintesi pronta, esegui QC + report
  python scripts/pipeline.py finalize books/MioLibro

  # tutto in una volta (utile in modalità batch automatica con LLM esterno)
  python scripts/pipeline.py all books/MioLibro.pdf --native --llm
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
PY = sys.executable


def run(cmd: list, check: bool = True) -> int:
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    r = subprocess.run(cmd)
    if check and r.returncode not in (0, 2):  # 2 = quality_check failed but did run
        sys.exit(f"Step fallito (exit {r.returncode}): {cmd[0:3]}")
    return r.returncode


def cmd_prepare(args: argparse.Namespace) -> None:
    pdf = args.pdf.resolve()
    if not pdf.exists():
        sys.exit(f"PDF non trovato: {pdf}")

    book_dir = pdf.parent / pdf.stem
    book_dir.mkdir(parents=True, exist_ok=True)
    extracted = book_dir / f"{pdf.stem} - estratto.md"

    if args.scan:
        run([PY, str(SCRIPTS / "ocr_to_text.py"), str(pdf)])
    else:
        cmd = [PY, str(SCRIPTS / "full_to_text.py"), str(pdf)]
        if args.skip_empty:
            cmd.append("--skip-empty")
        if args.exclude:
            cmd += ["--exclude", args.exclude]
        run(cmd)

    if not extracted.exists():
        sys.exit(f"Estrazione fallita: file atteso non presente: {extracted}")

    split_cmd = [PY, str(SCRIPTS / "split_chapters.py"), str(extracted)]
    if args.by_pages:
        split_cmd += ["--by-pages", str(args.by_pages)]
    elif args.pattern:
        split_cmd += ["--pattern", args.pattern]
    elif args.anchors:
        split_cmd += ["--anchors", str(args.anchors)]
    run(split_cmd, check=False)

    print("\n" + "=" * 60)
    print("PREPARE COMPLETO. Prossimi passi (manuali con agenti AI):")
    print("=" * 60)
    print(f"  1. Apri i capitoli in: {book_dir}/")
    print(f"  2. Per ogni '<libro> - cap_NN_… - estratto.md' produci")
    print(f"     '<libro> - capNN - sintesi.md' usando prompts/synth_chapter.md")
    print(f"  3. Crea l'amalgama in: {pdf.parent}/{pdf.stem}.md")
    print(f"     (usa prompts/amalgamate.md)")
    print(f"  4. Quando finito: python scripts/pipeline.py finalize {book_dir}")


def cmd_finalize(args: argparse.Namespace) -> None:
    book_dir = args.book.resolve()
    if not book_dir.exists():
        sys.exit(f"Cartella non trovata: {book_dir}")

    name = book_dir.name
    extracted = book_dir / f"{name} - estratto.md"
    synthesis = book_dir.parent / f"{name}.md"
    if not extracted.exists():
        sys.exit(f"Estratto mancante: {extracted}")
    if not synthesis.exists():
        sys.exit(f"Sintesi amalgama mancante: {synthesis}")

    qc_report = book_dir / "quality_check.md"
    qc_json = book_dir / "quality_check.json"

    # Eseguiamo QC due volte: una per il report markdown, una per il JSON
    # (modo più semplice che mantiene quality_check.py focalizzato).
    qc_cmd = [PY, str(SCRIPTS / "quality_check.py"),
              "--original", str(extracted),
              "--synthesis", str(synthesis),
              "--chapters-dir", str(book_dir),
              "--out", str(qc_report)]
    if args.llm:
        qc_cmd.append("--llm")
    run(qc_cmd, check=False)

    # JSON crudo (per il report finale)
    json_cmd = [PY, str(SCRIPTS / "quality_check.py"),
                "--original", str(extracted),
                "--synthesis", str(synthesis),
                "--json"]
    print(f"\n$ {' '.join(json_cmd)} > {qc_json}")
    proc = subprocess.run(json_cmd, capture_output=True, text=True)
    raw = proc.stdout
    if "--- JSON ---" in raw:
        json_part = raw.split("--- JSON ---", 1)[1].strip()
        try:
            qc_json.write_text(json_part, encoding="utf-8")
        except Exception:
            qc_json = None
    else:
        qc_json = None

    report_cmd = [PY, str(SCRIPTS / "report.py"),
                  "--book", str(book_dir),
                  "--out", str(book_dir / "REPORT.md")]
    if qc_json and qc_json.exists():
        report_cmd += ["--qc-json", str(qc_json)]
    if args.duration:
        report_cmd += ["--duration", str(args.duration)]
    run(report_cmd, check=False)

    print("\n" + "=" * 60)
    print("FINALIZE COMPLETO")
    print("=" * 60)
    print(f"  Report:        {book_dir / 'REPORT.md'}")
    print(f"  Quality check: {qc_report}")


def cmd_all(args: argparse.Namespace) -> None:
    start = time.time()
    cmd_prepare(args)
    pdf = args.pdf.resolve()
    book_dir = pdf.parent / pdf.stem

    print("\n" + "!" * 60)
    print("  ATTENZIONE: 'all' richiede che gli agenti AI abbiano già prodotto")
    print(f"  le sintesi per capitolo e l'amalgama '{pdf.stem}.md' nella")
    print(f"  cartella '{pdf.parent}'.")
    print("  Premi INVIO per continuare con finalize, Ctrl+C per uscire.")
    print("!" * 60)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        sys.exit("Interrotto.")
    args.book = book_dir
    args.duration = time.time() - start
    cmd_finalize(args)


def main() -> None:
    ap = argparse.ArgumentParser(description="Orchestratore uni-synthesis.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("prepare", help="Estrai + split capitoli")
    p1.add_argument("pdf", type=Path)
    grp = p1.add_mutually_exclusive_group()
    grp.add_argument("--native", action="store_true", help="PDF nativo (con testo)")
    grp.add_argument("--scan", action="store_true", help="PDF scansionato (OCR)")
    p1.add_argument("--skip-empty", action="store_true")
    p1.add_argument("--exclude", default="", help="Pagine da escludere, es. '1,2,250-260'")
    p1.add_argument("--pattern", default="", help="Regex per detection capitoli")
    p1.add_argument("--anchors", type=Path, default=None, help="File con titoli esatti")
    p1.add_argument("--by-pages", type=int, default=0, help="Spezza in N pagine/cap.")
    p1.set_defaults(func=cmd_prepare)

    p2 = sub.add_parser("finalize", help="QC + report dopo sintesi AI")
    p2.add_argument("book", type=Path, help="Cartella del libro (es. books/MioLibro)")
    p2.add_argument("--llm", action="store_true", help="Aggiungi giudizio LLM al QC")
    p2.add_argument("--duration", type=float, default=None)
    p2.set_defaults(func=cmd_finalize)

    p3 = sub.add_parser("all", help="prepare + (stop per agenti) + finalize")
    p3.add_argument("pdf", type=Path)
    grp3 = p3.add_mutually_exclusive_group()
    grp3.add_argument("--native", action="store_true")
    grp3.add_argument("--scan", action="store_true")
    p3.add_argument("--skip-empty", action="store_true")
    p3.add_argument("--exclude", default="")
    p3.add_argument("--pattern", default="")
    p3.add_argument("--anchors", type=Path, default=None)
    p3.add_argument("--by-pages", type=int, default=0)
    p3.add_argument("--llm", action="store_true")
    p3.set_defaults(func=cmd_all)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

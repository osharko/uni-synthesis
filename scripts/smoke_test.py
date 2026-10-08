#!/usr/bin/env python3
"""smoke_test.py — Verifica rapida che gli script del repo siano eseguibili.

Non richiede rete né PDF: controlla la CLI (`--help`) di ogni script e fa un
mini end-to-end di `quality_check.py` su due file temporanei.

Uso:  python scripts/smoke_test.py
Exit: 0 se tutto ok, 1 se qualcosa fallisce.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
SCRIPTS = ["full_to_text.py", "ocr_to_text.py", "split_pdf.py", "revise_extract.py",
           "ocr_crosscheck.py", "split_chapters.py", "quality_check.py",
           "report.py", "pipeline.py", "export_pdf.py"]


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([PY, *args], capture_output=True, text=True, cwd=ROOT)


def main() -> int:
    failures = []
    for name in SCRIPTS:
        p = ROOT / "scripts" / name
        if not p.exists():
            failures.append(f"{name}: mancante")
            continue
        r = run([str(p), "--help"])
        if r.returncode != 0:
            failures.append(f"{name}: --help exit {r.returncode}\n{r.stderr[:300]}")

    # mini end-to-end di quality_check (deterministico, senza LLM)
    with tempfile.TemporaryDirectory() as d:
        orig = Path(d) / "o.md"
        synth = Path(d) / "s.md"
        orig.write_text("Il gatto e il cane si somigliano meno di due levrieri. "
                        "Foucault parla di episteme classica e di somiglianza.\n", encoding="utf-8")
        synth.write_text("## Sintesi\nFoucault discute la somiglianza e l'episteme.\n", encoding="utf-8")
        r = run(["scripts/quality_check.py", "--original", str(orig), "--synthesis", str(synth)])
        if r.returncode not in (0, 2) or "Copertura" not in r.stdout:
            failures.append(f"quality_check mini-e2e: exit {r.returncode}\n{r.stdout[:300]}{r.stderr[:300]}")

    if failures:
        print("SMOKE TEST: FALLITO")
        for f in failures:
            print(" -", f)
        return 1
    print(f"SMOKE TEST: OK ({len(SCRIPTS)} script + quality_check e2e)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

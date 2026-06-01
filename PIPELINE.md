# PIPELINE.md — Cheatsheet workflow

> Riferimento rapido. Per il metodo completo: [`AGENTS.md`](AGENTS.md). Per l'uso umano: [`README.md`](README.md).

---

## Diagramma di flusso

```
              ┌──────────────────────┐
              │   books/<Libro>.pdf  │
              └──────────┬───────────┘
                         │
            PDF nativo? ─┼─ PDF scansione?
                  │      │      │
                  ▼      │      ▼
       full_to_text.py   │   ocr_to_text.py
            (PyMuPDF)    │   (split + enhance + ocrmypdf)
                  │      │      │
                  └──────┴──────┘
                         ▼
        books/<Libro>/<Libro> - estratto.md
                         │
                         ▼
                 split_chapters.py
        (pattern regex / anchors / by-pages)
                         │
                         ▼
   books/<Libro>/<Libro> - cap_NN_<slug> - estratto.md  ×N
                         │
                         ▼
           ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           ║  AGENTI AI IN PARALLELO   ║
           ║  prompts/synth_chapter.md ║
           ║  (3 fasi, opus, 1-2 cap)  ║
           ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                         │
                         ▼
     books/<Libro>/<Libro> - capNN - sintesi.md  ×N
                         │
                         ▼ (opzionale)
           ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           ║  AGENTI VERIFICA INCROC. ║
           ║  prompts/verify_chapter   ║
           ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                         │
                         ▼
                 AGENTE AMALGAMA
              prompts/amalgamate.md
                         │
                         ▼
                books/<Libro>.md
                         │
                         ▼
                 quality_check.py
        (deterministico + opz. --llm)
                         │
                         ▼
                    report.py
                         │
                         ▼
              books/<Libro>/REPORT.md
              books/<Libro>/quality_check.md
                         │
                         ▼ (opzionale)
            Copia in Obsidian/Unich/<Corso>/
```

---

## Tempo stimato per un libro di 250 pagine (PDF nativo)

| Step | Tool | Tempo |
|---|---|---|
| Estrazione testo | `full_to_text.py` | 10-30 s |
| Split capitoli | `split_chapters.py` | < 1 s |
| Sintesi capitoli (8-12 agenti paralleli opus) | AI | 15-30 min |
| Verifica incrociata | AI | 10-20 min |
| Amalgama | AI (1 agente) | 3-5 min |
| Quality check + report | Python | 5-15 s |

**Totale ~ 30-60 minuti** per un libro completo, con qualità di studio.

---

## Workflow standard (copia-incolla pronto)

### A) Setup una tantum
```bash
cd ~/Projects/uni-synthesis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo pacman -S tesseract tesseract-data-ita   # Arch; Debian: apt install tesseract-ocr-ita
cp .env.example .env                          # personalizza se serve
```

### A.bis) Setup opzionale per export PDF con math
```bash
# Catena LaTeX (qualità tipografica massima per la matematica):
sudo pacman -S pandoc texlive-{xetex,latex,fonts-recommended,latexextra,science}
# oppure Typst:
sudo pacman -S typst pandoc
# oppure WeasyPrint (nessun LaTeX richiesto):
pip install weasyprint
# Rendering nativo mermaid (opzionale):
npm install -g @mermaid-js/mermaid-cli
```

### B) Per ogni libro
```bash
# 1. Metti il PDF in books/
cp ~/Downloads/MioLibro.pdf books/

# 2. Prepara estratto + capitoli
python scripts/pipeline.py prepare books/MioLibro.pdf --native --skip-empty

# 3. Lancia gli agenti AI nella tua CLI agentic preferita:
#    Claude Code / opencode / Cursor / Aider → "Fai le sintesi secondo AGENTS.md"
#
#    (Gli agenti useranno prompts/synth_chapter.md + amalgamate.md.
#     Output atteso: books/MioLibro/*- sintesi.md  +  books/MioLibro.md)

# 4. Finalizza
python scripts/pipeline.py finalize books/MioLibro
# Genera:
#   books/MioLibro/quality_check.md
#   books/MioLibro/REPORT.md

# 5. (opzionale) Export PDF con math
python scripts/export_pdf.py books/MioLibro.md --toc
```

### C) Quality check con LLM (opzionale)
```bash
export ANTHROPIC_API_KEY=sk-...
python scripts/pipeline.py finalize books/MioLibro --llm
```

### D) Copia in Obsidian
```bash
# (esempio: vault Obsidian per un corso)
TARGET="$HOME/Obsidian/<Corso>/MioLibro"
mkdir -p "$TARGET"
cp "books/MioLibro/MioLibro - estratto.md"   "$TARGET/MioLibro.md"
cp "books/MioLibro.md"                       "$TARGET/Sintesi. MioLibro.md"
```

---

## Risoluzione problemi rapidi

| Problema | Soluzione |
|---|---|
| `Read` fallisce su nome file con apostrofi/ellissi/accenti | Leggi via `cat` (eccezione legittima) |
| Estratto ha sezioni vuote / brutte tabelle | PDF probabilmente "ibrido" → usa `ocr_to_text.py` con `--skip-ocr` per ri-renderizzare |
| Split capitoli sbaglia tagli | Usa `--anchors file.txt` con titoli esatti, o `--by-pages N` come fallback |
| Quality check sotto soglia ma sintesi sembra buona | Rilancia con `--llm` per filtrare falsi positivi |
| OCR molto rumoroso (scan CamScanner) | Trascrivi pagina per pagina con agenti opus usando `prompts/transcribe_page.md` |
| Capitolo "fantasma" assente nella sintesi | È successo storicamente — lancia un agente fix dedicato sull'estratto del capitolo mancante |
| Formule mate trasformate in testo piatto dall'OCR | Trascrivi con `prompts/transcribe_page.md` (agenti AI ricostruiscono in LaTeX leggendo l'immagine pagina) |
| Export PDF: math non viene renderizzato | Verifica engine: `xelatex`/`typst` rendono nativamente; `weasyprint` richiede `--mathjax` (già di default in `export_pdf.py`) |
| `export_pdf.py` non trova nessun engine | Installa almeno: `pip install weasyprint` (più semplice) **oppure** la catena LaTeX **oppure** typst |

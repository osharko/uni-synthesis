# uni-synthesis

Suite per produrre **sintesi di studio approfondite** da PDF di libri, manuali, saggi o articoli (nativi o scansionati). Adatta a contesti accademici, professionali, di ricerca. Combina:

- **Python locale** per le operazioni costose ma deterministiche (estrazione PDF, OCR, split capitoli, quality check, report) — *zero token consumati*.
- **Agenti AI** (Claude/opencode/Cursor/…) per il lavoro creativo (sintesi capitolo, verifica, amalgama) — istruzioni in `prompts/`.

> **Filosofia:** il Python fa il lavoro meccanico; gli agenti AI fanno il lavoro intellettuale. Il quality check è deterministico (Python) per default e usa LLM solo su richiesta esplicita.

> **Guida operativa completa per le IA:** vedi [`AGENTS.md`](AGENTS.md) (standard `agents.md`, letto da Claude Code, opencode, Cursor, Aider, …).

---

## Installazione

```bash
git clone <repo> uni-synthesis && cd uni-synthesis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Per OCR (Arch Linux):
sudo pacman -S tesseract tesseract-data-ita
# Debian/Ubuntu:
# sudo apt install tesseract-ocr tesseract-ocr-ita

# Per export PDF (uno qualsiasi dei seguenti basta):
# - LaTeX (qualità massima per la matematica):
sudo pacman -S pandoc texlive-{xetex,latex,fonts-recommended,latexextra,science}
# - oppure Typst (alternativa moderna):
sudo pacman -S typst pandoc
# - oppure WeasyPrint (nessun LaTeX, math via MathJax):
pip install weasyprint

cp .env.example .env   # personalizza i parametri
```

---

## Workflow end-to-end (più semplice)

### Caso A — PDF nativo (con layer testo)

```bash
# 1. Preparazione: estrazione testo + split capitoli
python scripts/pipeline.py prepare books/MioLibro.pdf --native --skip-empty

# 2. Apri Claude Code / opencode nella cartella e chiedi:
#    "Fai le sintesi dei capitoli secondo AGENTS.md"
#    Gli agenti produrranno:
#      books/MioLibro/MioLibro - capNN - sintesi.md  (uno per capitolo)
#      books/MioLibro.md                              (amalgama finale)

# 3. Finalizzazione: quality check + report
python scripts/pipeline.py finalize books/MioLibro
```

### Caso B — PDF scansionato (OCR)

```bash
# 1. Configura parametri OCR/split in .env (vedi commenti in .env.example)
# 2. Prepara
python scripts/pipeline.py prepare books/Scan.pdf --scan

# 3-4 come sopra
```

---

## Workflow per singoli step (utile in debug)

```bash
# Solo estrazione PDF nativo
python scripts/full_to_text.py books/MioLibro.pdf --skip-empty
python scripts/full_to_text.py books/MioLibro.pdf --exclude 1,2,250-260

# Solo OCR
python scripts/ocr_to_text.py books/Scan.pdf
python scripts/ocr_to_text.py books/Scan.pdf --no-split --skip-ocr   # solo enhance

# Solo split capitoli (dry-run mostra i tagli senza scrivere)
python scripts/split_chapters.py "books/MioLibro/MioLibro - estratto.md" --dry-run
python scripts/split_chapters.py "books/MioLibro/MioLibro - estratto.md" --by-pages 25
python scripts/split_chapters.py "books/MioLibro/MioLibro - estratto.md" \
  --anchors my_chapters.txt

# Solo quality check
python scripts/quality_check.py \
  --original "books/MioLibro/MioLibro - estratto.md" \
  --synthesis "books/MioLibro.md" \
  --chapters-dir books/MioLibro \
  --out books/MioLibro/quality_check.md

# Con giudizio LLM (endpoint OpenAI-compatibile, locale o cloud; vedi .env)
python scripts/quality_check.py ... --llm \
  --llm-base-url http://127.0.0.1:8080/v1 --llm-model <nome-modello>

# Solo report
python scripts/report.py --book books/MioLibro

# Export PDF (auto-rileva il miglior engine disponibile)
python scripts/export_pdf.py books/MioLibro.md --toc
python scripts/export_pdf.py books/MioLibro.md --engine xelatex --toc
python scripts/export_pdf.py books/MioLibro.md --engine weasyprint
```

---

## Supporto LaTeX e diagrammi

I prompt degli agenti impongono di:
- preservare ogni **formula matematica** in LaTeX (`$E=mc^2$`, `$$\nabla \times \vec{B} = \mu_0 \vec{J}$$`)
- usare **mhchem** per la chimica (`$\ce{2H2 + O2 -> 2H2O}$`)
- ricostruire **grafici e diagrammi** dell'originale con ` ```mermaid` / ` ```tikz` quando possibile, o descrizione testuale ricca

Il **quality check** conta formule inline, block e diagrammi sia nell'originale sia nella sintesi, e segnala se la sintesi ne ha molte meno.

L'**export PDF** sceglie automaticamente il miglior engine disponibile sul sistema:
1. **LaTeX** (xelatex/lualatex/tectonic) → resa tipografica perfetta, ideale per testi con molta matematica
2. **Typst** → veloce, font moderni
3. **WeasyPrint + MathJax** → fallback senza LaTeX, math renderizzato via JavaScript

---

## Cosa misura il quality check

| Metrica | Cosa controlla |
|---|---|
| **Ratio di sintesi** | Sintesi è 1/5..1/8 dell'originale? |
| **Copertura keyword** | Le top-50 parole-contenuto dell'originale compaiono nella sintesi? |
| **Copertura nomi propri** | Nomi di autori, persone, luoghi presenti? |
| **Copertura citazioni** | Le citazioni `«…»` di almeno 30 caratteri sono preservate? |
| **Riferimenti bibliografici** | Pattern `Autore (YYYY)` presenti? |
| **Capitoli presenti** | Tutti i capitoli rilevati nell'originale ci sono nella sintesi? |
| **Anni / date** | Date storiche preservate? |
| **Formule matematiche** | Le formule LaTeX (`$…$`, `$$…$$`, environments) sono preservate? Si confronta sul conteggio totale |
| **Diagrammi** | Blocchi `mermaid`/`tikz`/`dot` riportati nella sintesi |

Score complessivo pesato. **Soglia default: 75%.** Exit code 0 (passed) o 2 (failed), comodo per script.

---

## Report finale

`scripts/pipeline.py finalize` genera `books/<Libro>/REPORT.md`:

```markdown
# Report di lavorazione — <Libro>

## File principali
| Tipo | Path | Dimensione |
|---|---|---|
| PDF originale     | books/MioLibro.pdf            | 12.4 MB |
| Estratto markdown | …/MioLibro - estratto.md      | 580 KB · 95,420 parole · 18,200 righe |
| Sintesi amalgama  | books/MioLibro.md             | 92 KB · 14,800 parole · 2,100 righe |

**Ratio di compressione:** 1/6.45  (target ideale: 1/5 – 1/8)

## Capitoli
- Estratti: 12   · Sintetizzati: 12

## Quality check
- Score complessivo: **87.3%**  ·  Esito: ✅ PASSED
| Aspetto | Copertura |
|---|---:|
| Keyword (top-50)         | 94% |
| Nomi propri              | 89% |
| Citazioni letterali      | 81% |
| Rif. bibliografici       | 92% |
| Capitoli                 | 100% |
| Anni/date                | 96% |

## Tempo di lavorazione
1h 14m 03s
```

---

## Configurazione (`.env`)

Vedi [`.env.example`](.env.example) per la lista completa. Gruppi principali:

- **I/O**: `INPUT_PDF`, `WORK_DIR`
- **Split doppia pagina** (OCR): `AUTO_SPLIT`, `SPLIT_POSITION`, `CENTER_CROP_MARGIN`
- **Range pagine**: `PAGE_START`, `PAGE_END`
- **Rendering**: `RENDER_DPI`, `JPEG_QUALITY`
- **Image enhancement**: `ENHANCE_CONTRAST`, `SHARPEN`, `GRAYSCALE`, …
- **OCR**: `OCR_ENABLED`, `OCR_LANGUAGE`, `OCR_DPI`, `OCR_DESKEW`
- **Quality check**: `QC_RATIO_MIN`, `QC_RATIO_MAX`, `QC_COVERAGE_THRESHOLD`
- **LLM opzionale** (OpenAI-compatibile): `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_EXTRA_PARAMS`

---

## Esecuzione autonoma da agente AI

Apri Claude Code (o opencode) nella root del progetto e chiedi:

> "Voglio sintetizzare `books/MioLibro.pdf`. Segui AGENTS.md."

L'agente:
1. Riconoscerà se è PDF nativo o scan
2. Eseguirà `pipeline.py prepare`
3. Lancerà gli agenti paralleli per le sintesi (prompt in `prompts/synth_chapter.md`)
4. Eseguirà la verifica incrociata
5. Eseguirà l'amalgama
6. Eseguirà `pipeline.py finalize`
7. Ti mostrerà il `REPORT.md`

Tutta la parte costosa in token (sintesi creativa) viene fatta dall'AI; tutta la parte deterministica (estrazione, split, copertura, metriche) viene fatta dai Python locali.

---

## Layout repo

```
uni-synthesis/
├── AGENTS.md              ← guida per IA (Claude/opencode/Cursor/Aider)
├── README.md              ← questo file
├── PIPELINE.md            ← cheatsheet workflow
├── requirements.txt
├── .env.example
├── scripts/
│   ├── full_to_text.py
│   ├── ocr_to_text.py
│   ├── split_chapters.py
│   ├── quality_check.py
│   ├── report.py
│   └── pipeline.py
├── prompts/
│   ├── synth_chapter.md
│   ├── verify_chapter.md
│   ├── amalgamate.md
│   └── transcribe_page.md
└── books/                 ← workspace per ogni libro
```

---

## Licenza & crediti

Open-source per uso libero. Metodo e pipeline maturati su una decina di libri di studio.

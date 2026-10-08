# AGENTS.md — Guida operativa per IA (agnostica: Claude Code, opencode, Cursor, Aider, …)

> **A chi legge:** sei un'IA chiamata ad aiutare lo studente a produrre **sintesi di studio approfondite** a partire da PDF (nativi o scansionati) o da appunti grezzi. Questa guida è **autosufficiente**: contiene metodo, regole di qualità, pipeline, prompt riusabili e comandi concreti. Leggila tutta prima di agire.
>
> **Standard:** questo file segue la convenzione [agents.md](https://agents.md) (un solo file di istruzioni letto da molteplici tool agentici). Claude Code lo legge in assenza di `CLAUDE.md`; opencode lo legge come fonte primaria.

---

## 1. Profilo utente (default)

- **Persona che studia in profondità** un testo (studente, ricercatore, professionista, autodidatta).
- **Lingua:** segui la lingua dell'utente. Se non è chiaro, default italiano.
- **Output sempre in markdown.** PDF solo come export finale dal markdown.
- Si aspetta **massima profondità**: mai semplificare né banalizzare.
- Profilo tipicamente tecnico: a suo agio con Python, `.env`, CLI, git.
- Apprezza **parallelizzazione massima** con sotto-agenti in background.
- Preferisce essere informato del progresso ma non sommerso di dettagli tecnici.

---

## 2. Regole di qualità delle sintesi (NON negoziabili)

1. **Stile discorsivo, in paragrafi.** Si scrive un testo *da studiare*, non da ripetere a pappagallo.
2. **MAI gli elenchi puntati come stile principale.** Bullet solo per veri elenchi/classificazioni già presenti nell'originale.
3. **Profondità, non riassuntino.** Rielabora e migliora l'esposizione; non fare copia-incolla accorciato.
4. **Ratio target: 1/5 – 1/8** del testo originale (dipende dalla densità).
5. **Conserva sempre:** citazioni `«…»` con autore/anno, definizioni tecniche, nomi propri, riferimenti bibliografici, leggi, date.
6. **Grassetto** per i concetti chiave; *corsivo* per i termini tecnici/latinismi.
7. **A fine di ogni capitolo:** riepilogo schematico (tabella, mappa concettuale o schema — a discrezione). Unico spazio in cui lo schematismo è benvenuto.
8. L'**amalgama finale** del libro intero aggiunge una **mappa concettuale complessiva** per il ripasso/riepilogo.
9. **Formule matematiche, simboli, espressioni in notazione tecnica → SEMPRE in LaTeX.** Inline: `$E = mc^2$`. Block: `$$\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}$$`. Anche per chimica (`$\ce{H2O}$` con mhchem), logica (`$\forall x \in \mathbb{R}$`), notazione musicale, grafi. **Mai** trascrivere una formula come testo piatto se l'originale la presenta come formula.
10. **Grafici, diagrammi, schemi visivi** dell'originale: descriverli a parole nella sintesi e, se possibile, ricostruirli con sintassi diagrammatica testuale (`mermaid`, `tikz` in code block, tabelle ASCII). Esempio: ` ```mermaid` per flowchart, ` ```tikz` (LaTeX) per diagrammi formali.

---

## 3. Due scenari di lavoro

- **Scenario A — Sintesi da zero a partire da un libro** (PDF nativo o scansione/OCR). → Sezione 5.
- **Scenario B — Rielaborazione di una sintesi/appunti già scritti dall'utente** (testo grezzo, refusi da dettatura, da rendere scorrevole **senza stravolgere**). → Sezione 8.

> ⚠️ Sono lavori diversi. In B **non si riassume e non si cambiano termini/concetti**: si pulisce e si rende fluente. In A si *produce* la sintesi vera e propria.

---

## 4. Struttura del repository

```
uni-synthesis/
├── AGENTS.md              ← questo file (guida AI agnostica)
├── README.md              ← uso umano + report finale
├── PIPELINE.md            ← workflow step-by-step (riferimento rapido)
├── requirements.txt
├── .env.example           ← copia in .env per personalizzare
├── scripts/
│   ├── full_to_text.py     ← PDF nativo → markdown estratto
│   ├── ocr_to_text.py      ← PDF scan → split + enhance + OCR → markdown
│   ├── split_pdf.py        ← doppie pagine → pagine singole (vettoriale, conserva il layer testo)
│   ├── revise_extract.py   ← estratto → markdown pulito (paragrafi, note `>`, titoli)
│   ├── ocr_crosscheck.py   ← seconda lettura OCR CPU (tesseract) + confronto (cross-check)
│   ├── split_chapters.py   ← estratto.md → un file per capitolo
│   ├── quality_check.py    ← copertura sintesi vs originale (deterministico + opz. LLM)
│   ├── report.py           ← report di fine lavorazione
│   └── pipeline.py         ← orchestratore CLI (prepare / finalize / all)
├── prompts/
│   ├── synth_chapter.md   ← prompt agente sintesi (3 fasi)
│   ├── verify_chapter.md  ← prompt verifica incrociata
│   ├── amalgamate.md      ← prompt amalgama finale
│   └── transcribe_page.md ← trascrizione pagina scansione degradata
└── books/                 ← workspace operativa per ogni libro
```

**Convenzione cartelle dei libri:**
```
books/
├── <Nome Libro>.pdf                              ← PDF originale
├── <Nome Libro>.md                               ← amalgama finale (file di studio principale)
└── <Nome Libro>/                                 ← cartella per ogni libro
    ├── <Nome Libro> - estratto.md                ← testo completo estratto
    ├── <Nome Libro> - cap_NN_<slug> - estratto.md  ← capitolo grezzo
    ├── <Nome Libro> - capNN - sintesi.md         ← sintesi capitolo (prodotta da agente)
    ├── REPORT.md                                 ← report di fine lavorazione
    └── quality_check.md                          ← esito quality check
```

---

## 5. Scenario A — Pipeline completa

### Step 1 — Portare il libro in markdown

**5.1 PDF nativo (con layer testo):**
```bash
python scripts/full_to_text.py "books/<Libro>.pdf" --skip-empty
```
Output: `books/<Libro>/<Libro> - estratto.md`. Usa `--exclude 1,2,250-260` per escludere pagine (titolo, indice, note finali).

**5.2 PDF scansione / fotocopia:**
```bash
# 1. configura split/OCR in .env (vedi .env.example)
# 2. lancia la pipeline:
python scripts/ocr_to_text.py "books/<Scan>.pdf"
```
Output: PDF cercabile con layer OCR + `<Libro> - estratto.md`. Per scansioni molto degradate (es. CamScanner), considera di affidare la trascrizione pagina-per-pagina a un agente AI (usa il modello più capace disponibile) con `prompts/transcribe_page.md` (input: PNG + bozza OCR).

### Step 1b — Validazione OCR in CPU (cross-check) — consigliato

**Principio:** l'OCR base si fa **in CPU con tesseract** (nessun LLM); l'LLM interviene poi **solo sul testo** (comprensione, pulizia, scelta). Si produce una **seconda lettura indipendente** della pagina e la si confronta con il markdown: dove le due letture concordano → confermato; dove divergono → si arbitra (regole o LLM).

```bash
# a) mirato: recuperare frammenti [illeggibile] (JSON con page/before/after)
python scripts/ocr_crosscheck.py --mode fragments \
  --pdf "books/<Libro>/<Libro> - split.pdf" \
  --current "books/<Libro>/<Libro> - estratto.md" \
  --fragments frammenti.json --out /tmp/cross_frag.md

# b) completo: confronto pagina-per-pagina tesseract ↔ layer dell'estratto
python scripts/ocr_crosscheck.py --mode full --dpi 300 \
  --pdf "books/<Libro>/<Libro> - split.pdf" \
  --estratto "books/<Libro>/<Libro> - estratto.md" \
  --out "books/<Libro>/quality_check cross-ocr.md"
```

- Solo `tesseract` (`-l ita`) + PyMuPDF: gira in CPU in pochi minuti, **nessun modello multimodale**.
- Modalità `full`: misura la **concordanza tra due letture indipendenti** della stessa pagina (tesseract vs layer) e segnala le pagine a bassa concordanza (figure, scansioni degradate).
- Utile per: risolvere `[illeggibile]`, validare refusi, fare da "quality check" indipendente dall'LLM.
- Vedi anche `scripts/split_pdf.py` (split vettoriale, conserva il layer testo) e `scripts/revise_extract.py` (pulizia del markdown: paragrafi, note, titoli).

### Step 2 — Split in capitoli

```bash
python scripts/split_chapters.py "books/<Libro>/<Libro> - estratto.md" --dry-run
```
Se il dry-run mostra tagli corretti, ri-esegui senza `--dry-run`. Strategie disponibili:
- **regex automatico** (default): rileva "Capitolo N", "CAPITOLO N", "Cap. N"
- **--pattern**: regex custom
- **--anchors file.txt**: titoli esatti su righe (più affidabile)
- **--by-pages 25**: spezza in blocchi di N pagine

### Step 3 — Sintesi per capitolo (agenti paralleli)

**Cuore del metodo.** Lancia sotto-agenti AI (il modello più capace disponibile) in **parallelo e background**, uno ogni **1-2 capitoli** (max 3 solo se molto corti). *Più agenti piccoli > pochi agenti grandi*.

**Ogni agente esegue 3 fasi (vedi `prompts/synth_chapter.md`):**
1. **Estrazione concetti** — tesi, concetti chiave, citazioni, nomi, riferimenti, struttura
2. **Sintesi discorsiva** — paragrafi fluidi, ratio 1/5-1/8, riepilogo schematico finale
3. **Verifica riga per riga** — rilettura originale a fronte della sintesi, integrazione

**Output:** `books/<Libro>/<Libro> - capNN - sintesi.md`

**Step 3b (consigliato) — Verifica incrociata:** secondo round di agenti paralleli con `prompts/verify_chapter.md`. Confrontano sezione per sezione e sovrascrivono se servono correzioni.

### Step 4 — Amalgama

Un agente unisce tutte le sintesi in `books/<Libro>.md` usando `prompts/amalgamate.md`. **NON riassume ulteriormente** — uniforma heading, aggiunge transizioni minime e una **mappa concettuale finale**.

### Step 5 — Quality check + report

```bash
python scripts/pipeline.py finalize "books/<Libro>"
# Genera:
#   books/<Libro>/quality_check.md   (copertura entità, citazioni, capitoli)
#   books/<Libro>/REPORT.md          (dimensioni, ratio, capitoli, durata)
```

Aggiungi `--llm` se vuoi un giudizio semantico finale tramite un endpoint **OpenAI-compatibile** (locale o cloud; configurazione in `.env`: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, opz. `LLM_EXTRA_PARAMS`).

### Step 6 — Export PDF (opzionale)

```bash
# Auto-detect dell'engine migliore disponibile (xelatex > tectonic > typst > weasyprint)
python scripts/export_pdf.py books/MioLibro.md --toc

# Forza un engine specifico
python scripts/export_pdf.py books/MioLibro.md --engine xelatex --toc
python scripts/export_pdf.py books/MioLibro.md --engine weasyprint  # no LaTeX richiesto

# Renderizza i blocchi mermaid come SVG (richiede mermaid-cli `mmdc`)
python scripts/export_pdf.py books/MioLibro.md --render-mermaid --engine xelatex
```

Lo script supporta automaticamente formule **LaTeX inline `$…$`** e **block `$$…$$`**, environments `equation`/`align`/`gather`/`cases`/`matrix`, chimica via `\ce{…}` (mhchem), diagrammi mermaid/tikz/dot.

**Engine consigliati:**
- **xelatex / lualatex** — qualità tipografica massima, formule perfette. Su Arch: `sudo pacman -S texlive-{xetex,latex,fonts-recommended,latexextra,science}`.
- **typst** — rapido, font moderni, ottima math. Su Arch: `sudo pacman -S typst`.
- **weasyprint** (fallback) — niente LaTeX richiesto, math via MathJax. `pip install weasyprint`.

### Step 7 — Copia in Obsidian (opzionale)

Struttura `Obsidian/Unich/<Corso>/<Libro>/`:
- `<Libro>.md` ← testo originale estratto (rinominato senza "- estratto")
- `Sintesi. <Libro>.md` ← sintesi amalgamata (prefisso "Sintesi.")

⚠️ Prima di copiare il file "originale" leggi le prime 5 righe per assicurarti che NON sia per errore una sintesi.

---

## 6. Quality check — cosa misura

`scripts/quality_check.py` calcola **metriche deterministiche** in Python (zero token):

| Aspetto | Come |
|---|---|
| **Ratio di sintesi** | parole originale / parole sintesi, target 1/5..1/8 |
| **Copertura keyword** | top-50 keyword (TF semplice senza stopwords) presenti nella sintesi |
| **Copertura nomi propri** | regex `[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*`, esclusi inizi frase |
| **Copertura citazioni** | citazioni `«…»` di cui 30+ caratteri compaiono nella sintesi |
| **Copertura riferimenti bibliografici** | pattern `Autore (YYYY)` o `(Autore, YYYY)` |
| **Capitoli presenti** | confronto tra heading dei capitoli |
| **Anni** | tutte le date `19XX`/`20XX` presenti nell'originale |
| **Formule LaTeX** | `$…$` inline e `$$…$$` / `\begin{equation}` block; copertura = conteggio sintesi / conteggio originale |
| **Diagrammi** | conteggio blocchi ` ```mermaid `, ` ```tikz `, ` ```dot `, ` ```plantuml ` |

Score complessivo pesato (0-100%). I pesi si ridistribuiscono automaticamente quando una metrica non è applicabile (es. originale senza formule → il peso math si redistribuisce). Soglia di default: **75%** + ratio nel range + nessun capitolo mancante.

Output: report markdown con elenco dei mancanti (keyword, nomi, citazioni, capitoli). Exit code 0 (passed) o 2 (failed).

**Opzionale `--llm`:** dopo il calcolo deterministico, un LLM (endpoint OpenAI-compatibile, locale o cloud) legge le omissioni segnalate + 4K caratteri della sintesi e separa **vere omissioni** da **falsi positivi** (parafrasi, sinonimi).

---

## 7. Lancio agenti AI per le sintesi — istruzioni per IA

Quando l'utente è in **Claude Code** o **opencode** e ti chiede di "fare le sintesi", segui questa procedura:

1. **Verifica preparazione:** controlla che esistano i file `books/<Libro>/<Libro> - cap_NN_… - estratto.md`. Se no, suggerisci `python scripts/pipeline.py prepare …`.
2. **Lancia agenti in parallelo** (uno ogni 1-2 capitoli). In Claude Code: tool `Agent` con `subagent_type` adatto, in background. In opencode: agenti paralleli analoghi.
3. **Prompt da usare:** `prompts/synth_chapter.md`, sostituendo `{ESTRATTO_PATH}` e `{SINTESI_PATH}`.
4. **Dopo le sintesi:** lancia un round di verifica con `prompts/verify_chapter.md` (paralleli) — opzionale ma consigliato.
5. **Amalgama:** un singolo agente con `prompts/amalgamate.md`.
6. **Finalizza:** `python scripts/pipeline.py finalize books/<Libro>` (o con `--llm` se è configurato un endpoint LLM nel `.env`).
7. **Mostra il REPORT.md** all'utente.

---

## 8. Scenario B — Rielaborare una sintesi/appunti già esistenti

Caso tipico: l'utente (o un compagno) ha già scritto la sintesi "a mano", spesso con **errori da dettatura/OCR** (parole spezzate, omofoni sbagliati, punteggiatura saltata) e vuole renderla **scorrevole senza stravolgerla**.

**Regola d'oro:** *i termini e i concetti restano quelli del testo. Non si riassume, non si taglia, non si inventa.* Un "ChatGPT generico" tende a riassumere/cambiare termini: è proprio ciò che NON si vuole.

### 8.1 Chiarire il livello di intervento

Chiedi all'utente (o proponi un default):
- **Quanto intervenire:**
  - *Leggero* — solo errori evidenti e frasi rotte
  - *Medio (default consigliato)* — corregge errori + rende fluido, mantenendo tutto
  - *Deciso/discorsivo* — riscrive per massima fluidità; termini e concetti restano
- **Struttura:** mantenere com'è / convertire tutto in prosa / aggiungere schemi di ripasso

Se l'utente vuole **confrontare**, produci versioni multiple in file separati e usa `scripts/quality_check.py` per verificare che non si siano persi contenuti.

### 8.2 Errori ricorrenti da dettatura/OCR (esempi reali)

`facilita tori` → *facilitatori* · `osserva TiVo` → *osservativo* · `attività morale` → *molare* · `la luna veniva richiesto` → *all'alunna veniva richiesto* · `1:00 attività` → *una attività* · `elaboratori` → *laboratori* · `internazionale` (dimensione) → *interazionale* · link `x-apple-data-detectors://…` dentro gli orari → orari normali.

---

## 9. Trabocchetti e lezioni apprese

- **Non usare PNG per il quality-check testo:** i PNG possono tagliare testo ai bordi. Per confrontare PDF↔md leggi il PDF **direttamente** con `fitz.get_text()`.
- **Capitoli "fantasma":** è successo che un intero capitolo (o il corpo del cap. 1) fosse **assente** dall'estratto/sintesi e andasse ricostruito. In fase di verifica controlla che **tutti** i capitoli ci siano e siano pieni.
- **Sintesi ≠ rielaborazione:** non confondere lo Scenario A con il B (§3).
- **Granularità agenti:** preferisci sempre più agenti piccoli, paralleli, in background (il modello più capace disponibile).
- **Nomi file con Unicode:** apostrofi tipografici (`'`), ellissi (`…`), accenti possono far fallire `Read` per NFC/NFD → leggi con `cat` via shell come eccezione.
- **PDF nativo silenziosamente "ibrido":** alcuni PDF hanno layer testo solo su alcune pagine. Se `full_to_text.py` produce sezioni vuote, passa a `ocr_to_text.py`.
- **OCR: prima la CPU, poi l'LLM.** Per lettura/validazione del testo usa **tesseract in CPU** (`scripts/ocr_crosscheck.py`), non un LLM multimodale: è più veloce, gratis, riproducibile e non dipende da modello/GPU. Riserva l'LLM alla **comprensione e pulizia del testo** (e all'arbitraggio tra due letture). Il repo resta **agnostico rispetto al modello**: eventuali LLM (cloud o locali) si configurano **solo** via `.env` (vedi `.env.example`), mai hardcoded.

---

## 10. Dipendenze e prerequisiti

### Python
```bash
pip install -r requirements.txt
# include: PyMuPDF, Pillow, ocrmypdf, python-dotenv, numpy
# opzionale: --llm usa un endpoint OpenAI-compatibile via urllib (nessuna dipendenza extra)
```

### Sistema (per OCR)
- **Arch Linux:** `sudo pacman -S tesseract tesseract-data-ita`
- **Debian/Ubuntu:** `sudo apt install tesseract-ocr tesseract-ocr-ita`

### Export PDF (opzionale)
Vedi `scripts/export_pdf.py`. Almeno una di queste catene:
- **LaTeX (qualità max):** `pandoc` + `xelatex`/`lualatex` o `tectonic`. Su Arch: `sudo pacman -S pandoc texlive-{xetex,latex,fonts-recommended,latexextra,science}`. Su Debian: `sudo apt install pandoc texlive-xetex texlive-latex-extra texlive-science`.
- **Typst (alternativa moderna):** `sudo pacman -S typst` (o `cargo install typst-cli`).
- **WeasyPrint (no LaTeX):** `pip install weasyprint` (math renderizzato via MathJax).
- **Mermaid rendering (opzionale):** `npm i -g @mermaid-js/mermaid-cli` per `mmdc`.

---

## 11. Comandi rapidi

```bash
# Pipeline completa con prompt agli agenti AI manuale
python scripts/pipeline.py prepare books/MioLibro.pdf --native
# … qui lanci gli agenti AI con i prompt in prompts/ …
python scripts/pipeline.py finalize books/MioLibro

# OCR per scansione
python scripts/ocr_to_text.py books/Scan.pdf
python scripts/split_chapters.py "books/Scan/Scan - estratto.md" --by-pages 30

# Cross-check OCR in CPU (seconda lettura tesseract + confronto, senza LLM)
python scripts/ocr_crosscheck.py --mode full --dpi 300 \
  --pdf "books/MioLibro/MioLibro - split.pdf" \
  --current "books/MioLibro/MioLibro - estratto.md" \
  --out "books/MioLibro/quality_check cross-ocr.md"

# Solo quality check
python scripts/quality_check.py \
  --original "books/MioLibro/MioLibro - estratto.md" \
  --synthesis "books/MioLibro.md" \
  --chapters-dir books/MioLibro

# Solo report
python scripts/report.py --book books/MioLibro

# Export in PDF (auto-detect engine: xelatex > tectonic > typst > weasyprint)
python scripts/export_pdf.py books/MioLibro.md --toc
```

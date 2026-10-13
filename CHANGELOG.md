# Changelog

## [0.3.0] — 2026-10-13

### Added
- `scripts/ocr_to_markdown.py` — **nuovo Scenario C**: da scansione degradata a markdown
  *fedele* (nessuna sintesi), con **re-OCR in CPU** (tesseract):
  - divide ogni pagina in **unità** (pagina intera; metà pagina per gli **spread**) così da
    evitare l'interlacciamento delle due facciate;
  - estrae l'**immagine incorporata** (più veloce del render) e fa **upscale 2×** (Lanczos):
    risolve gli errori dovuti a scansioni a bassa risoluzione;
  - OCR parallelo con **cache** su disco (`<pdf>_-ocr_cache.json`);
  - rimozione di running header/footer rilevati **per ripetizione** sulle pagine (+ regex);
  - ricostruzione paragrafi, titoli capitolo/sezione, **note `[^n]`** (numerazione stampata);
  - parametri libro-specifici via `--config _config.json`.
- `scripts/merge_cleaned_parts.py` — amalgama i blocchi ripuliti in un markdown finale:
  indice con **ancore compatibili con pandoc**, sezione `## Note` unica, appendice
  `## Da verificare`, frontespizio.
- `prompts/normalize_ocr.md` — prompt per la **pulizia dei refusi OCR** (nessuna sintesi):
  corregge parole unite/spezzate, caratteri estranei, punteggiatura; non riassume; segnala
  i passi irricostruibili.
- `AGENTS.md` — nuova **Sezione 8-bis (Scenario C)** e sette nuove lezioni (§9).

### Fixed
- `scripts/export_pdf.py` — trova l'eseguibile **weasyprint** dell'interprete corrente
  (es. `.venv/bin/weasyprint`) e lo passa a pandoc: prima falliva con
  "weasyprint not found" quando non era nel `PATH`. Aggiornato `--mathjax` → `--math-method=mathjax`.
- Indice dei markdown: slug generati con l'algoritmo di **pandoc `auto_identifiers`**, così i
  link interni funzionano anche nel PDF esportato.

### Docs
- `README.md`, `PIPELINE.md` — elenco script, workflow e tabella di troubleshooting aggiornati
  (pagine doppie, upscale, testatine, ancore, weasyprint).

## [0.2.0] — 2026-10-08

### Added
- `scripts/split_pdf.py` — split **vettoriale** delle doppie pagine (conserva il layer testo).
- `scripts/revise_extract.py` — pulizia del markdown estratto (ricostruzione paragrafi, note `>`, titoli).
- `scripts/ocr_crosscheck.py` — **seconda lettura OCR in CPU** (tesseract) e confronto:
  - `--mode fragments`: recupera i passi `[illeggibile]`;
  - `--mode full`: concordanza **pagina-per-pagina** tesseract ↔ layer; opz. `--current` per confrontare col testo attuale.
- `scripts/smoke_test.py` — verifica rapida di CLI ed e2e (senza rete/PDF).
- `quality_check.py --llm` — giudizio semantico via **qualsiasi endpoint OpenAI-compatibile**
  (locale o cloud); `LLM_TIMEOUT` / `LLM_MAX_TOKENS` configurabili; retry su risposte vuote.
- `AGENTS.md` §5 — nuovo **Step 1b: validazione OCR in CPU**; lezione "prima la CPU, poi l'LLM".

### Changed
- **Repo agnostico rispetto al modello**: la configurazione LLM vive solo in `.env`
  (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_EXTRA_PARAMS`, alias `LOCAL_LLM_*`).
  Rimossi default e riferimenti a modelli specifici.
- `quality_check.py` — euristica **nomi propri** più precisa (esclude inizio frase/riga,
  stopword, parole tutte MAIUSCOLE, parole che ricorrono anche in minuscolo, suffissi verbali).
- `README.md` / `PIPELINE.md` — elenco script e istruzioni aggiornati.

### Removed
- `requirements.txt` — dipendenza `anthropic` (non più necessaria: si usa `urllib`).

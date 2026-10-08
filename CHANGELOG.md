# Changelog

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

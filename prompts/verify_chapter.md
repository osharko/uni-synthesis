# Prompt — Verifica incrociata sintesi di capitolo

> **Variabili:** `{ESTRATTO_PATH}`, `{SINTESI_PATH}`.
> Lanciare in parallelo dopo `synth_chapter.md`, uno per capitolo.

---

Sei un revisore di sintesi di studio approfondito. Hai due file:
- `{ESTRATTO_PATH}` — testo originale del capitolo
- `{SINTESI_PATH}` — sintesi già prodotta

## Compito

Confronta i due file **sezione per sezione** e:

1. Verifica che ogni paragrafo dell'estratto abbia rappresentazione nella sintesi.
2. Segnala omissioni di:
   - tesi argomentative
   - concetti chiave (devono essere in grassetto)
   - citazioni letterali (`«…»`)
   - nomi propri / autori / riferimenti bibliografici
   - esempi fondamentali per la comprensione
   - **formule matematiche / espressioni tecniche** (devono essere in LaTeX: `$...$` o `$$...$$`)
   - **grafici / diagrammi / schemi** (devono essere ricostruiti o descritti)
3. Identifica imprecisioni o termini cambiati rispetto all'originale. Per le formule: verifica che la sintesi LaTeX sia matematicamente equivalente alla formula nell'originale (non solo tipograficamente simile).
4. Verifica che il **riepilogo schematico finale** ci sia e sia coerente.

## Output

Se trovi **correzioni significative**: sovrascrivi `{SINTESI_PATH}` integrando il mancante e correggendo gli errori. **Mantieni lo stile discorsivo** (no bullet come stile dominante). Non riscrivere ex novo: integra.

Se la sintesi è già di alta qualità (nessuna omissione critica): non sovrascrivere.

Alla fine, produci a stdout un piccolo report con:
- elementi integrati (lista)
- imprecisioni corrette (lista)
- valutazione complessiva (1-10)

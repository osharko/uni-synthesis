# Prompt — Amalgama finale del libro

> **Variabili:** `{CHAPTERS_DIR}`, `{OUTPUT_PATH}`.
> Singolo agente, eseguito dopo che tutte le sintesi per capitolo sono pronte.

---

Sei l'agente di amalgama. Unisci tutte le sintesi per capitolo presenti in `{CHAPTERS_DIR}` (file con suffisso `- sintesi.md`) in un unico file di studio `{OUTPUT_PATH}`.

## Regole

1. **NON riassumere ulteriormente.** Solo unisci e uniforma. Il lavoro di sintesi è già stato fatto.
2. Ordina i capitoli per numero.
3. Uniforma gli **heading**: `# <Titolo libro>` come titolo, `## Capitolo N — <Titolo>` per ogni capitolo, sottosezioni `###`.
4. Aggiungi **transizioni minime** tra capitoli solo dove servono per la fluidità (1-2 frasi al massimo).
5. Mantieni grassetto, corsivo, citazioni `«…»`, riepiloghi schematici di fine capitolo, **formule LaTeX** (`$...$`, `$$...$$`), blocchi `mermaid`/`tikz`, tabelle.
6. **A fine documento aggiungi:**
   - `## Mappa concettuale del libro` — schema/tabella (preferibilmente `mermaid`) che mostra le relazioni tra i concetti chiave dei vari capitoli.
   - `## Indice dei nomi propri` — elenco alfabetico con riferimento al capitolo.
   - Se il libro contiene matematica: `## Formulario` — raccolta delle formule chiave (LaTeX) con didascalia e capitolo di riferimento.

## Verifica

Prima di salvare, controlla che:
- ci siano tutti i capitoli (numero = file nella cartella)
- non ci siano duplicazioni di heading
- la mappa concettuale finale evidenzi davvero le relazioni (non sia un semplice indice)

#!/usr/bin/env python3
"""
quality_check.py — Controlla che la sintesi non abbia perso contenuti rispetto
all'originale, usando metriche deterministiche (token, ratio, copertura entità,
citazioni, capitoli) calcolate localmente. Nessun token LLM consumato a meno
di passare --llm.

Esempi:
  # confronto sintesi vs estratto
  python scripts/quality_check.py \\
      --original "books/MioLibro/MioLibro - estratto.md" \\
      --synthesis "books/MioLibro.md"

  # verifica anche capitolo per capitolo (cartella sintesi)
  python scripts/quality_check.py \\
      --original "books/MioLibro/MioLibro - estratto.md" \\
      --synthesis "books/MioLibro.md" \\
      --chapters-dir "books/MioLibro/"

  # con giudizio LLM (richiede ANTHROPIC_API_KEY)
  python scripts/quality_check.py ... --llm

Output: report markdown stampato a stdout o scritto con --out.
Exit code: 0 se passa, 2 se sotto soglia.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Italian stopwords (lista minima ma efficace per TF-IDF/copertura keyword)
# ---------------------------------------------------------------------------
STOPWORDS_IT = {
    "a","ad","al","alla","alle","allo","agli","ai","anche","ancora","altro","altra","altri","altre",
    "che","chi","ci","come","con","contro","cosa","cui","da","dal","dalla","dalle","dallo","dai",
    "degli","del","della","delle","dello","dei","di","dove","due","e","ed","è","era","erano","essere",
    "fino","fra","gli","grande","ha","hai","hanno","ho","i","il","in","io","la","le","li","lo",
    "loro","lui","ma","me","mi","molto","ne","nei","nel","nella","nelle","nello","negli","noi","non",
    "nostro","o","od","per","perché","perche","più","piu","può","puo","quale","quali","quando",
    "quanto","quanti","quanta","quante","quel","quella","quelle","quelli","quello","questa","queste",
    "questi","questo","se","sé","secondo","sembra","senza","si","sia","siamo","sono","stato","stesso",
    "su","sua","sue","suo","suoi","sui","sul","sulla","sulle","sullo","te","ti","tra","tre","tu",
    "tuo","tutti","tutto","tutta","tutte","un","una","uno","vi","voi","vostro","altrettanto",
    "questa","queste","poi","ogni","ovvero","cioè","cioe","oppure","così","cosi","quindi",
    "deve","devo","devi","fare","fatto","fanno","fa","stata","stati","state","essere","essendo",
    "mentre","sopra","sotto","prima","dopo","invece","mai","sempre","già","gia","ora","molti","molte",
    "alcuni","alcune","altrettanto","tale","tali","tanti","tanto","tutti","insieme","verso","loro",
}

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ']{3,}")
# Nomi propri = parole capitalizzate non di inizio frase. Euristica: dopo non-punto.
PROPER_NAME_RE = re.compile(
    r"(?<![\.\?\!]\s)\b([A-ZÀ-Ý][a-zà-ÿ']{2,}(?:\s+[A-ZÀ-Ý][a-zà-ÿ']{2,}){0,3})\b"
)
# Anno tipo 1995, 1995a, (1995), 1995-2010
YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
# Citazioni con virgolette tipografiche italiane « », “ ”, " "
QUOTE_RE = re.compile(r"[«\"“][^«\"“”»]{8,400}[»\"”]")
# Riferimenti bibliografici tipo (Autore, 2012) o "Cognome (2012)"
BIB_REF_RE = re.compile(
    r"\b[A-ZÀ-Ý][a-zà-ÿ']{2,}(?:\s+[A-ZÀ-Ý][a-zà-ÿ']{2,})?\s*[\(,]\s*(?:19|20)\d{2}[a-z]?\)?",
)
# Formule LaTeX: inline $...$ (non $$), block $$...$$, e environments \begin{equation}...
MATH_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)([^\$\n]{2,400}?)(?<!\$)\$(?!\$)")
MATH_BLOCK_RE = re.compile(r"\$\$([^\$]{2,2000}?)\$\$", re.DOTALL)
MATH_ENV_RE = re.compile(
    r"\\begin\{(equation|align|gather|multline|eqnarray|cases|bmatrix|pmatrix|vmatrix)\*?\}"
    r"(.+?)\\end\{\1\*?\}",
    re.DOTALL,
)
# Diagrammi mermaid / tikz (blocchi fenced)
DIAGRAM_RE = re.compile(r"```(mermaid|tikz|dot|plantuml)\s*\n(.+?)\n```", re.DOTALL)
PAGE_MARKER_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:#{1,4}\s+)?(?:CAPITOLO|Capitolo|CAP\.?|Cap\.?)\s+([IVXLCDM]+|\d+)",
    re.MULTILINE,
)


@dataclass
class Metrics:
    chars: int = 0
    words: int = 0
    unique_words: int = 0
    proper_names: list[str] = field(default_factory=list)
    years: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    bib_refs: list[str] = field(default_factory=list)
    chapters: list[str] = field(default_factory=list)
    top_keywords: list[tuple[str, int]] = field(default_factory=list)
    math_inline: list[str] = field(default_factory=list)
    math_block: list[str] = field(default_factory=list)
    diagrams: list[str] = field(default_factory=list)


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text)]


def compute_metrics(text: str, top_k: int = 100) -> Metrics:
    m = Metrics()
    m.chars = len(text)
    tokens = tokenize(text)
    m.words = len(tokens)
    content = [t for t in tokens if t not in STOPWORDS_IT]
    m.unique_words = len(set(content))
    counter = Counter(content)
    m.top_keywords = counter.most_common(top_k)
    m.proper_names = sorted(set(PROPER_NAME_RE.findall(text)))
    m.years = sorted(set(YEAR_RE.findall(text)))
    m.quotes = QUOTE_RE.findall(text)
    m.bib_refs = sorted(set(BIB_REF_RE.findall(text)))
    m.chapters = [match.group(1) for match in CHAPTER_HEADING_RE.finditer(text)]
    m.math_inline = [re.sub(r"\s+", " ", f).strip() for f in MATH_INLINE_RE.findall(text)]
    block_math = [re.sub(r"\s+", " ", f).strip() for f in MATH_BLOCK_RE.findall(text)]
    env_math = [re.sub(r"\s+", " ", f).strip()
                for _, f in MATH_ENV_RE.findall(text)]
    m.math_block = block_math + env_math
    m.diagrams = [kind for kind, _ in DIAGRAM_RE.findall(text)]
    return m


def coverage(reference: set, candidate: set) -> tuple[float, list]:
    """% di elementi del reference presenti nel candidate. Restituisce (ratio, missing)."""
    if not reference:
        return 1.0, []
    missing = sorted(reference - candidate)
    found = len(reference) - len(missing)
    return found / len(reference), missing


def keyword_coverage(orig_kw: list[tuple[str, int]],
                     synth_kw: list[tuple[str, int]],
                     top_n: int = 50) -> tuple[float, list[str]]:
    """% delle top-N keyword dell'originale presenti almeno una volta nella sintesi."""
    orig_top = {w for w, _ in orig_kw[:top_n]}
    synth_set = {w for w, _ in synth_kw}
    return coverage(orig_top, synth_set)


def quote_coverage(orig_quotes: list[str], synth_text: str) -> tuple[float, list[str]]:
    """% di citazioni dell'originale di cui almeno 30 caratteri compaiono nella sintesi."""
    if not orig_quotes:
        return 1.0, []
    synth_lower = synth_text.lower()
    found, missing = 0, []
    for q in orig_quotes:
        core = re.sub(r"\s+", " ", q.strip("«\"“”»").strip())[:80].lower()
        if len(core) < 20:
            continue
        if core[:30] in synth_lower or core[-30:] in synth_lower:
            found += 1
        else:
            missing.append(q.strip())
    total = max(1, len(orig_quotes))
    return found / total, missing


def fmt_section(title: str, lines: list[str]) -> str:
    return f"### {title}\n\n" + ("\n".join(lines) if lines else "_nessun problema_") + "\n"


def evaluate(original: Path, synthesis: Path, ratio_min: int, ratio_max: int,
             threshold: float) -> dict:
    orig_text = original.read_text(encoding="utf-8")
    synth_text = synthesis.read_text(encoding="utf-8")

    orig = compute_metrics(orig_text)
    synth = compute_metrics(synth_text)

    ratio = orig.words / max(1, synth.words)  # rapporto orig:synth (es. 6 = 1/6)
    ratio_ok = ratio_min <= ratio <= ratio_max

    name_cov, missing_names = coverage(set(orig.proper_names), set(synth.proper_names))
    year_cov, missing_years = coverage(set(orig.years), set(synth.years))
    bib_cov, missing_bib = coverage(set(orig.bib_refs), set(synth.bib_refs))
    kw_cov, missing_kw = keyword_coverage(orig.top_keywords, synth.top_keywords)
    qt_cov, missing_quotes = quote_coverage(orig.quotes, synth_text)

    chap_orig = set(orig.chapters)
    chap_synth = set(synth.chapters)
    chap_cov, missing_chap = coverage(chap_orig, chap_synth)

    # Copertura formule matematiche: si confronta sul conteggio totale,
    # perché le formule non sono identificatori univoci (la stessa espressione
    # può comparire più volte in forme equivalenti).
    orig_math_total = len(orig.math_inline) + len(orig.math_block)
    synth_math_total = len(synth.math_inline) + len(synth.math_block)
    if orig_math_total == 0:
        math_cov = 1.0  # nessuna formula nell'originale → non penalizzare
    else:
        math_cov = min(1.0, synth_math_total / orig_math_total)

    # Score complessivo: media pesata.
    # I pesi si ridistribuiscono quando una metrica non è applicabile
    # (es. originale senza formule → il peso math va in proporzione su altre).
    base_weights = {"keywords": 0.18, "proper_names": 0.22, "quotes": 0.18,
                    "bib_refs": 0.08, "chapters": 0.18, "years": 0.04,
                    "math": 0.12}
    if orig_math_total == 0:
        # ridistribuisci il peso math proporzionalmente
        extra = base_weights.pop("math")
        total = sum(base_weights.values())
        for k in base_weights:
            base_weights[k] += extra * base_weights[k] / total
    weights = base_weights
    score = (kw_cov * weights["keywords"]
             + name_cov * weights["proper_names"]
             + qt_cov * weights["quotes"]
             + bib_cov * weights["bib_refs"]
             + chap_cov * weights["chapters"]
             + year_cov * weights["years"]
             + (math_cov * weights.get("math", 0)))

    return {
        "original_path": str(original),
        "synthesis_path": str(synthesis),
        "original": {"words": orig.words, "chars": orig.chars,
                     "unique_words": orig.unique_words,
                     "proper_names": len(orig.proper_names),
                     "years": len(orig.years), "quotes": len(orig.quotes),
                     "bib_refs": len(orig.bib_refs), "chapters": len(orig.chapters),
                     "math_inline": len(orig.math_inline),
                     "math_block": len(orig.math_block),
                     "diagrams": len(orig.diagrams)},
        "synthesis": {"words": synth.words, "chars": synth.chars,
                      "unique_words": synth.unique_words,
                      "proper_names": len(synth.proper_names),
                      "years": len(synth.years), "quotes": len(synth.quotes),
                      "bib_refs": len(synth.bib_refs), "chapters": len(synth.chapters),
                      "math_inline": len(synth.math_inline),
                      "math_block": len(synth.math_block),
                      "diagrams": len(synth.diagrams)},
        "ratio": ratio,
        "ratio_ok": ratio_ok,
        "ratio_target": f"1/{ratio_min}..1/{ratio_max}",
        "coverage": {
            "keywords": kw_cov, "proper_names": name_cov, "quotes": qt_cov,
            "bib_refs": bib_cov, "chapters": chap_cov, "years": year_cov,
            "math": math_cov,
        },
        "missing": {
            "keywords": missing_kw[:25],
            "proper_names": missing_names[:30],
            "quotes": missing_quotes[:10],
            "bib_refs": missing_bib[:20],
            "chapters": missing_chap,
            "years": missing_years[:20],
        },
        "score": score,
        "passed": score >= threshold and ratio_ok and not missing_chap,
    }


def per_chapter_check(chapters_dir: Path, ratio_min: int, ratio_max: int,
                      threshold: float) -> list[dict]:
    pairs = []
    estratti = sorted(chapters_dir.glob("* - cap_*_*- estratto.md"))
    if not estratti:
        # fallback: pattern più libero
        estratti = sorted(chapters_dir.glob("*cap*estratto*.md"))
    for est in estratti:
        # candidato sintesi: stesso prefisso ma "- sintesi.md"
        synth_guess = est.with_name(est.name.replace(" - estratto.md", " - sintesi.md"))
        if not synth_guess.exists():
            # ripiego: sostituisce cap_NN_xxx con capNN
            m = re.search(r"cap_(\d+)_", est.name)
            if m:
                num = m.group(1)
                alt = list(est.parent.glob(f"* - cap{num} - sintesi.md"))
                if alt:
                    synth_guess = alt[0]
        if not synth_guess.exists():
            pairs.append({"chapter": est.name, "synthesis_path": None,
                          "passed": False, "missing_synthesis": True})
            continue
        pairs.append(evaluate(est, synth_guess, ratio_min, ratio_max, threshold)
                     | {"chapter": est.name})
    return pairs


def format_report(result: dict, per_chapter: list[dict] | None) -> str:
    cov = result["coverage"]
    miss = result["missing"]
    lines = [
        f"# Quality check report",
        "",
        f"- **Originale:** `{result['original_path']}`",
        f"- **Sintesi:**   `{result['synthesis_path']}`",
        "",
        "## Metriche",
        "",
        "| Metrica | Originale | Sintesi |",
        "|---|---:|---:|",
        f"| Parole | {result['original']['words']:,} | {result['synthesis']['words']:,} |",
        f"| Caratteri | {result['original']['chars']:,} | {result['synthesis']['chars']:,} |",
        f"| Vocaboli unici | {result['original']['unique_words']:,} | "
            f"{result['synthesis']['unique_words']:,} |",
        f"| Nomi propri | {result['original']['proper_names']} | "
            f"{result['synthesis']['proper_names']} |",
        f"| Citazioni | {result['original']['quotes']} | "
            f"{result['synthesis']['quotes']} |",
        f"| Rif. bibliografici | {result['original']['bib_refs']} | "
            f"{result['synthesis']['bib_refs']} |",
        f"| Capitoli rilevati | {result['original']['chapters']} | "
            f"{result['synthesis']['chapters']} |",
        f"| Formule LaTeX inline `$…$` | {result['original']['math_inline']} | "
            f"{result['synthesis']['math_inline']} |",
        f"| Formule LaTeX block `$$…$$` | {result['original']['math_block']} | "
            f"{result['synthesis']['math_block']} |",
        f"| Diagrammi (mermaid/tikz) | {result['original']['diagrams']} | "
            f"{result['synthesis']['diagrams']} |",
        "",
        f"**Ratio di sintesi:** 1/{result['ratio']:.2f}  "
            f"(target {result['ratio_target']})  → "
            f"{'✅' if result['ratio_ok'] else '⚠️ FUORI RANGE'}",
        "",
        "## Copertura",
        "",
        "| Aspetto | Copertura |",
        "|---|---:|",
        f"| Keyword (top-50) | {cov['keywords']:.1%} |",
        f"| Nomi propri | {cov['proper_names']:.1%} |",
        f"| Citazioni letterali | {cov['quotes']:.1%} |",
        f"| Rif. bibliografici | {cov['bib_refs']:.1%} |",
        f"| Capitoli | {cov['chapters']:.1%} |",
        f"| Anni / date | {cov['years']:.1%} |",
        f"| Formule matematiche | {cov['math']:.1%}"
            + (" (nessuna formula nell'originale)"
               if result['original']['math_inline'] + result['original']['math_block'] == 0
               else "") + " |",
        "",
        f"**Score complessivo:** {result['score']:.1%}",
        "",
        f"**Esito:** {'✅ PASSED' if result['passed'] else '❌ FAILED — vedi sezioni mancanti'}",
        "",
        "## Elementi mancanti nella sintesi",
        "",
        fmt_section("Capitoli mancanti", miss["chapters"]),
        fmt_section("Keyword importanti mancanti (top-25)",
                    [f"- `{w}`" for w in miss["keywords"]]),
        fmt_section("Nomi propri non presenti (primi 30)",
                    [f"- {n}" for n in miss["proper_names"]]),
        fmt_section("Citazioni non presenti (prime 10)",
                    [f"- {q[:200]}" for q in miss["quotes"]]),
        fmt_section("Riferimenti bibliografici non presenti (primi 20)",
                    [f"- {r}" for r in miss["bib_refs"]]),
        fmt_section("Anni non citati (primi 20)",
                    [f"- {y}" for y in miss["years"]]),
    ]
    if per_chapter:
        lines += ["## Per capitolo", ""]
        lines.append("| Capitolo | Sintesi | Ratio | Keyword | Nomi | Citaz. | Score |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for c in per_chapter:
            if c.get("missing_synthesis"):
                lines.append(f"| {c['chapter']} | ⚠️ assente | – | – | – | – | – |")
                continue
            lines.append(
                f"| {c['chapter']} | ✅ | 1/{c['ratio']:.1f} | "
                f"{c['coverage']['keywords']:.0%} | "
                f"{c['coverage']['proper_names']:.0%} | "
                f"{c['coverage']['quotes']:.0%} | "
                f"{c['score']:.0%} |"
            )
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM opzionale (giudizio semantico finale)
# ---------------------------------------------------------------------------
def llm_judgement(result: dict, original: str, synthesis: str, model: str) -> str:
    try:
        from anthropic import Anthropic
    except ImportError:
        return "_(anthropic non installato — installa con `pip install anthropic`)_"
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "_(ANTHROPIC_API_KEY non settato — skip giudizio LLM)_"

    missing_summary = []
    for k in ("keywords", "proper_names", "quotes", "bib_refs", "chapters"):
        items = result["missing"][k]
        if items:
            missing_summary.append(f"- **{k}**: {', '.join(map(str, items[:15]))}")

    prompt = f"""Sei un revisore di sintesi di studio approfondito. Hai metriche oggettive di un
quality check e devi giudicare SEMANTICAMENTE se le omissioni segnalate sono reali problemi
o falsi positivi (sinonimi, parafrasi, riformulazioni).

## Score deterministico: {result['score']:.1%}
## Elementi che il check ha segnalato come mancanti:
{chr(10).join(missing_summary) or '(nessuno)'}

## Estratto dei primi 4000 caratteri della sintesi (per contesto):
{synthesis[:4000]}

Rispondi in italiano e in markdown, con queste sezioni:
1. **Vere omissioni** (cose realmente assenti e importanti per lo studio del testo)
2. **Falsi positivi** (presenti come parafrasi/sinonimi)
3. **Azioni consigliate** (cosa integrare, max 5 voci concrete)
"""
    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def main() -> None:
    ap = argparse.ArgumentParser(description="Quality check sintesi vs originale.")
    ap.add_argument("--original", required=True, type=Path, help="Estratto originale")
    ap.add_argument("--synthesis", required=True, type=Path, help="Sintesi (amalgama)")
    ap.add_argument("--chapters-dir", type=Path, default=None,
                    help="Cartella con sintesi per capitolo (opzionale)")
    ap.add_argument("--ratio-min", type=int, default=int(os.environ.get("QC_RATIO_MIN", 5)))
    ap.add_argument("--ratio-max", type=int, default=int(os.environ.get("QC_RATIO_MAX", 8)))
    ap.add_argument("--threshold", type=float,
                    default=float(os.environ.get("QC_COVERAGE_THRESHOLD", 0.75)))
    ap.add_argument("--out", type=Path, default=None, help="Salva report markdown qui")
    ap.add_argument("--json", action="store_true", help="Stampa anche JSON crudo")
    ap.add_argument("--llm", action="store_true",
                    help="Aggiungi giudizio LLM (Anthropic, richiede API key)")
    ap.add_argument("--llm-model", default=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"))
    args = ap.parse_args()

    if not args.original.exists():
        sys.exit(f"Errore: originale non trovato: {args.original}")
    if not args.synthesis.exists():
        sys.exit(f"Errore: sintesi non trovata: {args.synthesis}")

    result = evaluate(args.original, args.synthesis,
                      args.ratio_min, args.ratio_max, args.threshold)
    per_chapter = (per_chapter_check(args.chapters_dir, args.ratio_min,
                                     args.ratio_max, args.threshold)
                   if args.chapters_dir else None)

    report = format_report(result, per_chapter)
    if args.llm:
        synth_text = args.synthesis.read_text(encoding="utf-8")
        orig_text = args.original.read_text(encoding="utf-8")
        verdict = llm_judgement(result, orig_text, synth_text, args.llm_model)
        report += "\n## Giudizio LLM\n\n" + verdict + "\n"

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Report scritto in: {args.out}")
    else:
        print(report)

    if args.json:
        print("\n--- JSON ---")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    sys.exit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()

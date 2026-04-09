"""
ProductComparatorAgent
Pipeline: legge le specifiche tecniche del nostro prodotto e dei prodotti competitor
(da DB + PDF scaricati) → prompt AI strutturato → tabella comparativa + verdict.

Il modello NON usa memoria di training: tutte le specifiche vengono iniettate nel prompt.
"""
from __future__ import annotations

import json
import re
import anthropic
from openai import OpenAI
from datetime import datetime, timezone

from config.settings import settings
from config.logging import get_logger
from config.http_client import scrape_get

logger = get_logger("agents.product_comparator")

AI_MAX_TOKENS = 6000
MAX_TEXT = 6000          # max caratteri di testo inviati per prodotto
MAX_PDF_TEXT = 8000      # max caratteri estratti da PDF

SYSTEM_PROMPT = """Sei un ingegnere tecnico esperto in piattaforme aeree di lavoro (AWP / aerial work platforms).

REGOLA FONDAMENTALE: Basa il confronto ESCLUSIVAMENTE sui dati tecnici forniti nel messaggio.
NON integrare con la tua memoria di training. Se un dato non è presente, scrivi "n/d".

Restituisci SOLO JSON valido, senza markdown, senza backtick, senza testo fuori dal JSON."""

COMPARISON_SCHEMA = """{
  "summary": "Sintesi del confronto in 3-4 frasi",
  "comparison_table": [
    {
      "feature": "Nome caratteristica (es: Altezza di lavoro)",
      "our_value": "Valore nostro prodotto",
      "competitors": {"Nome modello concorrente": "Valore", "...": "..."},
      "advantage": "ours|theirs|neutral",
      "note": "Commento breve facoltativo"
    }
  ],
  "per_competitor": [
    {
      "name": "Nome modello concorrente",
      "competitor_name": "Nome azienda concorrente",
      "verdict": "forte|medio|debole",
      "score": 6,
      "strengths": ["punto di forza basato sui dati"],
      "weaknesses": ["debolezza rispetto al nostro prodotto"],
      "insights": "Analisi sintetica basata solo sui dati forniti"
    }
  ],
  "recommendations": [
    {
      "priority": "alta|media|bassa",
      "action": "Azione commerciale/marketing concreta",
      "rationale": "Motivazione basata sui dati"
    }
  ]
}"""


# ── Lettura PDF locale ──────────────────────────────────────────────────────────

def _read_pdf_text(filepath: str) -> str:
    """Estrae testo da un PDF scaricato localmente. Ritorna stringa vuota se fallisce."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(filepath)
        parts = []
        for page in doc:
            parts.append(page.get_text())
        return "\n".join(parts)[:MAX_PDF_TEXT]
    except ImportError:
        logger.debug("PyMuPDF non installato — skip lettura PDF")
    except Exception as e:
        logger.warning("Errore lettura PDF %s: %s", filepath, e)
    return ""


def _read_pdf_from_url(url: str) -> str:
    """Scarica e legge un PDF da URL in memoria."""
    try:
        import fitz
        import io
        resp = scrape_get(url, timeout=20)
        resp.raise_for_status()
        doc = fitz.open(stream=io.BytesIO(resp.content), filetype="pdf")
        parts = [page.get_text() for page in doc]
        return "\n".join(parts)[:MAX_PDF_TEXT]
    except ImportError:
        logger.debug("PyMuPDF non installato — skip PDF URL")
    except Exception as e:
        logger.warning("Errore lettura PDF URL %s: %s", url, e)
    return ""


# ── Costruzione blocchi testo per ogni prodotto ─────────────────────────────────

def _format_specs(tech_specs_json: str) -> str:
    """Formatta il JSON di specifiche come testo tabulare."""
    try:
        specs = json.loads(tech_specs_json) if tech_specs_json else []
    except Exception:
        return ""
    if not specs:
        return ""
    lines = []
    for s in specs:
        key = s.get("key", "")
        val = s.get("value", "")
        unit = s.get("unit", "")
        lines.append(f"  {key}: {val}{' ' + unit if unit else ''}")
    return "\n".join(lines)


def _build_own_product_block(own_product) -> str:
    """Costruisce il blocco testo per il nostro prodotto."""
    parts = [f"=== NOSTRO PRODOTTO: {own_product.name} ==="]

    if own_product.product_line:
        parts.append(f"Linea: {own_product.product_line}")
    if own_product.category:
        parts.append(f"Categoria: {own_product.category}")
    if own_product.description:
        parts.append(f"Descrizione: {own_product.description}")
    if own_product.working_height:
        parts.append(f"Altezza di lavoro: {own_product.working_height} m")

    # Specifiche strutturate
    spec_text = _format_specs(own_product.tech_specs)
    if spec_text:
        parts.append("[Specifiche tecniche strutturate]")
        parts.append(spec_text)

    # Riepilogo testuale
    if own_product.tech_summary:
        parts.append("[Riepilogo specifiche]")
        parts.append(own_product.tech_summary[:MAX_TEXT])

    # Prova a leggere il PDF
    pdf_text = ""
    if own_product.brochure_filename:
        import os
        pdf_path = os.path.join("storage", "own_brochures", own_product.brochure_filename)
        if os.path.exists(pdf_path):
            pdf_text = _read_pdf_text(pdf_path)
    if not pdf_text and own_product.brochure_url:
        pdf_text = _read_pdf_from_url(own_product.brochure_url)
    if pdf_text:
        parts.append("[Testo estratto da PDF scheda tecnica]")
        parts.append(pdf_text)

    return "\n".join(parts)


def _build_competitor_product_block(cp) -> str:
    """Costruisce il blocco testo per un prodotto concorrente."""
    competitor_name = cp.competitor.name if cp.competitor else "Concorrente"
    model_name = cp.name or "Modello sconosciuto"

    parts = [f"=== PRODOTTO CONCORRENTE: {model_name} (di {competitor_name}) ==="]

    if cp.product_line:
        parts.append(f"Linea: {cp.product_line}")
    if cp.category:
        parts.append(f"Categoria: {cp.category}")

    # Specifiche strutturate
    spec_text = _format_specs(cp.tech_specs)
    if spec_text:
        parts.append("[Specifiche tecniche strutturate]")
        parts.append(spec_text)

    # Riepilogo testuale
    if cp.tech_summary:
        parts.append("[Riepilogo specifiche]")
        parts.append(cp.tech_summary[:MAX_TEXT])

    # Prova a leggere il PDF
    pdf_text = ""
    if cp.brochure_filename:
        import os
        competitor_id = cp.competitor_id
        pdf_path = os.path.join("storage", "brochures", str(competitor_id), cp.brochure_filename)
        if os.path.exists(pdf_path):
            pdf_text = _read_pdf_text(pdf_path)
    if not pdf_text and cp.brochure_url:
        pdf_text = _read_pdf_from_url(cp.brochure_url)
    if pdf_text:
        parts.append("[Testo estratto da PDF scheda tecnica]")
        parts.append(pdf_text)

    return "\n".join(parts)


def _build_prompt(own_product, competitor_products: list) -> str:
    parts = []

    parts.append("ISTRUZIONI:")
    parts.append("Confronta il nostro prodotto con i prodotti concorrenti elencati.")
    parts.append("Usa SOLO i dati tecnici riportati qui sotto. Non inventare valori mancanti.")
    parts.append("")

    # Nostro prodotto
    if own_product:
        parts.append(_build_own_product_block(own_product))
    else:
        parts.append("=== NOSTRO PRODOTTO: non specificato — basa il confronto solo sui dati concorrenti ===")
    parts.append("")

    # Prodotti concorrenti
    parts.append("=== PRODOTTI CONCORRENTI DA CONFRONTARE ===")
    parts.append("")
    for cp in competitor_products:
        parts.append(_build_competitor_product_block(cp))
        parts.append("")

    parts.append("=== OUTPUT RICHIESTO ===")
    parts.append("Restituisci SOLO questo JSON (niente testo fuori):")
    parts.append(COMPARISON_SCHEMA)

    return "\n".join(parts)


# ── Chiamate AI ─────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict | None:
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        return json.loads(raw[start:end])
    except json.JSONDecodeError:
        return None


def _try_anthropic(prompt: str) -> tuple[dict | None, str]:
    if not settings.anthropic_api_key or settings.anthropic_api_key == "your_anthropic_api_key_here":
        return None, ""
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=AI_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_json(msg.content[0].text), "anthropic"
    except Exception:
        logger.warning("Errore Anthropic in comparazione prodotti", exc_info=True)
        return None, ""


def _try_openai(prompt: str) -> tuple[dict | None, str]:
    if not settings.openai_compatible_api_key:
        return None, ""
    try:
        client = OpenAI(
            base_url=settings.openai_compatible_base_url,
            api_key=settings.openai_compatible_api_key,
        )
        resp = client.chat.completions.create(
            model=settings.openai_compatible_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=AI_MAX_TOKENS,
        )
        return _parse_json(resp.choices[0].message.content or ""), "openai"
    except Exception:
        logger.warning("Errore OpenAI in comparazione prodotti", exc_info=True)
        return None, ""


def _fallback_result(own_product, competitor_products: list) -> dict:
    own_name = own_product.name if own_product else "n/d"
    return {
        "summary": "Analisi non disponibile: configura una chiave API in Impostazioni.",
        "comparison_table": [],
        "per_competitor": [
            {
                "name": cp.name,
                "competitor_name": cp.competitor.name if cp.competitor else "",
                "verdict": "medio", "score": 5,
                "strengths": [], "weaknesses": [], "insights": "",
            }
            for cp in competitor_products
        ],
        "recommendations": [],
    }


# ── Entry point ──────────────────────────────────────────────────────────────────

def run_comparison(own_product, competitor_products: list) -> dict:
    """
    Esegue la comparazione prodotti:
    1. Costruisce il prompt con le specifiche di tutti i prodotti
    2. Chiama AI (provider primario → fallback)
    3. Restituisce dict strutturato
    """
    if not competitor_products:
        raise ValueError("Seleziona almeno un prodotto concorrente da confrontare.")

    prompt = _build_prompt(own_product, competitor_products)
    logger.info(
        "Avvio comparazione: '%s' vs %d prodotti concorrenti",
        own_product.name if own_product else "n/d",
        len(competitor_products),
    )

    # Provider primario
    result, provider = (
        _try_anthropic(prompt)
        if settings.ai_primary_provider == "anthropic"
        else _try_openai(prompt)
    )

    # Fallback
    if not result:
        fallback_fn = _try_openai if settings.ai_primary_provider == "anthropic" else _try_anthropic
        result, provider = fallback_fn(prompt)

    if not result:
        result = _fallback_result(own_product, competitor_products)
        provider = "fallback"

    result["generated_by"] = provider
    logger.info("Comparazione completata via %s", provider)
    return result


# ── Scraping scheda prodotto da celaplatforms.com ───────────────────────────────

def scrape_own_product_page(url: str) -> dict:
    """
    Tenta di estrarre info di base da una pagina prodotto celaplatforms.com.
    Restituisce dict con: name, description, page_url, tech_summary
    Il sito usa JS rendering quindi il risultato è spesso parziale.
    """
    try:
        from bs4 import BeautifulSoup
        resp = scrape_get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["style", "script"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        # Prova a estrarre il titolo dalla pagina
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
        elif soup.title:
            title = soup.title.get_text(strip=True).split("|")[0].strip()

        # Cerca link PDF
        brochure_url = ""
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".pdf" in href.lower():
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                brochure_url = href
                break

        return {
            "name": title,
            "description": "",
            "page_url": url,
            "tech_summary": text[:3000],
            "brochure_url": brochure_url,
        }
    except Exception as e:
        logger.warning("Errore scraping %s: %s", url, e)
        return {"name": "", "description": "", "page_url": url, "tech_summary": "", "brochure_url": ""}

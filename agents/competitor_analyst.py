"""
CompetitorAnalyst Agent
Pipeline: scraping siti → ricerca web (Tavily) → prompt AI strutturato.

Il modello riceve SOLO dati raccolti da fonti esterne verificabili.
Non gli viene mai chiesto di attingere alla propria memoria di training.
"""
from __future__ import annotations
import json
import re
import httpx
from bs4 import BeautifulSoup
import anthropic
from openai import OpenAI
from datetime import datetime, timedelta, timezone
from config.settings import settings
from config.logging import get_logger
from config.http_client import scrape_get

logger = get_logger("agents.competitor_analyst")

MAX_SCRAPED_CONTENT = 4000
MAX_SEARCH_CONTENT = 600
MAX_PROMPT_SCRAPED = 3000
SCRAPED_PREVIEW = 300
HTTP_TIMEOUT = 12
AI_MAX_TOKENS = 4096

# Pattern per rilevare URL di profili social (escludi pagine generiche)
_SOCIAL_PATTERNS: dict[str, re.Pattern] = {
    "linkedin": re.compile(
        r'https?://(?:www\.)?linkedin\.com/company/[\w\-\.%]+',
        re.IGNORECASE,
    ),
    "facebook": re.compile(
        r'https?://(?:www\.)?(?:facebook|fb)\.com/'
        r'(?!share(?:r)?/|pages/create|hashtag|groups/create|watch|events|marketplace)'
        r'[\w\.\-]{3,}',
        re.IGNORECASE,
    ),
    "instagram": re.compile(
        r'https?://(?:www\.)?instagram\.com/'
        r'(?!p/|reel/|reels/|explore/|stories/|accounts/)'
        r'[\w\.]{2,}',
        re.IGNORECASE,
    ),
}


def _find_social_urls(text: str) -> dict[str, str]:
    """Estrae URL di profili social dal testo, uno per piattaforma."""
    found: dict[str, str] = {}
    for platform, pattern in _SOCIAL_PATTERNS.items():
        match = pattern.search(text)
        if match:
            found[platform] = match.group(0).rstrip("/")
    return found


def _search_social_profiles(name: str, sector: str = "") -> dict[str, str]:
    """
    Cerca i profili social ufficiali del competitor tramite Tavily.
    Ritorna un dict {platform: url} con i profili trovati.
    """
    if not settings.tavily_api_key or settings.tavily_api_key == "tvly-your_key_here":
        return {}

    sector_str = f" {sector}" if sector else ""
    query = f'"{name}"{sector_str} linkedin.com/company OR facebook.com OR instagram.com profilo ufficiale'
    results = _search_tavily(query)

    found: dict[str, str] = {}
    for r in results:
        # Prima controlla l'URL del risultato stesso (es: linkedin.com/company/nome)
        for platform, url in _find_social_urls(r.get("url", "")).items():
            if platform not in found:
                found[platform] = url
        # Poi cerca nel testo del risultato
        snippet = r.get("content", "") + " " + r.get("title", "")
        for platform, url in _find_social_urls(snippet).items():
            if platform not in found:
                found[platform] = url

    return found


# ── Sistema prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Sei un analista strategico specializzato in social media marketing competitivo.

REGOLA FONDAMENTALE: Basa la tua analisi ESCLUSIVAMENTE sui dati forniti nel messaggio.
NON usare la tua memoria di training per integrare informazioni sui competitor.
Se un'informazione non è presente nei dati forniti, dichiaralo esplicitamente con "dato non disponibile".
Questo garantisce che l'analisi sia accurata e verificabile.

Rispondi SOLO con JSON valido, senza markdown, senza backtick, senza testo fuori dal JSON."""


ANALYSIS_SCHEMA = """{
  "summary": "Sintesi esecutiva (2-3 frasi) basata SOLO sui dati raccolti",
  "landscape": "Panorama competitivo (4-6 frasi) basato SOLO sui dati raccolti",
  "data_quality": "commento sulla qualità e completezza dei dati raccolti per questa analisi",
  "per_competitor": [
    {
      "name": "Nome concorrente",
      "verdict": "forte|medio|debole",
      "social_score": 7,
      "data_sources": ["sito_web", "tavily", "manuale"],
      "insights": "Analisi basata sui dati raccolti. Se i dati sono scarsi, dillo.",
      "differentiator": "Differenziatore rilevato dai dati o 'dato non disponibile'",
      "vulnerability": "Vulnerabilità rilevata dai dati o 'dato non disponibile'"
    }
  ],
  "opportunities": ["Opportunità concreta supportata dai dati raccolti"],
  "threats": ["Minaccia concreta supportata dai dati raccolti"],
  "recommendations": [
    {
      "priority": "alta|media|bassa",
      "action": "Azione specifica",
      "rationale": "Motivazione basata sui dati"
    }
  ],
  "content_gaps": ["Gap identificato nei contenuti dei competitor"]
}"""


# ── Raccolta dati web ────────────────────────────────────────────────────────────

def _scrape_url(url: str) -> str:
    """Scarica e pulisce il testo di una pagina web."""
    try:
        resp = scrape_get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["style", "script"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return text[:MAX_SCRAPED_CONTENT]
    except Exception as e:
        logger.warning("Errore scraping %s: %s", url, e)
        return f"[errore scraping: {e}]"


def _search_tavily(query: str) -> list[dict]:
    """Cerca su Tavily e restituisce lista di {title, url, content}."""
    if not settings.tavily_api_key or settings.tavily_api_key == "tvly-your_key_here":
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        resp = client.search(query=query, max_results=4, search_depth="basic")
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:MAX_SEARCH_CONTENT],
            }
            for r in resp.get("results", [])
        ]
    except Exception:
        logger.warning("Errore ricerca Tavily per: %s", query)
        return []


def _gather_competitor_data(competitor) -> dict:
    """
    Raccoglie dati freschi per un singolo competitor:
    1. Scraping sito web (se URL presente e non aggiornato di recente)
    2. Ricerca Tavily su strategia social
    3. Ricerca Tavily dedicata ai profili social mancanti
    Restituisce un dict con tutto il materiale raccolto + found_socials.
    """
    gathered: dict = {"scraped": "", "search_results": [], "sources": [], "found_socials": {}}

    # 1. Scraping sito
    if competitor.website:
        needs_scrape = (
            not competitor.scraped_content
            or not competitor.last_scraped_at
            or (
                datetime.now(timezone.utc).replace(tzinfo=None)
                - (competitor.last_scraped_at.replace(tzinfo=None) if competitor.last_scraped_at else datetime.min)
            ) > timedelta(days=7)
        )
        if needs_scrape:
            scraped = _scrape_url(competitor.website)
            gathered["scraped"] = scraped
            gathered["sources"].append("sito_web")
            # Cerca URL social nel testo del sito (spesso sono in footer/header)
            found = _find_social_urls(scraped)
            gathered["found_socials"].update(found)
        elif competitor.scraped_content:
            gathered["scraped"] = competitor.scraped_content[:MAX_SCRAPED_CONTENT]
            gathered["sources"].append("sito_web_cache")
            found = _find_social_urls(competitor.scraped_content)
            gathered["found_socials"].update(found)

    # 2. Ricerca Tavily — due query mirate sulla strategia
    tavily_ok = bool(settings.tavily_api_key and settings.tavily_api_key != "tvly-your_key_here")
    if tavily_ok:
        sector = f" {competitor.sector}" if competitor.sector else ""
        queries = [
            f'"{competitor.name}"{sector} social media marketing strategy',
            f'"{competitor.name}" LinkedIn Facebook Instagram contenuti',
        ]
        for q in queries:
            results = _search_tavily(q)
            gathered["search_results"].extend(results)
            # Cerca URL social anche nei risultati Tavily
            for r in results:
                for platform, url in _find_social_urls(r.get("url", "") + " " + r.get("content", "")).items():
                    if platform not in gathered["found_socials"]:
                        gathered["found_socials"][platform] = url
        if gathered["search_results"]:
            gathered["sources"].append("tavily")

    # 3. Se mancano profili social, cerca specificamente con Tavily
    existing_platforms = {s.platform for s in competitor.socials if s.profile_url}
    missing_platforms = {"linkedin", "facebook", "instagram"} - existing_platforms - set(gathered["found_socials"])
    if missing_platforms and tavily_ok:
        logger.info("Cercando profili social mancanti per %s: %s", competitor.name, missing_platforms)
        social_found = _search_social_profiles(competitor.name, competitor.sector or "")
        for platform, url in social_found.items():
            if platform in missing_platforms and platform not in gathered["found_socials"]:
                gathered["found_socials"][platform] = url
        if social_found:
            gathered["sources"].append("tavily_social")

    if gathered["found_socials"]:
        logger.info("Profili social trovati per %s: %s", competitor.name, gathered["found_socials"])

    return gathered


# ── Costruzione prompt ───────────────────────────────────────────────────────────

def _build_prompt(competitors: list, company_ctx, web_data: dict[int, dict]) -> str:
    parts = []

    # Contesto aziendale nostro
    if company_ctx:
        parts.append("=== LA NOSTRA AZIENDA ===")
        parts.append(company_ctx.to_prompt_block())
        parts.append("")

    # Dati per ogni competitor
    parts.append("=== DATI RACCOLTI SUI COMPETITOR ===")
    parts.append("(Fonte: scraping siti web + ricerca Tavily + inserimento manuale utente)")
    parts.append("")

    for c in competitors:
        data = web_data.get(c.id, {})
        sources = data.get("sources", [])

        parts.append(f"{'='*60}")
        parts.append(f"COMPETITOR: {c.name}")
        parts.append(f"Fonti disponibili: {', '.join(sources) if sources else 'solo dati manuali'}")
        parts.append("")

        # Dati inseriti manualmente dall'utente
        manual_fields = [
            ("Settore", c.sector),
            ("Descrizione", c.description),
            ("Punti di forza", c.strengths),
            ("Punti di debolezza", c.weaknesses),
            ("Strategia contenuti", c.content_strategy),
            ("Target audience", c.target_audience),
            ("Tono di voce", c.tone_of_voice),
            ("Argomenti forti", c.unique_topics),
            ("Frequenza posting", c.posting_frequency),
        ]
        manual_present = [(k, v) for k, v in manual_fields if v and v.strip()]
        if manual_present:
            parts.append("[DATI MANUALI UTENTE]")
            for key, val in manual_present:
                parts.append(f"  {key}: {val}")

        # Dati social inseriti manualmente
        if c.socials:
            parts.append("[DATI SOCIAL MANUALI]")
            for s in c.socials:
                row = f"  {s.platform.upper()}: followers={s.followers or '?'} like_medi={s.avg_likes or '?'} commenti_medi={s.avg_comments or '?'}"
                if s.posting_days:
                    row += f" giorni={s.posting_days}"
                if s.content_types:
                    row += f" formati={s.content_types}"
                parts.append(row)
                if s.notes:
                    parts.append(f"    note: {s.notes}")

        # Osservazioni manuali
        if c.observations:
            parts.append("[OSSERVAZIONI MANUALI]")
            for obs in c.observations[:6]:
                parts.append(f"  [{obs.category.upper()}] {obs.content}")

        # Contenuto sito web scrapato
        if data.get("scraped"):
            parts.append("[SITO WEB — TESTO ESTRATTO]")
            parts.append(data["scraped"][:MAX_PROMPT_SCRAPED])

        # Risultati ricerca web
        if data.get("search_results"):
            parts.append("[RICERCA WEB — RISULTATI RECENTI]")
            for r in data["search_results"][:6]:
                parts.append(f"  Titolo: {r['title']}")
                parts.append(f"  URL: {r['url']}")
                parts.append(f"  Estratto: {r['content']}")
                parts.append("")

        parts.append("")

    # Istruzioni finali
    parts.append("=== ISTRUZIONI ===")
    parts.append("Analizza il panorama competitivo in chiave social media marketing.")
    parts.append("Basa ogni affermazione SOLO sui dati sopra. Non inventare dati mancanti.")
    parts.append("Se i dati su un competitor sono scarsi, indicalo nel campo 'insights'.")
    parts.append("")
    parts.append("Restituisci SOLO questo JSON:")
    parts.append(ANALYSIS_SCHEMA)

    return "\n".join(parts)


# ── Entry point ──────────────────────────────────────────────────────────────────

def run_analysis(competitors: list, company_ctx=None, db_session=None) -> dict:
    """
    Pipeline completa:
    1. Raccoglie dati web (scraping + Tavily) e li salva sul competitor nel DB
    2. Costruisce prompt con tutti i dati
    3. Chiama AI (provider primario → fallback)
    4. Restituisce dict strutturato con sources_used e data_quality
    """
    # Step 1: raccolta dati web + persistenza sul competitor
    from models.competitor import CompetitorSocial

    web_data: dict[int, dict] = {}
    for c in competitors:
        data = _gather_competitor_data(c)
        web_data[c.id] = data

        # Salva sul competitor nel DB se abbiamo una sessione
        if db_session:
            if data.get("scraped") and "sito_web" in data.get("sources", []):
                c.scraped_content = data["scraped"]
                c.last_scraped_at = datetime.now(timezone.utc)
            if data.get("search_results"):
                c.search_results = json.dumps(data["search_results"], ensure_ascii=False)
                c.last_searched_at = datetime.now(timezone.utc)

            # Salva i profili social trovati automaticamente
            found_socials: dict[str, str] = data.get("found_socials", {})
            if found_socials:
                # Mappa platform → record esistente
                existing: dict[str, object] = {s.platform: s for s in c.socials}
                for platform, url in found_socials.items():
                    if platform in existing:
                        # Aggiorna solo se il profilo non ha già un URL
                        social = existing[platform]
                        if not social.profile_url:
                            social.profile_url = url
                            logger.info(
                                "Aggiornato profilo %s per %s: %s",
                                platform, c.name, url,
                            )
                    else:
                        # Crea nuovo record social
                        new_social = CompetitorSocial(
                            competitor_id=c.id,
                            platform=platform,
                            profile_url=url,
                            notes="Trovato automaticamente durante l'analisi",
                        )
                        db_session.add(new_social)
                        logger.info(
                            "Aggiunto profilo %s per %s: %s",
                            platform, c.name, url,
                        )

    if db_session:
        db_session.commit()

    # Step 2: prompt
    prompt = _build_prompt(competitors, company_ctx, web_data)

    # Step 3: AI
    result, provider = _try_ai(prompt, primary=settings.ai_primary_provider)
    if not result:
        fallback = "openai" if settings.ai_primary_provider == "anthropic" else "anthropic"
        result, provider = _try_ai(prompt, primary=fallback)
    if not result:
        result = _fallback_result(competitors)
        provider = "fallback"

    result["generated_by"] = provider

    # Aggiungi sources_used: mappa nome competitor → fonti usate con titoli/url
    sources_used = {}
    for c in competitors:
        data = web_data.get(c.id, {})
        sources_used[c.name] = {
            "types": data.get("sources", []),
            "search_results": data.get("search_results", []),
            "scraped_preview": data.get("scraped", "")[:SCRAPED_PREVIEW] if data.get("scraped") else "",
            "found_socials": data.get("found_socials", {}),
        }
    result["sources_used"] = sources_used

    return result


def _try_ai(prompt: str, primary: str) -> tuple[dict | None, str]:
    if primary == "anthropic":
        return _try_anthropic(prompt)
    return _try_openai(prompt)


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
        logger.warning("Errore Anthropic in analisi competitor", exc_info=True)
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
        logger.warning("Errore OpenAI in analisi competitor", exc_info=True)
        return None, ""


def _fallback_result(competitors: list) -> dict:
    return {
        "summary": "Analisi non disponibile: configura una chiave API in Impostazioni.",
        "landscape": "",
        "data_quality": "Nessuna API configurata.",
        "per_competitor": [
            {"name": c.name, "verdict": "medio", "social_score": 5,
             "data_sources": [], "insights": "", "differentiator": "", "vulnerability": ""}
            for c in competitors
        ],
        "opportunities": [], "threats": [], "recommendations": [], "content_gaps": [],
    }

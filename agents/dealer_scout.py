"""
DealerScoutAgent — individua i concessionari/rivenditori ufficiali di un
costruttore concorrente tramite scraping del sito e ricerca Tavily,
e li archivia nell'anagrafica `competitor_dealers`.
"""
from __future__ import annotations

import re
import json
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from config.logging import get_logger
from config.settings import settings
from config.http_client import scrape_get

logger = get_logger("dealer_scout")

HTTP_TIMEOUT = 15

# Slug di pagine tipiche per liste dealer/rivenditori
_DEALER_PAGE_SLUGS = [
    "/dealers", "/dealer-locator", "/rivenditori", "/concessionari",
    "/dove-acquistare", "/find-a-dealer", "/store-locator", "/dove-trovarci",
    "/distributori", "/authorized-dealers", "/where-to-buy", "/network",
    "/partner", "/resellers", "/punti-vendita",
]

# Pattern per estrarre contatti inline
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,5}")

# Pattern per riconoscere rumore: CTA social, titoli articolo, pulsanti UI
_NOISE_RE = re.compile(
    r"follow|follower|connect|join linkedin|sign in|log in|cookie|subscribe|"
    r"newsletter|read more|leggi|scopri|contattaci|about us|chi siamo|"
    r"finalist|award|railway|exhibition|expo|webinar|demo tour|fleet|"
    r"strengthens|chooses|becomes|launches|announces|why spider|benefits of",
    re.I,
)
# Un vero dealer ha quasi sempre almeno uno di questi elementi
_HAS_CONTACT_RE = re.compile(
    r"(?:\+\d[\d\s\-]{6,})|"          # numero di telefono
    r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}|"  # email
    r"https?://|www\.|"               # sito web
    r"\b\d{5}\b|"                     # CAP
    r"via |viale |corso |piazza |str\.|avenue|road|street|rue |calle ",
    re.I,
)
# Titoli di articolo: troppe maiuscole consecutive o verbi all'infinito tipici
_ARTICLE_TITLE_RE = re.compile(
    r"^[A-Z][a-z]+ [A-Z][a-z]+ [A-Z][a-z]|"  # Tre Parole Maiuscole
    r"\b(why|how|when|what|top \d|best \d|\d+ tips)\b",
    re.I,
)


def _is_safe_url(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        host = p.hostname or ""
        if host in ("localhost", "::1"):
            return False
        if re.match(r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.)", host):
            return False
        return True
    except Exception:
        return False


def _fetch_page(url: str) -> str | None:
    """Scarica una pagina e restituisce il testo grezzo (max 200 KB)."""
    if not _is_safe_url(url):
        return None
    try:
        resp = scrape_get(url, timeout=HTTP_TIMEOUT)
        return resp.text[:200_000]
    except Exception as exc:
        logger.debug("Fetch fallito %s: %s", url, exc)
        return None


def _extract_contact_block(el: BeautifulSoup) -> dict:
    """Estrae email, telefono e sito web da un blocco HTML."""
    text = el.get_text(" ", strip=True)
    email = (_EMAIL_RE.search(text) or {0: ""}).group(0) if _EMAIL_RE.search(text) else ""
    phone_m = _PHONE_RE.search(text)
    phone = phone_m.group(0) if phone_m else ""
    # Link web nella card
    website = ""
    for a in el.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and "mailto:" not in href and "tel:" not in href:
            website = href
            break
    return {"email": email[:200], "phone": phone[:100], "website": website[:500]}


def _parse_address_text(text: str) -> dict:
    """
    Inferisce city / region / country da testo di indirizzo libero.
    Logica euristica semplice: ricerca CAP italiano o nomi di città comuni.
    """
    city = ""
    region = ""
    country = ""
    # CAP italiano: 5 cifre
    cap_m = re.search(r"\b\d{5}\b", text)
    if cap_m:
        country = "Italia"
    # Cerca parole che sembrano città (parola dopo virgola o newline)
    parts = [p.strip() for p in re.split(r"[,\n\r]", text) if p.strip()]
    if len(parts) >= 2:
        city = parts[-2][:200] if len(parts) >= 2 else ""
    return {"city": city, "region": region, "country": country}


def _scrape_dealer_page(url: str, source_url: str) -> list[dict]:
    """
    Analizza una pagina dealer del costruttore e ne estrae i rivenditori.
    Strategia: ogni blocco <li>, <article>, <div class~=dealer|store|location>
    che contiene un nome e almeno un contatto è considerato un dealer.
    """
    html = _fetch_page(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # Rimuovi header/footer/nav per ridurre il rumore
    for tag in soup.find_all(["header", "footer", "nav", "script", "style"]):
        tag.decompose()

    dealers: list[dict] = []

    # Cerca blocchi con classi dealer-like
    selectors = [
        {"class": re.compile(r"dealer|store|location|rivenditore|concessionario|punto.?vendita", re.I)},
        {"class": re.compile(r"card|item|entry|result", re.I)},
    ]
    candidates = []
    for sel in selectors:
        candidates.extend(soup.find_all(["li", "article", "div", "section"], attrs=sel))

    # Fallback: tutti i <li> con contenuto sufficiente
    if not candidates:
        candidates = [li for li in soup.find_all("li") if len(li.get_text(strip=True)) > 40]

    seen_names: set[str] = set()
    for block in candidates[:80]:  # limite per evitare elaborazioni infinite
        text = block.get_text(" ", strip=True)
        if len(text) < 20:
            continue

        # Scarta blocchi che non hanno nessun contatto/indirizzo riconoscibile
        if not _HAS_CONTACT_RE.search(text):
            continue

        # Scarta blocchi con contenuto tipico di social media / articoli
        if _NOISE_RE.search(text[:200]):
            continue

        # Il nome del dealer è spesso nel primo heading o strong/b
        name_el = block.find(["h2", "h3", "h4", "strong", "b"])
        name = name_el.get_text(strip=True)[:300] if name_el else text[:80]
        if not name or name in seen_names:
            continue

        # Scarta nomi che sembrano titoli di articolo
        if _NOISE_RE.search(name) or _ARTICLE_TITLE_RE.search(name):
            continue
        # Scarta nomi troppo lunghi (probabilmente frasi intere, non nomi aziendali)
        if len(name) > 120:
            continue

        seen_names.add(name)
        contacts = _extract_contact_block(block)
        addr_data = _parse_address_text(text)

        dealers.append({
            "name": name,
            "website": contacts["website"],
            "phone": contacts["phone"],
            "email": contacts["email"],
            "address": text[:300],
            "city": addr_data["city"],
            "region": addr_data["region"],
            "country": addr_data["country"],
            "source": "website",
            "source_url": source_url,
        })

    logger.info("Pagina %s: estratti %d dealer", url, len(dealers))
    return dealers


def _search_dealers_on_site(base_url: str) -> list[dict]:
    """
    Prova gli slug dealer tipici sulla radice del sito del costruttore.
    """
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    all_dealers: list[dict] = []
    found_any = False
    for slug in _DEALER_PAGE_SLUGS:
        url = root + slug
        dealers = _scrape_dealer_page(url, source_url=url)
        if dealers:
            all_dealers.extend(dealers)
            found_any = True
            if len(all_dealers) >= 100:
                break
    if not found_any:
        # Prova sulla homepage a cercare link a pagine dealer
        html = _fetch_page(base_url)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].lower()
                text = a.get_text(strip=True).lower()
                if any(kw in href or kw in text for kw in
                       ["dealer", "rivenditore", "concessionario", "store", "distributor", "rivenditor"]):
                    full = urljoin(base_url, a["href"])
                    if _is_safe_url(full):
                        dealers = _scrape_dealer_page(full, source_url=full)
                        all_dealers.extend(dealers)
                        if len(all_dealers) >= 100:
                            break
    return all_dealers


def _search_dealers_tavily(competitor_name: str, sector: str) -> list[dict]:
    """
    Usa Tavily per trovare dealer/concessionari del costruttore.
    """
    if not settings.tavily_api_key:
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        queries = [
            f'"{competitor_name}" concessionari rivenditori autorizzati lista',
            f'"{competitor_name}" dealer network authorized resellers {sector}',
        ]
        dealers: list[dict] = []
        seen_urls: set[str] = set()
        for query in queries:
            resp = client.search(query=query, max_results=6, include_raw_content=False)
            for r in resp.get("results", []):
                url = r.get("url", "")
                if not url or url in seen_urls or not _is_safe_url(url):
                    continue
                seen_urls.add(url)
                # Prova a scrapare la pagina risultante come lista dealer
                page_dealers = _scrape_dealer_page(url, source_url=url)
                if page_dealers:
                    dealers.extend(page_dealers)
                else:
                    # Salva almeno la pagina come riferimento
                    dealers.append({
                        "name": r.get("title", competitor_name + " dealer")[:300],
                        "website": url,
                        "phone": "", "email": "", "address": "",
                        "city": "", "region": "", "country": "",
                        "source": "tavily",
                        "source_url": url,
                    })
        logger.info("Tavily dealer search '%s': %d trovati", competitor_name, len(dealers))
        return dealers
    except Exception as exc:
        logger.warning("Errore Tavily dealer search per '%s': %s", competitor_name, exc)
        return []


def search_and_save_dealers(competitor_id: int, db: Session) -> list[dict]:
    """
    Pipeline completa:
    1. Scraping delle pagine dealer del sito costruttore
    2. Ricerca Tavily
    3. Salvataggio nel DB con deduplicazione per nome
    Ritorna lista di dealer salvati.
    """
    from models.competitor import Competitor, CompetitorDealer

    competitor = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not competitor:
        logger.error("Competitor %d non trovato", competitor_id)
        return []

    candidates: list[dict] = []

    if competitor.website:
        candidates.extend(_search_dealers_on_site(competitor.website))

    candidates.extend(_search_dealers_tavily(competitor.name, competitor.sector or ""))

    # Deduplicazione per nome (case-insensitive)
    seen_names: set[str] = set(
        d.name.lower() for d in db.query(CompetitorDealer).filter(
            CompetitorDealer.competitor_id == competitor_id).all()
    )

    saved: list[dict] = []
    for cand in candidates:
        key = (cand.get("name") or "").strip().lower()
        if not key or key in seen_names:
            continue
        seen_names.add(key)

        dealer = CompetitorDealer(
            competitor_id=competitor_id,
            name=(cand.get("name") or "")[:500],
            website=(cand.get("website") or "")[:1000],
            address=(cand.get("address") or "")[:500],
            city=(cand.get("city") or "")[:200],
            region=(cand.get("region") or "")[:200],
            country=(cand.get("country") or "")[:100],
            phone=(cand.get("phone") or "")[:100],
            email=(cand.get("email") or "")[:200],
            source=(cand.get("source") or "")[:100],
            source_url=(cand.get("source_url") or "")[:1000],
            found_at=datetime.utcnow(),
        )
        db.add(dealer)
        db.commit()
        db.refresh(dealer)
        saved.append({
            "id": dealer.id,
            "name": dealer.name,
            "website": dealer.website,
            "city": dealer.city,
            "country": dealer.country,
            "source": dealer.source,
        })

    logger.info("Dealer search completata per competitor %d: %d nuovi", competitor_id, len(saved))
    return saved

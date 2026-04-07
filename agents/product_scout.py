"""
ProductScoutAgent — cerca dati tecnici e brochure PDF dei prodotti di un concorrente
(costruttore) sia sul sito del costruttore stesso, sia sui siti dei suoi dealer.
Estrae specifiche tecniche strutturate e le archivia in `competitor_products`.
"""
from __future__ import annotations

import re
import json
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from config.logging import get_logger
from config.settings import settings
from config.http_client import scrape_get, scrape_stream

logger = get_logger("product_scout")

MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024   # 20 MB
HTTP_TIMEOUT = 15
MAX_PAGE_BYTES = 300_000                 # 300 KB per pagina HTML
BROCHURES_DIR = Path(__file__).parent.parent / "storage" / "brochures"

# Parole chiave per identificare documenti di natura tecnica
_TECH_KEYWORDS = re.compile(
    r"scheda.tecnica|datasheet|specif|technical|manuale|catalogo|brochure|"
    r"dimensioni|prestazioni|potenza|portata|capacit|rendimento|certificaz|"
    r"omologaz|norma|standard|classe.energ|efficien",
    re.I,
)

# Parole chiave da escludere (documenti non tecnici)
_EXCLUDE_KEYWORDS = re.compile(
    r"privacy|cookie|gdpr|termini|condizioni|careers|lavora.con|newsletter|"
    r"login|registra|checkout|carrello|offerta.lavoro|"
    r"bilancio|sostenibilit|annual.report|rassegna.stampa|press.release|"
    r"financial|investor|corporate.responsib|sustainability.report|"
    r"report.annuale|relazione.annual|assemblea|assembl|"
    r"ipaf|gis.expo|gis.2017|ista |iapa |bauma |conexpo|intermat|samoter",
    re.I,
)

# Slug che tipicamente contengono documentazione tecnica
_TECH_PAGE_SLUGS = [
    "/download", "/downloads", "/documenti", "/documents",
    "/schede-tecniche", "/technical-data", "/resources", "/risorse",
    "/supporto", "/support", "/media", "/press", "/prodotti", "/products",
    "/catalogo", "/catalog", "/specifiche", "/specifications",
]

# Unità di misura per identificare valori tecnici
_UNIT_RE = re.compile(
    r"(\d[\d.,]*)\s*(kg|kw|kva|mm|cm|m|l|lt|bar|°c|rpm|hz|v|a|w|db|m²|m³|"
    r"kgf|n|pa|kpa|mpa|%|psi|cfm|m/s|km/h|ltr|kJ|kcal|btu)",
    re.I,
)

# Pattern per estrarre coppie chiave:valore da testo (es. "Potenza: 3.5 kW")
_KV_RE = re.compile(
    r"([A-ZÀ-Ùa-zà-ù][^\n:]{2,60}?)\s*[:–\-]\s*([^\n]{1,120})"
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


def _safe_filename(url: str) -> str:
    basename = Path(urlparse(url).path).name
    basename = re.sub(r"[^\w.\-]", "_", basename)
    if not basename.endswith(".pdf"):
        basename += ".pdf"
    hash_suffix = hashlib.md5(url.encode()).hexdigest()[:6]
    return f"{Path(basename).stem[:60]}_{hash_suffix}.pdf"


def _fetch_html(url: str) -> str | None:
    if not _is_safe_url(url):
        return None
    try:
        resp = scrape_get(url, timeout=HTTP_TIMEOUT)
        return resp.text[:MAX_PAGE_BYTES]
    except Exception as exc:
        logger.debug("Fetch fallito %s: %s", url, exc)
        return None


def _is_tech_document(text: str, name: str) -> bool:
    combined = (name + " " + text[:500]).lower()
    if _EXCLUDE_KEYWORDS.search(combined):
        return False
    return bool(_TECH_KEYWORDS.search(combined))


def _categorize_document(name: str, url: str) -> str:
    """Inferisce la categoria del documento dal nome/URL."""
    combined = (name + " " + url).lower()
    if re.search(r"datasheet|scheda.tecnica|technical.data|spec", combined):
        return "Scheda tecnica"
    if re.search(r"manual|manuale|instruc", combined):
        return "Manuale"
    if re.search(r"catalog|catalogo", combined):
        return "Catalogo"
    if re.search(r"brochure|flyer|presentaz", combined):
        return "Brochure"
    if re.search(r"certif|omolog|dichiaraz|norm", combined):
        return "Certificazione"
    return "Documento tecnico"


def _extract_tech_specs(html: str, product_name: str) -> tuple[str, str]:
    """
    Estrae specifiche tecniche strutturate da una pagina HTML o da testo estratto da PDF.
    Ritorna (tech_specs_json, tech_summary).
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    specs: list[dict] = []

    # 1. Tabelle — fonte più affidabile
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) >= 2:
                key = cells[0][:100]
                value = " | ".join(cells[1:])[:200]
                if key and value and len(key) < 80 and not key.isdigit():
                    specs.append({"key": key, "value": value, "unit": ""})

    # 2. Definition lists
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            key = dt.get_text(strip=True)[:100]
            value = dd.get_text(strip=True)[:200]
            if key and value:
                specs.append({"key": key, "value": value, "unit": ""})

    # 3. Pattern chiave:valore nel testo
    text = soup.get_text(" ", strip=True)
    if not specs:
        for m in _KV_RE.finditer(text):
            key = m.group(1).strip()[:100]
            value = m.group(2).strip()[:200]
            # Filtra valori che sembrano specifiche tecniche
            if _UNIT_RE.search(value) or _TECH_KEYWORDS.search(key):
                specs.append({"key": key, "value": value, "unit": ""})

    # Arricchisci con unità di misura dove trovate
    for spec in specs:
        m = _UNIT_RE.search(spec["value"])
        if m:
            spec["unit"] = m.group(2)

    # Deduplica per chiave
    seen_keys: set[str] = set()
    unique_specs: list[dict] = []
    for s in specs:
        k = s["key"].lower()
        if k not in seen_keys:
            seen_keys.add(k)
            unique_specs.append(s)

    tech_specs_json = json.dumps(unique_specs[:60], ensure_ascii=False)

    # Sommario testuale
    summary_parts = [f"{s['key']}: {s['value']}" for s in unique_specs[:15]]
    tech_summary = " | ".join(summary_parts)[:1000]

    return tech_specs_json, tech_summary


def _find_pdf_links(html: str, base_url: str, source_label: str) -> list[dict]:
    """
    Estrae link a PDF da una pagina HTML, filtrando quelli tecnici.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"].strip()
        if not href.lower().endswith(".pdf"):
            continue
        full_url = urljoin(base_url, href)
        if not _is_safe_url(full_url):
            continue
        name = a.get_text(strip=True)[:300] or Path(urlparse(full_url).path).name
        if not _is_tech_document("", name):
            continue
        results.append({
            "url": full_url,
            "name": name,
            "page_url": base_url,
            "source": source_label,
            "category": _categorize_document(name, full_url),
        })
    return results


def _find_tech_pages(html: str, base_url: str) -> list[str]:
    """
    Individua link a pagine di documentazione tecnica nel sito.
    """
    soup = BeautifulSoup(html, "html.parser")
    tech_page_urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        href_lower = href.lower()
        if any(slug in href_lower for slug in _TECH_PAGE_SLUGS) or \
           _TECH_KEYWORDS.search(text):
            full = urljoin(base_url, href)
            if _is_safe_url(full) and full not in tech_page_urls:
                tech_page_urls.append(full)
        if len(tech_page_urls) >= 15:
            break
    return tech_page_urls


def _scan_site_for_tech_docs(base_url: str, source_label: str) -> list[dict]:
    """
    Scansione multi-livello del sito: homepage → pagine tech → estrazione PDF.
    """
    html = _fetch_html(base_url)
    if not html:
        return []

    all_docs: list[dict] = []

    # PDF diretti dalla homepage
    all_docs.extend(_find_pdf_links(html, base_url, source_label))

    # Prova slug diretti
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    for slug in _TECH_PAGE_SLUGS[:6]:
        url = root + slug
        sub_html = _fetch_html(url)
        if sub_html:
            all_docs.extend(_find_pdf_links(sub_html, url, source_label))

    # Pagine tech scoperte dalla homepage
    tech_pages = _find_tech_pages(html, base_url)
    for page_url in tech_pages[:8]:
        sub_html = _fetch_html(page_url)
        if sub_html:
            all_docs.extend(_find_pdf_links(sub_html, page_url, source_label))

    # Dedup per URL
    seen: set[str] = set()
    unique: list[dict] = []
    for d in all_docs:
        if d["url"] not in seen:
            seen.add(d["url"])
            unique.append(d)

    logger.info("Sito %s: trovati %d documenti tecnici", base_url, len(unique))
    return unique


def _search_tavily_tech(competitor_name: str, sector: str) -> list[dict]:
    """
    Ricerca Tavily focalizzata su schede tecniche e datasheet del costruttore.
    """
    if not settings.tavily_api_key:
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        queries = [
            f'"{competitor_name}" scheda tecnica datasheet specifiche tecniche filetype:pdf',
            f'"{competitor_name}" technical specifications datasheet {sector} PDF',
        ]
        results: list[dict] = []
        seen_urls: set[str] = set()
        for query in queries:
            resp = client.search(query=query, max_results=8, include_raw_content=False)
            for r in resp.get("results", []):
                url = r.get("url", "")
                if not url or url in seen_urls or not _is_safe_url(url):
                    continue
                seen_urls.add(url)
                name = r.get("title", "")[:300] or competitor_name
                if url.lower().endswith(".pdf"):
                    results.append({
                        "url": url,
                        "name": name,
                        "page_url": url,
                        "source": "tavily",
                        "category": _categorize_document(name, url),
                    })
                else:
                    # Scansiona la pagina per PDF tecnici
                    sub_html = _fetch_html(url)
                    if sub_html:
                        pdfs = _find_pdf_links(sub_html, url, "tavily")
                        if pdfs:
                            results.extend(pdfs)
                        elif _is_tech_document(sub_html[:2000], name):
                            # Pagina tecnica senza PDF — la teniamo come riferimento
                            results.append({
                                "url": url,
                                "name": name,
                                "page_url": url,
                                "source": "tavily",
                                "category": _categorize_document(name, url),
                            })
        logger.info("Tavily tech docs '%s': %d trovati", competitor_name, len(results))
        return results
    except Exception as exc:
        logger.warning("Errore Tavily tech search '%s': %s", competitor_name, exc)
        return []


def _download_pdf(pdf_url: str, save_dir: Path) -> tuple[str, int] | None:
    if not _is_safe_url(pdf_url):
        return None
    try:
        with scrape_stream(pdf_url, timeout=HTTP_TIMEOUT) as resp:
            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type and not pdf_url.lower().endswith(".pdf"):
                return None
            save_dir.mkdir(parents=True, exist_ok=True)
            filename = _safe_filename(pdf_url)
            dest = save_dir / filename
            total = 0
            chunks: list[bytes] = []
            for chunk in resp.iter_bytes(chunk_size=65536):
                total += len(chunk)
                if total > MAX_PDF_SIZE_BYTES:
                    logger.warning("PDF troppo grande, skip: %s", pdf_url)
                    return None
                chunks.append(chunk)
            dest.write_bytes(b"".join(chunks))
            return filename, total // 1024
    except Exception as exc:
        logger.warning("Errore download PDF %s: %s", pdf_url, exc)
        return None


def search_and_download(competitor_id: int, db: Session) -> list[dict]:
    """
    Pipeline completa ricerca dati tecnici:

    1. Scansione sito del costruttore per PDF tecnici
    2. Ricerca Tavily per datasheet/schede tecniche
    3. Scansione siti dei dealer già archiviati
    4. Download PDF + estrazione specifiche tecniche
    5. Salvataggio in DB (deduplicazione per URL)
    """
    from models.competitor import Competitor, CompetitorProduct, CompetitorDealer

    competitor = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not competitor:
        logger.error("Competitor %d non trovato", competitor_id)
        return []

    save_dir = BROCHURES_DIR / str(competitor_id)
    candidates: list[dict] = []

    # 1. Sito del costruttore
    if competitor.website:
        docs = _scan_site_for_tech_docs(competitor.website, "manufacturer_site")
        candidates.extend(docs)

    # Calcola domini affidabili: sito costruttore + dominio dei dealer
    trusted_domains: set[str] = set()
    if competitor.website:
        host = urlparse(competitor.website).hostname or ""
        trusted_domains.add(host.removeprefix("www."))

    # 2. Tavily
    candidates.extend(_search_tavily_tech(competitor.name, competitor.sector or ""))

    # 3. Siti dei dealer già in DB
    dealers = db.query(CompetitorDealer).filter(
        CompetitorDealer.competitor_id == competitor_id,
        CompetitorDealer.website != "",
    ).all()
    for dealer in dealers[:10]:  # limita per evitare scansioni eccessive
        if not dealer.website:
            continue
        dealer_host = urlparse(dealer.website).hostname or ""
        trusted_domains.add(dealer_host.removeprefix("www."))
        logger.info("Scansione dealer '%s': %s", dealer.name, dealer.website)
        dealer_docs = _scan_site_for_tech_docs(dealer.website, "dealer_site")
        for d in dealer_docs:
            d["dealer_id"] = dealer.id
        candidates.extend(dealer_docs)

    # Dedup per URL + filtro cross-domain per Tavily
    # (i documenti dal sito costruttore e dealer passano sempre)
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for c in candidates:
        if c["url"] in seen_urls:
            continue
        # Per i risultati Tavily: accetta solo se il dominio è tra quelli fidati
        if c.get("source") == "tavily":
            doc_host = urlparse(c["url"]).hostname or ""
            doc_host = doc_host.removeprefix("www.")
            if trusted_domains and doc_host not in trusted_domains:
                logger.debug("Scartato PDF da dominio terzo: %s", c["url"])
                continue
        seen_urls.add(c["url"])
        unique.append(c)

    # URL già in DB
    existing_urls = {p.brochure_url for p in db.query(CompetitorProduct).filter(
        CompetitorProduct.competitor_id == competitor_id).all()}

    saved: list[dict] = []
    for cand in unique:
        url = cand["url"]
        if url in existing_urls:
            continue

        filename = ""
        size_kb = 0
        tech_specs_json = "[]"
        tech_summary = ""

        if url.lower().endswith(".pdf"):
            dl_result = _download_pdf(url, save_dir)
            if dl_result:
                filename, size_kb = dl_result
                # Cerca la pagina sorgente per estrarre specifiche tecniche contestuali
                if cand.get("page_url") and cand["page_url"] != url:
                    page_html = _fetch_html(cand["page_url"])
                    if page_html:
                        tech_specs_json, tech_summary = _extract_tech_specs(page_html, cand["name"])
        else:
            # Pagina HTML con dati tecnici
            page_html = _fetch_html(url)
            if page_html:
                tech_specs_json, tech_summary = _extract_tech_specs(page_html, cand["name"])

        product = CompetitorProduct(
            competitor_id=competitor_id,
            dealer_id=cand.get("dealer_id"),
            name=cand["name"][:500],
            product_line="",
            category=cand.get("category", "Documento tecnico"),
            brochure_url=url,
            brochure_filename=filename,
            page_url=cand.get("page_url", "")[:1000],
            source=cand.get("source", ""),
            file_size_kb=size_kb,
            tech_specs=tech_specs_json,
            tech_summary=tech_summary,
            found_at=datetime.utcnow(),
        )
        db.add(product)
        db.commit()
        db.refresh(product)
        existing_urls.add(url)

        saved.append({
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "brochure_url": product.brochure_url,
            "brochure_filename": product.brochure_filename,
            "source": product.source,
            "file_size_kb": product.file_size_kb,
            "has_specs": bool(tech_summary),
        })
        logger.info("Prodotto tecnico salvato: %s [%s]", product.name, product.category)

    logger.info("Ricerca completata per competitor %d: %d nuovi documenti", competitor_id, len(saved))
    return saved

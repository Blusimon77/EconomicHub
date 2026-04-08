"""
DealerScoutAgent — individua i concessionari/rivenditori ufficiali di un
costruttore concorrente tramite scraping del sito e ricerca Tavily,
e li archivia nell'anagrafica `competitor_dealers` e nel registro globale.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from config.logging import get_logger
from config.http_client import scrape_get
from config.settings import settings

logger = get_logger("dealer_scout")

HTTP_TIMEOUT = 15

# ── Slug tipici per pagine dealer ─────────────────────────────────────────────
# NOTA: /contacts /contatti /contact /contatto sono ESCLUSI: sono pagine staff
# interno del produttore, non liste di dealer/rivenditori.
_DEALER_PAGE_SLUGS = [
    "/dealers", "/dealer-locator", "/rivenditori", "/concessionari",
    "/dove-acquistare", "/find-a-dealer", "/store-locator", "/dove-trovarci",
    "/distributori", "/authorized-dealers", "/where-to-buy", "/network",
    "/partner", "/resellers", "/punti-vendita", "/distributors",
    "/reseller", "/buy", "/en/dealers", "/en/resellers",
    "/en/distributors", "/en/network", "/en/authorized-dealers",
    "/it/rivenditori", "/it/concessionari", "/company/resellers",
    "/en/company/resellers",
]

# ── Estrazione contatti ───────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,5}"
)

# ── CONTATTO OBBLIGATORIO: telefono OPPURE email ──────────────────────────────
# Richiediamo almeno uno dei due — non basta un URL generico o un CAP.
_CONTACT_STRICT_RE = re.compile(
    r"(?:\+\d{1,3}[\s.\-]?)?\(?\d{2,4}\)?[\s.\-]?\d{3,5}[\s.\-]?\d{3,5}|"
    r"[a-z0-9._%+\-]{2,}@[a-z0-9.\-]{2,}\.[a-z]{2,}",
    re.I,
)

# ── Rumore: CTA social, articoli, UI ─────────────────────────────────────────
_NOISE_RE = re.compile(
    r"follow|follower|connect|join linkedin|sign in|log in|cookie|subscribe|"
    r"newsletter|read more|leggi tutto|scopri|contattaci|about us|chi siamo|"
    r"finalist|award|railway|exhibition|expo|webinar|demo tour|"
    r"strengthens|chooses|becomes|launches|announces|why spider|benefits of|"
    r"piattaforme aeree per|aerial platforms for|innovation meets|"
    r"l'impegno di|tra tecnologia|upcoming events|next events|on the road|"
    r"our mission|new establishment|welcome to|connect your|the company|"
    r"spare parts|find spare|privacy|gdpr|cookie policy|"
    r"^products?\b|drum handling|drum attachment|"
    r"facebook|instagram|linkedin|youtube|twitter|tiktok",
    re.I,
)

# ── Titoli di articolo / heading di sezione ───────────────────────────────────
_ARTICLE_TITLE_RE = re.compile(
    r"\b(why|how|when|what|who|where|top \d|best \d|\d+ tips|"
    r"launches?|announces?|debuts?|strengthens?|chooses?|becomes?|"
    r"showcases?|brings?|attends?|will represent|to debut|to attend|"
    r"piattaforme aeree per|l'impegno|tra tecnologia|innovation meets|"
    r"new dealer on|our dealer for|fleet with|commitment to)\b",
    re.I,
)

# ── Nomi geografici puri (paesi, continenti, regioni) ────────────────────────
_GEO_ONLY_RE = re.compile(
    r"^(?:north america|south america|central america|middle east|"
    r"sub.?saharan africa|asia pacific|"
    r"europe|africa|asia|oceania|americas|"
    r"france|italy|italia|germany|deutschland|spain|españa|"
    r"united kingdom|uk|ireland|netherlands|belgium|switzerland|"
    r"austria|portugal|sweden|norway|denmark|finland|poland|"
    r"czech republic|slovakia|hungary|romania|bulgaria|croatia|"
    r"usa|united states|canada|mexico|brazil|brasil|argentina|chile|"
    r"colombia|peru|venezuela|"
    r"australia|new zealand|japan|china|korea|india|"
    r"turkey|russia|ukraine|"
    r"algeria|angola|bahrain|bénin|benin|botswana|burkina faso|"
    r"capo verde|cape verde|cameroon|côte d'ivoire|egypt|ethiopia|"
    r"ghana|kenya|morocco|maroc|mozambique|nigeria|senegal|"
    r"south africa|tanzania|tunisia|uganda|zambia|zimbabwe|"
    r"bahrain|kuwait|oman|qatar|saudi arabia|uae|"
    r"israel|jordan|lebanon|"
    r"indonesia|malaysia|philippines|singapore|thailand|vietnam"
    r")s?$",
    re.I,
)

# Lista di parole-paese: se il nome contiene 3+ di queste, è una lista geografica
_COUNTRY_WORDS = re.compile(
    r"\b(france|italy|germany|spain|uk|usa|canada|mexico|brazil|"
    r"australia|japan|china|korea|india|turkey|russia|poland|"
    r"belgium|netherlands|sweden|norway|denmark|finland|portugal|"
    r"austria|switzerland|algeria|tunisia|morocco|nigeria|ghana|kenya|"
    r"angola|botswana|senegal|egypt|saudi|emirates|bahrain|qatar|oman)\b",
    re.I,
)

# ── Nomi di persona: primi nomi comuni (IT/FR/DE/ES/EN) ──────────────────────
# Usati per rilevare "Nome Cognome" anziché ragioni sociali.
_COMMON_FIRST_NAMES = {
    # Italiani
    "mario","luigi","giuseppe","antonio","giovanni","franco","carlo","marco",
    "luca","andrea","roberto","stefano","paolo","giorgio","massimo","alberto",
    "davide","matteo","simone","emanuele","michele","gianluca","fabrizio",
    "manuela","laura","anna","maria","paola","sara","giulia","elena","chiara",
    "francesca","valentina","alessia","federica","silvia","roberta","barbara",
    # Francesi
    "jean","pierre","michel","alain","bernard","patrick","nicolas","philippe",
    "marie","isabelle","nathalie","sylvie","chantal","hassna",
    # Tedeschi
    "hans","peter","thomas","michael","stefan","andreas","christian","markus",
    "sabine","petra","monika","ursula","birgit",
    # Spagnoli/Portoghesi
    "carlos","jose","juan","pedro","luis","miguel","jorge","fernando",
    "maria","ana","carmen","rosa","paula",
    # Inglesi
    "john","james","william","david","richard","charles","joseph","thomas",
    "robert","mark","paul","steven","kevin","brian","george","edward",
    "sarah","lisa","jennifer","amanda","jessica","emily","rachel",
}

# ── Suffissi societari: indicano una vera ragione sociale ─────────────────────
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(s\.?r\.?l\.?|s\.?p\.?a\.?|s\.?a\.?s\.?|s\.?n\.?c\.?|"
    r"llc|ltd\.?|gmbh|sarl|b\.?v\.?|n\.?v\.?|oy|ab|a\.?s\.?|kft|"
    r"inc\.?|corp\.?|pty\.?|"
    r"group|holding|distribuz\w*|service\w*|rental\w*|"
    r"nacelles|arbeitsbühnen|arbeitsbuhnen|piattaforme|"
    r"commerciale|equipment|solutions|"
    r"srl|spa|bvba|sprl|ag)\b",
    re.I,
)

# ── Artefatti HTML e simboli che non appartengono a ragioni sociali ───────────
_ARTIFACT_RE = re.compile(r"[|\[\]<>{}]|\bpdf\b|\d{4,}(?:\s+\d{4,})+", re.I)

# ── Soglia minima: se una pagina produce < N dealer validi, scarta tutto ──────
_MIN_DEALERS_PER_PAGE = 2


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
    if not _is_safe_url(url):
        return None
    try:
        resp = scrape_get(url, timeout=HTTP_TIMEOUT)
        return resp.text[:200_000]
    except Exception as exc:
        logger.debug("Fetch fallito %s: %s", url, exc)
        return None


def _extract_contact_block(el: BeautifulSoup) -> dict:
    text = el.get_text(" ", strip=True)
    email_m = _EMAIL_RE.search(text)
    phone_m = _PHONE_RE.search(text)
    website = ""
    for a in el.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and "mailto:" not in href and "tel:" not in href:
            website = href
            break
    return {
        "email": (email_m.group(0) if email_m else "")[:200],
        "phone": (phone_m.group(0) if phone_m else "")[:100],
        "website": website[:500],
    }


def _parse_address_text(text: str) -> dict:
    city = ""
    region = ""
    country = ""
    if re.search(r"\b\d{5}\b", text):
        country = "Italia"
    parts = [p.strip() for p in re.split(r"[,\n\r]", text) if p.strip()]
    if len(parts) >= 2:
        city = parts[-2][:200]
    return {"city": city, "region": region, "country": country}


def _looks_like_company(name: str) -> bool:
    """
    Verifica che il nome abbia caratteristiche di una ragione sociale.
    Restituisce True se il nome è plausibile come nome di azienda.
    """
    name = name.strip()

    # Lunghezza: nomi aziendali sono tipicamente 3-80 caratteri
    if len(name) < 4 or len(name) > 85:
        return False

    # Parola singola < 6 caratteri senza suffisso societario:
    # troppo breve per essere una ragione sociale (es. "Show", "Fair", "Expo")
    if (len(name.split()) == 1
            and len(name) < 6
            and not _COMPANY_SUFFIX_RE.search(name)):
        return False

    # Indirizzi email usati come nome
    if "@" in name:
        return False

    # Solo numeri, codici o simboli — non è un nome aziendale
    if re.match(r'^[\d\s\-_/.,;:]+$', name):
        return False

    # Deve contenere almeno 3 lettere
    if len(re.findall(r'[a-zA-Z]', name)) < 3:
        return False

    # Artefatti HTML: |, [, ], <, > nel nome
    if _ARTIFACT_RE.search(name):
        return False

    # Nome geografico puro
    if _GEO_ONLY_RE.match(name.strip()):
        return False

    # Lista di paesi (3+ nomi paese nel testo = lista geografica, non ragione sociale)
    if len(_COUNTRY_WORDS.findall(name)) >= 2:
        return False

    # Titoli di articolo
    if _ARTICLE_TITLE_RE.search(name):
        return False

    # Rumore generico
    if _NOISE_RE.search(name[:120]):
        return False

    # Tutto maiuscolo con 2+ parole > 13 caratteri senza suffisso aziendale:
    # tipico di heading di sezione ("MANUTENZIONE EDILIZIA", "APPLICAZIONI SPECIALI")
    # ma NON di sigle brevi ("LVM", "UP EQUIP" ≤ 13 caratteri)
    if (name == name.upper()
            and len(name.split()) >= 2
            and len(name) > 13
            and not _COMPANY_SUFFIX_RE.search(name)):
        return False

    # Inizia con un numero di 3+ cifre (es. "404", "2025")
    if re.match(r'^\d{3,}', name):
        return False

    # Contiene troppe parole tutto-maiuscole (> 4) senza suffisso: probabile menu/nav
    all_caps_words = re.findall(r'\b[A-Z]{2,}\b', name)
    if len(all_caps_words) > 4 and not _COMPANY_SUFFIX_RE.search(name):
        return False

    # Rilevamento nome di persona fisica:
    # "Nome Cognome" — esattamente 2 parole, entrambe solo-lettere, nessun suffisso
    # aziendale, e la prima parola è un nome comune.
    words = name.split()
    if (len(words) == 2
            and all(re.match(r'^[A-Za-zÀ-ÿ\u00c0-\u024f]+$', w) for w in words)
            and not _COMPANY_SUFFIX_RE.search(name)
            and words[0].lower() in _COMMON_FIRST_NAMES):
        return False

    return True


def _scrape_dealer_page(url: str, source_url: str) -> list[dict]:
    """
    Analizza una pagina dealer e ne estrae i rivenditori con criteri rigorosi.
    Un blocco viene accettato solo se:
      - il nome supera _looks_like_company()
      - il blocco contiene telefono OPPURE email
    Se la pagina produce < _MIN_DEALERS_PER_PAGE risultati validi, restituisce [].
    """
    html = _fetch_page(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["header", "footer", "nav", "script", "style"]):
        tag.decompose()

    # Rimuovi sezioni blog/news
    for tag in soup.find_all(True, attrs={"class": re.compile(r"blog|news|article|post|press", re.I)}):
        tag.decompose()

    # Selettori per blocchi dealer
    selectors = [
        {"class": re.compile(r"dealer|store|location|rivenditore|concessionario|punto.?vendita|distributor|reseller|partner", re.I)},
        {"class": re.compile(r"card|item|entry|result", re.I)},
    ]
    candidates = []
    for sel in selectors:
        candidates.extend(soup.find_all(["li", "article", "div", "section"], attrs=sel))

    if not candidates:
        candidates = [li for li in soup.find_all("li") if len(li.get_text(strip=True)) > 50]

    seen_names: set[str] = set()
    dealers: list[dict] = []

    for block in candidates[:100]:
        text = block.get_text(" ", strip=True)
        if len(text) < 25:
            continue

        # FILTRO 1: richiede telefono o email (non solo URL/CAP)
        if not _CONTACT_STRICT_RE.search(text):
            continue

        # FILTRO 2: nome del dealer
        name_el = block.find(["h2", "h3", "h4", "strong", "b"])
        name = name_el.get_text(strip=True)[:300] if name_el else text[:80]
        name = name.strip()

        if not name or name.lower() in seen_names:
            continue

        # FILTRO 3: validazione ragione sociale
        if not _looks_like_company(name):
            continue

        seen_names.add(name.lower())
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

    # Soglia minima: scarta pagine con troppo pochi risultati (quasi sicuramente
    # non è una vera pagina dealer list, o il contenuto è caricato via JS)
    if len(dealers) < _MIN_DEALERS_PER_PAGE:
        logger.debug(
            "Pagina %s scartata: solo %d dealer validi (soglia %d)",
            url, len(dealers), _MIN_DEALERS_PER_PAGE,
        )
        return []

    logger.info("Pagina %s: estratti %d dealer validi", url, len(dealers))
    return dealers


# ── Pattern per estrarre dealer da articoli/press-release ────────────────────
# Token nome: parola che inizia con maiuscola (non preposizione/articolo/nav comune)
_NT = r"[A-ZÀÈÉÙ][\wÀ-ÿ&\-]{1,}"
_STOP = (r"(?:At|In|For|And|The|A|An|Of|With|To|Their|Our|Its|"
         r"Skip|Read|More|Next|Easy|Events?|News|Shows?|Fairs?|Expos?|"
         r"Upcoming|Trade|German|Italian|Polish|French|Spanish|"
         r"January|February|March|April|May|June|July|August|"
         r"September|October|November|December)\b")

# Prefissi nav da strippare nei nomi estratti (breadcrumb/categoria)
_NAV_PREFIX_RE = re.compile(
    r"^(?:Events?\s+|News\s+|Shows?\s+|Fairs?\s+|Press\s+|Media\s+)+",
    re.I,
)

_DEALER_MENTION_RE = re.compile(
    # "NAME brings/showcases Easy Lift..." — 1-4 token prima del verbo
    r"((?:" + _NT + r")(?:\s+(?!" + _STOP + r")" + _NT + r"){0,3})"
    r"\s+(?:brings?\b|to\s+bring\b|showcases?\b|to\s+showcase\b|"
    r"represents?\b|to\s+represent\b|presenta\b|porta\b|debuts?\b|to\s+debut\b)",
    re.UNICODE,
)
_DEALER_MENTION_RE2 = re.compile(
    # "the dealer NAME," — pattern molto affidabile
    r"(?:the dealer|our dealer|our distributor|il (?:dealer|rivenditore|concessionario|distributore))\s+"
    r"((?:" + _NT + r")(?:\s+(?!" + _STOP + r")" + _NT + r"){0,3})"
    r"(?:\s*[,;\.]\s|\s+[-–]|\s+will\b|\s+has\b|\s*$)",  # \s* per "Name ,"
    re.I | re.UNICODE,
)
_DEALER_MENTION_RE3 = re.compile(
    # "with NAME at/in [event]" — max 3 token prima di preposizione
    r"\bwith\s+"
    r"((?:" + _NT + r")(?:\s+(?!" + _STOP + r")" + _NT + r"){0,2})"
    r"(?:\s+(?:at|in|for)\b|[,.])",
    re.UNICODE,
)
_DEALER_MENTION_RE4 = re.compile(
    # "dealer/rivenditore NAME, has/will..."
    r"(?:dealer|rivenditore|concessionario|distributore)(?:[^,]{0,50},\s*)?"
    r"((?:" + _NT + r")(?:\s+(?!" + _STOP + r")" + _NT + r"){0,3})"
    r"(?:,\s*(?:has|have|will|is|are)\b)",
    re.I | re.UNICODE,
)

# Slug comuni per sezioni news/blog (IT e EN)
_NEWS_SLUGS = [
    "/en/news/our-events/", "/en/news/our-updates/",
    "/en/news/", "/news/our-events/", "/news/our-updates/",
    "/news/", "/articoli/", "/blog/",
    "/press/", "/press-releases/", "/en/blog/", "/it/news/",
]

# Pattern per riconoscere link ad articoli individuali (almeno 3 segmenti di path)
_ARTICLE_PATH_RE = re.compile(r"^/\w[\w\-]+/[\w\-]+/[\w\-]")

# Tag/path da escludere (pagine di sistema, non articoli)
_NON_ARTICLE_KW = {
    "product", "prodotto", "category", "tag", "/page/", "login",
    "contact", "contatt", "about", "chi-siam", "aziend",
    "certif", "history", "mission", "service", "accessori",
}


def _comp_variants(competitor_name: str, base_url: str = "") -> set[str]:
    """
    Genera varianti del nome competitor per la ricerca nel testo degli articoli.
    Deriva anche dal dominio del sito (es. easy-lift.com → 'easy lift', 'easy-lift').
    """
    n = competitor_name.strip().lower()
    variants = {n}
    variants.add(n.replace(" ", "-"))
    variants.add(n.replace(" ", ""))
    # CamelCase: "EasyLift" → "easy lift"
    spaced = re.sub(r'([a-z])([A-Z])', r'\1 \2', competitor_name).lower()
    variants.add(spaced)
    # Dal dominio: "easy-lift.com" → "easy-lift", "easy lift"
    if base_url:
        try:
            domain = urlparse(base_url).hostname or ""
            # rimuovi www. e TLD
            stem = re.sub(r'^www\.', '', domain)
            stem = re.sub(r'\.[a-z]{2,4}$', '', stem)
            if stem:
                variants.add(stem.lower())
                variants.add(stem.lower().replace("-", " "))
                variants.add(stem.lower().replace("-", ""))
        except Exception:
            pass
    return variants


def _extract_dealers_from_news(base_url: str, competitor_name: str, site_url: str = "") -> list[dict]:
    """
    Scansiona la sezione news/blog del sito e cerca menzioni di dealer
    negli articoli di stampa (es. "LVM Nacelles brings Easy Lift to...").
    Utile per siti con mappa dealer JS-rendered.
    """
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    comp_variants = _comp_variants(competitor_name, site_url or base_url)

    # ── Raccogli link a sezioni news ──────────────────────────────────────────
    news_section_urls: list[str] = []
    for slug in _NEWS_SLUGS:
        url = root + slug
        try:
            r = scrape_get(url, timeout=HTTP_TIMEOUT)
            if r.status_code == 200 and len(r.text) > 2000:
                news_section_urls.append(url)
        except Exception:
            pass
        if len(news_section_urls) >= 3:
            break

    if not news_section_urls:
        return []

    # ── Estrai link ad articoli da tutte le sezioni trovate ──────────────────
    article_links: list[str] = []
    seen_paths: set[str] = set()

    for section_url in news_section_urls:
        html = _fetch_page(section_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            full = urljoin(base_url, a["href"])
            if not _is_safe_url(full):
                continue
            if urlparse(full).netloc != parsed.netloc:
                continue
            path = urlparse(full).path
            if path in seen_paths or not _ARTICLE_PATH_RE.match(path):
                continue
            if any(kw in path.lower() for kw in _NON_ARTICLE_KW):
                continue
            seen_paths.add(path)
            article_links.append(full)

    logger.debug("News: trovati %d articoli candidati in %s", len(article_links), base_url)

    # ── Leggi ogni articolo ed estrai nomi di dealer ──────────────────────────
    candidate_names: set[str] = set()
    seen_norm: set[str] = set()  # normalizzati per deduplicazione

    for art_url in article_links[:30]:
        art_html = _fetch_page(art_url)
        if not art_html:
            continue
        art_soup = BeautifulSoup(art_html, "html.parser")
        for tag in art_soup.find_all(["header", "footer", "nav", "script", "style"]):
            tag.decompose()
        text = art_soup.get_text(" ", strip=True)

        # Processa solo articoli che menzionano il competitor
        text_l = text.lower()
        if not any(v in text_l for v in comp_variants):
            continue

        # Applica i quattro pattern di estrazione
        for pattern in (_DEALER_MENTION_RE, _DEALER_MENTION_RE2,
                        _DEALER_MENTION_RE3, _DEALER_MENTION_RE4):
            for m in pattern.finditer(text):
                name = m.group(1).strip()
                # Pulizia: rimuovi trailing preposizioni e punteggiatura
                name = re.sub(
                    r"\s+(?:at|in|for|to|and|the|a|con|per|di|il|la|lo|le|gli)\b.*$",
                    "", name, flags=re.I,
                ).strip()
                name = re.sub(r"[,;.]+$", "", name).strip()
                # Rimuovi prefissi di navigazione (breadcrumb) rimasti nel testo
                name = _NAV_PREFIX_RE.sub("", name).strip()
                if (name
                        and _looks_like_company(name)
                        and not any(v in name.lower() for v in comp_variants)):
                    norm = re.sub(r'\s+', '', name.lower())
                    if norm not in seen_norm:
                        seen_norm.add(norm)
                        candidate_names.add(name)

    dealers: list[dict] = []
    for name in candidate_names:
        dealers.append({
            "name": name,
            "website": "", "phone": "", "email": "",
            "address": "", "city": "", "region": "", "country": "",
            "source": "news",
            "source_url": news_section_urls[0],
        })

    logger.info("News scraping '%s': %d dealer estratti da %d articoli",
                base_url, len(dealers), len(article_links))
    return dealers


def _search_dealers_on_site(base_url: str) -> list[dict]:
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
        # Cerca link a pagine dealer nella homepage
        html = _fetch_page(base_url)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            dealer_kw = [
                "dealer", "rivenditore", "concessionario", "store",
                "distributor", "reseller", "where-to-buy", "find-a",
            ]
            for a in soup.find_all("a", href=True):
                href = a["href"].lower()
                text = a.get_text(strip=True).lower()
                if any(kw in href or kw in text for kw in dealer_kw):
                    full = urljoin(base_url, a["href"])
                    if _is_safe_url(full) and full != base_url:
                        dealers = _scrape_dealer_page(full, source_url=full)
                        all_dealers.extend(dealers)
                        if len(all_dealers) >= 100:
                            break
    return all_dealers


def _search_dealers_tavily(competitor_name: str, sector: str) -> list[dict]:
    """
    Usa Tavily per trovare pagine con liste dealer del costruttore.
    NOTA: salva solo i dealer estratti da pagine reali, NON i risultati
    Tavily stessi come dealer (evita titoli di articoli e home-page generiche).
    """
    if not settings.tavily_api_key:
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        # Query mirate a trovare pagine con liste dealer con contatti
        queries = [
            f'"{competitor_name}" authorized dealers resellers list address phone',
            f'"{competitor_name}" rivenditori concessionari autorizzati telefono indirizzo',
        ]
        dealers: list[dict] = []
        seen_urls: set[str] = set()
        for query in queries:
            resp = client.search(query=query, max_results=5, include_raw_content=False)
            for r in resp.get("results", []):
                url = r.get("url", "")
                if not url or url in seen_urls or not _is_safe_url(url):
                    continue
                seen_urls.add(url)
                # Scrapiamo la pagina come potenziale lista dealer
                page_dealers = _scrape_dealer_page(url, source_url=url)
                # Aggiunge solo risultati reali (>= _MIN_DEALERS_PER_PAGE già verificato)
                dealers.extend(page_dealers)
                # Non aggiungiamo il link Tavily come dealer se la pagina non ha contenuto valido
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
    3. Salvataggio in competitor_dealers + anagrafica globale dealers
    Ritorna lista di dealer salvati.
    """
    from models.competitor import Competitor, CompetitorDealer
    from models.dealer import Dealer, DealerBrand

    competitor = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not competitor:
        logger.error("Competitor %d non trovato", competitor_id)
        return []

    candidates: list[dict] = []

    if competitor.website:
        # 1. Scraping diretto delle pagine dealer (funziona se contenuto è statico)
        candidates.extend(_search_dealers_on_site(competitor.website))
        # 2. Se la ricerca diretta non ha trovato nulla (siti con mappa JS),
        #    estrai dealer dagli articoli/press release del sito
        if not candidates:
            candidates.extend(
                _extract_dealers_from_news(competitor.website, competitor.name, competitor.website)
            )

    # 3. Ricerca Tavily (se configurata)
    candidates.extend(_search_dealers_tavily(competitor.name, competitor.sector or ""))

    # Deduplicazione per nome (case-insensitive)
    seen_names: set[str] = set(
        d.name.lower() for d in db.query(CompetitorDealer).filter(
            CompetitorDealer.competitor_id == competitor_id).all()
    )

    # Nomi da escludere: il competitor stesso non è un proprio dealer
    competitor_name_lower = competitor.name.strip().lower()

    saved: list[dict] = []
    for cand in candidates:
        key = (cand.get("name") or "").strip().lower()
        if not key or key in seen_names:
            continue
        # Salta se il nome coincide (quasi) con il nome del competitor
        if key == competitor_name_lower or competitor_name_lower in key:
            continue
        seen_names.add(key)

        # 1. Salva in competitor_dealers (per-competitor, esistente)
        cd = CompetitorDealer(
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
        db.add(cd)
        db.flush()

        # 2. Upsert nel registro globale dealers
        global_dealer = db.query(Dealer).filter(
            Dealer.name.ilike(cand.get("name", "").strip())
        ).first()
        if not global_dealer:
            global_dealer = Dealer(
                name=(cand.get("name") or "")[:500],
                website=(cand.get("website") or "")[:1000],
                email=(cand.get("email") or "")[:200],
                phone=(cand.get("phone") or "")[:100],
                address=(cand.get("address") or "")[:500],
                city=(cand.get("city") or "")[:200],
                state=(cand.get("region") or "")[:200],
                country=(cand.get("country") or "")[:100],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(global_dealer)
            db.flush()

        # Collega al competitor nel registry globale se non già presente
        already_linked = db.query(DealerBrand).filter(
            DealerBrand.dealer_id == global_dealer.id,
            DealerBrand.competitor_id == competitor_id,
        ).first()
        if not already_linked:
            db.add(DealerBrand(
                dealer_id=global_dealer.id,
                competitor_id=competitor_id,
                is_own_brand=False,
            ))

        db.commit()
        saved.append({
            "id": cd.id,
            "name": cd.name,
            "website": cd.website,
            "city": cd.city,
            "country": cd.country,
            "source": cd.source,
        })

    logger.info("Dealer search completata per competitor %d: %d nuovi", competitor_id, len(saved))
    return saved

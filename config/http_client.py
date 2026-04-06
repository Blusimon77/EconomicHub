"""
Configurazione centralizzata per le richieste HTTP di scraping.

Tutti gli agenti che scansionano siti web terzi devono usare le funzioni
di questo modulo per garantire:
- Header browser realistici
- Accettazione automatica dei banner cookie/privacy (cookie di consenso)
- Timeout e redirect uniformi
"""
from __future__ import annotations

import httpx

# ── Header di base simulanti un browser reale ────────────────────────────────
# User-Agent aggiornato (Chrome 124 su Windows)
_BASE_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "0",          # Do Not Track: No (necessario per alcuni siti)
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

# ── Cookie di consenso privacy/GDPR ──────────────────────────────────────────
# Coprono i principali sistemi di banner cookie in uso sul web:
#   - Cookieconsent.js (wook/orestbida)
#   - CookieYes / CookieLaw
#   - Cookie-Script
#   - Complianz
#   - Iubenda
#   - Usercentrics (flag generico)
#   - OneTrust (flag semplificato)
#   - Quantcast
#   - Drupal EU Cookie Compliance
#   - WP Cookie Notice
#   - Borlabs Cookie
#   - Faenza / implementazioni custom italiane
_CONSENT_COOKIES: dict[str, str] = {
    # Cookieconsent.js
    "cookieconsent_status": "allow",
    "cookieconsent_dismissed": "yes",
    # CookieYes
    "cookieyes-consent": "consentid:accepted,consent:yes,action:yes,necessary:yes,functional:yes,analytics:yes,performance:yes,advertisement:yes",
    # Cookie-Script
    "CookieScriptConsent": '{"action":"accept","categories":"[\\"necessary\\",\\"analytics\\",\\"marketing\\",\\"functional\\"]"}',
    # Complianz (WordPress)
    "cmplz_consent_status": "all",
    "complianz_consent_status": "all",
    # Iubenda
    "_iub_cs-consent": '{"timestamp":"2024-01-01T00:00:00.000Z","version":"1.0","purposes":{"1":true,"2":true,"3":true,"4":true,"5":true},"id":1}',
    # OneTrust (semplificato)
    "OptanonAlertBoxClosed": "2024-01-01T00:00:00.000Z",
    "OptanonConsent": "isIABGlobal=false&datestamp=Mon+Jan+01+2024&version=202309.1.0&isGpcEnabled=0&landingPath=NotLandingPage&groups=C0001%3A1%2CC0002%3A1%2CC0003%3A1%2CC0004%3A1",
    # Quantcast
    "addtl_consent": "accepted",
    # WP Cookie Notice (wp-cookie-notice)
    "cookie_notice_accepted": "1",
    "wpl_viewed_cookie": "yes",
    # Borlabs Cookie
    "borlabs-cookie": '{"consents":{"statistics":true,"marketing":true}}',
    # GDPR Cookie Compliance (Moove)
    "moove_gdpr_popup": '{"strict":true,"thirdparty":true,"advanced":true}',
    # Drupal EU Cookie Compliance
    "cookie-agreed": "2",
    "cookie-agreed-version": "1.0.0",
    # Generici custom (molto diffusi su siti italiani e internazionali)
    "cookie_consent": "1",
    "gdpr_consent": "1",
    "consent": "accepted",
    "cookieAccepted": "true",
    "CookieConsent": "true",
    "cookie_policy_accepted": "1",
    "privacy_accepted": "1",
    "accept_cookies": "1",
    "cookies_accepted": "yes",
    "eu_cookie_law_consent": "1",
}


def scrape_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """
    Restituisce gli header HTTP completi per le richieste di scraping,
    inclusi gli header di navigazione browser e i cookie di consenso.

    Uso:
        resp = httpx.get(url, headers=scrape_headers(), ...)
    """
    cookie_str = "; ".join(f"{k}={v}" for k, v in _CONSENT_COOKIES.items())
    headers = {**_BASE_HEADERS, "Cookie": cookie_str}
    if extra:
        headers.update(extra)
    return headers


def scrape_get(url: str, timeout: int = 15, **kwargs) -> httpx.Response:
    """
    Esegue una GET con header e cookie di consenso preimpostati.
    Wrapper conveniente per httpx.get().
    """
    return httpx.get(
        url,
        headers=scrape_headers(),
        timeout=timeout,
        follow_redirects=True,
        **kwargs,
    )


def scrape_stream(url: str, timeout: int = 15, **kwargs):
    """
    Context manager per download in streaming con header e cookie di consenso.
    Wrapper conveniente per httpx.stream().

    Uso:
        with scrape_stream(url) as resp:
            for chunk in resp.iter_bytes(): ...
    """
    return httpx.stream(
        "GET",
        url,
        headers=scrape_headers(),
        timeout=timeout,
        follow_redirects=True,
        **kwargs,
    )

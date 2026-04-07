# Piano di Miglioramento — Social Media Manager

**Data:** 2026-04-06  
**Stato:** Completato — tutte e 4 le fasi eseguite  
**Basato su:** Review completa del codebase

---

## Contesto

La review del progetto ha evidenziato problemi di sicurezza, robustezza e manutenibilità.
Il sistema funziona in locale ma non era pronto per un uso condiviso o in rete.
Questo piano ha organizzato gli interventi in fasi incrementali, ognuna auto-contenuta e committata separatamente.

---

## Fase 1 — Fix bloccanti e sicurezza base ✅

**Obiettivo:** Eliminare bug immediati e le vulnerabilità più gravi.

- [x] **1.1 Fix compatibilità Python 3.9**
  - `from __future__ import annotations` aggiunto in `main.py` e tutti gli agenti

- [x] **1.2 Validazione URL anti-SSRF**
  - `_is_safe_url()` in `dashboard/main.py` — blocca IP privati, loopback, schemi non-HTTP

- [x] **1.3 Sanitizzazione scrittura `.env`**
  - Whitelist `_SETTINGS_WHITELIST` + `_sanitize_env_value()` in `/settings` POST

- [x] **1.4 Autenticazione dashboard**
  - `AuthMiddleware` con cookie HMAC-SHA256 signed, route `/login` e `/logout`
  - Configurabile via `DASHBOARD_PASSWORD` in `.env`; disabilitata se vuoto

- [x] **1.5 Protezione CSRF**
  - `CSRFMiddleware` riscritto come middleware ASGI puro (no `BaseHTTPMiddleware`)
  - Body re-iniettato via `cached_receive()` senza consumare lo stream
  - Token in `scope["csrf_token"]`, iniettato via JS in tutti i form POST (inclusi dinamici con `MutationObserver`)

---

## Fase 2 — Robustezza e gestione errori ✅

- [x] **2.1 Logging strutturato** — `config/logging.py` con handler file + console; tutti i `print()` sostituiti con `logger.*`
- [x] **2.2 Try-except nei job schedulati** — `orchestrator.py` wrappa tutti i job
- [x] **2.3 Context manager sessioni DB** — `with Session() as session:` in orchestrator e agenti
- [x] **2.4 Gestione errori API** — nessun `except: pass` silente; fallback loggato
- [x] **2.5 Timeout espliciti** — `HTTP_TIMEOUT` costante usata in tutte le chiamate httpx

---

## Fase 3 — Qualità del codice ✅

- [x] **3.1 Costanti** — `MAX_SCRAPED_CONTENT`, `MAX_RAW_RESPONSE`, `HTTP_TIMEOUT`, `AI_MAX_TOKENS`, ecc.
- [x] **3.2 BeautifulSoup** — sostituisce regex su HTML in `dashboard/main.py` e `competitor_analyst.py`
- [x] **3.3 Pulizia dipendenze** — rimossi `linkedin-api`, `facebook-sdk`; versioni pinnate con `==`
- [x] **3.4 Paginazione query** — `.limit(100)` su post PENDING, `.limit(50)` su analisi
- [x] **3.5 Datetime timezone-aware** — `datetime.now(timezone.utc)` ovunque

---

## Fase 4 — Infrastruttura di test ✅

- [x] **4.1 pytest + fixtures** — `tests/conftest.py` con `db_session` (SQLite in-memory) e `test_client` (ASGI transport)
- [x] **4.2 Test route dashboard** — `tests/test_dashboard.py`: smoke 6 route, validazione URL SSRF, sanitizzazione .env
- [x] **4.3 Test agenti** — `tests/test_agents.py`: ContentGenerator, MonitorAgent, ReplyAgent, CompetitorAnalyst con mock API

---

## Sviluppi successivi al piano (2026-04-06 →)

Funzionalità aggiunte dopo il completamento del piano originale:

### Intelligence competitor potenziata
- **Ricerca profili social automatica** — durante l'analisi, l'agente cerca e salva LinkedIn/Facebook/Instagram mancanti via scraping + Tavily
- **ProductScoutAgent** (`agents/product_scout.py`) — ricerca dati tecnici e PDF sul sito costruttore, Tavily e siti dealer; estrae specifiche strutturate
- **DealerScoutAgent** (`agents/dealer_scout.py`) — individua la rete distributiva del competitor via scraping + Tavily; anagrafica strutturata
- **Nuovi modelli DB** — `CompetitorDealer`, `CompetitorProduct` (con `tech_specs` JSON, `category`, `dealer_id`)

### HTTP client centralizzato
- `config/http_client.py` — `scrape_headers()`, `scrape_get()`, `scrape_stream()`
- 26 cookie di consenso privacy/GDPR automatici (Cookieconsent, CookieYes, OneTrust, Iubenda, Complianz, ecc.)
- User-Agent e header browser realistici su tutti gli agenti di scraping

### Dashboard — pannello competitor a 6 tab
- Tab **Prodotti**: documenti tecnici con categoria, fonte, specifiche estratte espandibili, download PDF
- Tab **Concessionari**: anagrafica dealer raggruppata per paese, ricerca automatica, aggiunta manuale

---

## Prossimi step consigliati

| Priorità | Task |
|----------|------|
| 🔴 | Implementare `integrations/linkedin.py` — pubblicazione post via LinkedIn API |
| 🔴 | Implementare `integrations/facebook.py` — pubblicazione Facebook + Instagram |
| 🔴 | Completare scheduler pubblicazione in `orchestrator.py` |
| 🟠 | Form generazione post nel dashboard (attualmente solo CLI) |
| 🟠 | Analytics con grafici (metriche già raccolte, mancano visualizzazioni) |
| 🟡 | Upload immagini per post |
| 🟡 | Alembic per migrations automatiche |
| 🟡 | RBAC (admin / viewer) |

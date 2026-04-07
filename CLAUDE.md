# CLAUDE.md — Social Media Manager

Guida per sessioni Claude Code su questo progetto.
Leggi questo file prima di toccare qualsiasi cosa.

---

## Cos'è questo progetto

Sistema multi-agente Python per gestire i social aziendali (LinkedIn, Facebook, Instagram).
Stack: **Python 3.9 · FastAPI · SQLAlchemy · SQLite · Jinja2 · Anthropic SDK · OpenAI SDK · Tavily**.

Il dashboard gira su `http://localhost:8000` e si avvia con:
```bash
source .venv/bin/activate
python main.py dashboard
```

---

## Vincolo critico — Python 3.9

Il venv usa Python 3.9. La sintassi `X | Y` per i type hint non è supportata nativamente.
**Aggiungi sempre** `from __future__ import annotations` in cima a ogni file che usa union types.

```python
# SBAGLIATO su 3.9
def foo(x: str | None) -> dict | None: ...

# CORRETTO
from __future__ import annotations
def foo(x: str | None) -> dict | None: ...
```

---

## Struttura del progetto

```
social-media-manager/
├── agents/
│   ├── content_generator.py   # Genera post AI per piattaforma
│   ├── monitor.py             # Monitora commenti/menzioni via API social
│   ├── reply_agent.py         # Bozze risposte ai commenti
│   ├── analytics.py           # Raccoglie metriche da API social
│   ├── competitor_analyst.py  # Analisi competitiva: scraping + Tavily + AI
│   ├── product_scout.py       # Cerca dati tecnici/PDF sul sito costruttore e dealer
│   └── dealer_scout.py        # Individua concessionari/rivenditori del costruttore
├── workflows/
│   └── orchestrator.py        # APScheduler: monitor 15min, reply 30min, analytics 1h
├── integrations/              # INCOMPLETO — connettori pubblicazione reale
│   ├── linkedin.py            # Da implementare
│   ├── facebook.py            # Da implementare
│   └── instagram.py           # Da implementare
├── models/
│   ├── post.py                # Post, Comment + enum Platform/PostStatus
│   ├── context.py             # CompanyContext, ContextWebsite
│   └── competitor.py          # Competitor, CompetitorSocial, CompetitorObservation,
│                              # CompetitorDealer, CompetitorProduct, CompetitorAnalysis
├── dashboard/
│   ├── main.py                # TUTTE le route FastAPI (unico file, ~1000 righe)
│   └── templates/             # 6 template Jinja2
│       ├── index.html         # /  — coda approvazione post e risposte
│       ├── analytics.html     # /analytics
│       ├── context.html       # /context
│       ├── competitors.html   # /competitors (JS interattivo, 6 tab per competitor)
│       ├── competitor_analysis.html  # /competitors/analysis
│       └── settings.html      # /settings
├── config/
│   ├── settings.py            # pydantic-settings — legge .env
│   ├── logging.py             # setup_logging() + get_logger(name)
│   └── http_client.py         # scrape_headers(), scrape_get(), scrape_stream()
│                              # con 26 cookie di consenso privacy/GDPR
├── tests/
│   ├── conftest.py            # Fixture: db_session (SQLite in-memory), test_client
│   ├── test_dashboard.py      # Test smoke route + validazione URL + sanitizzazione
│   └── test_agents.py         # Test agenti con mock API esterne
├── storage/
│   ├── social_manager.db      # SQLite — unico file DB
│   ├── brochures/             # PDF tecnici scaricati: brochures/{competitor_id}/
│   └── app.log                # Log applicazione
├── plans/
│   └── 2026-04-06_improvement-plan.md
├── .env                       # Chiavi API — NON committare
├── .env.example               # Template
├── requirements.txt
├── main.py                    # CLI typer: dashboard / generate / start / analytics
├── START.md                   # Guida avvio
└── README.md                  # Documentazione progetto
```

---

## Database — regole importanti

Il DB è SQLite gestito da SQLAlchemy con `Base.metadata.create_all()`.

**`create_all()` NON aggiunge colonne a tabelle già esistenti.**
Se aggiungi una colonna a un modello, devi anche eseguire:
```python
from sqlalchemy import create_engine, text
engine = create_engine("sqlite:///./storage/social_manager.db")
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE nome_tabella ADD COLUMN nuova_colonna TEXT DEFAULT ""'))
    conn.commit()
```

**Schema attuale delle tabelle:**
- `posts` — id, platform, status, content, hashtags, image_url, media_path, topic, tone, generated_by, scheduled_at, published_at, platform_post_id, approved_by, approval_note
- `comments` — id, platform, platform_comment_id, platform_post_id, author_name, content, is_mention, reply_draft, reply_status, reply_published_at
- `company_context` — id, company_name, description, mission, values, founded, products_services, target_audience, sector, competitors, tone_of_voice, topics_to_avoid, content_pillars, additional_notes
- `context_websites` — id, url, label, category, notes, scraped_content, last_scraped_at, is_active
- `competitors` — id, name, website, sector, description, strengths, weaknesses, content_strategy, target_audience, tone_of_voice, unique_topics, posting_frequency, threat_level, is_active, scraped_content, last_scraped_at, search_results (JSON), last_searched_at
- `competitor_socials` — id, competitor_id, platform, profile_url, handle, followers, avg_likes, avg_comments, posting_days, content_types, notes
- `competitor_observations` — id, competitor_id, category, content
- `competitor_dealers` — id, competitor_id, name, website, address, city, region, country, phone, email, notes, source, source_url, found_at
- `competitor_products` — id, competitor_id, dealer_id (nullable), name, product_line, category, tech_specs (JSON), tech_summary, brochure_url, brochure_filename, page_url, source, file_size_kb, found_at
- `competitor_analyses` — id, summary, landscape, data_quality, per_competitor (JSON), opportunities (JSON), threats (JSON), recommendations (JSON), content_gaps (JSON), sources_used (JSON), raw_response, generated_by

---

## HTTP client centralizzato — config/http_client.py

**Tutti gli agenti che fanno scraping devono usare questo modulo**, non `httpx` direttamente.

```python
from config.http_client import scrape_get, scrape_stream, scrape_headers

# GET semplice
resp = scrape_get(url, timeout=15)

# Download in streaming (PDF)
with scrape_stream(url) as resp:
    for chunk in resp.iter_bytes(): ...

# Async (dashboard/main.py)
async with httpx.AsyncClient(...) as client:
    resp = await client.get(url, headers=scrape_headers())
```

Il modulo imposta automaticamente:
- User-Agent realistico (Chrome 124)
- Header `Sec-Fetch-*`, `Accept-Language: it-IT`, `DNT: 0`
- 26 cookie di consenso privacy/GDPR (Cookieconsent, CookieYes, OneTrust, Iubenda, Complianz, ecc.)

---

## Pattern AI — provider primario + fallback

Tutti gli agenti seguono lo stesso schema: tenta Claude, poi fallback su OpenAI-compatible.

```python
result, provider = _try_anthropic(prompt)
if not result:
    result, provider = _try_openai(prompt)
```

I provider sono configurati in `.env`:
- `AI_PRIMARY_PROVIDER=anthropic` (o `openai`)
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL=claude-sonnet-4-6`
- `OPENAI_COMPATIBLE_BASE_URL=http://10.99.97.102:8080/v1`
- `OPENAI_COMPATIBLE_API_KEY=none`
- `OPENAI_COMPATIBLE_MODEL=Qwen3.5-122B`

Il server Qwen locale è sempre disponibile come fallback su `http://10.99.97.102:8080/v1`.

---

## Analisi competitor — principio fondamentale

Il modello **NON deve usare la propria memoria di training** per dati sui competitor.
Il `SYSTEM_PROMPT` in `agents/competitor_analyst.py` lo istruisce esplicitamente.

Pipeline prima di ogni analisi:
1. Scraping sito web (`scrape_get` + BeautifulSoup) — aggiornato se >7 giorni
2. Ricerca Tavily — 2 query per competitor (`TAVILY_API_KEY` in `.env`)
3. Ricerca automatica profili social mancanti (LinkedIn, Facebook, Instagram)
4. Dati manuali dal DB
5. Tutto nel prompt → AI → JSON strutturato
6. `sources_used` salvato in `competitor_analyses` e mostrato nel template

---

## Ricerca prodotti tecnici — product_scout.py

Pipeline multi-sorgente per dati tecnici:
1. Sito costruttore — slug tecnici (`/download`, `/resources`, `/schede-tecniche`, ecc.)
2. Tavily — query focalizzate su `datasheet scheda tecnica filetype:pdf`
3. Siti dealer già in DB — scansione per PDF del costruttore

Ogni documento trovato viene:
- Classificato (Scheda tecnica / Manuale / Catalogo / Certificazione)
- Filtrato per pertinenza tecnica (esclude privacy, cookie, careers)
- Analizzato per specifiche strutturate (tabelle HTML, DL, pattern chiave:valore)
- Scaricato in `storage/brochures/{competitor_id}/` se PDF diretto (max 20 MB)

---

## Ricerca concessionari — dealer_scout.py

Pipeline per individuare la rete distributiva:
1. Scraping slug dealer-page sul sito costruttore (`/dealers`, `/rivenditori`, ecc.)
2. Ricerca Tavily — query mirate per dealer/rivenditori autorizzati
3. Estrazione strutturata: nome, email, telefono, indirizzo, città, paese
4. Salvataggio in `competitor_dealers` con deduplicazione per nome

---

## Route FastAPI — ordine critico

Tutte le route sono in `dashboard/main.py`. L'ordine conta per FastAPI:
le route statiche devono stare **prima** di quelle con parametri `{id}`.

```python
# CORRETTO — route statiche prima di quelle con {id}
@app.get("/competitors/analysis")          # ← prima
@app.post("/competitors/analysis/generate")
@app.post("/competitors/{cid}/products/search")  # ← dopo
@app.get("/api/competitors/{cid}/products")
@app.get("/api/competitors/{cid}")         # ← ultima
```

---

## Tab nel pannello competitor (competitors.html)

Il pannello dettaglio competitor ha 6 tab, tutte lazy-loaded via JS:

| Tab | ID | Caricamento |
|-----|----|-------------|
| Profilo | `tab-profilo` | Dati inline in `renderDetail(c)` |
| Social | `tab-social` | Dati inline in `renderDetail(c)` |
| Strategia | `tab-strategia` | Dati inline in `renderDetail(c)` |
| Note | `tab-osservazioni` | Dati inline in `renderDetail(c)` |
| Prodotti | `tab-prodotti` | Fetch `/api/competitors/{cid}/products` on click |
| Concessionari | `tab-concessionari` | Fetch `/api/competitors/{cid}/dealers` on click |

Le ultime due tab usano lazy-load separato. Se aggiungi una nuova tab, segui lo stesso pattern:
`onclick="activateTab('nome'); loadNome(${c.id})"` e una funzione `loadNome(cid, force)`.

---

## Template HTML — navigazione

La navbar è replicata in ogni template (non c'è un base layout condiviso).
La nav completa corretta è:

```html
<a href="/">Approvazioni</a>
<a href="/analytics">Analytics</a>
<a href="/context">Contesto</a>
<a href="/competitors">Concorrenti</a>
<a href="/competitors/analysis">Analisi</a>
<a href="/settings">Impostazioni</a>
```

Se aggiungi una nuova pagina, aggiorna la nav in **tutti e 6 i template**.

---

## Cosa è completo

- [x] Dashboard web a 6 sezioni (FastAPI + Jinja2)
- [x] Generazione contenuti AI con contesto aziendale iniettato nel prompt
- [x] Flusso approvazione umana (PENDING → APPROVED/REJECTED → PUBLISHED)
- [x] Monitor commenti e menzioni (polling via API social)
- [x] Reply agent con bozze AI per approvazione
- [x] Analytics agent (raccolta metriche da API social)
- [x] Sezione Contesto aziendale con scraping siti di riferimento
- [x] Sezione Competitor con pannello interattivo a 6 tab
- [x] Ricerca automatica profili social mancanti durante analisi
- [x] Analisi competitiva AI con scraping + Tavily + fonti verificabili
- [x] Ricerca dati tecnici/PDF prodotti (sito costruttore + Tavily + dealer)
- [x] Ricerca e anagrafica concessionari/rivenditori per ogni competitor
- [x] Settings page (provider AI, scheduling, monitoring)
- [x] Fallback automatico Claude → Qwen
- [x] Autenticazione dashboard con password + cookie HMAC-signed
- [x] Protezione CSRF (middleware ASGI puro, body re-injected)
- [x] Validazione URL anti-SSRF
- [x] Logging strutturato (file + console)
- [x] HTTP client centralizzato con consenso privacy automatico
- [x] Test pytest (route + agenti + sicurezza)

---

## Cosa manca (prossimi passi)

- [ ] **`integrations/linkedin.py`** — pubblicazione reale via LinkedIn API (`/posts`)
- [ ] **`integrations/facebook.py`** — pubblicazione Facebook + Instagram Graph API
- [ ] **Scheduler pubblicazione** — il cron in `orchestrator.py` che pubblica i post APPROVED all'orario pianificato chiama le integrations non ancora implementate
- [ ] **Form generazione post nel dashboard** — attualmente solo via CLI (`python main.py generate "..."`)
- [ ] **Analytics con grafici** — `AnalyticsAgent` raccoglie già le metriche ma `/analytics` mostra solo la lista post; mancano grafici reach/engagement
- [ ] **Upload immagini** — campi `image_url` e `media_path` nel modello ma non gestiti dalla UI
- [ ] **RBAC** — autenticazione binaria (sì/no), mancano ruoli (admin, viewer)
- [ ] **Alembic** — migrations manuali con `ALTER TABLE`; nessun versionamento schema

---

## Come approcciare nuovi task

**Aggiungere una nuova sezione al dashboard:**
1. Crea il modello in `models/` se serve un nuovo DB
2. Esegui `ALTER TABLE` per le colonne nuove (non affidarti a `create_all`)
3. Aggiungi le route in `dashboard/main.py` — route statiche prima di quelle con `{id}`
4. Crea il template in `dashboard/templates/` con la navbar completa
5. Aggiorna la navbar in tutti gli altri 6 template

**Aggiungere un nuovo agente di scraping:**
- Importa `scrape_get` / `scrape_stream` da `config/http_client.py` (mai `httpx` diretto)
- Segui il pattern: build_prompt → try_anthropic → try_openai → fallback
- Usa `get_logger(__name__)` da `config/logging.py`

**Aggiungere una colonna al DB:**
- Aggiornala nel modello Python
- Esegui `ALTER TABLE` sul DB esistente
- Non ricreare il DB — conterrà dati reali

**Debug rapido:**
```bash
cd ~/Documents/social-media-manager
source .venv/bin/activate
python -c "
import asyncio
from httpx import AsyncClient, ASGITransport
from dashboard.main import app

async def test():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        for path in ['/', '/analytics', '/context', '/competitors', '/competitors/analysis', '/settings']:
            r = await c.get(path)
            print(f'{path}: {r.status_code}')

asyncio.run(test())
"

# Esegui i test
pytest tests/ -v
```

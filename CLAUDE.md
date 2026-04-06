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
│   └── competitor_analyst.py  # Analisi competitiva: scraping + Tavily + AI
├── workflows/
│   └── orchestrator.py        # APScheduler: monitor 15min, reply 30min, analytics 1h
├── integrations/              # INCOMPLETO — connettori pubblicazione reale
│   ├── linkedin.py            # Da implementare
│   ├── facebook.py            # Da implementare
│   └── instagram.py          # Da implementare
├── models/
│   ├── post.py                # Post, Comment + enum Platform/PostStatus
│   ├── context.py             # CompanyContext, ContextWebsite
│   └── competitor.py          # Competitor, CompetitorSocial, CompetitorObservation, CompetitorAnalysis
├── dashboard/
│   ├── main.py                # TUTTE le route FastAPI (unico file)
│   └── templates/             # 6 template Jinja2
│       ├── index.html         # /  — coda approvazione
│       ├── analytics.html     # /analytics
│       ├── context.html       # /context
│       ├── competitors.html   # /competitors  (JS interattivo, carica via /api/competitors/{id})
│       ├── competitor_analysis.html  # /competitors/analysis
│       └── settings.html      # /settings
├── config/
│   └── settings.py            # pydantic-settings — legge .env
├── storage/
│   └── social_manager.db      # SQLite — unico file DB
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

Oppure suggerisci all'utente di eseguire lo snippet se preferisce farlo manualmente.

**Schema attuale delle tabelle:**
- `posts` — id, platform, status, content, hashtags, topic, tone, generated_by, scheduled_at, published_at, platform_post_id, approved_by, approval_note
- `comments` — id, platform, platform_comment_id, platform_post_id, author_name, content, is_mention, reply_draft, reply_status
- `company_context` — id, company_name, description, mission, values, founded, products_services, target_audience, sector, competitors, tone_of_voice, topics_to_avoid, content_pillars, additional_notes
- `context_websites` — id, url, label, category, notes, scraped_content, last_scraped_at, is_active
- `competitors` — id, name, website, sector, description, strengths, weaknesses, content_strategy, target_audience, tone_of_voice, unique_topics, posting_frequency, threat_level, is_active, scraped_content, last_scraped_at, **search_results**, **last_searched_at**
- `competitor_socials` — id, competitor_id, platform, profile_url, handle, followers, avg_likes, avg_comments, posting_days, content_types, notes
- `competitor_observations` — id, competitor_id, category, content
- `competitor_analyses` — id, summary, landscape, data_quality, per_competitor (JSON), opportunities (JSON), threats (JSON), recommendations (JSON), content_gaps (JSON), **sources_used** (JSON), raw_response, generated_by

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
1. Scraping sito web (`httpx` + pulizia regex) — aggiornato se >7 giorni
2. Ricerca Tavily — 2 query per competitor (`TAVILY_API_KEY` in `.env`)
3. Dati manuali dal DB
4. Tutto nel prompt → AI → JSON strutturato
5. `sources_used` salvato in `competitor_analyses` e mostrato nel template

---

## Route FastAPI — ordine critico

Tutte le route sono in `dashboard/main.py`. L'ordine conta per FastAPI:
le route statiche devono stare **prima** di quelle con parametri `{id}`.

```python
# CORRETTO — /competitors/analysis prima di /competitors/{cid}
@app.get("/competitors/analysis")   # ← prima
@app.get("/competitors/{cid}")      # ← dopo
```

Se aggiungi nuove route sotto `/competitors/`, rispetta questo ordine.

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
- [x] Analytics agent (raccolta metriche)
- [x] Sezione Contesto aziendale con scraping siti di riferimento
- [x] Sezione Competitor con schede interattive (profilo, social, strategia, osservazioni)
- [x] Analisi competitiva AI con scraping + Tavily + fonti verificabili nel report
- [x] Settings page (provider AI, scheduling, monitoring)
- [x] Fallback automatico Claude → Qwen

---

## Cosa manca (prossimi passi)

- [ ] **`integrations/linkedin.py`** — pubblicazione reale via LinkedIn API
- [ ] **`integrations/facebook.py`** — pubblicazione Facebook + Instagram Graph API
- [ ] **Autenticazione dashboard** — ora è completamente aperta, nessun login
- [ ] **Scheduler pubblicazione** — il cron che pubblica i post `APPROVED` all'orario pianificato è definito in `orchestrator.py` ma le chiamate reali alle API social non sono implementate
- [ ] **Generazione post da dashboard** — il form di generazione esiste solo via CLI (`python main.py generate "..."`)
- [ ] **Upload immagini** — i campi `image_url` e `media_path` esistono nel modello ma non sono gestiti dalla UI

---

## Come approcciare nuovi task

**Aggiungere una nuova sezione al dashboard:**
1. Crea il modello in `models/` se serve un nuovo DB
2. Esegui `ALTER TABLE` per le colonne nuove (non affidarti a `create_all`)
3. Aggiungi le route in `dashboard/main.py` — route statiche prima di quelle con `{id}`
4. Crea il template in `dashboard/templates/` con la navbar completa
5. Aggiorna la navbar in tutti gli altri 6 template

**Modificare un agente AI:**
- I prompt sono in costanti uppercase nella testa del file
- Il pattern di chiamata è sempre: build_prompt → try_anthropic → try_openai → fallback
- I risultati JSON vengono parsati con `_parse_json()` che è tollerante a testo extra

**Aggiungere una colonna al DB:**
- Aggiornala nel modello Python
- Esegui `ALTER TABLE` sul DB esistente
- Non ricreare il DB — conterrà dati reali

**Debug rapido:**
```bash
# Testa tutte le route
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
```

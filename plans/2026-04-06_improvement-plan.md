# Piano di Miglioramento — Social Media Manager

**Data:** 2026-04-06
**Basato su:** Review completa del codebase

---

## Contesto

La review del progetto ha evidenziato problemi di sicurezza, robustezza e manutenibilità.
Il sistema funziona in locale ma non è pronto per un uso condiviso o in rete.
Questo piano organizza gli interventi in fasi incrementali, ognuna auto-contenuta e committabile.

---

## Fase 1 — Fix bloccanti e sicurezza base

**Obiettivo:** Eliminare bug immediati e le vulnerabilità più gravi.

- [x] **1.1 Fix compatibilità Python 3.9**
  - **File:** `main.py`
  - **Cosa:** Aggiungere `from __future__ import annotations` in testa
  - **Perché:** `list[str]` causa `TypeError` su Python 3.9

- [x] **1.2 Validazione URL anti-SSRF**
  - **File:** `dashboard/main.py` (route scraping siti e competitor)
  - **Cosa:** Validare che gli URL inizino con `http://` o `https://` prima di passarli a `httpx.get()`
  - **Perché:** URL `file://` o indirizzi interni (169.254.x.x) sono un rischio SSRF

- [x] **1.3 Sanitizzazione scrittura `.env`**
  - **File:** `dashboard/main.py` (route `/settings` POST)
  - **Cosa:** Validare i valori prima di scriverli nel `.env` — nessun newline, nessun `=` nei valori, whitelist delle chiavi ammesse
  - **Perché:** Input utente scritto direttamente su file di configurazione

- [x] **1.4 Autenticazione base sul dashboard**
  - **File:** `dashboard/main.py`, `config/settings.py`, `dashboard/templates/*.html`
  - **Cosa:** Aggiungere autenticazione con password singola (configurata in `.env` come `DASHBOARD_PASSWORD`)
    - Middleware FastAPI che richiede login
    - Pagina login semplice
    - Cookie di sessione firmato con `dashboard_secret_key`
  - **Perché:** Tutte le route sono attualmente aperte a chiunque

- [x] **1.5 Protezione CSRF**
  - **File:** `dashboard/main.py`, template HTML con form
  - **Cosa:** Aggiungere token CSRF ai form POST (campo hidden + validazione server-side)
  - **Perché:** Tutti i form POST sono vulnerabili a CSRF

**Verifica Fase 1:**
```bash
# Test Python 3.9
python -c "from main import app"

# Test route protette
curl -s http://localhost:8000/ | grep -q "login"

# Test SSRF
# Verificare che URL file:// vengano rifiutati dalla UI
```

---

## Fase 2 — Robustezza e gestione errori

**Obiettivo:** Rendere il sistema resiliente a errori runtime.

### 2.1 Logging strutturato
- **File:** nuovo `config/logging.py`, tutti gli agenti, `dashboard/main.py`, `workflows/orchestrator.py`
- **Cosa:** Configurare `logging` Python con output su file (`storage/app.log`) e console. Sostituire tutti i `print()` con `logger.info/error/warning`
- **Perché:** Senza log, il debug in produzione è impossibile

### 2.2 Try-except nei job schedulati
- **File:** `workflows/orchestrator.py`
- **Cosa:** Wrappare `_run_monitor()`, `_run_reply_drafts()`, `_run_analytics()` in try-except con logging dell'errore
- **Perché:** Un'eccezione non gestita può crashare l'intero scheduler

### 2.3 Context manager per sessioni DB
- **File:** `workflows/orchestrator.py`, `agents/content_generator.py`, `agents/competitor_analyst.py`
- **Cosa:** Sostituire `session = Session(); ... session.close()` con `with Session() as session:`
- **Perché:** Session leak se avviene un'eccezione tra open e close

### 2.4 Gestione errori API negli agenti
- **File:** `agents/content_generator.py`, `agents/reply_agent.py`, `agents/monitor.py`, `agents/analytics.py`
- **Cosa:** Sostituire `except Exception: pass` con logging dell'errore + ritorno di un risultato di errore strutturato
- **Perché:** Errori silenti rendono impossibile capire cosa non funziona

### 2.5 Timeout espliciti sulle chiamate HTTP
- **File:** tutti gli agenti, `dashboard/main.py`
- **Cosa:** Aggiungere `timeout=15` a tutte le chiamate `httpx.get()` e `httpx.post()`
- **Perché:** Chiamate senza timeout possono bloccare indefinitamente

**Verifica Fase 2:**
```bash
# Verificare che i log vengano scritti
python main.py start &
sleep 5
cat storage/app.log

# Simulare errore API (chiave invalida) e verificare log
```

---

## Fase 3 — Qualità del codice

**Obiettivo:** Ridurre debito tecnico e migliorare manutenibilità.

### 3.1 Costanti per numeri magici
- **File:** `dashboard/main.py`, `agents/competitor_analyst.py`
- **Cosa:** Estrarre costanti: `MAX_SCRAPED_CONTENT = 8000`, `MAX_TOKENS = 1024`, `FACEBOOK_API_VERSION = "v19.0"`, ecc.
- **Perché:** Numeri hardcoded sparsi in tutto il codice

### 3.2 Parsing HTML con BeautifulSoup
- **File:** `dashboard/main.py`, `agents/competitor_analyst.py`
- **Cosa:** Sostituire catene di `re.sub()` su HTML con `BeautifulSoup(html, "html.parser").get_text()`
- **Perché:** Regex su HTML è fragile e potenzialmente lento (regex DoS)

### 3.3 Pulizia dipendenze
- **File:** `requirements.txt`
- **Cosa:** Rimuovere `linkedin-api` e `facebook-sdk` (non usati). Pinnare versioni con `==`
- **Perché:** Dipendenze fantasma e rischio di breaking changes

### 3.4 Paginazione query DB
- **File:** `dashboard/main.py`
- **Cosa:** Aggiungere `.limit(100)` alle query principali (post, commenti). Opzionale: parametro `?page=` nelle route
- **Perché:** `.all()` senza limiti carica tutto in memoria

### 3.5 Datetime timezone-aware
- **File:** `models/post.py`, `models/context.py`, `models/competitor.py`
- **Cosa:** Sostituire `datetime.utcnow()` con `datetime.now(timezone.utc)` nei default delle colonne
- **Perché:** Datetime naive sono deprecati e causano bug sottili

**Verifica Fase 3:**
```bash
# Test route dashboard
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

---

## Fase 4 — Infrastruttura di test

**Obiettivo:** Creare una rete di sicurezza per le modifiche future.

### 4.1 Setup pytest
- **File:** nuovo `tests/conftest.py`, `requirements.txt`
- **Cosa:** Aggiungere `pytest` e `httpx` ai dev requirements. Fixture per DB in-memory e client FastAPI di test

### 4.2 Test delle route principali
- **File:** nuovo `tests/test_dashboard.py`
- **Cosa:** Test smoke per tutte le 6 pagine (status 200), test POST per creazione/modifica/cancellazione

### 4.3 Test degli agenti
- **File:** nuovo `tests/test_agents.py`
- **Cosa:** Test unitari con mock delle API esterne (Anthropic, OpenAI, Tavily)

**Verifica Fase 4:**
```bash
pytest tests/ -v
```

---

## Riepilogo priorità

| Fase | Sforzo stimato | Impatto |
|------|---------------|---------|
| **Fase 1** — Sicurezza | Medio | Critico — prerequisito per qualsiasi uso reale |
| **Fase 2** — Robustezza | Medio | Alto — il sistema smette di fallire silenziosamente |
| **Fase 3** — Qualità codice | Basso-Medio | Medio — manutenibilità a lungo termine |
| **Fase 4** — Test | Medio | Alto — rete di sicurezza per sviluppo futuro |

Le fasi sono indipendenti ma l'ordine proposto è quello consigliato.
Ogni fase produce un commit separato.

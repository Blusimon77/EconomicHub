# Avvio rapido

## 1. Attiva il virtual environment

```bash
cd ~/Documents/social-media-manager
source .venv/bin/activate
```

---

## 2. Configura `.env`

Apri il file `.env` e inserisci le chiavi necessarie:

```bash
# AI — provider primario
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6

# AI — fallback OpenAI-compatible (es. Qwen locale o remoto)
OPENAI_COMPATIBLE_BASE_URL=http://10.99.97.102:8080/v1
OPENAI_COMPATIBLE_API_KEY=none
OPENAI_COMPATIBLE_MODEL=Qwen3.5-122B

# Quale provider usare per primo: "anthropic" o "openai"
AI_PRIMARY_PROVIDER=anthropic

# Ricerca web per analisi competitor, prodotti e dealer (free tier: tavily.com)
TAVILY_API_KEY=tvly-...

# Dashboard — lascia vuoto per disabilitare l'autenticazione
DASHBOARD_PASSWORD=la-tua-password

# LinkedIn
LINKEDIN_ACCESS_TOKEN=...
LINKEDIN_ORGANIZATION_ID=...

# Facebook / Instagram
FACEBOOK_ACCESS_TOKEN=...
FACEBOOK_PAGE_ID=...
INSTAGRAM_BUSINESS_ACCOUNT_ID=...

# Azienda
COMPANY_NAME=La Mia Azienda
BRAND_KEYWORDS=keyword1,keyword2
```

---

## 3. Avvia il dashboard

```bash
python main.py dashboard
```

Apri **http://localhost:8000** nel browser.

---

## 4. Comandi CLI

```bash
# Avvia dashboard
python main.py dashboard

# Genera post (rimangono in attesa di approvazione nel dashboard)
python main.py generate "Argomento del post"
python main.py generate "Lancio prodotto" --platform linkedin --platform facebook
python main.py generate "Evento" --platform instagram --tone ispirazionale

# Avvia tutti gli agenti in background (monitor, reply, analytics)
python main.py start

# Mostra metriche social da terminale
python main.py analytics

# Esegui i test
pytest tests/ -v
```

---

## 5. Sezioni del dashboard

| Pagina | URL | Cosa fare |
|---|---|---|
| **Approvazioni** | `/` | Approva, modifica o rifiuta post e risposte ai commenti |
| **Analytics** | `/analytics` | Visualizza i post pubblicati |
| **Contesto** | `/context` | Inserisci il profilo aziendale e i siti di riferimento |
| **Concorrenti** | `/competitors` | Gestisci competitor, dati tecnici e rete distributiva |
| **Analisi** | `/competitors/analysis` | Genera il report AI della concorrenza |
| **Impostazioni** | `/settings` | Configura AI, orari di pubblicazione, monitoring |

---

## 6. Flusso di lavoro consigliato

### Prima configurazione
1. Vai in **Contesto** → compila il profilo aziendale completo
2. Vai in **Concorrenti** → aggiungi i principali competitor con siti e dati social
3. Vai in **Impostazioni** → verifica provider AI e orari di pubblicazione

### Uso quotidiano
```
1. python main.py dashboard       ← tieni aperto in un terminale
2. python main.py generate "..."  ← genera contenuti
3. Approva dal browser            ← http://localhost:8000
4. python main.py start           ← avvia monitoring automatico
```

### Analisi competitor
1. Vai in **Concorrenti** → assicurati che ogni competitor abbia URL e dati base
2. Vai in **Analisi** → premi **Genera analisi**
3. Il sistema scrapa automaticamente i siti, cerca su Tavily e scopre i profili social prima di chiamare l'AI
4. Il report mostra le fonti usate per ogni insight — verificabili direttamente

### Ricerca prodotti tecnici
1. Vai in **Concorrenti** → seleziona un competitor → tab **Prodotti**
2. Premi **Cerca dati tecnici**
3. Il sistema scansiona il sito del costruttore, Tavily e i siti dei dealer già archiviati
4. I PDF vengono scaricati in locale; le specifiche tecniche vengono estratte e mostrate nella card

### Ricerca concessionari
1. Vai in **Concorrenti** → seleziona un competitor → tab **Concessionari**
2. Premi **Cerca concessionari**
3. Il sistema cerca le pagine dealer sul sito del costruttore e su Tavily
4. I concessionari trovati appaiono in lista raggruppata per paese
5. Puoi aggiungerne altri manualmente con il pulsante **+ Aggiungi manualmente**

---

## 7. Struttura file

| File / Cartella | Contenuto |
|---|---|
| `agents/` | Logica AI: content generation, monitor, reply, analytics, competitor analysis, product scout, dealer scout |
| `workflows/orchestrator.py` | Job schedulati (monitor 15min, reply 30min, analytics 1h) |
| `dashboard/main.py` | Tutte le route FastAPI |
| `dashboard/templates/` | Template HTML delle 6 pagine |
| `models/` | Schema DB: Post, Comment, CompanyContext, Competitor, CompetitorDealer, CompetitorProduct, CompetitorAnalysis |
| `config/settings.py` | Configurazione validata da pydantic — legge `.env` |
| `config/http_client.py` | HTTP client centralizzato con consenso privacy/GDPR |
| `config/logging.py` | Logger centralizzato (file `storage/app.log` + console) |
| `tests/` | Test pytest: route dashboard, agenti, sicurezza |
| `storage/social_manager.db` | Database SQLite — creato automaticamente al primo avvio |
| `storage/brochures/` | PDF tecnici scaricati, organizzati per competitor ID |
| `storage/app.log` | Log applicazione |
| `.env` | Chiavi API — **non condividere mai, non committare** |

---

## 8. Note importanti

- **Approvazione obbligatoria** — nessun post o risposta viene pubblicato senza il tuo OK esplicito
- **Analisi competitor** — il modello AI usa solo dati da scraping e Tavily, mai la propria memoria di training
- **Prodotti tecnici** — la ricerca scansiona costruttore + dealer; i PDF vengono salvati in `storage/brochures/`
- **Consenso privacy** — tutti gli agenti inviano automaticamente cookie di consenso GDPR durante lo scraping
- **Fallback automatico** — se Claude non è disponibile, il sistema usa automaticamente il provider OpenAI-compatible configurato
- **Database** — SQLite locale in `storage/social_manager.db` — nessun dato esce dalla tua macchina
- **Autenticazione** — imposta `DASHBOARD_PASSWORD` nel `.env` per proteggere il dashboard; lascia vuoto per disabilitarla

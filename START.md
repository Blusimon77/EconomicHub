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

# AI — fallback OpenAI-compatible (es. Qwen locale o remoto)
OPENAI_COMPATIBLE_BASE_URL=http://10.99.97.102:8080/v1
OPENAI_COMPATIBLE_API_KEY=none
OPENAI_COMPATIBLE_MODEL=Qwen3.5-122B

# Quale provider usare per primo: "anthropic" o "openai"
AI_PRIMARY_PROVIDER=anthropic

# Ricerca web per analisi competitor (free tier: tavily.com)
TAVILY_API_KEY=tvly-...

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

# Genera post (rimangono in attesa di approvazione)
python main.py generate "Argomento del post"
python main.py generate "Lancio prodotto" --platform linkedin --platform facebook
python main.py generate "Evento" --platform instagram --tone ispirazionale

# Avvia tutti gli agenti in background (monitor, reply, analytics)
python main.py start

# Mostra metriche social da terminale
python main.py analytics
```

---

## 5. Sezioni del dashboard

| Pagina | URL | Cosa fare |
|---|---|---|
| **Approvazioni** | `/` | Approva, modifica o rifiuta post e risposte ai commenti |
| **Analytics** | `/analytics` | Visualizza i post pubblicati |
| **Contesto** | `/context` | Inserisci il profilo aziendale e i siti di riferimento |
| **Concorrenti** | `/competitors` | Aggiungi competitor, dati social, osservazioni |
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
3. Il sistema scrapa automaticamente i siti e cerca su Tavily prima di chiamare l'AI
4. Il report mostra le fonti usate per ogni insight — verificabili direttamente

---

## 7. Struttura file

| File / Cartella | Contenuto |
|---|---|
| `agents/` | Logica AI: generazione contenuti, monitor, risposte, analytics, analisi competitor |
| `workflows/orchestrator.py` | Job schedulati (monitor 15min, reply 30min, analytics 1h) |
| `dashboard/main.py` | Tutte le route FastAPI |
| `dashboard/templates/` | Template HTML delle 6 pagine |
| `models/` | Schema DB: Post, Comment, CompanyContext, Competitor, CompetitorAnalysis |
| `config/settings.py` | Configurazione validata da pydantic — legge `.env` |
| `storage/` | Database SQLite — creato automaticamente al primo avvio |
| `.env` | Chiavi API — **non condividere mai, non committare** |

---

## 8. Note importanti

- **Approvazione obbligatoria**: nessun post o risposta viene pubblicato senza il tuo OK esplicito
- **Analisi competitor**: il modello AI usa solo dati raccolti da scraping e Tavily, mai la propria memoria di training
- **Fallback automatico**: se Claude non è disponibile, il sistema usa automaticamente il provider OpenAI-compatible configurato
- **Database**: SQLite locale in `storage/social_manager.db` — nessun dato esce dalla tua macchina

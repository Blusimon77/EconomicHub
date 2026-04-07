# Social Media Manager — Multi-Agent System

Sistema multi-agente per la gestione dei social aziendali (LinkedIn, Facebook, Instagram).
Genera contenuti con AI, pianifica le pubblicazioni, monitora menzioni e commenti, analizza la concorrenza e la rete distributiva dei competitor — tutto con approvazione umana obbligatoria prima di qualsiasi pubblicazione.

---

## Architettura

```
social-media-manager/
├── agents/
│   ├── content_generator.py    # Genera post con Claude / OpenAI-compatible
│   ├── monitor.py              # Monitora menzioni e nuovi commenti
│   ├── reply_agent.py          # Bozze risposte ai commenti
│   ├── analytics.py            # Raccoglie metriche di performance
│   ├── competitor_analyst.py   # Analisi AI della concorrenza (scraping + Tavily)
│   ├── product_scout.py        # Cerca dati tecnici e PDF prodotti (costruttore + dealer)
│   └── dealer_scout.py         # Individua concessionari/rivenditori ufficiali
├── workflows/
│   └── orchestrator.py         # Coordinatore job schedulati (APScheduler)
├── integrations/               # Connettori pubblicazione — da implementare
│   ├── linkedin.py
│   ├── facebook.py
│   └── instagram.py
├── models/
│   ├── post.py                 # Post, Comment, stati del ciclo di vita
│   ├── context.py              # CompanyContext, ContextWebsite
│   └── competitor.py           # Competitor, CompetitorSocial, CompetitorObservation,
│                               # CompetitorDealer, CompetitorProduct, CompetitorAnalysis
├── dashboard/
│   ├── main.py                 # App FastAPI con tutte le route
│   └── templates/
│       ├── index.html          # Coda approvazione post e risposte
│       ├── analytics.html      # Post pubblicati
│       ├── context.html        # Contesto aziendale e siti di riferimento
│       ├── competitors.html    # Gestione competitor (pannello interattivo a 6 tab)
│       ├── competitor_analysis.html  # Report AI analisi competitiva
│       └── settings.html       # Impostazioni AI, social, scheduling
├── config/
│   ├── settings.py             # Configurazione validata da pydantic — legge .env
│   ├── logging.py              # Logger centralizzato (file + console)
│   └── http_client.py          # HTTP client con consenso privacy/GDPR automatico
├── tests/                      # pytest — test route, agenti, sicurezza
├── storage/
│   ├── social_manager.db       # Database SQLite (auto-creato)
│   └── brochures/              # PDF tecnici scaricati per competitor
├── .env                        # Chiavi API — non committare mai
├── .env.example                # Template variabili d'ambiente
├── requirements.txt
└── main.py                     # Entry point CLI (typer)
```

---

## Flusso principale

```
[Generazione Contenuto AI]
        ↓
  [PENDING — attesa approvazione]
        ↓
  Umano approva / modifica / rifiuta  ←── Dashboard http://localhost:8000
        ↓
  [APPROVED → SCHEDULED → PUBLISHED]

[Monitor commenti] → [Bozza risposta AI] → [Approvazione umana] → [Pubblicazione]

[Analisi concorrenza]
  → scraping siti + ricerca Tavily + ricerca profili social
  → Report AI strutturato con fonti verificabili

[Ricerca prodotti tecnici]
  → sito costruttore + Tavily + siti dealer
  → PDF scaricati + specifiche strutturate estratte

[Ricerca concessionari]
  → pagine dealer del sito + Tavily
  → Anagrafica strutturata per competitor
```

---

## Sezioni del Dashboard

| Pagina | URL | Funzione |
|---|---|---|
| Approvazioni | `/` | Coda post e risposte in attesa |
| Analytics | `/analytics` | Post pubblicati |
| Contesto | `/context` | Profilo aziendale, siti di riferimento |
| Concorrenti | `/competitors` | Pannello interattivo: profilo, social, strategia, note, prodotti tecnici, concessionari |
| Analisi | `/competitors/analysis` | Report AI con fonti verificabili |
| Impostazioni | `/settings` | AI provider, scheduling, monitoring |

---

## Agenti AI

| Agente | Responsabilità |
|---|---|
| `ContentGeneratorAgent` | Genera post ottimizzati per piattaforma usando il contesto aziendale |
| `MonitorAgent` | Controlla nuovi commenti e menzioni ogni N minuti |
| `ReplyAgent` | Bozze risposte ai commenti, mai pubblicate senza approvazione |
| `AnalyticsAgent` | Raccoglie metriche da LinkedIn, Facebook Graph, Instagram |
| `CompetitorAnalystAgent` | Scraping siti + Tavily search + social discovery → analisi AI strutturata |
| `ProductScoutAgent` | Cerca dati tecnici e PDF sul sito costruttore, su Tavily e sui siti dealer |
| `DealerScoutAgent` | Individua concessionari ufficiali via scraping e Tavily, archivia anagrafica |

Ogni agente usa **Claude (Anthropic)** come provider primario con fallback automatico su qualsiasi API **OpenAI-compatible v1** (es. Qwen, Mistral, LM Studio).

---

## Analisi della concorrenza

L'analisi competitiva si basa esclusivamente su dati raccolti da fonti esterne — mai dalla memoria di training del modello:

1. **Scraping sito web** — testo del sito del competitor (aggiornato ogni 7 giorni)
2. **Ricerca Tavily** — risultati web recenti su strategia social e marketing
3. **Social discovery** — ricerca automatica profili LinkedIn, Facebook, Instagram mancanti
4. **Dati manuali** — tutto ciò che inserisci nelle schede competitor

Il report include per ogni competitor: verdict, score presenza social, insight, differenziatore, vulnerabilità — con le fonti esatte usate, verificabili direttamente nel dashboard.

---

## Intelligence prodotti e rete distributiva

### Dati tecnici prodotti
Per ogni competitor è possibile avviare una ricerca automatica di schede tecniche, datasheet e manuali:
- Scansione multi-livello del sito costruttore (homepage → slug tecnici → pagine scoperte)
- Ricerca Tavily focalizzata su `datasheet scheda tecnica filetype:pdf`
- Scansione dei siti dei dealer già archiviati
- Download PDF in locale (max 20 MB) + estrazione specifiche tecniche strutturate (tabelle, DL, pattern chiave:valore)
- Classificazione automatica: Scheda tecnica / Manuale / Catalogo / Certificazione

### Concessionari e rete distributiva
Per ogni competitor costruttore è possibile mappare la rete di distribuzione:
- Scraping delle pagine dealer del sito costruttore (`/dealers`, `/rivenditori`, ecc.)
- Ricerca Tavily per rivenditori autorizzati
- Anagrafica strutturata: nome, sito, indirizzo, città, regione, paese, telefono, email
- Aggiunta manuale tramite form nel dashboard
- Visualizzazione raggruppata per paese nel tab "Concessionari"

---

## HTTP client con consenso privacy

Tutti gli agenti di scraping usano `config/http_client.py` che invia automaticamente:
- User-Agent realistico (Chrome 124 su Windows)
- 26 cookie di consenso privacy/GDPR (Cookieconsent, CookieYes, OneTrust, Iubenda, Complianz, Borlabs, ecc.)
- Header browser standard (`Accept-Language: it-IT`, `Sec-Fetch-*`, `DNT: 0`)

---

## API e integrazioni

| Servizio | Uso |
|---|---|
| Anthropic Claude | Generazione contenuti, risposte, analisi (provider primario) |
| OpenAI-compatible v1 | Fallback — funziona con qualsiasi endpoint compatibile |
| Tavily | Ricerca web per analisi competitor, prodotti e dealer |
| LinkedIn API | Pubblicazione post, raccolta commenti, analytics |
| Facebook Graph API | Facebook e Instagram — pubblicazione, monitoring, analytics |

---

## Sicurezza

- **Autenticazione** — login con password configurabile in `.env` (`DASHBOARD_PASSWORD`); cookie di sessione firmato HMAC-SHA256
- **CSRF** — middleware ASGI puro con token double-submit; body re-iniettato senza consumare lo stream
- **SSRF** — validazione URL prima di ogni scraping (blocca IP privati, loopback, schemi non-HTTP)
- **Sanitizzazione .env** — whitelist chiavi + rimozione newline/null byte prima della scrittura

---

## Principio di approvazione

**Nulla viene mai pubblicato automaticamente.**
Ogni post generato e ogni risposta a un commento rimane in stato `PENDING` finché un umano non preme esplicitamente Approva nel dashboard.

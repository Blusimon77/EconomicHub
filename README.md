# Social Media Manager — Multi-Agent System

Sistema multi-agente per la gestione dei social aziendali (LinkedIn, Facebook, Instagram).
Genera contenuti con AI, pianifica le pubblicazioni, monitora menzioni e commenti, analizza la concorrenza — tutto con approvazione umana obbligatoria prima di qualsiasi pubblicazione.

---

## Architettura

```
social-media-manager/
├── agents/
│   ├── content_generator.py    # Genera post con Claude / OpenAI-compatible
│   ├── monitor.py              # Monitora menzioni e nuovi commenti
│   ├── reply_agent.py          # Bozze risposte ai commenti
│   ├── analytics.py            # Raccoglie metriche di performance
│   └── competitor_analyst.py  # Analisi AI della concorrenza (scraping + Tavily)
├── workflows/
│   └── orchestrator.py         # Coordinatore job schedulati (node-cron)
├── integrations/               # Connettori pubblicazione (LinkedIn, Facebook, Instagram)
├── models/
│   ├── post.py                 # Post, Comment, stati del ciclo di vita
│   ├── context.py              # CompanyContext, ContextWebsite
│   └── competitor.py          # Competitor, CompetitorSocial, CompetitorObservation, CompetitorAnalysis
├── dashboard/
│   ├── main.py                 # App FastAPI con tutte le route
│   └── templates/
│       ├── index.html          # Coda approvazione post e risposte
│       ├── analytics.html      # Post pubblicati
│       ├── context.html        # Contesto aziendale e siti di riferimento
│       ├── competitors.html    # Gestione concorrenti (pannello interattivo)
│       ├── competitor_analysis.html  # Report AI analisi competitiva
│       └── settings.html       # Impostazioni AI, social, scheduling
├── config/
│   └── settings.py             # Configurazione centralizzata (pydantic-settings)
├── storage/                    # Database SQLite (auto-creato)
├── .env                        # Chiavi API — non committare mai
├── .env.example                # Template variabili d'ambiente
├── requirements.txt
├── main.py                     # Entry point CLI (typer)
└── START.md                    # Guida avvio rapido
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

[Analisi concorrenza] → scraping siti + ricerca Tavily → Report AI
```

---

## Sezioni del Dashboard

| Pagina | URL | Funzione |
|---|---|---|
| Approvazioni | `/` | Coda post e risposte in attesa |
| Analytics | `/analytics` | Post pubblicati e metriche |
| Contesto | `/context` | Profilo aziendale, siti di riferimento |
| Concorrenti | `/competitors` | Schede competitor con dati social |
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
| `CompetitorAnalystAgent` | Scraping siti + Tavily search → analisi AI strutturata |

Ogni agente usa **Claude (Anthropic)** come provider primario con fallback automatico su qualsiasi API **OpenAI-compatible v1** (es. Qwen, Mistral, LM Studio).

---

## Analisi della concorrenza

L'analisi competitiva si basa esclusivamente su dati raccolti da fonti esterne — mai dalla memoria di training del modello:

1. **Scraping sito web** — testo della homepage del competitor (aggiornato ogni 7 giorni)
2. **Ricerca Tavily** — risultati web recenti su strategia social e marketing
3. **Dati manuali** — tutto ciò che inserisci nelle schede competitor

Il report include per ogni competitor: verdict, score presenza social, insight, differenziatore, vulnerabilità da sfruttare — con le fonti esatte usate, verificabili direttamente nel dashboard.

---

## API e integrazioni

| Servizio | Uso |
|---|---|
| Anthropic Claude | Generazione contenuti, risposte, analisi (provider primario) |
| OpenAI-compatible v1 | Fallback — funziona con qualsiasi endpoint compatibile |
| Tavily | Ricerca web per analisi competitor (free tier disponibile) |
| LinkedIn API | Pubblicazione post, raccolta commenti, analytics |
| Facebook Graph API | Facebook e Instagram — pubblicazione, monitoring, analytics |

---

## Principio di approvazione

**Nulla viene mai pubblicato automaticamente.**
Ogni post generato e ogni risposta a un commento rimane in stato `PENDING` finché un umano non preme esplicitamente Approva nel dashboard.

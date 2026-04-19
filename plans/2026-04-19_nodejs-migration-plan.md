# Piano di Migrazione: Python FastAPI → Node.js NestJS + Vercel

**Data:** 2026-04-19
**Target:** NestJS + Prisma + Vercel Postgres + Vercel Cron Jobs
**Durata stimata:** 10–14 settimane (4 fasi)

---

## Executive Summary

Sistema Python 3.9/FastAPI multi-agente per gestione social, ben strutturato con buone fondamenta di sicurezza (HMAC auth, CSRF, validazione SSRF) ma con debito architetturale significativo — file route monolitico da ~1.600 righe, agenti sincroni bloccanti chiamati da route async, accoppiamento stretto a SQLite. La migrazione a NestJS + Prisma + Vercel Postgres è tecnicamente fattibile in tre fasi principali, ma richiede gestione attenta dello scheduler background (incompatibile con Vercel serverless), del client HTTP centralizzato per scraping e del modello di autenticazione binaria a singola password.

---

## Architettura Attuale

```
┌─────────────────────────────────────────────────────────────────┐
│                    CLI Entry Point (main.py)                    │
│              typer: dashboard | start | generate | analytics    │
└─────────────┬───────────────────────────────┬───────────────────┘
              │                               │
              ▼                               ▼
┌─────────────────────────┐   ┌───────────────────────────────────┐
│  FastAPI Dashboard      │   │  Orchestrator (APScheduler)       │
│  dashboard/main.py      │   │  workflows/orchestrator.py        │
│  ~1,600 lines           │   │  - monitor: every 15 min          │
│  8 page routes          │   │  - reply drafts: every 30 min     │
│  20+ API/action routes  │   │  - analytics: every 1 hr          │
│  Jinja2 templates       │   │  Writes PID file to storage/      │
└────────┬────────────────┘   └────────────────┬──────────────────┘
         │                                     │
         │  Both create their own              │
         │  SQLAlchemy engines                 │
         ▼                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Agents Layer                                │
│  content_generator.py  monitor.py        reply_agent.py         │
│  analytics.py          competitor_analyst.py (legacy)           │
│  product_comparator.py product_scout.py  dealer_scout.py        │
│  All: try_anthropic → try_openai fallback pattern               │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Supporting Infrastructure                     │
│  config/settings.py    (pydantic-settings, .env)                │
│  config/http_client.py (centralized scraping + 26 GDPR cookies) │
│  config/logging.py     (file + console)                         │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              SQLite (storage/social_manager.db)                 │
│  15 tables: posts, comments, competitors, competitor_socials,   │
│  competitor_observations, competitor_products, competitor_      │
│  dealers, competitor_analyses (legacy), own_products,           │
│  product_comparisons, dealers, dealer_brands,                   │
│  company_context, context_websites                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Findings Code Review

### Criticità (Critical)

**C1 — File route monolitico: `dashboard/main.py` (~1.600 righe)**
L'intero layer HTTP, middleware di autenticazione, middleware CSRF, tutta la business logic, tutto l'accesso al database e funzioni utility vivono in un singolo file. Non c'è separazione tra HTTP handler, service layer e repository layer. Ogni route esegue direttamente `db.query(...)` inline. Aggiungere feature richiede navigare ~1.600 righe e rischia di rompere route adiacenti.

**C2 — Agenti sincroni bloccanti chiamati da route async**
Route come `POST /generate` e `POST /competitors/analysis/generate` chiamano `agent.generate()` e `run_comparison()` sincronamente dentro handler `async def`. Le chiamate Anthropic SDK sono I/O bloccante. Sotto qualsiasi carico concorrente, questo blocca l'intero event loop di uvicorn. Il pattern corretto è `await asyncio.to_thread(run_comparison, ...)` o usare varianti async dell'SDK.

File: `dashboard/main.py` righe 314–332 (`generate_post_form`) e 650 (`run_comparison`).

**C3 — Multipli engine SQLAlchemy indipendenti**
`dashboard/main.py` crea il proprio engine, `workflows/orchestrator.py` crea il proprio engine, e `agents/content_generator.py` crea ancora un altro engine dentro `_load_company_context()`. Tre pool di connessione separati allo stesso file SQLite — questo è sicuro solo perché SQLite è single-file e serializzato, ma è un rischio di correttezza passando a PostgreSQL dove l'isolamento transazionale conta.

**C4 — Accoppiamento PID-file orchestrator/dashboard**
L'orchestrator viene spawnato come processo figlio via `subprocess.Popen` dal dashboard (`/api/orchestrator/start`), con coordinamento tramite PID file in `storage/orchestrator.pid`. Questo pattern è completamente incompatibile con deployment serverless (Vercel) e fragile in ambienti containerizzati. Il ciclo di vita del processo è gestito dallo stato del filesystem.

**C5 — Settings scritte su `.env` a runtime**
`POST /settings` legge e riscrive `.env` su disco. In ambienti serverless o con filesystem read-only questo fallirà silenziosamente o crasherà. Le variabili d'ambiente dovrebbero essere read-only a runtime; le impostazioni mutabili andrebbero memorizzate nel database.

### Alta severità (High)

**H1 — Nessuna validazione input sui campi form**
Gli handler form accettano parametri `str` senza controlli di lunghezza o validazione di tipo sulla maggior parte dei campi oltre a quanto imposto dal layer modello. Non c'è validazione Pydantic model al layer route per i dati form. Il campo `threat_level` accetta interi arbitrari senza enforcement di range a livello API (`dashboard/main.py` riga 782).

**H2 — `_is_safe_url` duplicato in tre file**
La funzione di protezione SSRF è copia-incollata in `dashboard/main.py:255`, `agents/dealer_scout.py:153`, e `agents/product_scout.py:130`. Se un'istanza viene patchata (es. aggiungendo blocco IPv6), le altre due restano vulnerabili. C'è anche una sottile lacuna: nessuna delle tre controlla range privati IPv6 (`::1` è controllato come string match ma non i prefissi privati IPv6 completi come `fc00::/7`, `fe80::/10`).

**H3 — Session token senza enforcement di scadenza oltre `max_age`**
Il cookie HMAC-signed contiene solo un nonce random e il suo HMAC. `max_age=86400` (24h) è settato nell'header Set-Cookie, ma poiché i token non sono memorizzati server-side, un token rubato è valido per l'intera durata del cookie senza possibilità di invalidazione (nessun logout-all, nessuna rotazione). Le funzioni `_make_session_token` / `_verify_session_token` in `dashboard/main.py:57–70` non hanno componente timestamp.

**H4 — `datetime.utcnow()` deprecato, inconsistenza timezone**
Il codebase mischia `datetime.utcnow()` (naive, deprecato da Python 3.12) con `datetime.now(timezone.utc)` (timezone-aware). I modelli usano `default=datetime.utcnow` come default colonna (riferimento callable, non un valore timezone-aware). Quando le query confrontano con valori timezone-aware, produce bug sottili di ordinamento. File affetti: `models/post.py:58–59`, `models/competitor.py:38–39`, `models/dealer.py:38–39`, `agents/dealer_scout.py:706`.

**H5 — `alembic` in `requirements.txt` ma mai usato**
Alembic è listato come dipendenza ma CLAUDE.md documenta esplicitamente che le migrazioni si fanno via `ALTER TABLE` manuale. Questo significa che il drift schema tra ambienti è non tracciato e non riproducibile.

**H6 — Protezione path traversal brochure incompleta**
`serve_brochure` in `dashboard/main.py:1004` controlla `/`, `\\`, e `..` nel parametro `filename`. Tuttavia, varianti URL-encoded (`%2F`, `%5C`, `%2E%2E`) sono decodificate da FastAPI prima che l'handler le veda. FastAPI/Starlette normalizza i parametri path, ma affidarsi a controlli character-level string piuttosto che confronto `Path.resolve()` è fragile. Approccio corretto: `Path(brochure_path).resolve().is_relative_to(expected_dir)`.

### Media severità (Medium)

**M1 — Nessun rate limiting sugli endpoint sensibili**
`POST /login`, `POST /api/test-key/anthropic`, e `POST /competitors/{cid}/products/search` (che triggera I/O di rete e chiamate AI) non hanno rate limiting. Un attacco credential stuffing su `/login` o chiamate AI/scraping costose ripetute non hanno throttle.

**M2 — Scraping competitor usa regex HTML stripping invece di BeautifulSoup**
`scrape_competitor` in `dashboard/main.py:839–850` usa tre chiamate `re.sub` per rimuovere `<style>`, `<script>`, e tag generici. Meno robusto di BeautifulSoup (già importato e usato altrove nello stesso file). HTML malformato con event handler inline o URI `data:` passerebbe attraverso non rimosso.

**M3 — JSON memorizzato come colonne TEXT senza struttura database-level**
`tech_specs`, `search_results`, `competitor_products_snapshot`, `comparison_table`, `per_competitor`, `recommendations`, `opportunities`, `threats` sono tutte colonne TEXT contenenti JSON. Non c'è validazione database-level che contengano JSON valido, e qualsiasi scrittura che fallisca la serializzazione memorizzerà silenziosamente una stringa vuota o JSON invalido. Il tipo nativo `jsonb` di PostgreSQL imporrebbe validità e permetterebbe indicizzazione.

**M4 — `_load_company_context()` crea un nuovo DB engine a ogni chiamata**
In `agents/content_generator.py:16–30`, ogni volta che viene generato un post, un nuovo `create_engine()` SQLAlchemy viene chiamato. La creazione engine è costosa (setup del connection pool). Questa funzione dovrebbe ricevere una session o usare un engine singleton a livello modulo.

**M5 — Gap di copertura test**
La suite test copre route smoke, validazione URL, sanitizzazione env, e test unitari agenti base. Manca copertura di: tutte le route POST (submission form, workflow approvazione), comportamento middleware CSRF, middleware autenticazione (route protette ritornano 302 senza session), endpoint competitor products/dealers, logica `_looks_like_company` in `dealer_scout.py`, e la funzione `_extract_tech_specs`. Il file test in `tests/test_dashboard.py` ha 0 test per route POST.

**M6 — `analytics.py` usa `httpx.get()` sincrono in contesto non-async ma è chiamato da route async**
La pagina `/analytics` chiama `AnalyticsAgent.collect_all()` che è completamente sincrono e usa `httpx.get()`. Blocca l'event loop fino a 3 × 15 secondi (3 chiamate social API × timeout). Stesso problema per i metodi `MonitorAgent._check_*`.

**M7 — `settings.dashboard_password` default a stringa vuota, disabilita silenziosamente auth**
In `config/settings.py:37`, `dashboard_password` default a `""`. Il `AuthMiddleware` in `dashboard/main.py:77` skippa esplicitamente tutta l'autenticazione se la password è vuota: `if not settings.dashboard_password: return await call_next(request)`. Un deployment misconfigurato non ha silenziosamente nessuna autenticazione.

### Bassa severità (Low)

**L1 — `from __future__ import annotations` mancante in alcuni modelli**
`models/post.py` e `models/context.py` non includono `from __future__ import annotations` ma non usano ancora union type hints. Crescendo il codebase su Python 3.9, qualsiasi aggiunta di sintassi `str | None` senza questo import causerà `TypeError` al caricamento modulo.

**L2 — Righe multi-statement riducono leggibilità**
Diversi update handler impacchettano assegnazioni multiple su una riga con punto e virgola, es. `dashboard/main.py:813–817`:
```python
c.name = name; c.website = website; c.sector = sector
```
Legale Python ma viola PEP 8 e rende diff git più difficili da revieware.

**L3 — Legacy `competitor_analyst.py` ancora importato nei test**
`tests/test_agents.py:140–161` testa `competitor_analyst._parse_json` e `_fallback_result`. CLAUDE.md afferma che questo agente non è più usato da `/competitors/analysis`. Il test crea un burden di manutenzione per codice morto.

**L4 — Flag `secure` non settato sul cookie auth**
In `dashboard/main.py:128`, `response.set_cookie(...)` setta `httponly=True` e `samesite="strict"` ma non `secure=True`. Su HTTP plain il session cookie è trasmesso in chiaro.

**L5 — Geocode proxy espone Nominatim senza autenticazione o caching**
`GET /api/geocode` proxa richieste a Nominatim con User-Agent custom ma senza caching. Geocoding ripetuto dello stesso indirizzo fa chiamate esterne ridondanti e potrebbe violare la usage policy di Nominatim per richieste bulk.

---

## Strategia di Migrazione: Python → NestJS + Prisma + Vercel Postgres

### Mapping Tecnologico

| Python (Attuale) | Node.js/NestJS (Target) |
|---|---|
| FastAPI | NestJS con `@nestjs/platform-express` |
| Jinja2 templates | NestJS + `@nestjs/serve-static` + React/Next.js SPA, o server-side con Handlebars (`hbs`) |
| SQLAlchemy ORM | Prisma ORM |
| SQLite | Vercel Postgres (PostgreSQL 15) |
| pydantic-settings | `@nestjs/config` + `joi` o `zod` per validazione |
| APScheduler | `@nestjs/schedule` (decorator cron/interval) |
| Anthropic SDK | `@anthropic-ai/sdk` |
| openai SDK | `openai` npm package |
| httpx | `axios` o native `fetch` (Node 18+) |
| BeautifulSoup | `cheerio` |
| Tavily Python SDK | Tavily REST API diretta via `axios` |
| PyMuPDF (fitz) | `pdf-parse` o `pdfjs-dist` |
| HMAC auth + cookie | `passport-local` + `express-session` + `connect-pg-simple`, o JWT |
| pytest | Jest + `@nestjs/testing` + `supertest` |
| uvicorn | `@nestjs/platform-fastify` o Express (built-in in NestJS) |
| typer CLI | Comandi custom `@nestjs/cli` o `commander` |
| APScheduler background | Decorator `@Cron()` NestJS (long-running); Vercel Cron (serverless) |

---

### Schema Prisma Completo (SQLite → PostgreSQL)

```prisma
// schema.prisma
generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

enum Platform {
  linkedin
  facebook
  instagram
}

enum PostStatus {
  draft
  pending
  approved
  rejected
  scheduled
  published
  failed
}

model Post {
  id               Int        @id @default(autoincrement())
  platform         Platform
  status           PostStatus @default(draft)
  content          String
  hashtags         String     @default("")
  imageUrl         String?    @db.VarChar(500)
  mediaPath        String?    @db.VarChar(500)
  topic            String?    @db.VarChar(200)
  tone             String     @default("professionale") @db.VarChar(50)
  generatedBy      String     @default("anthropic") @db.VarChar(50)
  scheduledAt      DateTime?
  publishedAt      DateTime?
  platformPostId   String?    @db.VarChar(200)
  approvedBy       String?    @db.VarChar(100)
  approvalNote     String?
  likes            Int?
  commentsCount    Int?
  shares           Int?
  reach            Int?
  impressions      Int?
  engagementRate   Float?
  createdAt        DateTime   @default(now())
  updatedAt        DateTime   @updatedAt

  @@map("posts")
}

model Comment {
  id                 Int        @id @default(autoincrement())
  platform           Platform
  platformCommentId  String     @unique @db.VarChar(200)
  platformPostId     String     @db.VarChar(200)
  authorName         String     @default("") @db.VarChar(200)
  content            String
  isMention          Boolean    @default(false)
  replyDraft         String?
  replyStatus        PostStatus?
  replyPublishedAt   DateTime?
  createdAt          DateTime   @default(now())

  @@map("comments")
}

model CompanyContext {
  id               Int      @id @default(autoincrement())
  companyName      String   @default("") @db.VarChar(200)
  description      String   @default("")
  mission          String   @default("")
  values           String   @default("")
  founded          String   @default("") @db.VarChar(50)
  productsServices String   @default("")
  targetAudience   String   @default("")
  sector           String   @default("") @db.VarChar(200)
  competitors      String   @default("")
  toneOfVoice      String   @default("")
  topicsToAvoid    String   @default("")
  contentPillars   String   @default("")
  additionalNotes  String   @default("")
  updatedAt        DateTime @updatedAt

  @@map("company_context")
}

model ContextWebsite {
  id              Int       @id @default(autoincrement())
  url             String    @db.VarChar(500)
  label           String    @default("") @db.VarChar(200)
  category        String    @default("") @db.VarChar(100)
  notes           String    @default("")
  scrapedContent  String    @default("")
  lastScrapedAt   DateTime?
  isActive        Boolean   @default(true)
  createdAt       DateTime  @default(now())

  @@map("context_websites")
}

model Competitor {
  id               Int                    @id @default(autoincrement())
  name             String                 @db.VarChar(200)
  website          String                 @default("") @db.VarChar(500)
  sector           String                 @default("") @db.VarChar(200)
  description      String                 @default("")
  strengths        String                 @default("")
  weaknesses       String                 @default("")
  contentStrategy  String                 @default("")
  targetAudience   String                 @default("")
  toneOfVoice      String                 @default("")
  uniqueTopics     String                 @default("")
  postingFrequency String                 @default("") @db.VarChar(100)
  threatLevel      Int                    @default(2)
  isActive         Boolean                @default(true)
  scrapedContent   String                 @default("")
  lastScrapedAt    DateTime?
  searchResults    Json?
  lastSearchedAt   DateTime?
  createdAt        DateTime               @default(now())
  updatedAt        DateTime               @updatedAt

  socials          CompetitorSocial[]
  observations     CompetitorObservation[]
  products         CompetitorProduct[]
  dealers          CompetitorDealer[]
  dealerBrands     DealerBrand[]

  @@map("competitors")
}

model CompetitorSocial {
  id             Int        @id @default(autoincrement())
  competitorId   Int
  platform       String     @db.VarChar(50)
  profileUrl     String     @default("") @db.VarChar(500)
  handle         String     @default("") @db.VarChar(200)
  followers      String     @default("") @db.VarChar(50)
  avgLikes       String     @default("") @db.VarChar(50)
  avgComments    String     @default("") @db.VarChar(50)
  postingDays    String     @default("") @db.VarChar(200)
  contentTypes   String     @default("")
  notes          String     @default("")

  competitor     Competitor @relation(fields: [competitorId], references: [id], onDelete: Cascade)

  @@map("competitor_socials")
}

model CompetitorObservation {
  id           Int        @id @default(autoincrement())
  competitorId Int
  category     String     @default("generale") @db.VarChar(100)
  content      String
  createdAt    DateTime   @default(now())

  competitor   Competitor @relation(fields: [competitorId], references: [id], onDelete: Cascade)

  @@map("competitor_observations")
}

model CompetitorDealer {
  id           Int                @id @default(autoincrement())
  competitorId Int
  name         String             @db.VarChar(500)
  website      String             @default("") @db.VarChar(1000)
  address      String             @default("") @db.VarChar(500)
  city         String             @default("") @db.VarChar(200)
  region       String             @default("") @db.VarChar(200)
  country      String             @default("") @db.VarChar(100)
  phone        String             @default("") @db.VarChar(100)
  email        String             @default("") @db.VarChar(200)
  notes        String             @default("")
  source       String             @default("") @db.VarChar(100)
  sourceUrl    String             @default("") @db.VarChar(1000)
  foundAt      DateTime           @default(now())

  competitor   Competitor         @relation(fields: [competitorId], references: [id], onDelete: Cascade)
  products     CompetitorProduct[]

  @@map("competitor_dealers")
}

model CompetitorProduct {
  id               Int               @id @default(autoincrement())
  competitorId     Int
  dealerId         Int?
  name             String            @default("") @db.VarChar(500)
  productLine      String            @default("") @db.VarChar(300)
  category         String            @default("") @db.VarChar(200)
  techSpecs        Json?
  techSummary      String            @default("")
  brochureUrl      String            @default("") @db.VarChar(1000)
  brochureFilename String            @default("") @db.VarChar(300)
  pageUrl          String            @default("") @db.VarChar(1000)
  source           String            @default("") @db.VarChar(100)
  fileSizeKb       Int               @default(0)
  foundAt          DateTime          @default(now())

  competitor       Competitor        @relation(fields: [competitorId], references: [id], onDelete: Cascade)
  dealer           CompetitorDealer? @relation(fields: [dealerId], references: [id])

  @@map("competitor_products")
}

model CompetitorAnalysis {
  id              Int      @id @default(autoincrement())
  summary         String   @default("")
  landscape       String   @default("")
  perCompetitor   Json?
  opportunities   Json?
  threats         Json?
  recommendations Json?
  contentGaps     Json?
  dataQuality     String   @default("")
  sourcesUsed     Json?
  rawResponse     String   @default("")
  generatedBy     String   @default("anthropic") @db.VarChar(50)
  createdAt       DateTime @default(now())

  @@map("competitor_analyses")
}

model OwnProduct {
  id               Int               @id @default(autoincrement())
  name             String            @db.VarChar(300)
  productLine      String            @default("") @db.VarChar(200)
  category         String            @default("") @db.VarChar(200)
  description      String            @default("")
  workingHeight    Float?
  techSpecs        Json?
  techSummary      String            @default("")
  pageUrl          String            @default("") @db.VarChar(1000)
  brochureUrl      String            @default("") @db.VarChar(1000)
  brochureFilename String            @default("") @db.VarChar(300)
  scrapedAt        DateTime?
  createdAt        DateTime          @default(now())
  updatedAt        DateTime          @updatedAt

  comparisons      ProductComparison[]

  @@map("own_products")
}

model ProductComparison {
  id                          Int         @id @default(autoincrement())
  ownProductId                Int?
  ownProductName              String      @default("") @db.VarChar(300)
  competitorProductsSnapshot  Json?
  title                       String      @default("") @db.VarChar(300)
  summary                     String      @default("")
  comparisonTable             Json?
  perCompetitor               Json?
  recommendations             Json?
  rawResponse                 String      @default("")
  generatedBy                 String      @default("anthropic") @db.VarChar(50)
  createdAt                   DateTime    @default(now())

  ownProduct   OwnProduct? @relation(fields: [ownProductId], references: [id])

  @@map("product_comparisons")
}

model Dealer {
  id          Int          @id @default(autoincrement())
  name        String       @db.VarChar(500)
  website     String       @default("") @db.VarChar(1000)
  email       String       @default("") @db.VarChar(200)
  phone       String       @default("") @db.VarChar(100)
  address     String       @default("") @db.VarChar(500)
  city        String       @default("") @db.VarChar(200)
  state       String       @default("") @db.VarChar(200)
  country     String       @default("") @db.VarChar(100)
  postalCode  String       @default("") @db.VarChar(20)
  latitude    Float?
  longitude   Float?
  notes       String       @default("")
  createdAt   DateTime     @default(now())
  updatedAt   DateTime     @updatedAt

  brands      DealerBrand[]

  @@map("dealers")
}

model DealerBrand {
  id           Int        @id @default(autoincrement())
  dealerId     Int
  competitorId Int?
  isOwnBrand   Boolean    @default(false)

  dealer       Dealer      @relation(fields: [dealerId], references: [id], onDelete: Cascade)
  competitor   Competitor? @relation(fields: [competitorId], references: [id])

  @@map("dealer_brands")
}
```

**Trasformazioni chiave SQLite → PostgreSQL:**
- Tutte le colonne `TEXT` che memorizzano JSON diventano `Json` (mappato a `jsonb` in Postgres)
- Annotazioni di lunghezza `String` diventano `@db.VarChar(n)` per enforcement esplicito
- `Boolean` default funzionano nativamente in Postgres
- `Float` mappa a `Double Precision` via Prisma
- `DateTime @default(now())` sostituisce `default=datetime.utcnow` — sempre UTC, sempre timezone-aware
- Prisma gestisce `@updatedAt` automaticamente

---

### Mapping File-by-File

```
Python                                  Node.js/NestJS
─────────────────────────────────────────────────────────────────
main.py (CLI)                    →  src/main.ts (bootstrap) +
                                    src/cli/cli.module.ts

config/settings.py               →  src/config/configuration.ts
                                    (ConfigModule.forRoot con
                                    Joi validation schema)

config/http_client.py            →  src/common/http-client.service.ts
                                    (Injectable service wrapping axios
                                    con privacy headers + cookie jar)

config/logging.py                →  NestJS built-in Logger +
                                    @nestjs/common LoggerModule o
                                    pino via nestjs-pino

models/post.py                   →  prisma/schema.prisma (Post, Comment)
models/competitor.py             →  prisma/schema.prisma (Competitor, ...)
models/context.py                →  prisma/schema.prisma (CompanyContext, ...)
models/dealer.py                 →  prisma/schema.prisma (Dealer, ...)
models/product_comparison.py     →  prisma/schema.prisma (OwnProduct, ...)

dashboard/main.py                →  Split in 8 moduli NestJS:
  (routes /)                        src/posts/posts.controller.ts
  (routes /analytics)               src/analytics/analytics.controller.ts
  (routes /context)                 src/context/context.controller.ts
  (routes /competitors)             src/competitors/competitors.controller.ts
  (routes /competitors/analysis)    src/analysis/analysis.controller.ts
  (routes /dealers)                 src/dealers/dealers.controller.ts
  (routes /settings)                src/settings/settings.controller.ts
  (routes /generate)                src/generate/generate.controller.ts
  (middleware Auth)                 src/auth/auth.middleware.ts
  (middleware CSRF)                 src/auth/csrf.middleware.ts
  (_is_safe_url)                    src/common/url-validator.ts
  (scrape_website/competitor)       src/common/scraper.service.ts

agents/content_generator.py      →  src/agents/content-generator.service.ts
agents/monitor.py                →  src/agents/monitor.service.ts
agents/reply_agent.py            →  src/agents/reply.service.ts
agents/analytics.py              →  src/agents/analytics.service.ts
agents/competitor_analyst.py     →  src/agents/competitor-analyst.service.ts
agents/product_comparator.py     →  src/agents/product-comparator.service.ts
agents/product_scout.py          →  src/agents/product-scout.service.ts
agents/dealer_scout.py           →  src/agents/dealer-scout.service.ts

workflows/orchestrator.py        →  src/scheduler/scheduler.module.ts
                                    (@Cron() decorators via @nestjs/schedule)

integrations/linkedin.py (stub)  →  src/integrations/linkedin.service.ts
integrations/facebook.py (stub)  →  src/integrations/facebook.service.ts
integrations/instagram.py (stub) →  src/integrations/instagram.service.ts

dashboard/templates/*.html       →  Opzione A: server-side con
                                    @nestjs/serve-static + template hbs
                                    Opzione B: frontend Next.js separato
                                    che chiama NestJS come REST API

tests/conftest.py                →  test/setup.ts (Jest globalSetup) +
                                    @prisma/jest-environment
tests/test_dashboard.py          →  test/posts.e2e-spec.ts
                                    test/auth.e2e-spec.ts
tests/test_agents.py             →  test/agents/content-generator.spec.ts
                                    test/agents/monitor.spec.ts
                                    (mock Jest sostituiscono unittest.mock.patch)
```

---

### Dettagli Trasformazioni Chiave

#### 1. Migrazione Autenticazione

**Attuale:** Cookie HMAC-signed con `nonce:hmac(nonce)`, password singola da env, nessuno storage token.

**Target Node.js (Opzione A — cambio minimo, cookie-based):**
```typescript
// src/auth/auth.service.ts
import * as crypto from 'crypto';

export class AuthService {
  makeSessionToken(secret: string): string {
    const nonce = crypto.randomBytes(16).toString('hex');
    const sig = crypto.createHmac('sha256', secret).update(nonce).digest('hex');
    return `${nonce}:${sig}`;
  }

  verifySessionToken(token: string, secret: string): boolean {
    const [nonce, sig] = token.split(':');
    if (!nonce || !sig) return false;
    const expected = crypto.createHmac('sha256', secret).update(nonce).digest('hex');
    return crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected));
  }
}
```

**Target Node.js (Opzione B — upgrade a JWT, raccomandato):**
Usare `@nestjs/passport` + `passport-jwt`. Aggiunge scaling orizzontale stateless, expiry nel payload token, invalidazione facile via `iat` + blocklist database.

#### 2. Migrazione HTTP Client (Critica — preserva capacità scraping)

```typescript
// src/common/http-client.service.ts
import { Injectable } from '@nestjs/common';
import axios, { AxiosInstance } from 'axios';

const CONSENT_COOKIES: Record<string, string> = {
  cookieconsent_status: 'allow',
  cookieconsent_dismissed: 'yes',
  'cookieyes-consent': 'consentid:accepted,consent:yes,...',
  cmplz_consent_status: 'all',
  // ... tutti i 26 cookie da config/http_client.py
};

const BASE_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...',
  'Accept': 'text/html,application/xhtml+xml,...',
  'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8',
  'Sec-Fetch-Dest': 'document',
  'Sec-Fetch-Mode': 'navigate',
};

@Injectable()
export class HttpClientService {
  private readonly client: AxiosInstance;

  constructor() {
    const cookieStr = Object.entries(CONSENT_COOKIES)
      .map(([k, v]) => `${k}=${v}`)
      .join('; ');

    this.client = axios.create({
      headers: { ...BASE_HEADERS, Cookie: cookieStr },
      maxRedirects: 10,
      timeout: 15000,
    });
  }

  async get(url: string, timeoutMs = 15000) {
    return this.client.get(url, { timeout: timeoutMs });
  }

  async stream(url: string) {
    return this.client.get(url, { responseType: 'stream' });
  }
}
```

#### 3. Migrazione Pattern Agenti

Gli agenti Python usano pattern bloccante `try_anthropic → try_openai`. In Node.js diventa service async pulito:

```typescript
// src/agents/content-generator.service.ts
import { Injectable } from '@nestjs/common';
import Anthropic from '@anthropic-ai/sdk';
import OpenAI from 'openai';
import { ConfigService } from '@nestjs/config';

@Injectable()
export class ContentGeneratorService {
  private readonly anthropic: Anthropic;
  private readonly openai: OpenAI;

  constructor(private config: ConfigService) {
    this.anthropic = new Anthropic({ apiKey: config.get('ANTHROPIC_API_KEY') });
    this.openai = new OpenAI({
      baseURL: config.get('OPENAI_COMPATIBLE_BASE_URL'),
      apiKey: config.get('OPENAI_COMPATIBLE_API_KEY'),
    });
  }

  async generate(topic: string, platform: string, tone: string): Promise<GenerateResult> {
    const prompt = this.buildPrompt(topic, platform, tone);

    if (this.config.get('AI_PRIMARY_PROVIDER') === 'anthropic') {
      const result = await this.tryAnthropic(prompt);
      if (result) return { ...result, generatedBy: 'anthropic' };
    }

    const result = await this.tryOpenAI(prompt);
    if (result) return { ...result, generatedBy: 'openai' };

    throw new Error('All AI providers failed');
  }

  private async tryAnthropic(prompt: string): Promise<Partial<GenerateResult> | null> {
    try {
      const msg = await this.anthropic.messages.create({
        model: this.config.get('ANTHROPIC_MODEL'),
        max_tokens: 1024,
        system: SYSTEM_PROMPT,
        messages: [{ role: 'user', content: prompt }],
      });
      return this.parseResponse((msg.content[0] as any).text);
    } catch {
      return null;
    }
  }
}
```

#### 4. Migrazione Scheduler

**Attuale:** APScheduler `BackgroundScheduler` + PID file + `subprocess.Popen`.

**Target NestJS (server long-running):**
```typescript
// src/scheduler/scheduler.service.ts
import { Injectable } from '@nestjs/common';
import { Cron, CronExpression } from '@nestjs/schedule';

@Injectable()
export class SchedulerService {
  @Cron('*/15 * * * *')  // ogni 15 minuti
  async runMonitor() { ... }

  @Cron(CronExpression.EVERY_30_MINUTES)
  async runReplyDrafts() { ... }

  @Cron(CronExpression.EVERY_HOUR)
  async runAnalytics() { ... }
}
```

**Vincolo serverless Vercel:** Vercel Functions hanno timeout max di 60s (piano Pro). Scheduler background non funziona in serverless. Due opzioni:
- **Opzione A:** Deploy NestJS come container long-running su Railway/Fly.io/Render, usare Vercel Postgres solo per database.
- **Opzione B:** Vercel Cron Jobs (configurati in `vercel.json`) per triggerare endpoint HTTP su schedule. Approccio Vercel-native raccomandato.

```json
// vercel.json
{
  "crons": [
    { "path": "/api/cron/monitor",     "schedule": "*/15 * * * *" },
    { "path": "/api/cron/reply-drafts","schedule": "*/30 * * * *" },
    { "path": "/api/cron/analytics",   "schedule": "0 * * * *" }
  ]
}
```

Questi endpoint cron devono essere protetti con header `CRON_SECRET` condiviso, non con l'auth user-facing.

#### 5. Migrazione Storage Settings

Sostituire il pattern di scrittura file `.env` con tabella database `settings`:

```prisma
model AppSettings {
  key       String @id @db.VarChar(100)
  value     String
  updatedAt DateTime @updatedAt
  @@map("app_settings")
}
```

Il dashboard legge/scrive settings via Prisma. Valori sensibili (API keys) dovrebbero usare il management variabili d'ambiente built-in di Vercel, non una tabella database — presentare all'utente un link alla dashboard Vercel per quei campi.

---

## Piano Fase-per-Fase

### Fase 1: Fondamenta & Data Layer (Settimane 1–3)

**Obiettivo:** Progetto NestJS in esecuzione su Vercel Postgres, tutti i dati accessibili, zero perdita di feature.

1. Inizializzare progetto NestJS (`@nestjs/cli new social-media-manager-node`)
2. Aggiungere Prisma, eseguire `prisma migrate dev` con lo schema sopra
3. Scrivere script migrazione one-time SQLite → PostgreSQL (usare `pg-copy-streams` o INSERT SQL diretti da dump `better-sqlite3`)
4. Implementare `ConfigModule` con tutte le env validate da `zod`
5. Portare `HttpClientService` con tutti i 26 cookie privacy
6. Implementare `PrismaService` come singleton injectable
7. Aggiungere `AuthMiddleware` (cookie HMAC, port della logica esistente)
8. Aggiungere `CsrfMiddleware` (pacchetto `csurf` o port dell'implementazione pure-ASGI)
9. Portare `_is_safe_url` a `UrlValidatorService` — fixare gap IPv6 usando `net.isIP()` Node + `ipaddr.js`

**Deliverable:** App NestJS si avvia, si connette a Vercel Postgres, auth funziona.

### Fase 2: Route Dashboard (Settimane 4–6)

**Obiettivo:** Tutte le 8 pagine dashboard funzionanti in NestJS, template Jinja2 convertiti.

10. Creare un modulo NestJS per sezione dashboard (Posts, Analytics, Context, Competitors, Analysis, Dealers, Settings, Generate)
11. Ogni modulo ha: `Controller`, `Service`, e se serve un `Repository` che wrappa chiamate Prisma
12. Portare template Jinja2 a Handlebars (`hbs`) — la logica è minima abbastanza per conversione diretta. Alternativa: template statici HTML via `@nestjs/serve-static` con NestJS API come backend JSON puro
13. Portare injection CSRF `_template_response` a interceptor NestJS
14. Portare tutte le 20+ route action (approve, reject, edit, add, delete, scrape)
15. Portare endpoint `GET /api/...` JSON
16. Portare export CSV e file serve (brochures) — usare `@nestjs/serve-static` o `StreamableFile`
17. Portare start/stop orchestrator — sostituire approccio PID file con flag di stato DB-backed (o skippare per Vercel; usare Vercel Cron)

**Deliverable:** Piena feature parity con dashboard Python attuale.

### Fase 3: Agenti & Scheduler (Settimane 7–10)

**Obiettivo:** Tutti gli agenti AI e pipeline scraping funzionanti come NestJS services.

18. Portare `ContentGeneratorService` (diretto — SDK Anthropic e OpenAI hanno API identiche in JS)
19. Portare `MonitorService` (diretto — stessi endpoint HTTP, async/await invece di httpx sync)
20. Portare `ReplyService`
21. Portare `AnalyticsService`
22. Portare `ProductComparatorService` — per lettura PDF usare `pdf-parse` invece di PyMuPDF; nota: `pdf-parse` è solo estrazione testo (no grafica), sufficiente per l'uso corrente
23. Portare `ProductScoutService` — `cheerio` sostituisce BeautifulSoup per parsing HTML; i pattern regex traducono direttamente in JS
24. Portare `DealerScoutService` — l'agente più complesso (~750 righe). La funzione regex-based `_looks_like_company` traduce direttamente in JS. Portare tutti i 4 pattern `_DEALER_MENTION_RE` (sintassi regex JS compatibile con pattern Python non-VERBOSE usati qui)
25. Portare `CompetitorAnalystService` (legacy ma ancora testato)
26. Implementare modulo scheduler (`@Cron()` NestJS per long-running, endpoint HTTP Vercel Cron per serverless)

**Deliverable:** Tutti gli agenti pienamente funzionali.

### Fase 4: Testing, Hardening & Deployment (Settimane 11–14)

27. Portare tutti i test pytest a Jest:
    - `conftest.py` → `test/prisma-test-environment.ts` usando `@prisma/jest-environment` con database test
    - Smoke test `test_dashboard.py` → `test/*.e2e-spec.ts` con `supertest`
    - `test_agents.py` → `test/agents/*.spec.ts` con `jest.mock()`
    - Aggiungere test route POST mancanti (attualmente copertura zero)
    - Aggiungere test middleware CSRF
28. Fixare gap sicurezza durante migrazione: aggiungere `secure: true` a cookie auth, rate limiting via `@nestjs/throttler`, fixare gap IPv6 SSRF, usare `Path.resolve()` per validazione path brochure
29. Setup deployment Vercel:
    - `vercel.json` con configurazione `builds` e `routes`
    - Variabili d'ambiente in dashboard Vercel (non in file `.env`)
    - `prisma generate` in build step
    - Connection string Vercel Postgres in `DATABASE_URL`
30. Migrazione dati da SQLite produzione:
    - Export via `sqlite3 social_manager.db .dump > dump.sql`
    - Trasformare nomi schema (snake_case → camelCase) per matchare Prisma
    - Import via `psql $DATABASE_URL < transformed.sql`

---

## Risk Matrix

| Rischio | Probabilità | Impatto | Mitigazione |
|---|---|---|---|
| Vercel serverless incompatibile con scheduler background | Certa | Alto | Usare Vercel Cron Jobs (HTTP-triggered) o deploy su Railway/Render |
| Regressione qualità estrazione PDF (PyMuPDF → pdf-parse) | Media | Medio | Benchmark entrambi su brochure sample; `pdfjs-dist` alternativa higher-fidelity |
| Mismatch tipi dati SQLite→PostgreSQL (JSON come TEXT) | Alta | Basso | Script migrazione valida JSON prima insert; righe JSON invalide diventano `null` |
| Gap conversione template Jinja2 → Handlebars | Media | Medio | Template usano logica Jinja2 minima; rischio principale sono equivalenti filter/macro custom. Considerare SPA Next.js |
| Differenze comportamento `cheerio` vs BeautifulSoup | Bassa | Medio | Parsing HTML dealer_scout e product_scout usa tag selector che funzionano identicamente in entrambi; unit test con fixture HTML salvate |
| Migrazione auth password binaria → JWT rompe sessioni esistenti | Bassa | Basso | Non è una preoccupazione — sessioni short-lived (cookie 24h) e c'è un solo utente |
| Sostituzione UX settings scritte su `.env` (Vercel env read-only) | Alta | Alto | Deve essere sostituito con tabella settings DB-backed prima di deploy su Vercel; bloccante Fase 2 |
| Chiamate scraping/AI long-running eccedono timeout Vercel Function (60s) | Alta | Alto | Spostare tutto scraping e chiamate agent AI a background workers (Vercel Background Functions, o service long-running separato) |
| Test competitor analyst riferisce agente legacy | Bassa | Basso | Cancellare classe test `TestCompetitorAnalyst` o portarla a testare product_comparator |

---

## Stima Timeline

| Fase | Durata | Rischio Chiave |
|---|---|---|
| Fase 1: Fondamenta | 2–3 settimane | Correttezza migrazione DB |
| Fase 2: Dashboard | 2–3 settimane | Conversione template, parity CSRF |
| Fase 3: Agenti | 3–4 settimane | Complessità DealerScout, estrazione PDF |
| Fase 4: Testing + Deploy | 2–4 settimane | Vincoli timeout Vercel |
| **Totale** | **10–14 settimane** | Modello scheduler serverless Vercel |

---

## File Chiave Referenziati

- [dashboard/main.py](dashboard/main.py) — file route monolitico, tutto il middleware di sicurezza
- [config/http_client.py](config/http_client.py) — client scraping 26-cookie (preservare esattamente)
- [config/settings.py](config/settings.py) — tutte le env var (diventa schema Prisma `app_settings` + env Vercel)
- [agents/dealer_scout.py](agents/dealer_scout.py) — agente più complesso, ~750 righe
- [agents/product_scout.py](agents/product_scout.py) — pipeline PDF, dipende da PyMuPDF
- [workflows/orchestrator.py](workflows/orchestrator.py) — scheduler PID-file, incompatibile con Vercel
- [models/](models/) — tutti i 5 file modelli → singolo `prisma/schema.prisma`
- [tests/](tests/) — 3 file test, tutti convertibili a Jest

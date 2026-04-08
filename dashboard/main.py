"""
Dashboard FastAPI — Approvazione umana dei post e delle risposte ai commenti.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from pathlib import Path
import uvicorn
import ipaddress
from urllib.parse import urlparse

import re
from bs4 import BeautifulSoup
import hmac
import hashlib
import secrets
import httpx
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from config.settings import settings
from config.logging import get_logger
from config.http_client import scrape_headers

logger = get_logger("dashboard")
from models.post import Base, Post, Comment, PostStatus, Platform
from models.context import CompanyContext, ContextWebsite
import json
from models.competitor import Competitor, CompetitorSocial, CompetitorObservation, CompetitorAnalysis, CompetitorProduct, CompetitorDealer
from models.dealer import Dealer, DealerBrand
from datetime import datetime, timezone
from pathlib import Path as FilePath
from fastapi.responses import FileResponse

MAX_SCRAPED_CONTENT = 8000
MAX_RAW_RESPONSE = 10000
SCRAPED_PREVIEW_LENGTH = 500
HTTP_TIMEOUT = 15

engine = create_engine(settings.database_url)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

app = FastAPI(title="Social Media Manager — Dashboard")


# ── Autenticazione ────────────────────────────────────────────────────────────

_AUTH_COOKIE = "smm_session"
_PUBLIC_PATHS = {"/login", "/login/"}


def _make_session_token(secret: str) -> str:
    """Genera un token di sessione firmato."""
    nonce = secrets.token_hex(16)
    sig = hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
    return f"{nonce}:{sig}"


def _verify_session_token(token: str, secret: str) -> bool:
    """Verifica che il token di sessione sia valido."""
    if ":" not in token:
        return False
    nonce, sig = token.split(":", 1)
    expected = hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Se non c'è password configurata, skip auth
        if not settings.dashboard_password:
            return await call_next(request)

        # Percorsi pubblici
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        # Risorse statiche
        if request.url.path.startswith("/static"):
            return await call_next(request)

        # Verifica cookie di sessione
        session_token = request.cookies.get(_AUTH_COOKIE, "")
        if _verify_session_token(session_token, settings.dashboard_secret_key):
            return await call_next(request)

        return RedirectResponse("/login", status_code=303)


app.add_middleware(AuthMiddleware)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    error = request.query_params.get("error", "")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Login — Social Media Manager</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
.card {{ background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.1); width: 320px; }}
h2 {{ margin-top: 0; text-align: center; }}
input[type=password] {{ width: 100%; padding: .5rem; border: 1px solid #ccc; border-radius: 4px; margin: .5rem 0 1rem; box-sizing: border-box; }}
button {{ width: 100%; padding: .6rem; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1rem; }}
button:hover {{ background: #1d4ed8; }}
.error {{ color: #dc2626; text-align: center; font-size: .9rem; }}
</style></head><body>
<div class="card">
<h2>Social Media Manager</h2>
{"<p class='error'>Password errata</p>" if error else ""}
<form method="post" action="/login">
<label>Password</label>
<input type="password" name="password" autofocus required>
<button type="submit">Accedi</button>
</form></div></body></html>""")


@app.post("/login")
async def login_submit(password: str = Form(...)):
    if hmac.compare_digest(password, settings.dashboard_password):
        token = _make_session_token(settings.dashboard_secret_key)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            _AUTH_COOKIE, token,
            httponly=True, samesite="strict", max_age=86400,
        )
        return response
    return RedirectResponse("/login?error=1", status_code=303)


@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(_AUTH_COOKIE)
    return response


# ── CSRF Protection ───────────────────────────────────────────────────────────

_CSRF_COOKIE = "smm_csrf"
_CSRF_FIELD = "csrf_token"


def _generate_csrf_token() -> str:
    return secrets.token_hex(32)


def _extract_cookie(cookie_header: str, name: str) -> str:
    """Estrae il valore di un cookie dall'header Cookie raw."""
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part[len(name) + 1:].strip()
    return ""


class CSRFMiddleware:
    """
    Middleware ASGI puro per protezione CSRF.
    Legge e ri-inietta il body del form senza consumarlo,
    evitando il bug di BaseHTTPMiddleware con form data.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Leggi il cookie CSRF dalla richiesta
        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("utf-8", errors="replace")
        csrf_token = _extract_cookie(cookie_header, _CSRF_COOKIE)

        # Genera token se non esiste — sarà impostato nella response
        if not csrf_token:
            csrf_token = _generate_csrf_token()

        # Memorizza nel scope per uso da _template_response
        scope["csrf_token"] = csrf_token

        method = scope.get("method", "")
        path = scope.get("path", "")

        if method == "POST" and path not in _PUBLIC_PATHS:
            # Leggi il body completo
            chunks: list[bytes] = []
            more_body = True
            while more_body:
                message = await receive()
                chunks.append(message.get("body", b""))
                more_body = message.get("more_body", False)
            body = b"".join(chunks)

            # Estrai csrf_token dal form URL-encoded oppure dall'header X-CSRF-Token (fetch API)
            from urllib.parse import parse_qs
            try:
                params = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
                form_token = params.get(_CSRF_FIELD, [""])[0]
            except Exception:
                form_token = ""

            # Fallback: header X-CSRF-Token per richieste fetch/AJAX senza body form
            if not form_token:
                form_token = headers.get(b"x-csrf-token", b"").decode("utf-8", errors="replace")

            if not csrf_token or not form_token or not hmac.compare_digest(csrf_token, form_token):
                location = (path + "?error=csrf").encode()
                await send({"type": "http.response.start", "status": 303,
                            "headers": [[b"location", location]]})
                await send({"type": "http.response.body", "body": b""})
                return

            # Ri-inietta il body così il route handler lo riceve intatto
            body_sent = False

            async def cached_receive():
                nonlocal body_sent
                if not body_sent:
                    body_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            receive = cached_receive

        # Wrappa send per impostare il cookie CSRF nella response se assente
        async def send_with_csrf_cookie(message):
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                has_cookie = any(
                    k == b"set-cookie" and _CSRF_COOKIE.encode() in v
                    for k, v in hdrs
                )
                if not has_cookie:
                    cookie_val = (
                        f"{_CSRF_COOKIE}={csrf_token}; HttpOnly; SameSite=strict; Path=/"
                    )
                    hdrs.append([b"set-cookie", cookie_val.encode()])
                    message = {**message, "headers": hdrs}
            await send(message)

        await self.app(scope, receive, send_with_csrf_cookie)


app.add_middleware(CSRFMiddleware)


def _is_safe_url(url: str) -> bool:
    """Valida che l'URL sia HTTP/HTTPS e non punti a indirizzi interni."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        # Blocca indirizzi riservati/privati
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return False
        except ValueError:
            # È un hostname, non un IP — blocca localhost
            if hostname in ("localhost", "localhost.localdomain"):
                return False
        return True
    except Exception:
        return False
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _template_response(request: Request, name: str, context: dict) -> HTMLResponse:
    """Wrapper che inietta automaticamente csrf_token nel contesto del template."""
    # Usa il token già generato/estratto dal middleware (sempre coerente con il cookie)
    csrf = request.scope.get("csrf_token") or request.cookies.get(_CSRF_COOKIE, _generate_csrf_token())
    context["request"] = request
    context["csrf_token"] = csrf
    return templates.TemplateResponse(request, name, context)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    pending_posts = db.query(Post).filter(Post.status == PostStatus.PENDING).order_by(Post.created_at.desc()).limit(100).all()
    pending_replies = db.query(Comment).filter(Comment.reply_status == PostStatus.PENDING).order_by(Comment.created_at.desc()).limit(100).all()
    return _template_response(request, "index.html", {
        "pending_posts": pending_posts,
        "pending_replies": pending_replies,
        "msg": request.query_params.get("msg", ""),
    })


@app.post("/posts/{post_id}/approve")
async def approve_post(post_id: int, note: str = Form(default=""), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if post:
        post.status = PostStatus.APPROVED
        post.approval_note = note
        db.commit()
    return RedirectResponse("/?msg=approved", status_code=303)


@app.post("/posts/{post_id}/reject")
async def reject_post(post_id: int, note: str = Form(default=""), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if post:
        post.status = PostStatus.REJECTED
        post.approval_note = note
        db.commit()
    return RedirectResponse("/?msg=rejected", status_code=303)


@app.post("/posts/{post_id}/edit")
async def edit_post(
    post_id: int,
    content: str = Form(...),
    hashtags: str = Form(default=""),
    image_url: str = Form(default=""),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if post:
        post.content = content
        post.hashtags = hashtags
        if image_url:
            # Validazione anti-SSRF prima di salvare l'URL immagine
            if _is_safe_url(image_url):
                post.image_url = image_url[:1000]
        db.commit()
    return RedirectResponse("/?msg=edited", status_code=303)


@app.post("/replies/{comment_id}/approve")
async def approve_reply(comment_id: int, reply_draft: str = Form(default=""), db: Session = Depends(get_db)):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if comment:
        if reply_draft:
            comment.reply_draft = reply_draft
        comment.reply_status = PostStatus.APPROVED
        db.commit()
    return RedirectResponse("/?msg=reply_approved", status_code=303)


@app.post("/replies/{comment_id}/reject")
async def reject_reply(comment_id: int, db: Session = Depends(get_db)):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if comment:
        comment.reply_status = PostStatus.REJECTED
        db.commit()
    return RedirectResponse("/?msg=reply_rejected", status_code=303)


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, db: Session = Depends(get_db)):
    published = db.query(Post).filter(Post.status == PostStatus.PUBLISHED).order_by(Post.published_at.desc()).limit(50).all()

    # Aggregati per piattaforma
    from collections import defaultdict
    platform_stats: dict = defaultdict(lambda: {"count": 0, "likes": 0, "reach": 0, "impressions": 0, "comments": 0})
    for p in published:
        ps = platform_stats[p.platform.value]
        ps["count"] += 1
        ps["likes"] += p.likes or 0
        ps["reach"] += p.reach or 0
        ps["impressions"] += p.impressions or 0
        ps["comments"] += p.comments_count or 0

    # Trend engagement ultimi 30 giorni (raggruppa per giorno)
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=30)
    recent = [p for p in published if p.published_at and p.published_at >= cutoff]
    trend: dict = {}
    for p in recent:
        day = p.published_at.strftime("%Y-%m-%d")
        if day not in trend:
            trend[day] = {"likes": 0, "reach": 0, "count": 0}
        trend[day]["likes"] += p.likes or 0
        trend[day]["reach"] += p.reach or 0
        trend[day]["count"] += 1
    trend_sorted = sorted(trend.items())

    has_metrics = any((p.likes or p.reach or p.impressions) for p in published)

    return _template_response(request, "analytics.html", {
        "posts": published[:20],
        "platform_stats": dict(platform_stats),
        "trend": trend_sorted,
        "has_metrics": has_metrics,
    })


@app.get("/context", response_class=HTMLResponse)
async def context_page(request: Request, db: Session = Depends(get_db)):
    ctx = db.query(CompanyContext).first()
    websites = db.query(ContextWebsite).filter(ContextWebsite.is_active == True).order_by(ContextWebsite.created_at.desc()).all()
    return _template_response(request, "context.html", {
        "ctx": ctx,
        "websites": websites,
        "saved": request.query_params.get("saved", False),
    })


@app.post("/context")
async def save_context(
    company_name: str = Form(default=""),
    description: str = Form(default=""),
    mission: str = Form(default=""),
    values: str = Form(default=""),
    founded: str = Form(default=""),
    products_services: str = Form(default=""),
    target_audience: str = Form(default=""),
    sector: str = Form(default=""),
    competitors: str = Form(default=""),
    tone_of_voice: str = Form(default=""),
    topics_to_avoid: str = Form(default=""),
    content_pillars: str = Form(default=""),
    additional_notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    ctx = db.query(CompanyContext).first()
    if not ctx:
        ctx = CompanyContext()
        db.add(ctx)
    ctx.company_name = company_name
    ctx.description = description
    ctx.mission = mission
    ctx.values = values
    ctx.founded = founded
    ctx.products_services = products_services
    ctx.target_audience = target_audience
    ctx.sector = sector
    ctx.competitors = competitors
    ctx.tone_of_voice = tone_of_voice
    ctx.topics_to_avoid = topics_to_avoid
    ctx.content_pillars = content_pillars
    ctx.additional_notes = additional_notes
    db.commit()
    return RedirectResponse("/context?saved=1", status_code=303)


@app.post("/context/websites/add")
async def add_website(
    url: str = Form(...),
    label: str = Form(default=""),
    category: str = Form(default=""),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    site = ContextWebsite(url=url, label=label, category=category, notes=notes)
    db.add(site)
    db.commit()
    return RedirectResponse("/context?saved=1", status_code=303)


@app.post("/context/websites/{site_id}/delete")
async def delete_website(site_id: int, db: Session = Depends(get_db)):
    site = db.query(ContextWebsite).filter(ContextWebsite.id == site_id).first()
    if site:
        site.is_active = False
        db.commit()
    return RedirectResponse("/context", status_code=303)


@app.post("/context/websites/{site_id}/scrape")
async def scrape_website(site_id: int, db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    site = db.query(ContextWebsite).filter(ContextWebsite.id == site_id).first()
    if not site:
        return RedirectResponse("/context", status_code=303)
    if not _is_safe_url(site.url):
        return RedirectResponse("/context?error=invalid_url", status_code=303)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(site.url, headers=scrape_headers())
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["style", "script"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            site.scraped_content = text[:MAX_SCRAPED_CONTENT]  # max 8k caratteri
            site.last_scraped_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        logger.warning("Errore scraping sito %s", site.url, exc_info=True)
    return RedirectResponse("/context", status_code=303)


# ── Competitor Analysis ────────────────────────────────────────────────────────

@app.get("/competitors/analysis", response_class=HTMLResponse)
async def analysis_page(request: Request, db: Session = Depends(get_db)):
    analyses = db.query(CompetitorAnalysis).order_by(CompetitorAnalysis.created_at.desc()).limit(50).all()
    competitors = db.query(Competitor).filter(Competitor.is_active == True).all()

    # Seleziona l'analisi da visualizzare: ?id= oppure l'ultima
    selected_id = request.query_params.get("id")
    if selected_id:
        try:
            selected_id = int(selected_id)
            target = next((a for a in analyses if a.id == selected_id), analyses[0] if analyses else None)
        except (ValueError, TypeError):
            target = analyses[0] if analyses else None
    else:
        target = analyses[0] if analyses else None

    def load(field):
        try:
            return json.loads(field) if field else []
        except Exception:
            return []

    parsed = None
    if target:
        sources_used = {}
        try:
            sources_used = json.loads(target.sources_used) if target.sources_used else {}
        except Exception:
            pass

        parsed = {
            "id": target.id,
            "summary": target.summary,
            "landscape": target.landscape,
            "data_quality": target.data_quality or "",
            "per_competitor": load(target.per_competitor),
            "opportunities": load(target.opportunities),
            "threats": load(target.threats),
            "recommendations": load(target.recommendations),
            "content_gaps": load(target.content_gaps) if hasattr(target, 'content_gaps') else [],
            "sources_used": sources_used,
            "generated_by": target.generated_by,
            "created_at": target.created_at.strftime("%d/%m/%Y %H:%M"),
        }

    # Lista sintetica per il selettore storico
    analyses_list = [
        {"id": a.id, "label": a.created_at.strftime("%d/%m/%Y %H:%M")}
        for a in analyses
    ]

    return _template_response(request, "competitor_analysis.html", {
        "analysis": parsed,
        "analyses_list": analyses_list,
        "competitors_count": len(competitors),
        "analyses_count": len(analyses),
        "generating": request.query_params.get("generating", False),
    })


@app.post("/competitors/analysis/generate")
async def generate_analysis(db: Session = Depends(get_db)):
    from agents.competitor_analyst import run_analysis
    competitors = (
        db.query(Competitor)
        .filter(Competitor.is_active == True)
        .all()
    )
    if not competitors:
        return RedirectResponse("/competitors/analysis?error=no_competitors", status_code=303)

    company_ctx = db.query(CompanyContext).first()
    result = run_analysis(competitors, company_ctx, db_session=db)

    def dump(val):
        if isinstance(val, (list, dict)):
            return json.dumps(val, ensure_ascii=False)
        return str(val) if val else ""

    analysis = CompetitorAnalysis(
        summary=result.get("summary", ""),
        landscape=result.get("landscape", ""),
        data_quality=result.get("data_quality", ""),
        per_competitor=dump(result.get("per_competitor", [])),
        opportunities=dump(result.get("opportunities", [])),
        threats=dump(result.get("threats", [])),
        recommendations=dump(result.get("recommendations", [])),
        content_gaps=dump(result.get("content_gaps", [])),
        sources_used=dump(result.get("sources_used", {})),
        raw_response=json.dumps(result, ensure_ascii=False)[:MAX_RAW_RESPONSE],
        generated_by=result.get("generated_by", ""),
    )
    db.add(analysis)
    db.commit()
    return RedirectResponse("/competitors/analysis", status_code=303)


@app.post("/competitors/analysis/delete-all")
async def delete_all_analyses(db: Session = Depends(get_db)):
    db.query(CompetitorAnalysis).delete()
    db.commit()
    return RedirectResponse("/competitors/analysis", status_code=303)


# ── Competitors ────────────────────────────────────────────────────────────────

@app.get("/competitors", response_class=HTMLResponse)
async def competitors_page(request: Request, db: Session = Depends(get_db)):
    competitors = (
        db.query(Competitor)
        .filter(Competitor.is_active == True)
        .order_by(Competitor.threat_level.desc(), Competitor.name)
        .all()
    )
    return _template_response(request, "competitors.html", {
        "competitors": competitors,
        "msg": request.query_params.get("msg", ""),
    })


@app.post("/competitors/add")
async def add_competitor(
    name: str = Form(...),
    website: str = Form(default=""),
    sector: str = Form(default=""),
    description: str = Form(default=""),
    threat_level: int = Form(default=2),
    db: Session = Depends(get_db),
):
    c = Competitor(name=name, website=website, sector=sector,
                   description=description, threat_level=threat_level)
    db.add(c)
    db.commit()
    return RedirectResponse(f"/competitors?msg=added&sel={c.id}", status_code=303)


@app.post("/competitors/{cid}/update")
async def update_competitor(
    cid: int,
    name: str = Form(...),
    website: str = Form(default=""),
    sector: str = Form(default=""),
    description: str = Form(default=""),
    threat_level: int = Form(default=2),
    strengths: str = Form(default=""),
    weaknesses: str = Form(default=""),
    content_strategy: str = Form(default=""),
    target_audience: str = Form(default=""),
    tone_of_voice: str = Form(default=""),
    unique_topics: str = Form(default=""),
    posting_frequency: str = Form(default=""),
    db: Session = Depends(get_db),
):
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if c:
        c.name = name; c.website = website; c.sector = sector
        c.description = description; c.threat_level = threat_level
        c.strengths = strengths; c.weaknesses = weaknesses
        c.content_strategy = content_strategy; c.target_audience = target_audience
        c.tone_of_voice = tone_of_voice; c.unique_topics = unique_topics
        c.posting_frequency = posting_frequency
        db.commit()
    return RedirectResponse(f"/competitors?msg=saved&sel={cid}", status_code=303)


@app.post("/competitors/{cid}/delete")
async def delete_competitor(cid: int, db: Session = Depends(get_db)):
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if c:
        c.is_active = False
        db.commit()
    return RedirectResponse("/competitors", status_code=303)


@app.post("/competitors/{cid}/scrape")
async def scrape_competitor(cid: int, db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if not c or not c.website:
        return RedirectResponse(f"/competitors?sel={cid}", status_code=303)
    if not _is_safe_url(c.website):
        return RedirectResponse(f"/competitors?sel={cid}&error=invalid_url", status_code=303)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(c.website, headers=scrape_headers())
            resp.raise_for_status()
            text = re.sub(r"<style[^>]*>.*?</style>", " ", resp.text, flags=re.DOTALL)
            text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            c.scraped_content = text[:MAX_SCRAPED_CONTENT]
            c.last_scraped_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        logger.warning("Errore scraping competitor %s", c.website, exc_info=True)
    return RedirectResponse(f"/competitors?sel={cid}", status_code=303)


# Social profiles
@app.post("/competitors/{cid}/socials/add")
async def add_social(
    cid: int,
    platform: str = Form(...),
    profile_url: str = Form(default=""),
    handle: str = Form(default=""),
    followers: str = Form(default=""),
    avg_likes: str = Form(default=""),
    avg_comments: str = Form(default=""),
    posting_days: str = Form(default=""),
    content_types: str = Form(default=""),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    # Sostituisce se esiste già per quella piattaforma
    existing = db.query(CompetitorSocial).filter(
        CompetitorSocial.competitor_id == cid,
        CompetitorSocial.platform == platform
    ).first()
    if existing:
        existing.profile_url = profile_url; existing.handle = handle
        existing.followers = followers; existing.avg_likes = avg_likes
        existing.avg_comments = avg_comments; existing.posting_days = posting_days
        existing.content_types = content_types; existing.notes = notes
    else:
        s = CompetitorSocial(competitor_id=cid, platform=platform, profile_url=profile_url,
                             handle=handle, followers=followers, avg_likes=avg_likes,
                             avg_comments=avg_comments, posting_days=posting_days,
                             content_types=content_types, notes=notes)
        db.add(s)
    db.commit()
    return RedirectResponse(f"/competitors?sel={cid}#socials", status_code=303)


@app.post("/competitors/{cid}/socials/{sid}/delete")
async def delete_social(cid: int, sid: int, db: Session = Depends(get_db)):
    s = db.query(CompetitorSocial).filter(CompetitorSocial.id == sid).first()
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse(f"/competitors?sel={cid}#socials", status_code=303)


# Observations
@app.post("/competitors/{cid}/observations/add")
async def add_observation(
    cid: int,
    category: str = Form(default="generale"),
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    obs = CompetitorObservation(competitor_id=cid, category=category, content=content)
    db.add(obs)
    db.commit()
    return RedirectResponse(f"/competitors?sel={cid}#osservazioni", status_code=303)


@app.post("/competitors/{cid}/observations/{oid}/delete")
async def delete_observation(cid: int, oid: int, db: Session = Depends(get_db)):
    obs = db.query(CompetitorObservation).filter(CompetitorObservation.id == oid).first()
    if obs:
        db.delete(obs)
        db.commit()
    return RedirectResponse(f"/competitors?sel={cid}#osservazioni", status_code=303)


@app.post("/competitors/{cid}/observations/{oid}/update")
async def update_observation(
    cid: int, oid: int,
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    obs = db.query(CompetitorObservation).filter(CompetitorObservation.id == oid).first()
    if obs:
        obs.content = content[:2000]
        db.commit()
    return RedirectResponse(f"/competitors?sel={cid}#osservazioni", status_code=303)


# API JSON per aggiornamenti inline
@app.get("/api/competitors/{cid}")
async def api_competitor(cid: int, db: Session = Depends(get_db)):
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "id": c.id, "name": c.name, "website": c.website, "sector": c.sector,
        "description": c.description, "threat_level": c.threat_level,
        "strengths": c.strengths, "weaknesses": c.weaknesses,
        "content_strategy": c.content_strategy, "target_audience": c.target_audience,
        "tone_of_voice": c.tone_of_voice, "unique_topics": c.unique_topics,
        "posting_frequency": c.posting_frequency,
        "scraped_content": c.scraped_content[:SCRAPED_PREVIEW_LENGTH] if c.scraped_content else "",
        "last_scraped_at": c.last_scraped_at.isoformat() if c.last_scraped_at else None,
        "socials": [
            {"id": s.id, "platform": s.platform, "profile_url": s.profile_url,
             "handle": s.handle, "followers": s.followers, "avg_likes": s.avg_likes,
             "avg_comments": s.avg_comments, "posting_days": s.posting_days,
             "content_types": s.content_types, "notes": s.notes}
            for s in c.socials
        ],
        "observations": [
            {"id": o.id, "category": o.category, "content": o.content,
             "created_at": o.created_at.strftime("%d/%m/%Y %H:%M")}
            for o in c.observations
        ],
    })


@app.get("/api/competitors/{cid}/products")
async def api_competitor_products(cid: int, db: Session = Depends(get_db)):
    products = db.query(CompetitorProduct).filter(
        CompetitorProduct.competitor_id == cid
    ).order_by(CompetitorProduct.found_at.desc()).all()
    return JSONResponse([
        {
            "id": p.id,
            "name": p.name,
            "product_line": p.product_line,
            "category": p.category,
            "brochure_url": p.brochure_url,
            "brochure_filename": p.brochure_filename,
            "page_url": p.page_url,
            "source": p.source,
            "dealer_id": p.dealer_id,
            "file_size_kb": p.file_size_kb,
            "tech_summary": p.tech_summary or "",
            "tech_specs": json.loads(p.tech_specs) if p.tech_specs else {},
            "found_at": p.found_at.strftime("%d/%m/%Y %H:%M") if p.found_at else "",
            "has_local_file": bool(p.brochure_filename),
        }
        for p in products
    ])


@app.post("/competitors/{cid}/products/search")
async def competitor_products_search(cid: int, db: Session = Depends(get_db)):
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        from agents.product_scout import search_and_download
        saved = search_and_download(cid, db)
        return JSONResponse({"ok": True, "found": len(saved), "products": saved})
    except Exception as exc:
        logger.error("Errore product search per competitor %d: %s", cid, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/competitors/{cid}/brochures/{filename}")
async def serve_brochure(cid: int, filename: str, db: Session = Depends(get_db)):
    # Verifica che il file appartenga al competitor e sanitizza il nome
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse({"error": "invalid"}, status_code=400)
    brochure_path = FilePath(__file__).parent.parent / "storage" / "brochures" / str(cid) / filename
    if not brochure_path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(brochure_path), media_type="application/pdf", filename=filename)


@app.post("/competitors/{cid}/products/{pid}/delete")
async def delete_competitor_product(cid: int, pid: int, db: Session = Depends(get_db)):
    product = db.query(CompetitorProduct).filter(
        CompetitorProduct.id == pid,
        CompetitorProduct.competitor_id == cid,
    ).first()
    if product:
        # Elimina il file locale se esiste
        if product.brochure_filename:
            local = FilePath(__file__).parent.parent / "storage" / "brochures" / str(cid) / product.brochure_filename
            if local.exists():
                local.unlink()
        db.delete(product)
        db.commit()
    return RedirectResponse(f"/competitors?sel={cid}&msg=saved", status_code=303)


@app.get("/api/competitors/{cid}/dealers")
async def api_competitor_dealers(cid: int, db: Session = Depends(get_db)):
    dealers = db.query(CompetitorDealer).filter(
        CompetitorDealer.competitor_id == cid
    ).order_by(CompetitorDealer.name).all()
    return JSONResponse([
        {
            "id": d.id,
            "name": d.name,
            "website": d.website,
            "address": d.address,
            "city": d.city,
            "region": d.region,
            "country": d.country,
            "phone": d.phone,
            "email": d.email,
            "notes": d.notes,
            "source": d.source,
            "source_url": d.source_url,
            "found_at": d.found_at.strftime("%d/%m/%Y") if d.found_at else "",
        }
        for d in dealers
    ])


@app.post("/competitors/{cid}/dealers/search")
async def competitor_dealers_search(cid: int, db: Session = Depends(get_db)):
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        from agents.dealer_scout import search_and_save_dealers
        saved = search_and_save_dealers(cid, db)
        return JSONResponse({"ok": True, "found": len(saved), "dealers": saved})
    except Exception as exc:
        logger.error("Errore dealer search per competitor %d: %s", cid, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/competitors/{cid}/dealers/add")
async def add_dealer_manual(
    cid: int,
    name: str = Form(...),
    website: str = Form(default=""),
    address: str = Form(default=""),
    city: str = Form(default=""),
    region: str = Form(default=""),
    country: str = Form(default=""),
    phone: str = Form(default=""),
    email: str = Form(default=""),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if not c:
        return RedirectResponse(f"/competitors", status_code=303)
    dealer = CompetitorDealer(
        competitor_id=cid,
        name=name[:500],
        website=website[:1000],
        address=address[:500],
        city=city[:200],
        region=region[:200],
        country=country[:100],
        phone=phone[:100],
        email=email[:200],
        notes=notes,
        source="manual",
        found_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(dealer)
    db.commit()
    return RedirectResponse(f"/competitors?sel={cid}&msg=saved", status_code=303)


@app.post("/competitors/{cid}/dealers/{did}/update")
async def update_dealer(
    cid: int,
    did: int,
    name: str = Form(...),
    website: str = Form(default=""),
    address: str = Form(default=""),
    city: str = Form(default=""),
    region: str = Form(default=""),
    country: str = Form(default=""),
    phone: str = Form(default=""),
    email: str = Form(default=""),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    dealer = db.query(CompetitorDealer).filter(
        CompetitorDealer.id == did, CompetitorDealer.competitor_id == cid
    ).first()
    if dealer:
        dealer.name = name[:500]
        dealer.website = website[:1000]
        dealer.address = address[:500]
        dealer.city = city[:200]
        dealer.region = region[:200]
        dealer.country = country[:100]
        dealer.phone = phone[:100]
        dealer.email = email[:200]
        dealer.notes = notes
        db.commit()
    return RedirectResponse(f"/competitors?sel={cid}&msg=saved", status_code=303)


@app.post("/competitors/{cid}/dealers/{did}/delete")
async def delete_dealer(cid: int, did: int, db: Session = Depends(get_db)):
    dealer = db.query(CompetitorDealer).filter(
        CompetitorDealer.id == did, CompetitorDealer.competitor_id == cid
    ).first()
    if dealer:
        db.delete(dealer)
        db.commit()
    return RedirectResponse(f"/competitors?sel={cid}&msg=saved", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return _template_response(request, "settings.html", {
        "settings": settings,
        "saved": request.query_params.get("saved", False),
    })


# Chiavi ammesse per la scrittura nel .env da dashboard
_SETTINGS_WHITELIST = {
    "COMPANY_NAME", "BRAND_KEYWORDS", "AI_PRIMARY_PROVIDER",
    "ANTHROPIC_MODEL", "ANTHROPIC_API_KEY",
    "OPENAI_COMPATIBLE_MODEL", "OPENAI_COMPATIBLE_BASE_URL",
    "MONITOR_INTERVAL_MINUTES", "LINKEDIN_POST_TIMES", "FACEBOOK_POST_TIMES",
    "INSTAGRAM_POST_TIMES",
    "TAVILY_API_KEY",
    "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_ORGANIZATION_ID",
    "FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET", "FACEBOOK_ACCESS_TOKEN", "FACEBOOK_PAGE_ID",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID",
}


def _sanitize_env_value(value: str) -> str:
    """Rimuove caratteri pericolosi dai valori .env."""
    # Niente newline, carriage return o null bytes
    return value.replace("\n", "").replace("\r", "").replace("\0", "")


@app.post("/settings")
async def save_settings(
    request: Request,
    company_name: str = Form(default=""),
    brand_keywords: str = Form(default=""),
    ai_primary_provider: str = Form(default="anthropic"),
    anthropic_api_key: str = Form(default=""),
    anthropic_model: str = Form(default="claude-sonnet-4-6"),
    openai_compatible_model: str = Form(default="Qwen3.5-122B"),
    openai_compatible_base_url: str = Form(default=""),
    monitor_interval_minutes: int = Form(default=15),
    linkedin_post_times: str = Form(default="09:00,12:00,17:00"),
    facebook_post_times: str = Form(default="10:00,14:00,19:00"),
    instagram_post_times: str = Form(default="08:00,13:00,18:00"),
    tavily_api_key: str = Form(default=""),
    linkedin_client_id: str = Form(default=""),
    linkedin_client_secret: str = Form(default=""),
    linkedin_access_token: str = Form(default=""),
    linkedin_organization_id: str = Form(default=""),
    facebook_app_id: str = Form(default=""),
    facebook_app_secret: str = Form(default=""),
    facebook_access_token: str = Form(default=""),
    facebook_page_id: str = Form(default=""),
    instagram_business_account_id: str = Form(default=""),
):
    env_path = Path(__file__).parent.parent / ".env"
    lines = env_path.read_text().splitlines()

    updates = {
        "COMPANY_NAME": company_name,
        "BRAND_KEYWORDS": brand_keywords,
        "AI_PRIMARY_PROVIDER": ai_primary_provider,
        "ANTHROPIC_API_KEY": anthropic_api_key,
        "ANTHROPIC_MODEL": anthropic_model,
        "OPENAI_COMPATIBLE_MODEL": openai_compatible_model,
        "OPENAI_COMPATIBLE_BASE_URL": openai_compatible_base_url,
        "MONITOR_INTERVAL_MINUTES": str(monitor_interval_minutes),
        "LINKEDIN_POST_TIMES": linkedin_post_times,
        "FACEBOOK_POST_TIMES": facebook_post_times,
        "INSTAGRAM_POST_TIMES": instagram_post_times,
        "TAVILY_API_KEY": tavily_api_key,
        "LINKEDIN_CLIENT_ID": linkedin_client_id,
        "LINKEDIN_CLIENT_SECRET": linkedin_client_secret,
        "LINKEDIN_ACCESS_TOKEN": linkedin_access_token,
        "LINKEDIN_ORGANIZATION_ID": linkedin_organization_id,
        "FACEBOOK_APP_ID": facebook_app_id,
        "FACEBOOK_APP_SECRET": facebook_app_secret,
        "FACEBOOK_ACCESS_TOKEN": facebook_access_token,
        "FACEBOOK_PAGE_ID": facebook_page_id,
        "INSTAGRAM_BUSINESS_ACCOUNT_ID": instagram_business_account_id,
    }

    # Filtra solo chiavi nella whitelist e sanitizza valori
    updates = {
        k: _sanitize_env_value(v)
        for k, v in updates.items()
        if k in _SETTINGS_WHITELIST
    }

    new_lines = []
    updated_keys = set()
    for line in lines:
        if "=" not in line:
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")
    return RedirectResponse("/settings?saved=1", status_code=303)


# ── Anagrafica rivenditori globale ────────────────────────────────────────────

@app.get("/dealers", response_class=HTMLResponse)
async def dealers_page(request: Request, db: Session = Depends(get_db)):
    dealers = db.query(Dealer).order_by(Dealer.country, Dealer.name).all()
    competitors = db.query(Competitor).filter(Competitor.is_active == True).order_by(Competitor.name).all()
    countries = sorted({d.country for d in dealers if d.country})
    context_row = db.query(CompanyContext).first()
    company_name = context_row.company_name if context_row else settings.company_name
    return _template_response(request, "dealers.html", {
        "dealers": dealers,
        "competitors": competitors,
        "countries": countries,
        "company_name": company_name,
        "msg": request.query_params.get("msg", ""),
    })


@app.post("/dealers/add")
async def dealer_add(
    request: Request,
    name: str = Form(...),
    website: str = Form(default=""),
    email: str = Form(default=""),
    phone: str = Form(default=""),
    address: str = Form(default=""),
    city: str = Form(default=""),
    state: str = Form(default=""),
    country: str = Form(default=""),
    postal_code: str = Form(default=""),
    latitude: str = Form(default=""),
    longitude: str = Form(default=""),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    dealer = Dealer(
        name=name[:500],
        website=website[:1000],
        email=email[:200],
        phone=phone[:100],
        address=address[:500],
        city=city[:200],
        state=state[:200],
        country=country[:100],
        postal_code=postal_code[:20],
        latitude=float(latitude) if latitude else None,
        longitude=float(longitude) if longitude else None,
        notes=notes,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(dealer)
    db.flush()

    # Brand associations dai campi brand_own / brand_{id}
    form = await request.form()
    _save_dealer_brands(db, dealer.id, form)

    db.commit()
    return RedirectResponse("/dealers?msg=added", status_code=303)


@app.post("/dealers/import")
async def dealer_import(request: Request, db: Session = Depends(get_db)):
    """Importa i dealer dai competitor_dealers nel registro globale."""
    comp_dealers = db.query(CompetitorDealer).all()
    imported = 0
    for cd in comp_dealers:
        name_key = (cd.name or "").strip().lower()
        if not name_key:
            continue
        existing = db.query(Dealer).filter(
            Dealer.name.ilike(cd.name.strip())
        ).first()
        if not existing:
            existing = Dealer(
                name=cd.name[:500],
                website=(cd.website or "")[:1000],
                email=(cd.email or "")[:200],
                phone=(cd.phone or "")[:100],
                address=(cd.address or "")[:500],
                city=(cd.city or "")[:200],
                state=(cd.region or "")[:200],
                country=(cd.country or "")[:100],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(existing)
            db.flush()
            imported += 1

        # Collega al competitor se non già presente
        already = db.query(DealerBrand).filter(
            DealerBrand.dealer_id == existing.id,
            DealerBrand.competitor_id == cd.competitor_id,
        ).first()
        if not already:
            db.add(DealerBrand(
                dealer_id=existing.id,
                competitor_id=cd.competitor_id,
                is_own_brand=False,
            ))

    db.commit()
    return RedirectResponse(f"/dealers?msg=imported_{imported}", status_code=303)


@app.post("/dealers/{did}/edit")
async def dealer_edit(
    request: Request,
    did: int,
    name: str = Form(...),
    website: str = Form(default=""),
    email: str = Form(default=""),
    phone: str = Form(default=""),
    address: str = Form(default=""),
    city: str = Form(default=""),
    state: str = Form(default=""),
    country: str = Form(default=""),
    postal_code: str = Form(default=""),
    latitude: str = Form(default=""),
    longitude: str = Form(default=""),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    dealer = db.query(Dealer).filter(Dealer.id == did).first()
    if not dealer:
        return RedirectResponse("/dealers", status_code=303)
    dealer.name = name[:500]
    dealer.website = website[:1000]
    dealer.email = email[:200]
    dealer.phone = phone[:100]
    dealer.address = address[:500]
    dealer.city = city[:200]
    dealer.state = state[:200]
    dealer.country = country[:100]
    dealer.postal_code = postal_code[:20]
    dealer.latitude = float(latitude) if latitude else None
    dealer.longitude = float(longitude) if longitude else None
    dealer.notes = notes
    dealer.updated_at = datetime.utcnow()

    # Aggiorna brand associations
    for b in list(dealer.brands):
        db.delete(b)
    db.flush()
    form = await request.form()
    _save_dealer_brands(db, dealer.id, form)

    db.commit()
    return RedirectResponse("/dealers?msg=saved", status_code=303)


@app.post("/dealers/{did}/delete")
async def dealer_delete(did: int, db: Session = Depends(get_db)):
    dealer = db.query(Dealer).filter(Dealer.id == did).first()
    if dealer:
        db.delete(dealer)
        db.commit()
    return RedirectResponse("/dealers?msg=deleted", status_code=303)


@app.get("/api/geocode")
async def geocode_proxy(q: str):
    """Proxy per Nominatim (OpenStreetMap) — risolve CORS e User-Agent."""
    import urllib.parse
    url = "https://nominatim.openstreetmap.org/search"
    params = f"?q={urllib.parse.quote(q)}&format=json&addressdetails=1&limit=6"
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "SocialMediaManager/1.0 (internal tool)"},
            timeout=8,
        ) as client:
            resp = await client.get(url + params)
            return JSONResponse(resp.json())
    except Exception as exc:
        logger.warning("Geocode proxy error: %s", exc)
        return JSONResponse([])


@app.get("/api/dealers/{did}")
async def api_dealer_detail(did: int, db: Session = Depends(get_db)):
    dealer = db.query(Dealer).filter(Dealer.id == did).first()
    if not dealer:
        return JSONResponse({}, status_code=404)
    return JSONResponse({
        "id": dealer.id,
        "name": dealer.name,
        "website": dealer.website or "",
        "email": dealer.email or "",
        "phone": dealer.phone or "",
        "address": dealer.address or "",
        "city": dealer.city or "",
        "state": dealer.state or "",
        "country": dealer.country or "",
        "postal_code": dealer.postal_code or "",
        "latitude": dealer.latitude,
        "longitude": dealer.longitude,
        "notes": dealer.notes or "",
        "is_own_brand": any(b.is_own_brand for b in dealer.brands),
        "brand_competitor_ids": [b.competitor_id for b in dealer.brands if b.competitor_id],
    })


@app.get("/dealers/export.csv")
async def export_dealers_csv(db: Session = Depends(get_db)):
    """Scarica l'anagrafica dealer in formato CSV."""
    import csv, io
    dealers = db.query(Dealer).order_by(Dealer.name).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Nome", "Sito web", "Email", "Telefono",
        "Indirizzo", "Città", "Stato/Provincia", "Paese", "CAP",
        "Latitudine", "Longitudine", "Note", "Creato il",
    ])
    for d in dealers:
        writer.writerow([
            d.id, d.name or "", d.website or "", d.email or "", d.phone or "",
            d.address or "", d.city or "", d.state or "", d.country or "", d.postal_code or "",
            d.latitude or "", d.longitude or "", d.notes or "",
            d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "",
        ])
    from fastapi.responses import Response
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dealers.csv"'},
    )


def _save_dealer_brands(db: Session, dealer_id: int, form) -> None:
    """Crea i record DealerBrand a partire dai checkbox del form."""
    if form.get("brand_own"):
        db.add(DealerBrand(dealer_id=dealer_id, competitor_id=None, is_own_brand=True))
    for key in form.keys():
        if key.startswith("brand_c_"):
            try:
                cid = int(key[len("brand_c_"):])
                db.add(DealerBrand(dealer_id=dealer_id, competitor_id=cid, is_own_brand=False))
            except ValueError:
                pass


# ── API key test ─────────────────────────────────────────────────────────────

@app.post("/api/test-key/anthropic")
async def test_key_anthropic(request: Request):
    """Verifica che la chiave Anthropic sia valida con una chiamata minimale."""
    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=settings.anthropic_api_key)
        client.messages.create(
            model=settings.anthropic_model,
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        return JSONResponse({"ok": True, "msg": "Chiave valida"})
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "auth" in msg.lower() or "invalid" in msg.lower():
            return JSONResponse({"ok": False, "msg": "Chiave non valida o scaduta"})
        if "insufficient_quota" in msg or "quota" in msg.lower():
            return JSONResponse({"ok": False, "msg": "Quota esaurita"})
        return JSONResponse({"ok": False, "msg": f"Errore: {msg[:120]}"})


@app.post("/api/test-key/tavily")
async def test_key_tavily(request: Request):
    """Verifica che la chiave Tavily sia valida."""
    if not settings.tavily_api_key:
        return JSONResponse({"ok": False, "msg": "Chiave non configurata"})
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        client.search(query="test", max_results=1)
        return JSONResponse({"ok": True, "msg": "Chiave valida"})
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "Unauthorized" in msg or "invalid" in msg.lower():
            return JSONResponse({"ok": False, "msg": "Chiave non valida o scaduta"})
        return JSONResponse({"ok": False, "msg": f"Errore: {msg[:120]}"})


# ── Orchestrator start/stop ───────────────────────────────────────────────────

_ORCH_PID_FILE = Path(__file__).parent.parent / "storage" / "orchestrator.pid"


def _orch_pid() -> int | None:
    """Restituisce il PID dell'orchestrator se il file esiste, None altrimenti."""
    try:
        return int(_ORCH_PID_FILE.read_text().strip())
    except Exception:
        return None


def _orch_running() -> bool:
    """True se il processo dell'orchestrator è ancora attivo."""
    import os
    import signal
    pid = _orch_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)   # signal 0 = solo check esistenza processo
        return True
    except (ProcessLookupError, PermissionError):
        _ORCH_PID_FILE.unlink(missing_ok=True)
        return False


@app.get("/api/orchestrator/status")
async def orchestrator_status():
    running = _orch_running()
    pid = _orch_pid() if running else None
    started_at = None
    if running and _ORCH_PID_FILE.exists():
        import datetime as _dt
        ts = _ORCH_PID_FILE.stat().st_mtime
        started_at = _dt.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")
    return JSONResponse({"running": running, "pid": pid, "started_at": started_at})


@app.post("/api/orchestrator/start")
async def orchestrator_start(request: Request):
    if _orch_running():
        return JSONResponse({"ok": False, "error": "già in esecuzione"})
    import subprocess, sys
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent.parent / "main.py"), "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    logger.info("Orchestrator avviato dal dashboard (PID %s)", proc.pid)
    return JSONResponse({"ok": True, "pid": proc.pid})


@app.post("/api/orchestrator/stop")
async def orchestrator_stop(request: Request):
    import os, signal
    pid = _orch_pid()
    if not pid or not _orch_running():
        return JSONResponse({"ok": False, "error": "non in esecuzione"})
    try:
        os.kill(pid, signal.SIGTERM)
        _ORCH_PID_FILE.unlink(missing_ok=True)
        logger.info("Orchestrator fermato dal dashboard (PID %s)", pid)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    uvicorn.run("dashboard.main:app", host=settings.dashboard_host, port=settings.dashboard_port, reload=True)

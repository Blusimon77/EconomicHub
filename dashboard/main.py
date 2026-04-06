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

logger = get_logger("dashboard")
from models.post import Base, Post, Comment, PostStatus, Platform
from models.context import CompanyContext, ContextWebsite
import json
from models.competitor import Competitor, CompetitorSocial, CompetitorObservation, CompetitorAnalysis

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


def _get_or_set_csrf(request: Request, response=None) -> str:
    """Restituisce il token CSRF dal cookie, o ne genera uno nuovo."""
    token = request.cookies.get(_CSRF_COOKIE)
    if not token:
        token = _generate_csrf_token()
    if response:
        response.set_cookie(_CSRF_COOKIE, token, httponly=True, samesite="strict")
    return token


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            # Escludi login (non ha ancora il token)
            if request.url.path not in _PUBLIC_PATHS:
                cookie_token = request.cookies.get(_CSRF_COOKIE, "")
                # Leggi il token dal form body
                form = await request.form()
                form_token = form.get(_CSRF_FIELD, "")
                if not cookie_token or not hmac.compare_digest(cookie_token, form_token):
                    return RedirectResponse(request.url.path + "?error=csrf", status_code=303)
                # Ricostruisci il body perché è già stato consumato
                from starlette.datastructures import FormData
                request._form = form

        response = await call_next(request)

        # Assicura che il cookie CSRF esista sempre
        if not request.cookies.get(_CSRF_COOKIE):
            token = _generate_csrf_token()
            response.set_cookie(_CSRF_COOKIE, token, httponly=True, samesite="strict")

        return response


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
    csrf = request.cookies.get(_CSRF_COOKIE, _generate_csrf_token())
    context["request"] = request
    context["csrf_token"] = csrf
    return templates.TemplateResponse(name, context)


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
    })


@app.post("/posts/{post_id}/approve")
async def approve_post(post_id: int, note: str = Form(default=""), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if post:
        post.status = PostStatus.APPROVED
        post.approval_note = note
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/posts/{post_id}/reject")
async def reject_post(post_id: int, note: str = Form(default=""), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if post:
        post.status = PostStatus.REJECTED
        post.approval_note = note
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/posts/{post_id}/edit")
async def edit_post(post_id: int, content: str = Form(...), hashtags: str = Form(default=""), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if post:
        post.content = content
        post.hashtags = hashtags
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/replies/{comment_id}/approve")
async def approve_reply(comment_id: int, db: Session = Depends(get_db)):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if comment:
        comment.reply_status = PostStatus.APPROVED
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/replies/{comment_id}/reject")
async def reject_reply(comment_id: int, db: Session = Depends(get_db)):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if comment:
        comment.reply_status = PostStatus.REJECTED
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, db: Session = Depends(get_db)):
    published = db.query(Post).filter(Post.status == PostStatus.PUBLISHED).order_by(Post.published_at.desc()).limit(20).all()
    return _template_response(request, "analytics.html", {"posts": published})


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
            resp = await client.get(site.url, headers={"User-Agent": "Mozilla/5.0"})
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
    latest = analyses[0] if analyses else None

    def load(field):
        try:
            return json.loads(field) if field else []
        except Exception:
            return []

    def load_str(field):
        return field or ""

    parsed = None
    if latest:
        sources_used = {}
        try:
            sources_used = json.loads(latest.sources_used) if latest.sources_used else {}
        except Exception:
            pass

        parsed = {
            "summary": latest.summary,
            "landscape": latest.landscape,
            "data_quality": latest.data_quality or "",
            "per_competitor": load(latest.per_competitor),
            "opportunities": load(latest.opportunities),
            "threats": load(latest.threats),
            "recommendations": load(latest.recommendations),
            "content_gaps": load(latest.content_gaps) if hasattr(latest, 'content_gaps') else [],
            "sources_used": sources_used,
            "generated_by": latest.generated_by,
            "created_at": latest.created_at.strftime("%d/%m/%Y %H:%M"),
        }

    return _template_response(request, "competitor_analysis.html", {
        "analysis": parsed,
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
            resp = await client.get(c.website, headers={"User-Agent": "Mozilla/5.0"})
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


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return _template_response(request, "settings.html", {
        "settings": settings,
        "saved": request.query_params.get("saved", False),
    })


# Chiavi ammesse per la scrittura nel .env da dashboard
_SETTINGS_WHITELIST = {
    "COMPANY_NAME", "BRAND_KEYWORDS", "AI_PRIMARY_PROVIDER",
    "ANTHROPIC_MODEL", "OPENAI_COMPATIBLE_MODEL", "OPENAI_COMPATIBLE_BASE_URL",
    "MONITOR_INTERVAL_MINUTES", "LINKEDIN_POST_TIMES", "FACEBOOK_POST_TIMES",
    "INSTAGRAM_POST_TIMES",
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
    anthropic_model: str = Form(default="claude-sonnet-4-6"),
    openai_compatible_model: str = Form(default="Qwen3.5-122B"),
    openai_compatible_base_url: str = Form(default=""),
    monitor_interval_minutes: int = Form(default=15),
    linkedin_post_times: str = Form(default="09:00,12:00,17:00"),
    facebook_post_times: str = Form(default="10:00,14:00,19:00"),
    instagram_post_times: str = Form(default="08:00,13:00,18:00"),
):
    env_path = Path(__file__).parent.parent / ".env"
    lines = env_path.read_text().splitlines()

    updates = {
        "COMPANY_NAME": company_name,
        "BRAND_KEYWORDS": brand_keywords,
        "AI_PRIMARY_PROVIDER": ai_primary_provider,
        "ANTHROPIC_MODEL": anthropic_model,
        "OPENAI_COMPATIBLE_MODEL": openai_compatible_model,
        "OPENAI_COMPATIBLE_BASE_URL": openai_compatible_base_url,
        "MONITOR_INTERVAL_MINUTES": str(monitor_interval_minutes),
        "LINKEDIN_POST_TIMES": linkedin_post_times,
        "FACEBOOK_POST_TIMES": facebook_post_times,
        "INSTAGRAM_POST_TIMES": instagram_post_times,
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


if __name__ == "__main__":
    uvicorn.run("dashboard.main:app", host=settings.dashboard_host, port=settings.dashboard_port, reload=True)

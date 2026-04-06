"""
Dashboard FastAPI — Approvazione umana dei post e delle risposte ai commenti.
"""
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from pathlib import Path
import uvicorn

import re
import httpx
from fastapi.responses import JSONResponse
from config.settings import settings
from models.post import Base, Post, Comment, PostStatus, Platform
from models.context import CompanyContext, ContextWebsite
import json
from models.competitor import Competitor, CompetitorSocial, CompetitorObservation, CompetitorAnalysis

engine = create_engine(settings.database_url)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

app = FastAPI(title="Social Media Manager — Dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    pending_posts = db.query(Post).filter(Post.status == PostStatus.PENDING).order_by(Post.created_at.desc()).all()
    pending_replies = db.query(Comment).filter(Comment.reply_status == PostStatus.PENDING).order_by(Comment.created_at.desc()).all()
    return templates.TemplateResponse("index.html", {
        "request": request,
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
    return templates.TemplateResponse("analytics.html", {"request": request, "posts": published})


@app.get("/context", response_class=HTMLResponse)
async def context_page(request: Request, db: Session = Depends(get_db)):
    ctx = db.query(CompanyContext).first()
    websites = db.query(ContextWebsite).filter(ContextWebsite.is_active == True).order_by(ContextWebsite.created_at.desc()).all()
    return templates.TemplateResponse("context.html", {
        "request": request,
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
    from datetime import datetime
    site = db.query(ContextWebsite).filter(ContextWebsite.id == site_id).first()
    if not site:
        return RedirectResponse("/context", status_code=303)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(site.url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            # Estrae testo grezzo rimuovendo tag HTML con regex minimale
            text = re.sub(r"<style[^>]*>.*?</style>", " ", resp.text, flags=re.DOTALL)
            text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            site.scraped_content = text[:8000]  # max 8k caratteri
            site.last_scraped_at = datetime.utcnow()
            db.commit()
    except Exception:
        pass
    return RedirectResponse("/context", status_code=303)


# ── Competitor Analysis ────────────────────────────────────────────────────────

@app.get("/competitors/analysis", response_class=HTMLResponse)
async def analysis_page(request: Request, db: Session = Depends(get_db)):
    analyses = db.query(CompetitorAnalysis).order_by(CompetitorAnalysis.created_at.desc()).all()
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

    return templates.TemplateResponse("competitor_analysis.html", {
        "request": request,
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
        raw_response=json.dumps(result, ensure_ascii=False)[:10000],
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
    return templates.TemplateResponse("competitors.html", {
        "request": request,
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
    from datetime import datetime
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if not c or not c.website:
        return RedirectResponse(f"/competitors?sel={cid}", status_code=303)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(c.website, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            text = re.sub(r"<style[^>]*>.*?</style>", " ", resp.text, flags=re.DOTALL)
            text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            c.scraped_content = text[:8000]
            c.last_scraped_at = datetime.utcnow()
            db.commit()
    except Exception:
        pass
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
        "scraped_content": c.scraped_content[:500] if c.scraped_content else "",
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
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings,
        "saved": request.query_params.get("saved", False),
    })


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

    new_lines = []
    updated_keys = set()
    for line in lines:
        key = line.split("=")[0].strip()
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

"""
Orchestrator
Coordinatore centrale che gestisce il ciclo di vita degli agenti e dei task schedulati.
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from rich.console import Console
from rich.table import Table
from datetime import datetime

from config.settings import settings
from models.post import Base, Platform, Post, PostStatus, Comment
from agents.monitor import MonitorAgent
from agents.reply_agent import ReplyAgent
from agents.analytics import AnalyticsAgent
from agents.content_generator import ContentGeneratorAgent

console = Console()


class Orchestrator:
    def __init__(self):
        engine = create_engine(settings.database_url)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.scheduler = BackgroundScheduler()
        self.content_agent = ContentGeneratorAgent()
        self.analytics_agent = AnalyticsAgent()

    def start(self):
        """Avvia tutti i job schedulati."""
        # Monitoring ogni N minuti
        self.scheduler.add_job(
            self._run_monitor,
            IntervalTrigger(minutes=settings.monitor_interval_minutes),
            id="monitor",
            replace_existing=True,
        )

        # Analytics ogni ora
        self.scheduler.add_job(
            self._run_analytics,
            IntervalTrigger(hours=1),
            id="analytics",
            replace_existing=True,
        )

        # Reply drafts ogni 30 minuti
        self.scheduler.add_job(
            self._run_reply_drafts,
            IntervalTrigger(minutes=30),
            id="reply_drafts",
            replace_existing=True,
        )

        self.scheduler.start()
        console.print("[green]Orchestrator avviato.[/green] Premi Ctrl+C per fermare.")

        try:
            import time
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            self.scheduler.shutdown()
            console.print("[yellow]Orchestrator fermato.[/yellow]")

    def generate_post(
        self,
        topic: str,
        platforms: list[Platform] | None = None,
        tone: str = "professionale",
    ) -> list[Post]:
        """Genera post per le piattaforme specificate e li mette in stato PENDING."""
        platforms = platforms or [Platform.LINKEDIN, Platform.FACEBOOK, Platform.INSTAGRAM]
        session = self.Session()
        created = []

        for platform in platforms:
            result = self.content_agent.generate(topic=topic, platform=platform, tone=tone)
            post = Post(
                platform=platform,
                status=PostStatus.PENDING,
                content=result["content"],
                hashtags=result["hashtags"],
                topic=topic,
                tone=tone,
                generated_by=result["generated_by"],
            )
            session.add(post)
            session.commit()
            created.append(post)
            console.print(f"[blue]Post generato[/blue] per {platform.value} (ID: {post.id}) — in attesa di approvazione")

        session.close()
        return created

    def _run_monitor(self):
        session = self.Session()
        agent = MonitorAgent(db_session=session)
        results = agent.run_full_check()
        total = sum(len(v) for v in results.values() if isinstance(v, list))
        if total:
            console.print(f"[cyan][Monitor][/cyan] {total} nuove interazioni rilevate alle {datetime.now().strftime('%H:%M')}")
        session.close()

    def _run_reply_drafts(self):
        session = self.Session()
        agent = ReplyAgent(db_session=session)
        drafts = agent.generate_reply_drafts()
        if drafts:
            console.print(f"[cyan][ReplyAgent][/cyan] {len(drafts)} bozze generate — in attesa di approvazione")
        session.close()

    def _run_analytics(self):
        metrics = self.analytics_agent.collect_all()
        console.print(f"[cyan][Analytics][/cyan] Metriche aggiornate alle {datetime.now().strftime('%H:%M')}")
        return metrics

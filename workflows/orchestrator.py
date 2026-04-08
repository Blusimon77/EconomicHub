"""
Orchestrator
Coordinatore centrale che gestisce il ciclo di vita degli agenti e dei task schedulati.
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from pathlib import Path

from config.settings import settings
from config.logging import setup_logging, get_logger
from models.post import Base, Platform, Post, PostStatus, Comment
from agents.monitor import MonitorAgent
from agents.reply_agent import ReplyAgent
from agents.analytics import AnalyticsAgent
from agents.content_generator import ContentGeneratorAgent

setup_logging()
logger = get_logger("orchestrator")

_PID_FILE = Path(__file__).parent.parent / "storage" / "orchestrator.pid"


def _write_pid() -> None:
    import os
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def _remove_pid() -> None:
    try:
        _PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


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
        self.scheduler.add_job(
            self._run_monitor,
            IntervalTrigger(minutes=settings.monitor_interval_minutes),
            id="monitor",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self._run_analytics,
            IntervalTrigger(hours=1),
            id="analytics",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self._run_reply_drafts,
            IntervalTrigger(minutes=30),
            id="reply_drafts",
            replace_existing=True,
        )

        self.scheduler.start()
        _write_pid()
        logger.info("Orchestrator avviato (PID %s). Premi Ctrl+C per fermare.", _PID_FILE.read_text())

        try:
            import time
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            self.scheduler.shutdown()
            _remove_pid()
            logger.info("Orchestrator fermato.")

    def generate_post(
        self,
        topic: str,
        platforms: list[Platform] | None = None,
        tone: str = "professionale",
    ) -> list[Post]:
        """Genera post per le piattaforme specificate e li mette in stato PENDING."""
        platforms = platforms or [Platform.LINKEDIN, Platform.FACEBOOK, Platform.INSTAGRAM]
        created = []

        with self.Session() as session:
            for platform in platforms:
                try:
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
                    logger.info("Post generato per %s (ID: %s)", platform.value, post.id)
                except Exception:
                    session.rollback()
                    logger.exception("Errore generazione post per %s", platform.value)

        return created

    def _run_monitor(self):
        try:
            with self.Session() as session:
                agent = MonitorAgent(db_session=session)
                results = agent.run_full_check()
                total = sum(len(v) for v in results.values() if isinstance(v, list))
                if total:
                    logger.info("[Monitor] %d nuove interazioni rilevate", total)
        except Exception:
            logger.exception("[Monitor] Errore durante il check")

    def _run_reply_drafts(self):
        try:
            with self.Session() as session:
                agent = ReplyAgent(db_session=session)
                drafts = agent.generate_reply_drafts()
                if drafts:
                    logger.info("[ReplyAgent] %d bozze generate", len(drafts))
        except Exception:
            logger.exception("[ReplyAgent] Errore durante la generazione bozze")

    def _run_analytics(self):
        try:
            metrics = self.analytics_agent.collect_all()
            logger.info("[Analytics] Metriche aggiornate")
            return metrics
        except Exception:
            logger.exception("[Analytics] Errore durante la raccolta metriche")
            return {}

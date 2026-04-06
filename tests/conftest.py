"""
Fixtures condivise per i test.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from models.post import Base

_TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture()
def db_session():
    """Sessione DB in-memory per test isolati."""
    engine = create_engine(_TEST_DB_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def test_client():
    """Client HTTPX per testare le route FastAPI con DB in-memory."""
    engine = create_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    from dashboard.main import app, get_db

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    from httpx import AsyncClient, ASGITransport
    import asyncio

    class SyncTestClient:
        def __init__(self):
            self.transport = ASGITransport(app=app)

        def _run(self, coro):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        def get(self, path, **kwargs):
            async def _get():
                async with AsyncClient(transport=self.transport, base_url="http://test") as c:
                    return await c.get(path, **kwargs)
            return self._run(_get())

        def post(self, path, **kwargs):
            async def _post():
                async with AsyncClient(transport=self.transport, base_url="http://test") as c:
                    return await c.post(path, **kwargs)
            return self._run(_post())

    yield SyncTestClient()
    app.dependency_overrides.clear()

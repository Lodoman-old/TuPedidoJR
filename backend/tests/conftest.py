from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app

TEST_DATABASE_URL = settings.DATABASE_URL + "_test"

engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)


async def _ensure_test_database() -> None:
    """Create the test database on the server if it does not exist yet."""
    url = make_url(TEST_DATABASE_URL)
    admin_engine = create_async_engine(
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    await _ensure_test_database()
    async with engine.begin() as conn:
        # PostGIS types (geography) are required by the models.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM delivery_locations"))
        await conn.execute(text("DELETE FROM cash_advances"))
        await conn.execute(text("DELETE FROM order_items"))
        await conn.execute(text("UPDATE delivery_persons SET current_order_id = NULL"))
        await conn.execute(text("DELETE FROM orders"))
        await conn.execute(text("DELETE FROM delivery_payouts"))
        await conn.execute(text("DELETE FROM restaurant_payouts"))
        await conn.execute(text("DELETE FROM cash_advances"))
        await conn.execute(text("DELETE FROM mandados"))
        await conn.execute(text("DELETE FROM reservations"))
        await conn.execute(text("DELETE FROM delivery_persons"))
        await conn.execute(text("DELETE FROM menu_items"))
        await conn.execute(text("DELETE FROM menu_categories"))
        await conn.execute(text("DELETE FROM restaurant_schedules"))
        await conn.execute(text("DELETE FROM restaurants"))
        await conn.execute(text("DELETE FROM settings"))
        await conn.execute(text("DELETE FROM users"))


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

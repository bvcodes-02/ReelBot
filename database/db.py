from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine
)

from database.models import Base


# Locate the project root and ensure the data directory exists.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "reelbot.db"

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"


# Create the asynchronous database engine.
engine = create_async_engine(
    DATABASE_URL,
    echo=False
)


# Enable foreign-key enforcement in SQLite.
@event.listens_for(engine.sync_engine, "connect")
def enable_foreign_keys(dbapi_connection, connection_record):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


# Session factory.
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_db():
    await engine.dispose()


async def get_session():
    async with SessionLocal() as session:
        yield session

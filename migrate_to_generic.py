"""
migrate_to_generic.py
---------------------
One-time migration from the original single-guild schema to the
multi-guild schema.

Changes applied:
  movies    : imdb_id (PK, str) → tmdb_id (PK, int)
              imdb_rating       → tmdb_rating
  watchlist : imdb_id (FK, str) → tmdb_id (FK, int)
              adds guild_id column (BigInteger, NOT NULL)
  ratings   : imdb_id (FK, str) → tmdb_id (FK, int)
              adds guild_id column (BigInteger, NOT NULL)
              renames rating → score

Because the old data was keyed by IMDb IDs and cannot be automatically
mapped to TMDb IDs without an API call, the safest path is:

  1. Back up the existing database.
  2. Drop and recreate the tables with the new schema.
  3. Leave movies/ratings empty (they will repopulate as the bot is used).

If you have existing watchlist entries you want to preserve, run the
TMDb search for each movie manually, note the TMDb ID, and re-add them
via /watchlist_add.

Usage:
    python migrate_to_generic.py
"""

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from database.models import Base

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "reelbot.db"


async def migrate():
    if not DB_PATH.exists():
        print("No existing database found — nothing to migrate.")
        return

    # Back up before touching anything.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DATA_DIR / f"reelbot_pre_generic_{timestamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"Backed up existing database to: {backup_path}")

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{DB_PATH}",
        echo=False
    )

    async with engine.begin() as conn:
        # Drop old tables and recreate with the new schema.
        # This discards old IMDb-keyed data, which cannot be automatically
        # remapped to TMDb IDs.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()

    print("Migration complete.")
    print(
        "Old movie and watchlist data was cleared because it used IMDb IDs.\n"
        "Re-add movies via /watchlist_add using TMDb IDs from /search."
    )


if __name__ == "__main__":
    asyncio.run(migrate())

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Movie, Watchlist


async def add_to_watchlist(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    movie_data: dict,
    priority: str = "normal"
) -> str:
    """
    Add a movie to the calling guild's watchlist.

    movie_data must contain at least:
        tmdb_id  (int)   – TMDb movie ID
        title    (str)
    Optional keys: year, genre, director, plot, poster, tmdb_rating.

    Returns "added" or "exists".
    """

    tmdb_id = movie_data.get("tmdb_id")

    if not tmdb_id:
        raise ValueError("movie_data must include a valid tmdb_id")

    if priority not in ("low", "normal", "high"):
        raise ValueError("priority must be low, normal, or high")

    # Duplicate check is scoped to this guild.
    result = await session.execute(
        select(Watchlist).where(
            Watchlist.guild_id == guild_id,
            Watchlist.tmdb_id == tmdb_id
        )
    )

    if result.scalar_one_or_none() is not None:
        return "exists"

    # Reuse shared movie metadata when already cached.
    movie = await session.get(Movie, tmdb_id)

    if movie is None:
        tmdb_rating = movie_data.get("tmdb_rating")

        try:
            tmdb_rating = float(tmdb_rating)
        except (ValueError, TypeError):
            tmdb_rating = None

        movie = Movie(
            tmdb_id=tmdb_id,
            title=movie_data.get("title", "Unknown Title"),
            year=movie_data.get("year"),
            genre=movie_data.get("genre"),
            director=movie_data.get("director"),
            plot=movie_data.get("plot"),
            poster=movie_data.get("poster"),
            tmdb_rating=tmdb_rating
        )

        session.add(movie)

    entry = Watchlist(
        guild_id=guild_id,
        tmdb_id=tmdb_id,
        user_id=user_id,
        status="pending",
        priority=priority
    )

    session.add(entry)
    await session.commit()

    return "added"


async def get_watchlist(
    session: AsyncSession,
    guild_id: int
) -> list:
    """Return the guild's watchlist in FIFO order (oldest first)."""

    result = await session.execute(
        select(Watchlist, Movie)
        .join(Movie, Watchlist.tmdb_id == Movie.tmdb_id)
        .where(Watchlist.guild_id == guild_id)
        .order_by(
            Watchlist.added_at.asc(),
            Watchlist.id.asc()
        )
    )

    return result.all()


async def mark_as_watched(
    session: AsyncSession,
    guild_id: int,
    tmdb_id: int
) -> str:
    """Mark a movie as watched for the whole guild. Returns a status string."""

    result = await session.execute(
        select(Watchlist).where(
            Watchlist.guild_id == guild_id,
            Watchlist.tmdb_id == tmdb_id
        )
    )

    entry = result.scalar_one_or_none()

    if entry is None:
        return "not_found"

    if entry.status == "watched":
        return "already_watched"

    entry.status = "watched"
    await session.commit()

    return "updated"


async def remove_from_watchlist(
    session: AsyncSession,
    guild_id: int,
    tmdb_id: int
) -> str:
    """
    Remove a watchlist entry for this guild.
    The Movie metadata row is intentionally preserved.
    """

    result = await session.execute(
        select(Watchlist).where(
            Watchlist.guild_id == guild_id,
            Watchlist.tmdb_id == tmdb_id
        )
    )

    entry = result.scalar_one_or_none()

    if entry is None:
        return "not_found"

    await session.delete(entry)
    await session.commit()

    return "removed"


async def get_watchlisted_tmdb_ids(
    session: AsyncSession,
    guild_id: int
) -> set[int]:
    """
    Return the set of TMDb IDs currently in this guild's watchlist.
    Used by discovery to exclude already-listed movies.
    """

    result = await session.execute(
        select(Watchlist.tmdb_id).where(
            Watchlist.guild_id == guild_id
        )
    )

    return {row[0] for row in result.all()}

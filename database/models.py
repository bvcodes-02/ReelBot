from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
    BigInteger,
    Float,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint
)

from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship
)


class Base(DeclarativeBase):
    pass


class Movie(Base):
    """
    Canonical movie metadata, keyed by TMDb ID.
    Shared across all guilds – never deleted when a watchlist entry is removed.
    """

    __tablename__ = "movies"

    tmdb_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    year: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True
    )

    genre: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    director: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    plot: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True
    )

    poster: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    tmdb_rating: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )

    # Relationships — no cascade delete so movie metadata survives watchlist removal.
    watchlist_entries: Mapped[list["Watchlist"]] = relationship(
        back_populates="movie",
        cascade="save-update, merge"
    )

    ratings: Mapped[list["Rating"]] = relationship(
        back_populates="movie",
        cascade="save-update, merge"
    )


class Watchlist(Base):
    """
    One entry per (guild, movie). Each guild maintains its own independent watchlist.
    Records which user added the entry and their chosen priority.
    """

    __tablename__ = "watchlist"

    __table_args__ = (
        # A movie can appear only once per guild.
        UniqueConstraint(
            "guild_id",
            "tmdb_id",
            name="uq_watchlist_guild_movie"
        ),
        CheckConstraint(
            "status IN ('pending', 'watched')",
            name="ck_watchlist_status"
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high')",
            name="ck_watchlist_priority"
        )
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True
    )

    tmdb_id: Mapped[int] = mapped_column(
        ForeignKey("movies.tmdb_id"),
        nullable=False
    )

    # Discord user ID of the person who added this entry.
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False
    )

    priority: Mapped[str] = mapped_column(
        String(20),
        default="normal",
        nullable=False
    )

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    movie: Mapped["Movie"] = relationship(
        back_populates="watchlist_entries"
    )


class Rating(Base):
    """
    One rating per (guild, user, movie).
    Ratings are per-guild so the same movie can be rated independently in each server.
    """

    __tablename__ = "ratings"

    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "tmdb_id",
            "user_id",
            name="uq_rating_guild_movie_user"
        ),
        CheckConstraint(
            "score >= 1 AND score <= 10",
            name="ck_rating_range"
        )
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True
    )

    tmdb_id: Mapped[int] = mapped_column(
        ForeignKey("movies.tmdb_id"),
        nullable=False
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )

    score: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    rated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    movie: Mapped["Movie"] = relationship(
        back_populates="ratings"
    )

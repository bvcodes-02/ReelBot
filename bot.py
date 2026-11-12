"""
ReelBot — a Discord movie watchlist companion.

Designed to work in any server: each guild has its own independent
watchlist, ratings, and history. No hardcoded guild IDs.
"""

import os

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

from services.tmdb import tmdb, TMDbService
from services.watchlist import (
    add_to_watchlist,
    get_watchlist,
    mark_as_watched,
    remove_from_watchlist,
    get_watchlisted_tmdb_ids,
)
from database.db import init_db, close_db, SessionLocal


# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")


# --------------------------------------------------
# Bot setup
# --------------------------------------------------

class ReelBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()

        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):
        await init_db()
        print("Database initialised.")

        # Register slash commands globally so they work in every server.
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} global slash commands.")

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        print("ReelBot is ready! 🎬")

    async def close(self):
        await super().close()
        await close_db()
        print("Database connection closed.")


bot = ReelBot()


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def _require_guild(interaction: discord.Interaction) -> int | None:
    """
    Return the guild ID or send an ephemeral error and return None.
    All watchlist operations require a guild context.
    """
    if interaction.guild_id is None:
        return None
    return interaction.guild_id


def _tmdb_movie_to_dict(data: dict) -> dict:
    """
    Normalise a TMDb movie object (from search or details) into the
    flat dict that add_to_watchlist expects.
    """
    genres = data.get("genres")  # present in detail responses
    genre_names = (
        ", ".join(g["name"] for g in genres)
        if genres
        else None
    )

    # Director is only available in a credits append — omit for now.
    return {
        "tmdb_id": data.get("id"),
        "title": data.get("title", "Unknown Title"),
        "year": (data.get("release_date") or "")[:4] or None,
        "genre": genre_names,
        "plot": data.get("overview"),
        "poster": TMDbService.get_poster_url(data.get("poster_path")),
        "tmdb_rating": data.get("vote_average"),
    }


def _search_result_embed(movie: dict, index: int, total: int) -> discord.Embed:
    """Build a Discord embed for a TMDb search result."""

    title = movie.get("title", "Unknown Title")
    year = (movie.get("release_date") or "")[:4] or "Unknown"
    overview = movie.get("overview") or "No overview available."
    vote = movie.get("vote_average")
    tmdb_id = movie.get("id")

    embed = discord.Embed(
        title=f"{title} ({year})",
        description=overview[:300] + ("…" if len(overview) > 300 else ""),
        color=discord.Color.dark_purple()
    )

    embed.add_field(name="TMDb ID", value=str(tmdb_id) or "N/A", inline=True)

    if vote:
        embed.add_field(name="TMDb Rating", value=f"⭐ {vote:.1f}/10", inline=True)

    poster_url = TMDbService.get_poster_url(movie.get("poster_path"))

    if poster_url:
        embed.set_thumbnail(url=poster_url)

    embed.set_footer(text=f"Result {index + 1} of {total} · Powered by TMDb")

    return embed


# --------------------------------------------------
# Search navigation view
# --------------------------------------------------

class MovieSearchView(discord.ui.View):

    def __init__(self, movies: list):
        super().__init__(timeout=180)
        self.movies = movies
        self.index = 0
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.movies) - 1

    async def _update(self, interaction: discord.Interaction):
        self._refresh_buttons()
        embed = _search_result_embed(
            self.movies[self.index],
            self.index,
            len(self.movies)
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        await self._update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        await self._update(interaction)


# --------------------------------------------------
# Slash commands
# --------------------------------------------------

@bot.tree.command(
    name="ping",
    description="Check whether ReelBot is alive"
)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! 🍿 ReelBot is online!")


@bot.tree.command(
    name="hello",
    description="Say hello to ReelBot"
)
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Hey {interaction.user.mention}! Ready for movie night? 🎬"
    )


@bot.tree.command(
    name="search",
    description="Search for a movie on TMDb"
)
@app_commands.describe(title="The movie title to search for")
async def search(interaction: discord.Interaction, title: str):
    await interaction.response.defer()

    data, error = await tmdb.search_movies(title)

    if error:
        await interaction.followup.send(f"❌ Search failed: {error}", ephemeral=True)
        return

    movies = data.get("results", [])

    if not movies:
        await interaction.followup.send(
            "🎬 No movies found. Try a different title!",
            ephemeral=True
        )
        return

    view = MovieSearchView(movies)
    embed = _search_result_embed(movies[0], 0, len(movies))

    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(
    name="watchlist_add",
    description="Add a movie to this server's watchlist"
)
@app_commands.describe(
    tmdb_id="TMDb movie ID (shown in /search results)",
    priority="Priority level for this movie (default: normal)"
)
@app_commands.choices(priority=[
    app_commands.Choice(name="Low", value="low"),
    app_commands.Choice(name="Normal", value="normal"),
    app_commands.Choice(name="High", value="high"),
])
async def watchlist_add(
    interaction: discord.Interaction,
    tmdb_id: int,
    priority: app_commands.Choice[str] = None
):
    guild_id = _require_guild(interaction)

    if guild_id is None:
        await interaction.response.send_message(
            "❌ This command must be used inside a server.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    chosen_priority = priority.value if priority else "normal"

    movie_data, error = await tmdb.get_movie(tmdb_id)

    if error or not movie_data:
        await interaction.followup.send(
            f"❌ Couldn't fetch that movie: {error or 'Unknown error'}",
            ephemeral=True
        )
        return

    normalized = _tmdb_movie_to_dict(movie_data)

    try:
        async with SessionLocal() as session:
            result = await add_to_watchlist(
                session=session,
                guild_id=guild_id,
                user_id=interaction.user.id,
                movie_data=normalized,
                priority=chosen_priority
            )

        if result == "added":
            await interaction.followup.send(
                f"🍿 **{normalized['title']}** ({normalized['year'] or '?'}) "
                f"added to the watchlist by {interaction.user.mention}! "
                f"Priority: **{chosen_priority}**",
                ephemeral=True
            )
        elif result == "exists":
            await interaction.followup.send(
                "🎬 This movie is already on the watchlist!",
                ephemeral=True
            )

    except Exception as exc:
        print(f"watchlist_add error: {exc}")
        await interaction.followup.send(
            "❌ Something went wrong while adding the movie.",
            ephemeral=True
        )


@bot.tree.command(
    name="watchlist",
    description="View this server's movie watchlist"
)
async def watchlist(interaction: discord.Interaction):
    guild_id = _require_guild(interaction)

    if guild_id is None:
        await interaction.response.send_message(
            "❌ This command must be used inside a server.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        async with SessionLocal() as session:
            entries = await get_watchlist(session, guild_id)
    except Exception as exc:
        print(f"watchlist error: {exc}")
        await interaction.followup.send(
            "❌ Couldn't load the watchlist.",
            ephemeral=True
        )
        return

    if not entries:
        await interaction.followup.send(
            "🎬 The watchlist is empty! Add a movie with `/watchlist_add`."
        )
        return

    embed = discord.Embed(
        title="🍿 Server Watchlist",
        description=(
            f"**{len(entries)} movie{'s' if len(entries) != 1 else ''}** · "
            "Ordered oldest first."
        ),
        color=discord.Color.dark_purple()
    )

    priority_icon = {"high": "🔴", "normal": "🟡", "low": "🟢"}

    for i, (entry, movie) in enumerate(entries[:10], start=1):
        status = "✅ Watched" if entry.status == "watched" else "⏳ Pending"
        picon = priority_icon.get(entry.priority, "🟡")

        embed.add_field(
            name=f"{i}. {movie.title} ({movie.year or '?'})",
            value=(
                f"**Status:** {status}\n"
                f"**Priority:** {picon} {entry.priority.title()}\n"
                f"**Added by:** <@{entry.user_id}>\n"
                f"**TMDb ID:** `{movie.tmdb_id}`"
            ),
            inline=False
        )

    first_movie = entries[0][1]
    if first_movie.poster:
        embed.set_thumbnail(url=first_movie.poster)

    embed.set_footer(
        text=f"Showing {min(len(entries), 10)} of {len(entries)}"
    )

    await interaction.followup.send(
        embed=embed,
        allowed_mentions=discord.AllowedMentions.none()
    )


@bot.tree.command(
    name="watched",
    description="Mark a movie as watched for this server"
)
@app_commands.describe(tmdb_id="TMDb ID of the movie to mark as watched")
async def watched(interaction: discord.Interaction, tmdb_id: int):
    guild_id = _require_guild(interaction)

    if guild_id is None:
        await interaction.response.send_message(
            "❌ This command must be used inside a server.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        async with SessionLocal() as session:
            result = await mark_as_watched(
                session=session,
                guild_id=guild_id,
                tmdb_id=tmdb_id
            )
    except Exception as exc:
        print(f"watched error: {exc}")
        await interaction.followup.send(
            "❌ Couldn't update the movie status.",
            ephemeral=True
        )
        return

    if result == "updated":
        await interaction.followup.send(
            f"✅ TMDb `{tmdb_id}` marked as watched for this server!"
        )
    elif result == "already_watched":
        await interaction.followup.send(
            "🎬 That movie is already marked as watched.",
            ephemeral=True
        )
    elif result == "not_found":
        await interaction.followup.send(
            "❌ That movie isn't on this server's watchlist.",
            ephemeral=True
        )


@bot.tree.command(
    name="watchlist_remove",
    description="Remove a movie from this server's watchlist"
)
@app_commands.describe(tmdb_id="TMDb ID of the movie to remove")
async def watchlist_remove(interaction: discord.Interaction, tmdb_id: int):
    guild_id = _require_guild(interaction)

    if guild_id is None:
        await interaction.response.send_message(
            "❌ This command must be used inside a server.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        async with SessionLocal() as session:
            result = await remove_from_watchlist(
                session=session,
                guild_id=guild_id,
                tmdb_id=tmdb_id
            )
    except Exception as exc:
        print(f"watchlist_remove error: {exc}")
        await interaction.followup.send(
            "❌ Something went wrong while removing the movie.",
            ephemeral=True
        )
        return

    if result == "removed":
        await interaction.followup.send(
            f"🗑️ TMDb `{tmdb_id}` removed from the watchlist.",
            ephemeral=True
        )
    elif result == "not_found":
        await interaction.followup.send(
            "❌ That movie isn't on this server's watchlist.",
            ephemeral=True
        )

@bot.tree.command(
    name="sync",
    description="Sync slash commands (owner only)"
)
async def sync(interaction: discord.Interaction):
    if interaction.user.id != (await bot.application_info()).owner.id:
        await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    synced = await bot.tree.sync()
    await interaction.followup.send(f"✅ Synced {len(synced)} commands.", ephemeral=True)

# --------------------------------------------------
# Run bot
# --------------------------------------------------

bot.run(TOKEN)

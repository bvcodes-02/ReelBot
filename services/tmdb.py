import os
import random
import ssl

import aiohttp
from dotenv import load_dotenv


load_dotenv()

TMDB_HOST = "api.themoviedb.org"
BASE_URL = f"https://{TMDB_HOST}/3"

# Optional: set TMDB_FORCE_IP in .env to bypass DNS when your ISP/hotspot
# cannot resolve api.themoviedb.org. Find a current CloudFront IP with:
#   nslookup api.themoviedb.org 8.8.8.8
# Leave blank or unset to use normal DNS (recommended when DNS works).
_FORCE_IP = os.getenv("TMDB_FORCE_IP", "").strip()


def _make_connector() -> aiohttp.TCPConnector | None:
    """
    Return a TCPConnector that routes all requests to TMDB_FORCE_IP when set,
    keeping the correct Host header and TLS SNI so the certificate validates.
    Returns None when no override is configured (normal DNS path).
    """
    if not _FORCE_IP:
        return None

    # Resolve the hostname to the forced IP while keeping SNI intact.
    class _ForcedResolver(aiohttp.abc.AbstractResolver):
        async def resolve(self, host: str, port: int, family: int):
            return [
                {
                    "hostname": host,
                    "host": _FORCE_IP,
                    "port": port,
                    "family": family,
                    "proto": 0,
                    "flags": 0,
                }
            ]

        async def close(self):
            pass

    ssl_ctx = ssl.create_default_context()
    return aiohttp.TCPConnector(
        resolver=_ForcedResolver(),
        ssl=ssl_ctx
    )


class TMDbService:

    def __init__(self):
        self.access_token = os.getenv("TMDB_ACCESS_TOKEN")
        self.api_key = os.getenv("TMDB_API_KEY")

        if not self.access_token and not self.api_key:
            raise RuntimeError(
                "TMDB_ACCESS_TOKEN or TMDB_API_KEY is missing from .env"
            )

        if _FORCE_IP:
            print(
                f"[TMDb] DNS override active: "
                f"{TMDB_HOST} → {_FORCE_IP}"
            )

    async def _request(self, endpoint: str, params: dict = None):
        """Make an authenticated request to TMDb."""

        request_params = dict(params or {})

        headers = {
            "Accept": "application/json",
            "Host": TMDB_HOST,
        }

        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        else:
            request_params["api_key"] = self.api_key

        timeout = aiohttp.ClientTimeout(total=20)
        connector = _make_connector()

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            ) as session:

                async with session.get(
                    f"{BASE_URL}/{endpoint.lstrip('/')}",
                    params=request_params,
                    headers=headers
                ) as response:

                    data = await response.json(
                        content_type=None
                    )

                    if response.status >= 400:
                        message = data.get(
                            "status_message",
                            f"TMDb returned HTTP {response.status}"
                        )
                        return None, message

                    return data, None

        except aiohttp.ClientError as error:
            return None, f"Network error: {error}"

        except TimeoutError:
            return None, "TMDb request timed out."

        except ValueError:
            return None, "TMDb returned an invalid response."

    async def search_movies(
        self,
        query: str,
        page: int = 1,
        language: str = "en-US"
    ):
        """Search movies by title."""

        return await self._request(
            "search/movie",
            {
                "query": query,
                "page": page,
                "language": language,
                "include_adult": "false"
            }
        )

    async def get_movie(
        self,
        movie_id: int,
        language: str = "en-US"
    ):
        """Retrieve detailed information about a movie."""

        return await self._request(
            f"movie/{movie_id}",
            {
                "language": language
            }
        )

    async def get_genres(
        self,
        language: str = "en-US"
    ):
        """Retrieve the available movie genres."""

        data, error = await self._request(
            "genre/movie/list",
            {
                "language": language
            }
        )

        if error:
            return None, error

        return data.get("genres", []), None

    async def get_languages(self):
        """Retrieve TMDb's supported language list."""

        data, error = await self._request(
            "configuration/languages"
        )

        if error:
            return None, error

        return data, None

    async def discover_movies(
        self,
        genre_id: int,
        original_language: str = None,
        page: int = 1,
        language: str = "en-US"
    ):
        """Discover movies using genre and original-language filters."""

        params = {
            "with_genres": genre_id,
            "page": page,
            "language": language,
            "include_adult": "false",
            "sort_by": "popularity.desc"
        }

        if original_language:
            params["with_original_language"] = original_language

        return await self._request(
            "discover/movie",
            params
        )

    async def discover_random_movie(
        self,
        genre_id: int,
        original_language: str = None,
        exclude_tmdb_ids: set[int] = None
    ):
        """
        Choose a random movie matching the supplied filters,
        skipping any IDs in exclude_tmdb_ids (e.g. already on the watchlist).
        """

        exclude = exclude_tmdb_ids or set()

        first_page, error = await self.discover_movies(
            genre_id=genre_id,
            original_language=original_language,
            page=1
        )

        if error:
            return None, error

        results = first_page.get("results", [])
        total_pages = min(first_page.get("total_pages", 0), 500)

        if not results or total_pages == 0:
            return None, "No movies found for those filters."

        # Try up to 5 random pages to find a movie not on the watchlist.
        pages_to_try = random.sample(
            range(1, total_pages + 1),
            min(5, total_pages)
        )

        for page_num in pages_to_try:
            if page_num == 1:
                candidates = results
            else:
                page_data, error = await self.discover_movies(
                    genre_id=genre_id,
                    original_language=original_language,
                    page=page_num
                )

                if error:
                    continue

                candidates = page_data.get("results", [])

            # Filter out already-listed movies.
            candidates = [
                m for m in candidates
                if m.get("id") not in exclude
            ]

            if candidates:
                return random.choice(candidates), None

        return None, "No new movies found — everything matching is already on your watchlist!"

    @staticmethod
    def get_poster_url(
        poster_path: str,
        size: str = "w500"
    ):
        """Convert a TMDb poster path into a full image URL."""

        if not poster_path:
            return None

        return f"https://image.tmdb.org/t/p/{size}{poster_path}"


tmdb = TMDbService()
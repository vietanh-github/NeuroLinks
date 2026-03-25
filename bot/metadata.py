"""Async metadata extractor for URLs.

Fetches page <title>, og:title, og:description, og:image.
Never raises — always returns a dict (may be empty on error).
"""

import asyncio
import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; NeuroLinksBot/1.0; "
        "+https://linva.net/NeuroLinks)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT = 8.0       # seconds
MAX_BYTES = 200_000  # read at most ~200 KB (enough for <head>)


def _parse(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    def og(prop: str) -> str:
        tag = soup.find("meta", property=f"og:{prop}")
        if tag and tag.get("content"):
            return tag["content"].strip()[:300]
        return ""

    def meta_name(name: str) -> str:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()[:300]
        return ""

    title = (
        og("title")
        or (soup.title.get_text(strip=True)[:200] if soup.title else "")
        or meta_name("title")
    )
    description = og("description") or meta_name("description")
    og_image    = og("image")

    return {
        "title":       title,
        "description": description,
        "og_image":    og_image,
    }


async def fetch_metadata(url: str) -> dict[str, Any]:
    """Fetch <title> / OG metadata for *url*.

    Returns dict with keys: title, description, og_image.
    All values are strings (may be empty). Never raises.
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=TIMEOUT,
            headers=HEADERS,
        ) as client:
            async with client.stream("GET", url) as resp:
                # Only process HTML responses
                ct = resp.headers.get("content-type", "")
                if "html" not in ct:
                    return {}
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_BYTES:
                        break
                html = b"".join(chunks).decode("utf-8", errors="replace")
        return _parse(html)
    except Exception as exc:
        logger.debug("metadata fetch failed for %s: %s", url, exc)
        return {}

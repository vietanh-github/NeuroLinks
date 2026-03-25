"""AI-powered tag generator for NeuroLinks.

Calls the custom AI API to suggest 1–3 category tags for a given URL.
Accepts existing tags so the AI harmonises new tags with the current vocabulary.
Never raises — returns [] on any error.
"""

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

AI_API_URL = "https://ai.cuti.uk/v1/chat/completions"
AI_MODEL   = "codex/gpt-5-codex-mini"
AI_TIMEOUT = 60.0  # seconds


def _api_key() -> str:
    return os.getenv("AI_TAGGER_API_KEY", "")


def _build_messages(
    url: str,
    title: str,
    description: str,
    existing_tags: list[str],
) -> list[dict[str, str]]:
    context_parts = [f"URL: {url}"]
    if title:       context_parts.append(f"Title: {title}")
    if description: context_parts.append(f"Description: {description}")
    context = "\n".join(context_parts)

    # Build system prompt — include existing tag vocabulary when available
    tag_hint = ""
    if existing_tags:
        vocab = ", ".join(f'"{t}"' for t in existing_tags[:60])  # cap at 60 tags
        tag_hint = (
            f"\n\nExisting tags already in use: [{vocab}]. "
            "PREFER reusing one of these tags if it fits. "
            "Only invent a NEW tag if none of the existing ones match well. "
            "Never create a tag that is a near-duplicate of an existing tag (e.g. 'AI' vs 'Artificial Intelligence')."
        )

    return [
        {
            "role": "system",
            "content": (
                "You are a content categorization assistant. "
                "Given a URL with its title and description, respond ONLY with a valid JSON array "
                "of 1 to 3 short category tags in English (e.g. [\"AI\", \"Research\"]). "
                "No explanations. No markdown. Just the JSON array."
                + tag_hint
            ),
        },
        {
            "role": "user",
            "content": context,
        },
    ]


async def ai_generate_tags(
    url: str,
    title: str = "",
    description: str = "",
    existing_tags: list[str] | None = None,
) -> list[str]:
    """Return 1–3 AI-suggested tags. Returns [] silently on any error.

    Pass existing_tags (from firebase_client.get_all_ai_tags()) so the AI
    harmonises new tags with the existing vocabulary.
    """
    api_key = _api_key()
    if not api_key:
        logger.warning("AI_TAGGER_API_KEY not set — skipping AI tagging")
        return []

    messages = _build_messages(url, title, description, existing_tags or [])
    payload: dict[str, Any] = {
        "model":    AI_MODEL,
        "messages": messages,
        "stream":   False,
    }

    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT) as client:
            resp = await client.post(
                AI_API_URL,
                json=payload,
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )

        if resp.status_code == 401:
            logger.warning("🔑 AI tagger: 401 Unauthorized — API key sai hoặc hết hạn")
            return []
        if resp.status_code == 400:
            logger.warning("⚠️  AI tagger: 400 Bad Request — %s", resp.text[:200])
            return []
        if resp.status_code != 200:
            logger.warning("⚠️  AI tagger: HTTP %s — %s", resp.status_code, resp.text[:200])
            return []

        data = resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        tags = json.loads(raw)
        if isinstance(tags, list):
            return [str(t).strip()[:40] for t in tags[:3] if str(t).strip()]
        return []

    except httpx.TimeoutException:
        logger.warning("⏱️  AI tagger: Timeout sau %ss — bỏ qua", AI_TIMEOUT)
        return []
    except Exception as exc:
        logger.debug("AI tagger error for %s: %s", url, exc)
        return []

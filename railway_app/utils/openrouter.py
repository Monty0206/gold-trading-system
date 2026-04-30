import json
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = "https://openrouter.ai/api/v1"
HEADERS_BASE = {
    "HTTP-Referer": "https://gold-session-sniper.railway.app",
    "X-Title": "Gold Session Sniper v2.0",
}


def _extract_json(content: str) -> dict:
    """Extract JSON from model response, stripping think tags and markdown fences."""
    # Strip DeepSeek R1 <think>...</think> reasoning tokens
    content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()

    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try JSON inside ```json ... ``` or ``` ... ``` fences
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try to find outermost { ... } block
    brace_match = re.search(r"\{[\s\S]*\}", content)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Could not parse JSON from model response. First 400 chars:\n{content[:400]}"
    )


def _build_headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        **HEADERS_BASE,
    }


async def call_openrouter(
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> dict:
    """Call OpenRouter and return a parsed JSON dict."""
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{BASE_URL}/chat/completions",
            headers=_build_headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    return _extract_json(content)


async def get_credits_info() -> dict:
    """
    Fetch API key usage from GET /api/v1/auth/key.
    Returns usage_total (lifetime USD spent on this key), credits_remaining
    (limit - usage if a key-level spending cap is set, else None), and limit.
    Call twice — before and after a session — and diff usage_total to get exact cost.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{BASE_URL}/auth/key",
                headers=_build_headers(),
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})

        usage = float(data.get("usage") or 0)
        limit = data.get("limit")
        credits_remaining = (float(limit) - usage) if limit is not None else None

        return {
            "usage_total": usage,
            "limit": float(limit) if limit is not None else None,
            "credits_remaining": credits_remaining,
            "is_free_tier": bool(data.get("is_free_tier", False)),
            "error": None,
        }
    except Exception as e:
        return {
            "usage_total": 0.0,
            "limit": None,
            "credits_remaining": None,
            "is_free_tier": False,
            "error": str(e),
        }


async def call_openrouter_text(
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """Call OpenRouter and return raw text (used for Bull/Bear debate arguments)."""
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{BASE_URL}/chat/completions",
            headers=_build_headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"]

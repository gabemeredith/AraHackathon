"""Thin Sendblue HTTP client + webhook signature verification."""

import hmac
import os

import httpx

SENDBLUE_SEND_URL = "https://api.sendblue.co/api/send-message"


async def send_message(to: str, body: str) -> dict:
    """POST to Sendblue. Raises httpx.HTTPStatusError on non-2xx."""
    headers = {
        "sb-api-key-id": os.environ["SENDBLUE_API_KEY_ID"],
        "sb-api-secret-key": os.environ["SENDBLUE_API_SECRET"],
        "content-type": "application/json",
    }
    payload = {
        "number": to,
        "from_number": os.environ["SENDBLUE_FROM_NUMBER"],
        "content": body,
        "send_style": "",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(SENDBLUE_SEND_URL, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()


def verify_signature(header_value: str | None) -> bool:
    """Constant-time compare of the sb-signing-secret header against SB_SECRET."""
    expected = os.environ.get("SB_SECRET", "")
    if not expected or not header_value:
        return False
    return hmac.compare_digest(expected, header_value)

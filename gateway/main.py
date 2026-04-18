"""Sendblue gateway.

Owns inbound webhook, outbound send, and the in-process session store.
"""

import hmac
import logging
import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

from .sendblue import send_message, verify_signature
from .store import store

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gateway")

app = FastAPI()


def _require_gateway_key(x_gateway_key: str | None) -> None:
    expected = os.environ.get("GATEWAY_KEY", "")
    if not expected or not x_gateway_key or not hmac.compare_digest(expected, x_gateway_key):
        raise HTTPException(401, "bad gateway key")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/sessions")
async def create_session(req: Request, x_gateway_key: str | None = Header(default=None)) -> dict:
    _require_gateway_key(x_gateway_key)
    body = await req.json()
    session_id = store.create_session(
        initiator=body["initiator"],
        participants=body["participants"],
        duration_min=body["duration_min"],
        window=body["window"],
    )
    return {"session_id": session_id}


@app.post("/send")
async def send(req: Request, x_gateway_key: str | None = Header(default=None)) -> dict:
    _require_gateway_key(x_gateway_key)
    body = await req.json()
    to = body["to"]
    content = body["body"]
    try:
        result = await send_message(to, content)
    except httpx.HTTPStatusError as e:
        log.warning("sendblue rejected: %s %s", e.response.status_code, e.response.text)
        raise HTTPException(502, f"sendblue error: {e.response.status_code}")
    except httpx.TimeoutException:
        log.warning("sendblue timed out")
        raise HTTPException(504, "sendblue timeout")
    except httpx.RequestError as e:
        log.warning("sendblue request error: %s", e)
        raise HTTPException(502, "sendblue unreachable")
    return {"message_handle": result.get("message_handle"), "status": result.get("status")}


@app.post("/sendblue/inbound")
async def sendblue_inbound(
    req: Request, sb_signing_secret: str | None = Header(default=None)
) -> dict:
    if not verify_signature(sb_signing_secret):
        raise HTTPException(401, "bad signature")
    payload = await req.json()

    if payload.get("is_outbound") or payload.get("opted_out") or payload.get("group_id"):
        return {"ok": True, "deduped": False, "skipped": True}

    if payload.get("service") != "iMessage" or payload.get("was_downgraded"):
        log.warning(
            "non-iMessage inbound: service=%s downgraded=%s from=%s",
            payload.get("service"),
            payload.get("was_downgraded"),
            payload.get("from_number"),
        )

    from_number = payload["from_number"]
    session_id = store.session_id_for_handle(from_number)
    if session_id is None:
        log.info("unknown sender %s; dropping", from_number)
        return {"ok": True, "deduped": False}

    appended = store.append_inbound(
        session_id,
        payload["message_handle"],
        from_number,
        payload["content"],
        payload["date_sent"],
    )
    return {"ok": True, "deduped": not appended}


@app.get("/inbound")
async def get_inbound(session_id: str, since: str | None = None) -> list[dict]:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(404, "unknown session")
    msgs = session["inbound"]
    if since:
        msgs = [m for m in msgs if m["ts"] > since]
    return msgs

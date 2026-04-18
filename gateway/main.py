"""Twilio gateway.

Owns: inbound SMS webhook, outbound SMS send, shared-store R/W.
See docs/gateway.md for the full implementation brief.
"""

import os
from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from twilio.rest import Client as TwilioClient

from .store import Store

app = FastAPI()
store = Store(url=os.environ["STORE_URL"], token=os.environ["STORE_TOKEN"])

twilio = TwilioClient(os.environ["TWILIO_SID"], os.environ["TWILIO_TOKEN"])
TWILIO_FROM = os.environ["TWILIO_FROM"]
GATEWAY_KEY = os.environ["GATEWAY_KEY"]


class SendBody(BaseModel):
    to: str
    body: str
    session_id: str


@app.post("/sms")
async def inbound_sms(From: str = Form(...), Body: str = Form(...)):
    """Twilio webhook. Append to session.inbound. Return empty TwiML."""
    raise NotImplementedError
    return Response(content="<Response/>", media_type="application/xml")


@app.post("/send")
async def outbound_sms(body: SendBody, x_gateway_key: str = Header(...)):
    """Authenticated outbound send. Returns {sid}."""
    if x_gateway_key != GATEWAY_KEY:
        raise HTTPException(401, "bad key")
    raise NotImplementedError


@app.get("/inbound")
async def get_inbound(session_id: str, since: str | None = None):
    """Return inbound messages for a session after `since`."""
    raise NotImplementedError

from fastapi import FastAPI, Request, Header, HTTPException
from dotenv import load_dotenv
import json, os

load_dotenv()

app = FastAPI()
EXPECTED_SECRET = os.getenv("SB_SECRET", "")


@app.post("/sendblue/inbound")
async def inbound(req: Request, sb_signing_secret: str | None = Header(default=None)):
    if EXPECTED_SECRET and sb_signing_secret != EXPECTED_SECRET:
        raise HTTPException(401, "bad secret")
    payload = await req.json()
    print("INBOUND:", json.dumps(payload, indent=2))
    return {"ok": True}
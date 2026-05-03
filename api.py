"""ChangeAgent — Change Management Agent.

Endpoints:
  GET  /health
  POST /api/v1/change/assess    — SVAS change impact assessment
  GET  /api/v1/change/requests  — change request history

LLM: OpenRouter. Mock fallback when key absent.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger("ChangeAgent")
logging.basicConfig(level=logging.INFO)

_DB       = os.getenv("CHANGEAGENT_DB_PATH", "changeagent.db")
_OR_KEY   = os.getenv("OPENROUTER_API_KEY", "")
_OR_BASE  = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
_OR_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-haiku")

_SYSTEM_PROMPT = """You are ChangeAgent, an enterprise change management expert.
Given a change intent, produce a change impact assessment in JSON:
{
  "change_type": "STANDARD|NORMAL|EMERGENCY",
  "risk_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "affected_systems": ["...", "..."],
  "stakeholders": ["...", "..."],
  "rollback_steps": ["...", "..."],
  "approval_required": true|false,
  "change_window": "...",
  "summary": "...",
  "next_steps": ["...", "..."]
}
Respond with valid JSON only. Be specific to the change described."""

_MOCK_ASSESSMENT = {
    "change_type": "NORMAL",
    "risk_level": "MEDIUM",
    "affected_systems": ["Production API", "Database", "CDN"],
    "stakeholders": ["Engineering Lead", "Product Owner", "Operations"],
    "rollback_steps": ["Revert deployment", "Restore database snapshot",
                       "Clear CDN cache", "Verify service health"],
    "approval_required": True,
    "change_window": "Saturday 02:00-06:00 UTC",
    "summary": "Change requires CAB approval. Medium risk. 4-hour maintenance window recommended.",
    "next_steps": ["Submit CAB request", "Notify stakeholders 48h in advance",
                   "Prepare rollback runbook"],
}


def _init_db():
    conn = sqlite3.connect(_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS changes (
        id TEXT PRIMARY KEY, workflow_id TEXT, intent TEXT,
        change_type TEXT, risk_level TEXT, approval_required INTEGER,
        summary TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit(); conn.close()


def _call_or(intent: str) -> dict:
    payload = json.dumps({
        "model": _OR_MODEL, "max_tokens": 768,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": f"Change intent: {intent}"},
        ],
    }).encode()
    req = urllib.request.Request(
        f"{_OR_BASE}/chat/completions", data=payload,
        headers={"Authorization": f"Bearer {_OR_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    return json.loads(body["choices"][0]["message"]["content"].strip())


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _init_db(); yield


app = FastAPI(title="ChangeAgent", version="1.0.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class ChangeRequest(BaseModel):
    intent: str
    workflow_id: str = ""
    context: dict = {}
    change_title: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "healthy", "service": "ChangeAgent", "llm_available": bool(_OR_KEY)}


@app.post("/api/v1/change/assess")
def assess(req: ChangeRequest):
    cid = hashlib.sha256(f"{req.workflow_id}:{req.intent}".encode()).hexdigest()[:12]
    source = "openrouter"
    if _OR_KEY:
        try:
            data = _call_or(req.intent)
        except Exception as exc:
            logger.warning("OR failed (%s) — mock", exc)
            data = {**_MOCK_ASSESSMENT}; source = "mock"
    else:
        data = {**_MOCK_ASSESSMENT}; source = "mock"

    conn = sqlite3.connect(_DB)
    conn.execute("INSERT OR IGNORE INTO changes (id, workflow_id, intent, change_type, risk_level, approval_required, summary) VALUES (?,?,?,?,?,?,?)",
                 (cid, req.workflow_id, req.intent[:200],
                  data.get("change_type", "NORMAL"),
                  data.get("risk_level", "MEDIUM"),
                  int(data.get("approval_required", True)),
                  data.get("summary", "")[:300]))
    conn.commit(); conn.close()

    logger.info("Change assess: id=%s workflow=%s risk=%s", cid, req.workflow_id, data.get("risk_level"))
    return {"change_id": cid, "workflow_id": req.workflow_id, "source": source, **data}


@app.get("/api/v1/change/requests")
def list_requests(limit: int = 50):
    conn = sqlite3.connect(_DB); conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT id, workflow_id, change_type, risk_level, approval_required, created_at FROM changes ORDER BY created_at DESC LIMIT ?",
        (limit,)).fetchall()]
    conn.close()
    return {"requests": rows, "count": len(rows)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8013")))

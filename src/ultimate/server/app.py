"""Standalone FastAPI Application Server for ULTIMATE."""

from __future__ import annotations

import hmac
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from ultimate.core import AgentLoop
from ultimate.engine.groq_failover import GroqFailoverEngine
from ultimate.security.enclave import get_ultimate_enclave
from ultimate.security.offline_transport import execute_offline_nl_command
from ultimate.server.control_routes import router as control_router
from ultimate.tools.laptop_control import LaptopControlTool
from ultimate.tools.phone_control import PhoneControlTool


class ChatCompletionRequest(BaseModel):
    model: str = "openai/gpt-oss-120b"
    messages: List[Dict[str, Any]]
    stream: bool = False
    temperature: Optional[float] = 0.3
    max_tokens: Optional[int] = 2048


def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    x_key = request.headers.get("X-API-Key", "")
    if x_key:
        return x_key.strip()
    return str(request.query_params.get("api_key", "")).strip()


def create_app(*, api_key: Optional[str] = None) -> FastAPI:
    """Create the standalone ULTIMATE FastAPI server."""
    app = FastAPI(
        title="ULTIMATE Core API",
        description="Tri-Anchor Personal OS uniting Windows DPAPI Enclave, Direct Device Control, Offline Modes, and Phone-as-Microphone Voice Assistant",
        version="1.0.0",
    )

    enclave = get_ultimate_enclave()
    expected_key = (
        api_key
        or os.environ.get("ULTIMATE_API_KEY", "").strip()
        or enclave.api_key
    )

    laptop_tool = LaptopControlTool()
    phone_tool = PhoneControlTool()
    engine = GroqFailoverEngine()
    agent = AgentLoop(engine, tools=[laptop_tool, phone_tool])

    app.state.enclave = enclave
    app.state.engine = engine
    app.state.agent = agent

    @app.middleware("http")
    async def api_key_guard(request: Request, call_next):
        path = request.url.path
        if path in ("/", "/health", "/ultimate", "/control", "/remote"):
            return await call_next(request)
        if expected_key:
            presented = _extract_token(request)
            if not presented or not hmac.compare_digest(presented, expected_key):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized: invalid or missing API key"},
                )
        return await call_next(request)

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/ultimate")

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "system": "ULTIMATE",
            "windows_user": enclave.identity["windows_user"],
            "anchor_fingerprint": enclave.identity["anchor_fingerprint"],
            "groq_configured": engine.health(),
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest) -> Dict[str, Any]:
        user_text = ""
        for m in reversed(req.messages):
            if m.get("role") == "user":
                user_text = str(m.get("content", "")).strip()
                break
        if not user_text:
            return {"choices": [{"message": {"role": "assistant", "content": ""}}]}

        reply_text = ""
        used_model = req.model
        try:
            res = agent.run(user_text)
            reply_text = res.content
            used_model = res.metadata.get("model", req.model)
        except Exception:
            off = execute_offline_nl_command(user_text)
            reply_text = str(off.get("reply", "Executed via offline engine."))
            used_model = "ultimate-offline-nl"

        return {
            "id": f"ult_{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": used_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply_text},
                    "finish_reason": "stop",
                }
            ],
        }

    app.include_router(control_router)
    return app


__all__ = ["create_app"]

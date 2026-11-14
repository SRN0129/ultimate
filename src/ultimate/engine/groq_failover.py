"""Resilient Direct Multi-Model Groq Inference & Whisper Engine for ULTIMATE.

Uses direct httpx requests with automatic multi-model failover:
- Primary Model: openai/gpt-oss-120b
- Failover 1:    openai/gpt-oss-20b
- Failover 2:    qwen/qwen3.8-27b
- Speech-to-Text: whisper-large-v3-turbo
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any, Dict, List

import httpx

from ultimate.core import Message, messages_to_dicts

logger = logging.getLogger(__name__)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_GROQ_FAILOVER_CHAIN = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]


def _normalize_groq_model(model: str) -> str:
    m = (model or "").strip()
    if m.startswith("groq/"):
        m = m[len("groq/") :]
    if not m or m in (
        "default",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama3-70b-8192",
    ):
        return "openai/gpt-oss-120b"
    return m


def transcribe_audio_bytes(audio_bytes: bytes, filename: str = "voice.webm") -> str:
    """Transcribe phone microphone audio via Groq whisper-large-v3-turbo."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set for Whisper transcription")
    with httpx.Client(timeout=25.0) as client:
        resp = client.post(
            f"{_GROQ_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (filename, audio_bytes, "audio/webm")},
            data={
                "model": "whisper-large-v3-turbo",
                "language": "en",
                "response_format": "json",
            },
        )
        resp.raise_for_status()
        return str(resp.json().get("text", "")).strip()


class GroqFailoverEngine:
    """Direct Groq OpenAI-compatible engine with multi-model automatic failover."""

    engine_id = "groq-failover"

    def __init__(
        self,
        *,
        api_base: str | None = None,
        default_model: str = "openai/gpt-oss-120b",
    ) -> None:
        self._api_base = api_base or _GROQ_BASE_URL
        self._default_model = default_model

    def _build_candidate_chain(self, requested_model: str) -> List[str]:
        primary = _normalize_groq_model(requested_model or self._default_model)
        chain = [primary]
        for fallback in _GROQ_FAILOVER_CHAIN:
            if fallback not in chain:
                chain.append(fallback)
        return chain

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")

        msg_dicts = messages_to_dicts(messages)
        tools = kwargs.pop("tools", None)
        candidates = self._build_candidate_chain(model)

        last_err: Exception | None = None
        with httpx.Client(timeout=45.0) as client:
            for candidate_model in candidates:
                payload: Dict[str, Any] = {
                    "model": candidate_model,
                    "messages": msg_dicts,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

                try:
                    resp = client.post(
                        f"{self._api_base}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if resp.status_code == 400 and "tool_use_failed" in resp.text and tools:
                        logger.warning(
                            "Model %s returned tool_use_failed; failing over to next model",
                            candidate_model,
                        )
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    msg = choice["message"]
                    usage = data.get("usage", {})

                    result: Dict[str, Any] = {
                        "content": msg.get("content") or "",
                        "usage": {
                            "prompt_tokens": usage.get("prompt_tokens", 0),
                            "completion_tokens": usage.get("completion_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                        },
                        "model": data.get("model", candidate_model),
                        "finish_reason": choice.get("finish_reason") or "stop",
                    }
                    raw_tcs = msg.get("tool_calls")
                    if raw_tcs:
                        result["tool_calls"] = [
                            {
                                "id": tc.get("id", f"call_{i}"),
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments": tc.get("function", {}).get("arguments", "{}"),
                            }
                            for i, tc in enumerate(raw_tcs)
                        ]
                    return result
                except Exception as exc:
                    last_err = exc
                    logger.warning(
                        "Groq model %s failed (%s); trying next failover model...",
                        candidate_model,
                        exc,
                    )
                    continue

        raise RuntimeError(f"All Groq failover models failed. Last error: {last_err}")

    def list_models(self) -> List[str]:
        return list(_GROQ_FAILOVER_CHAIN)

    def health(self) -> bool:
        return bool(os.environ.get("GROQ_API_KEY"))


__all__ = ["GroqFailoverEngine", "transcribe_audio_bytes"]

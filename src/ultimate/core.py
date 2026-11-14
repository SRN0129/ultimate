"""Core data types, tool interfaces, config loader, and agent execution loop."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def get_project_root() -> Path:
    """Resolve the repository/working root directory cleanly across installations."""
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


def load_ultimate_config() -> Dict[str, Any]:
    """Load TOML settings from configs/ultimate.toml if present."""
    cfg_path = get_project_root() / "configs" / "ultimate.toml"
    if not cfg_path.exists():
        return {}
    try:
        import tomllib

        with cfg_path.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


@dataclass
class Message:
    role: str
    content: str = ""
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    category: str = "system"
    requires_confirmation: bool = False
    timeout_seconds: float = 60.0

    def to_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    tool_name: str
    content: str
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        raise NotImplementedError

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError


def messages_to_dicts(messages: Sequence[Message]) -> List[Dict[str, Any]]:
    """Convert internal Message objects into OpenAI-compatible wire dictionaries."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        role_val = m.role.value if hasattr(m.role, "value") else str(m.role)
        item: Dict[str, Any] = {"role": role_val, "content": m.content or ""}
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        if m.name:
            item["name"] = m.name
        if m.tool_calls:
            wire_calls = []
            for tc in m.tool_calls:
                args = tc.get("arguments", "{}")
                if not isinstance(args, str):
                    args = json.dumps(args)
                wire_calls.append(
                    {
                        "id": tc.get("id", "call_0"),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": args,
                        },
                    }
                )
            item["tool_calls"] = wire_calls
        out.append(item)
    return out


class AgentLoop:
    """Multi-turn tool-calling orchestrator over GroqFailoverEngine."""

    def __init__(
        self,
        engine: Any,
        *,
        model: str = "openai/gpt-oss-120b",
        tools: Optional[Sequence[BaseTool]] = None,
        system_prompt: Optional[str] = None,
        max_turns: int = 10,
    ) -> None:
        self.engine = engine
        self.model = model
        self.tools: Dict[str, BaseTool] = {t.spec.name: t for t in (tools or [])}
        self.tool_schemas = [t.spec.to_openai_schema() for t in self.tools.values()]
        cfg = load_ultimate_config()
        default_prompt = (
            cfg.get("agent", {}).get("system_prompt")
            or "You are ULTIMATE, a personal AI operating system controlling the user's Windows laptop and Android phone."
        )
        self.system_prompt = system_prompt or default_prompt
        self.max_turns = max_turns

    def run(self, user_prompt: str) -> ToolResult:
        messages: List[Message] = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=user_prompt),
        ]
        for _ in range(self.max_turns):
            reply = self.engine.generate(
                messages,
                model=self.model,
                tools=self.tool_schemas if self.tool_schemas else None,
            )
            tool_calls = reply.get("tool_calls") or []
            if not tool_calls:
                return ToolResult(
                    tool_name="ultimate_agent",
                    content=str(reply.get("content") or "").strip(),
                    success=True,
                    metadata={"model": reply.get("model", self.model)},
                )

            messages.append(
                Message(
                    role="assistant",
                    content=reply.get("content") or "",
                    tool_calls=tool_calls,
                )
            )
            for tc in tool_calls:
                name = tc.get("name", "")
                raw_args = tc.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except Exception:
                    args = {}
                tool = self.tools.get(name)
                if tool is None:
                    result_txt = f"Unknown tool: {name}"
                else:
                    res = tool.execute(**args)
                    result_txt = res.content
                messages.append(
                    Message(
                        role="tool",
                        name=name,
                        tool_call_id=tc.get("id", "call_0"),
                        content=result_txt,
                    )
                )

        return ToolResult(
            tool_name="ultimate_agent",
            content="Reached maximum reasoning turns without a final reply.",
            success=False,
        )


__all__ = [
    "AgentLoop",
    "BaseTool",
    "Message",
    "ToolResult",
    "ToolSpec",
    "get_project_root",
    "load_ultimate_config",
    "messages_to_dicts",
]

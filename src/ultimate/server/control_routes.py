"""Direct REST, Tri-Anchor Ratchet Enclave, Offline Engine, Voice Bridge, and 100km+ Companion API."""

from __future__ import annotations

import base64
import collections
import hashlib
import json
import time
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ultimate.core import AgentLoop, Message, get_project_root
from ultimate.engine.groq_failover import GroqFailoverEngine, transcribe_audio_bytes
from ultimate.security.enclave import get_ultimate_enclave
from ultimate.security.guardian import get_autonomous_guardian
from ultimate.security.offgrid_100km import verify_and_execute_ult1_packet
from ultimate.security.offline_transport import (
    execute_offline_nl_command,
    get_airgap_receiver,
    get_offline_radio_links,
)
from ultimate.tools.laptop_control import LaptopControlTool
from ultimate.tools.phone_control import PhoneControlTool
from ultimate.voice.speaker import speak_on_laptop_async

router = APIRouter(tags=["ultimate-control"])

_laptop_tool = LaptopControlTool()
_phone_tool = PhoneControlTool()
_direct_llm = GroqFailoverEngine()
_fallback_agent: Optional[AgentLoop] = None


def _get_fallback_agent() -> AgentLoop:
    global _fallback_agent
    if _fallback_agent is None:
        _fallback_agent = AgentLoop(
            _direct_llm,
            model="openai/gpt-oss-120b",
            tools=[_laptop_tool, _phone_tool],
            max_turns=8,
        )
    return _fallback_agent


_PHONE_COMPANION_STATE: Dict[str, Any] = {
    "connected": False,
    "last_seen": 0.0,
    "battery_percent": None,
    "charging": None,
    "network": "Unknown",
    "user_agent": "",
    "screen": "",
    "gps": None,
    "last_clipboard": "",
}
_PHONE_COMMAND_QUEUE: Deque[Dict[str, Any]] = collections.deque(maxlen=100)


def queue_remote_phone_command(cmd: Dict[str, Any]) -> Dict[str, Any]:
    """Queue a command for the remote phone companion over the 100km+ bridge."""
    cmd_with_id = {
        "id": f"cmd_{int(time.time() * 1000)}",
        "timestamp": int(time.time()),
        **cmd,
    }
    _PHONE_COMMAND_QUEUE.append(cmd_with_id)
    return cmd_with_id


def get_remote_phone_state() -> Dict[str, Any]:
    now = time.time()
    alive = (now - float(_PHONE_COMPANION_STATE.get("last_seen") or 0)) < 30.0
    return {**_PHONE_COMPANION_STATE, "connected": alive}


class LaptopControlRequest(BaseModel):
    action: str
    target: Optional[str] = ""
    value: Optional[str] = ""
    text: Optional[str] = ""
    title: Optional[str] = "ULTIMATE"
    command: Optional[str] = ""
    x: Optional[int] = None
    y: Optional[int] = None
    amount: Optional[int] = 5
    press_enter: Optional[bool] = False


class PhoneControlRequest(BaseModel):
    action: str
    target: Optional[str] = ""
    value: Optional[str] = ""
    text: Optional[str] = ""
    command: Optional[str] = ""
    device: Optional[str] = ""
    x: Optional[int] = None
    y: Optional[int] = None
    x2: Optional[int] = None
    y2: Optional[int] = None
    duration_ms: Optional[int] = 300
    press_enter: Optional[bool] = False


class OfflineChatRequest(BaseModel):
    prompt: str


class AirGapControlRequest(BaseModel):
    enable: bool


class OffGridPacketRequest(BaseModel):
    packet: str


class GuardianMissionRequest(BaseModel):
    action: str = "add"
    command: str = "lock laptop"
    trigger_type: str = "timer_minutes"
    trigger_value: int = 5


class VoiceAudioRequest(BaseModel):
    audio_base64: Optional[str] = None
    filename: str = "phone_mic.webm"
    transcript: Optional[str] = None
    speak_on_laptop: bool = True


class SpeakRequest(BaseModel):
    text: str


class PhoneBridgeTelemetry(BaseModel):
    battery_percent: Optional[float] = None
    charging: Optional[bool] = None
    network: Optional[str] = None
    user_agent: Optional[str] = None
    screen: Optional[str] = None
    gps: Optional[Dict[str, Any]] = None
    clipboard: Optional[str] = None


def _verify_optional_ratchet(
    raw_body: str,
    x_ult_nonce: Optional[str],
    x_ult_ts: Optional[str],
    x_ult_step: Optional[str],
    x_ult_sig: Optional[str],
) -> Optional[str]:
    """Verify the UTA-QRP one-time ratchet headers if presented by the client."""
    if not (x_ult_nonce and x_ult_ts and x_ult_step and x_ult_sig):
        return None
    enclave = get_ultimate_enclave()
    body_hash = hashlib.sha256(raw_body.encode("utf-8")).hexdigest()
    ok, proof_or_err = enclave.verify_ratchet_envelope(
        nonce=x_ult_nonce,
        timestamp=int(x_ult_ts),
        step=int(x_ult_step),
        body_sha256=body_hash,
        signature=x_ult_sig,
    )
    if not ok:
        raise HTTPException(status_code=403, detail=f"UTA-QRP Security Violation: {proof_or_err}")
    return proof_or_err


@router.post("/v1/control/laptop")
async def control_laptop(
    req: LaptopControlRequest,
    x_ult_nonce: Optional[str] = Header(default=None),
    x_ult_ts: Optional[str] = Header(default=None),
    x_ult_step: Optional[str] = Header(default=None),
    x_ult_sig: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Execute a direct laptop control action and return the result + ratchet proof."""
    payload_dict = req.model_dump(exclude_none=True)
    server_proof = None
    if x_ult_sig:
        raw_canonical = json.dumps(payload_dict, separators=(",", ":"), sort_keys=True)
        server_proof = _verify_optional_ratchet(
            raw_canonical, x_ult_nonce, x_ult_ts, x_ult_step, x_ult_sig
        )
    res = _laptop_tool.execute(**payload_dict)
    return {
        "success": res.success,
        "content": res.content,
        "metadata": res.metadata,
        "ratchet_proof": server_proof,
    }


@router.post("/v1/control/phone")
async def control_phone(
    req: PhoneControlRequest,
    x_ult_nonce: Optional[str] = Header(default=None),
    x_ult_ts: Optional[str] = Header(default=None),
    x_ult_step: Optional[str] = Header(default=None),
    x_ult_sig: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Execute a phone control action via ADB or 100km+ Remote Companion Bridge."""
    payload_dict = req.model_dump(exclude_none=True)
    server_proof = None
    if x_ult_sig:
        raw_canonical = json.dumps(payload_dict, separators=(",", ":"), sort_keys=True)
        server_proof = _verify_optional_ratchet(
            raw_canonical, x_ult_nonce, x_ult_ts, x_ult_step, x_ult_sig
        )
    res = _phone_tool.execute(**payload_dict)
    return {
        "success": res.success,
        "content": res.content,
        "metadata": res.metadata,
        "ratchet_proof": server_proof,
    }


@router.post("/v1/control/offline-chat")
async def offline_chat(req: OfflineChatRequest) -> Dict[str, Any]:
    """Zero-Internet Offline Natural Language Command Executor."""
    return execute_offline_nl_command(req.prompt)


@router.post("/v1/control/airgap")
async def toggle_airgap(req: AirGapControlRequest) -> Dict[str, Any]:
    """Start or stop the on-demand Acoustic Air-Gap Receiver on the laptop mic."""
    rx = get_airgap_receiver()
    msg = rx.start() if req.enable else rx.stop()
    return {"running": rx.running, "message": msg, "last_detected": rx.last_detected}


@router.post("/v1/control/offgrid-packet")
async def execute_offgrid_packet(req: OffGridPacketRequest) -> Dict[str, Any]:
    """Verify and execute a compact ULT1 ratcheted SMS / LoRa off-grid packet."""
    ok, reply = verify_and_execute_ult1_packet(req.packet)
    return {"success": ok, "reply": reply}


@router.post("/v1/control/guardian")
async def configure_guardian(req: GuardianMissionRequest) -> Dict[str, Any]:
    """Configure 1-Laptop + 1-Phone Autonomous Offline Guardian."""
    g = get_autonomous_guardian()
    if req.action == "set_autolock":
        g.auto_lock_on_phone_away_mins = max(0, int(req.trigger_value))
        return {
            "ok": True,
            "message": f"Auto-Lock when phone leaves set to {g.auto_lock_on_phone_away_mins} min.",
            "status": g.status(),
        }
    if req.action == "clear":
        g.clear_missions()
        return {"ok": True, "message": "Cleared offline missions.", "status": g.status()}
    m = g.add_mission(req.command, req.trigger_type, req.trigger_value)
    return {
        "ok": True,
        "message": f"Scheduled Offline Mission: '{m.command}' on {m.trigger_type}={m.trigger_value}",
        "status": g.status(),
    }


def _run_ultimate_agent_or_llm(request: Optional[Request], prompt: str) -> str:
    """Run prompt through the tool-enabled AgentLoop, failing over to offline NL engine."""
    agent = getattr(request.app.state, "agent", None) if request else None
    if agent is None:
        agent = _get_fallback_agent()
    try:
        res = agent.run(prompt)
        if res and getattr(res, "content", ""):
            return str(res.content).strip()
    except Exception:
        pass
    try:
        out = _direct_llm.generate(
            [
                Message(role="system", content="You are ULTIMATE, a direct, capable AI assistant."),
                Message(role="user", content=prompt),
            ]
        )
        if out.get("content"):
            return str(out["content"]).strip()
    except Exception:
        pass
    off = execute_offline_nl_command(prompt)
    return str(off.get("reply", "Executed offline command."))


@router.post("/v1/control/voice-audio")
async def voice_audio_command(req: VoiceAudioRequest, request: Request) -> Dict[str, Any]:
    """Use the Phone as a Wireless Microphone to talk to ULTIMATE on the Laptop."""
    transcript = (req.transcript or "").strip()
    if not transcript and req.audio_base64:
        raw_b64 = req.audio_base64.strip()
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        audio_bytes = base64.b64decode(raw_b64)
        transcript = transcribe_audio_bytes(audio_bytes, filename=req.filename)

    if not transcript:
        return {
            "success": False,
            "transcript": "",
            "reply": "I did not catch any speech from the phone microphone. Please tap Speak and try again.",
        }

    reply = _run_ultimate_agent_or_llm(request, transcript)
    if req.speak_on_laptop and reply:
        speak_on_laptop_async(reply)

    return {
        "success": True,
        "transcript": transcript,
        "reply": reply,
        "spoke_on_laptop": bool(req.speak_on_laptop),
    }


@router.post("/v1/control/speak")
async def speak_on_laptop(req: SpeakRequest) -> Dict[str, Any]:
    """Speak text aloud on the laptop speakers via Windows SAPI."""
    speak_on_laptop_async(req.text)
    return {"success": True, "reply": req.text}


@router.post("/v1/control/phone-bridge/sync")
async def phone_bridge_sync(telemetry: PhoneBridgeTelemetry) -> Dict[str, Any]:
    """100km+ Phone Companion heartbeat: updates telemetry and dequeues queued commands."""
    _PHONE_COMPANION_STATE["connected"] = True
    _PHONE_COMPANION_STATE["last_seen"] = time.time()
    if telemetry.battery_percent is not None:
        _PHONE_COMPANION_STATE["battery_percent"] = telemetry.battery_percent
    if telemetry.charging is not None:
        _PHONE_COMPANION_STATE["charging"] = telemetry.charging
    if telemetry.network:
        _PHONE_COMPANION_STATE["network"] = telemetry.network
    if telemetry.user_agent:
        _PHONE_COMPANION_STATE["user_agent"] = telemetry.user_agent
    if telemetry.screen:
        _PHONE_COMPANION_STATE["screen"] = telemetry.screen
    if telemetry.gps:
        _PHONE_COMPANION_STATE["gps"] = telemetry.gps
    if telemetry.clipboard:
        _PHONE_COMPANION_STATE["last_clipboard"] = telemetry.clipboard

    pending: List[Dict[str, Any]] = []
    while _PHONE_COMMAND_QUEUE:
        pending.append(_PHONE_COMMAND_QUEUE.popleft())

    return {
        "ok": True,
        "commands": pending,
        "windows_anchor": get_ultimate_enclave().identity["anchor_fingerprint"],
    }


@router.get("/v1/control/status")
async def control_status() -> Dict[str, Any]:
    """Return combined Windows Account, Laptop, Offline Links, and Phone status."""
    enclave = get_ultimate_enclave()
    rx = get_airgap_receiver()
    laptop_res = _laptop_tool.execute(action="system_status")
    phone_res = _phone_tool.execute(action="devices")
    laptop_data = laptop_res.metadata or {}
    if not laptop_data and laptop_res.content:
        try:
            laptop_data = json.loads(laptop_res.content)
        except Exception:
            laptop_data = {"raw": laptop_res.content}

    tunnel_url = ""
    try:
        url_file = get_project_root() / ".ultimate_tunnel_url.txt"
        if url_file.exists():
            tunnel_url = url_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    return {
        "assistant_name": "ULTIMATE",
        "enclave": {
            "protocol": "UTA-QRP-v1 (DPAPI + X25519MLKEM768 + SHA256-Chain-Ratchet)",
            "windows_user": enclave.identity["windows_user"],
            "windows_sid": enclave.identity["windows_sid"],
            "anchor_fingerprint": enclave.identity["anchor_fingerprint"],
            "ratchet_step": enclave._ratchet_step,
            "global_tunnel_url": tunnel_url,
            "offline_radio_links": get_offline_radio_links(),
            "airgap_running": rx.running,
            "airgap_last": rx.last_detected,
        },
        "laptop": laptop_data,
        "phone_adb": phone_res.metadata or {"raw": phone_res.content},
        "phone_companion_100km": get_remote_phone_state(),
    }


_REMOTE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="theme-color" content="#070a12" />
<title>ULTIMATE - Direct Zero-Trust Control</title>
<style>
  :root {
    --bg: #070a12;
    --card: #101726;
    --card-border: #1e293b;
    --accent: #38bdf8;
    --quantum: #a855f7;
    --success: #22c55e;
    --danger: #ef4444;
    --warn: #f59e0b;
    --text: #f8fafc;
    --muted: #94a3b8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); padding-bottom: 85px;
  }
  header {
    position: sticky; top: 0; z-index: 50;
    background: rgba(7, 10, 18, 0.94); backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--card-border); padding: 12px 16px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 1.05rem; letter-spacing: 0.5px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--success); box-shadow: 0 0 10px var(--success); }
  .badge-pq {
    background: rgba(168, 85, 247, 0.2); border: 1px solid var(--quantum);
    color: #e9d5ff; font-size: 0.68rem; padding: 3px 8px; border-radius: 999px; font-weight: 700;
  }
  .tabs {
    display: flex; gap: 6px; padding: 10px 12px;
    background: #0b101d; border-bottom: 1px solid var(--card-border);
    position: sticky; top: 52px; z-index: 49;
  }
  .tab-btn {
    flex: 1; padding: 10px 4px; border: 1px solid var(--card-border);
    background: var(--card); color: var(--muted); border-radius: 10px;
    font-weight: 700; font-size: 0.8rem; cursor: pointer; text-align: center;
  }
  .tab-btn.active {
    background: linear-gradient(135deg, var(--accent), var(--quantum));
    color: #fff; border-color: transparent;
  }
  .panel { display: none; padding: 12px; max-width: 920px; margin: 0 auto; }
  .panel.active { display: block; }
  .card {
    background: var(--card); border: 1px solid var(--card-border);
    border-radius: 14px; padding: 14px; margin-bottom: 14px;
  }
  .card h3 {
    font-size: 0.92rem; color: var(--accent); margin-bottom: 10px;
    display: flex; justify-content: space-between; align-items: center;
  }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
  button.btn {
    background: #1a2438; color: var(--text); border: 1px solid #2d3d5b;
    padding: 12px 8px; border-radius: 10px; font-size: 0.82rem; font-weight: 600;
    cursor: pointer; transition: transform 0.08s, background 0.15s;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
  }
  button.btn:active { transform: scale(0.96); background: #334155; }
  button.btn.primary { background: var(--accent); color: #000; border-color: var(--accent); font-weight: 700; }
  button.btn.quantum { background: var(--quantum); color: #fff; border-color: var(--quantum); font-weight: 700; }
  button.btn.danger { background: rgba(239, 68, 68, 0.2); color: #fca5a5; border-color: var(--danger); }
  button.btn.warn { background: rgba(245, 158, 11, 0.2); color: #fcd34d; border-color: var(--warn); }
  .row { display: flex; gap: 8px; margin-top: 8px; align-items: center; }
  input[type="text"], input[type="number"], textarea {
    width: 100%; background: #070a12; color: var(--text);
    border: 1px solid #334155; border-radius: 10px; padding: 11px 12px;
    font-size: 0.9rem; outline: none;
  }
  .status-pills { display: flex; flex-wrap: wrap; gap: 8px; }
  .pill {
    background: #070a12; border: 1px solid #26344d; border-radius: 8px;
    padding: 8px 10px; font-size: 0.79rem; flex: 1 1 45%;
  }
  .pill span { color: var(--muted); display: block; font-size: 0.7rem; margin-bottom: 2px; }
  .touchpad {
    width: 100%; height: 170px; background: radial-gradient(circle, #162238 0%, #090e1a 100%);
    border: 2px dashed #334155; border-radius: 14px;
    display: flex; align-items: center; justify-content: center;
    color: var(--muted); font-size: 0.88rem; font-weight: 600;
    touch-action: none; user-select: none; cursor: pointer;
  }
  .item-list { display: flex; flex-direction: column; gap: 6px; max-height: 240px; overflow-y: auto; }
  .item-row {
    background: #070a12; border: 1px solid #1e293b; border-radius: 8px;
    padding: 8px 10px; display: flex; justify-content: space-between; align-items: center;
    font-size: 0.82rem;
  }
  .toast {
    position: fixed; bottom: 16px; left: 16px; right: 16px; z-index: 100;
    background: #131c31; border-left: 4px solid var(--accent); color: var(--text);
    padding: 12px 14px; border-radius: 10px; font-size: 0.84rem;
    box-shadow: 0 10px 25px rgba(0,0,0,0.7); display: none;
    max-height: 160px; overflow-y: auto; white-space: pre-wrap;
  }
  .chat-log {
    height: 52vh; overflow-y: auto; background: #070a12;
    border: 1px solid #1e293b; border-radius: 10px; padding: 12px;
    display: flex; flex-direction: column; gap: 10px; margin-bottom: 10px;
  }
  .msg { padding: 10px 12px; border-radius: 10px; max-width: 88%; font-size: 0.9rem; line-height: 1.4; white-space: pre-wrap; }
  .msg.user { background: var(--accent); color: #000; align-self: flex-end; font-weight: 600; }
  .msg.bot { background: #1a2438; color: var(--text); align-self: flex-start; }
  input[type="range"] { width: 100%; accent-color: var(--accent); }
</style>
</head>
<body>
<header>
  <div class="brand"><div class="dot"></div> ULTIMATE <span class="badge-pq" id="ratchet-badge">UTA-QRP #0</span></div>
</header>

<div class="tabs">
  <div class="tab-btn active" onclick="switchTab('laptop', this)">Laptop</div>
  <div class="tab-btn" onclick="switchTab('phone', this)">Phone</div>
  <div class="tab-btn" onclick="switchTab('mesh', this)">Offline &amp; Mesh</div>
  <div class="tab-btn" onclick="switchTab('chat', this)">Ultimate AI</div>
</div>

<!-- PHONE-AS-WIRELESS-MICROPHONE BAR -->
<div style="max-width:920px;margin:10px auto 0 auto;padding:0 12px;">
  <div class="card" style="margin-bottom:4px;border-color:var(--accent);background:linear-gradient(135deg,#0f172a,#1e1b4b);">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;">
      <div style="flex:1;min-width:190px;">
        <div style="font-weight:800;font-size:0.92rem;color:#38bdf8;">Phone Wireless Microphone -&gt; ULTIMATE Speaks on Laptop</div>
        <div id="mic-status-text" style="font-size:0.78rem;color:#cbd5e1;margin-top:2px;">Tap Speak to talk into your phone mic. ULTIMATE executes commands and speaks back through laptop speakers.</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;">
        <button id="phone-mic-btn" class="btn primary" style="padding:12px 16px;font-size:0.9rem;border-radius:999px;" onclick="togglePhoneMic()">Tap to Speak</button>
        <button class="btn quantum" style="padding:12px 12px;font-size:0.8rem;border-radius:999px;" onclick="testLaptopVoice()">Test Voice</button>
      </div>
    </div>
  </div>
</div>

<div id="panel-laptop" class="panel active">
  <div class="card">
    <h3>Live Laptop Telemetry <button class="btn" style="padding:4px 10px;font-size:0.75rem" onclick="refreshStatus()">Refresh</button></h3>
    <div id="laptop-stats" class="status-pills">
      <div class="pill"><span>CPU / RAM</span>Loading...</div>
      <div class="pill"><span>Battery / Active Window</span>Loading...</div>
    </div>
  </div>

  <div class="card">
    <h3>Direct Virtual Touchpad (Slide to Move Cursor, Tap to Click)</h3>
    <div id="touchpad" class="touchpad">Slide here to move laptop cursor directly (Zero screenshots required)</div>
    <div class="grid-4" style="margin-top:8px">
      <button class="btn primary" onclick="laptopCmd({action:'mouse_click',value:'left'})">Left Click</button>
      <button class="btn" onclick="laptopCmd({action:'mouse_click',value:'double'})">Double Click</button>
      <button class="btn" onclick="laptopCmd({action:'mouse_click',value:'right'})">Right Click</button>
      <button class="btn" onclick="laptopCmd({action:'mouse_scroll',amount:-5})">Scroll Dn</button>
    </div>
  </div>

  <div class="card">
    <h3>Direct Open Windows Manager <button class="btn primary" style="padding:4px 10px;font-size:0.75rem" onclick="loadOpenWindows()">Load Windows</button></h3>
    <div id="windows-list" class="item-list">
      <div class="item-row"><span>Tap "Load Windows" to focus, minimize, or close open laptop apps directly</span></div>
    </div>
  </div>

  <div class="card">
    <h3>Direct Laptop File Explorer <button class="btn primary" style="padding:4px 10px;font-size:0.75rem" onclick="loadFiles('')">Desktop</button></h3>
    <div id="files-list" class="item-list">
      <div class="item-row"><span>Tap "Desktop" to browse and open laptop files directly</span></div>
    </div>
  </div>

  <div class="card">
    <h3>Audio Volume, Media &amp; Brightness</h3>
    <div class="grid-4">
      <button class="btn" onclick="laptopCmd({action:'volume',value:'mute'})">Mute</button>
      <button class="btn" onclick="laptopCmd({action:'volume',value:'down',amount:6})">Vol -</button>
      <button class="btn" onclick="laptopCmd({action:'volume',value:'up',amount:6})">Vol +</button>
      <button class="btn primary" onclick="laptopCmd({action:'media',value:'play_pause'})">Play/Pause</button>
    </div>
    <div class="grid" style="margin-top:8px">
      <button class="btn" onclick="laptopCmd({action:'media',value:'prev'})">Prev</button>
      <button class="btn" onclick="laptopCmd({action:'media',value:'stop'})">Stop</button>
      <button class="btn" onclick="laptopCmd({action:'media',value:'next'})">Next</button>
    </div>
    <div class="row" style="margin-top:12px">
      <span style="font-size:0.8rem;color:var(--muted);min-width:75px">Volume %</span>
      <input type="range" min="0" max="100" value="50" onchange="laptopCmd({action:'volume',value:this.value})" />
    </div>
    <div class="row">
      <span style="font-size:0.8rem;color:var(--muted);min-width:75px">Brightness</span>
      <input type="range" min="10" max="100" value="80" onchange="laptopCmd({action:'brightness',value:this.value})" />
    </div>
  </div>

  <div class="card">
    <h3>Launch &amp; Control Windows Applications</h3>
    <div class="grid">
      <button class="btn" onclick="laptopCmd({action:'open_app',target:'chrome'})">Chrome</button>
      <button class="btn" onclick="laptopCmd({action:'open_app',target:'explorer'})">Files</button>
      <button class="btn" onclick="laptopCmd({action:'open_app',target:'notepad'})">Notepad</button>
      <button class="btn" onclick="laptopCmd({action:'open_app',target:'spotify'})">Spotify</button>
      <button class="btn" onclick="laptopCmd({action:'open_app',target:'whatsapp'})">WhatsApp</button>
      <button class="btn" onclick="laptopCmd({action:'open_app',target:'settings'})">Settings</button>
      <button class="btn" onclick="laptopCmd({action:'open_app',target:'calc'})">Calculator</button>
      <button class="btn" onclick="laptopCmd({action:'open_app',target:'terminal'})">Terminal</button>
      <button class="btn" onclick="laptopCmd({action:'open_app',target:'taskmgr'})">TaskMgr</button>
    </div>
    <div class="row">
      <input type="text" id="laptop-app-input" placeholder="App name, file path, or https:// URL..." />
      <button class="btn primary" onclick="laptopCmd({action:'open_app',target:document.getElementById('laptop-app-input').value})">Open</button>
      <button class="btn danger" onclick="laptopCmd({action:'close_app',target:document.getElementById('laptop-app-input').value})">Kill</button>
    </div>
  </div>

  <div class="card">
    <h3>Direct Keyboard, Clipboard &amp; Windows Shortcuts</h3>
    <div class="row">
      <input type="text" id="laptop-type-input" placeholder="Type text directly onto laptop..." />
      <button class="btn primary" onclick="laptopCmd({action:'type_text',text:document.getElementById('laptop-type-input').value,press_enter:true})">Type+Enter</button>
      <button class="btn" onclick="laptopCmd({action:'clipboard_set',text:document.getElementById('laptop-type-input').value})">Set Clip</button>
    </div>
    <div class="grid-4" style="margin-top:8px">
      <button class="btn" onclick="laptopCmd({action:'press_key',value:'enter'})">Enter</button>
      <button class="btn" onclick="laptopCmd({action:'press_key',value:'space'})">Space</button>
      <button class="btn" onclick="laptopCmd({action:'press_key',value:'backspace'})">Back</button>
      <button class="btn" onclick="laptopCmd({action:'press_key',value:'esc'})">Esc</button>
      <button class="btn" onclick="laptopCmd({action:'hotkey',value:'alt+tab'})">Alt+Tab</button>
      <button class="btn" onclick="laptopCmd({action:'hotkey',value:'win+d'})">Desktop</button>
      <button class="btn" onclick="laptopCmd({action:'hotkey',value:'alt+f4'})">Alt+F4</button>
      <button class="btn" onclick="laptopCmd({action:'clipboard_get'})">Get Clip</button>
    </div>
  </div>

  <div class="card">
    <h3>Windows Account &amp; Power Control</h3>
    <div class="grid">
      <button class="btn warn" onclick="laptopCmd({action:'power',value:'lock'})">Lock Account</button>
      <button class="btn warn" onclick="laptopCmd({action:'power',value:'screen_off'})">Screen Off</button>
      <button class="btn warn" onclick="laptopCmd({action:'power',value:'sleep'})">Sleep</button>
      <button class="btn danger" onclick="if(confirm('Shutdown laptop in 10s?')) laptopCmd({action:'power',value:'shutdown'})">Shutdown</button>
      <button class="btn danger" onclick="if(confirm('Restart laptop in 10s?')) laptopCmd({action:'power',value:'restart'})">Restart</button>
      <button class="btn" onclick="laptopCmd({action:'power',value:'cancel_shutdown'})">Abort Off</button>
    </div>
  </div>

  <div class="card">
    <h3>Windows Account PowerShell Console</h3>
    <div class="row">
      <input type="text" id="laptop-ps-input" placeholder="e.g. whoami; Get-Process | Select -First 5" />
      <button class="btn primary" onclick="laptopCmd({action:'powershell',command:document.getElementById('laptop-ps-input').value})">Execute</button>
    </div>
  </div>
</div>

<div id="panel-phone" class="panel">
  <div class="card">
    <h3>Phone Control (100km+ Bridge + Optional ADB) <button class="btn" style="padding:4px 10px;font-size:0.75rem" onclick="phoneCmd({action:'status'})">Check Status</button></h3>
    <div id="phone-stats" class="status-pills" style="margin-bottom:8px">
      <div class="pill"><span>Zero-Side-Effect Mode</span>Runs in mobile browser (No root/APK needed)</div>
      <div class="pill"><span>Phone Status</span>Tap Check Status</div>
    </div>
  </div>

  <div class="card">
    <h3>Direct Phone Hardware &amp; Navigation Controls</h3>
    <div class="grid-4">
      <button class="btn" onclick="phoneCmd({action:'keyevent',value:'back'})">Back</button>
      <button class="btn primary" onclick="phoneCmd({action:'keyevent',value:'home'})">Home</button>
      <button class="btn" onclick="phoneCmd({action:'keyevent',value:'recents'})">Recents</button>
      <button class="btn warn" onclick="phoneCmd({action:'find_phone'})">Find Phone</button>
      <button class="btn" onclick="phoneCmd({action:'keyevent',value:'volume_down'})">Vol -</button>
      <button class="btn" onclick="phoneCmd({action:'keyevent',value:'volume_up'})">Vol +</button>
      <button class="btn" onclick="phoneCmd({action:'keyevent',value:'wakeup'})">Wake</button>
      <button class="btn" onclick="phoneCmd({action:'keyevent',value:'sleep'})">Lock</button>
    </div>
  </div>

  <div class="card">
    <h3>Launch Phone Apps Directly</h3>
    <div class="grid">
      <button class="btn" onclick="phoneCmd({action:'open_app',target:'whatsapp'})">WhatsApp</button>
      <button class="btn" onclick="phoneCmd({action:'open_app',target:'youtube'})">YouTube</button>
      <button class="btn" onclick="phoneCmd({action:'open_app',target:'chrome'})">Chrome</button>
      <button class="btn" onclick="phoneCmd({action:'open_app',target:'instagram'})">Instagram</button>
      <button class="btn" onclick="phoneCmd({action:'open_app',target:'spotify'})">Spotify</button>
      <button class="btn" onclick="phoneCmd({action:'open_app',target:'camera'})">Camera</button>
      <button class="btn" onclick="phoneCmd({action:'open_app',target:'maps'})">Maps</button>
      <button class="btn" onclick="phoneCmd({action:'open_app',target:'settings'})">Settings</button>
      <button class="btn" onclick="phoneCmd({action:'open_app',target:'phone'})">Dialer</button>
    </div>
    <div class="row">
      <input type="text" id="phone-app-input" placeholder="App name or URL..." />
      <button class="btn primary" onclick="phoneCmd({action:'open_app',target:document.getElementById('phone-app-input').value})">Open</button>
    </div>
  </div>

  <div class="card">
    <h3>Direct Calls &amp; SMS</h3>
    <div class="row">
      <input type="text" id="phone-num-input" placeholder="Phone number (+1...)" />
      <button class="btn primary" onclick="phoneCmd({action:'call_number',target:document.getElementById('phone-num-input').value})">Call</button>
    </div>
    <div class="row">
      <input type="text" id="phone-sms-input" placeholder="SMS message..." />
      <button class="btn primary" onclick="phoneCmd({action:'send_sms',target:document.getElementById('phone-num-input').value,text:document.getElementById('phone-sms-input').value})">Send SMS</button>
    </div>
  </div>
</div>

<div id="panel-mesh" class="panel">
  <div class="card" style="border-color:var(--quantum)">
    <h3 style="color:#e9d5ff">Tri-Anchor Enclave &amp; Offline Radio Links <button class="btn quantum" style="padding:4px 10px;font-size:0.75rem" onclick="refreshStatus()">Verify</button></h3>
    <div id="enclave-stats" class="status-pills">
      <div class="pill"><span>1. Windows Account Anchor</span>Verifying DPAPI SID...</div>
      <div class="pill"><span>2. Offline Radio Interfaces</span>Scanning...</div>
    </div>
  </div>

  <div class="card">
    <h3>Zero-Network Acoustic Air-Gap Beam (Works With Wi-Fi &amp; Internet OFF)</h3>
    <p style="font-size:0.78rem;color:var(--muted);margin-bottom:10px">
      When your laptop has no internet and no Wi-Fi, enable the Air-Gap Receiver below. Your phone speaker emits a 2450 Hz preamble plus a command tone decoded by the laptop microphone.
    </p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
      <button class="btn primary" onclick="toggleAirGap(true)">Enable Audio Receiver</button>
      <button class="btn danger" onclick="toggleAirGap(false)">Disable Receiver</button>
    </div>
    <div class="grid">
      <button class="btn quantum" onclick="beamAudioTone(2800, 'Lock PC')">Beam: Lock PC</button>
      <button class="btn quantum" onclick="beamAudioTone(3000, 'Mute PC')">Beam: Mute PC</button>
      <button class="btn quantum" onclick="beamAudioTone(3200, 'Play/Pause')">Beam: Play/Pause</button>
      <button class="btn quantum" onclick="beamAudioTone(3400, 'Screen Off')">Beam: Screen Off</button>
      <button class="btn quantum" onclick="beamAudioTone(3600, 'Vol +')">Beam: Vol +</button>
      <button class="btn quantum" onclick="beamAudioTone(3800, 'Vol -')">Beam: Vol -</button>
    </div>
  </div>

  <div class="card" style="border-color:var(--success)">
    <h3 style="color:var(--success)">1-Laptop + 1-Phone Autonomous Offline Guardian</h3>
    <p style="font-size:0.78rem;color:var(--muted);margin-bottom:8px">
      Offline buttons queue in your phone Store-and-Forward Vault and execute automatically when reconnected. Set offline laptop auto-protection rules below.
    </p>
    <div class="grid" style="margin-bottom:8px">
      <button class="btn primary" onclick="setAutoLock(2)">Auto-Lock Away 2m</button>
      <button class="btn" onclick="addOfflineMission('lock laptop','timer_minutes',15)">Lock PC in 15m</button>
      <button class="btn" onclick="addOfflineMission('sleep','battery_below',20)">Sleep Batt &lt; 20%</button>
    </div>
    <div class="row">
      <input type="text" id="guardian-cmd" placeholder="Offline rule command (e.g. close chrome, mute, sleep)" />
      <input type="number" id="guardian-mins" value="10" style="max-width:85px" placeholder="Mins" />
      <button class="btn quantum" onclick="addOfflineMission(document.getElementById('guardian-cmd').value, 'timer_minutes', document.getElementById('guardian-mins').value)">Set Timer</button>
    </div>
  </div>

  <div class="card">
    <h3>100km Zero-Internet SMS &amp; LoRa Packet Generator (ULT1 Ratchet)</h3>
    <div class="row">
      <input type="text" id="offgrid-phone" placeholder="Relay Phone Number" />
      <input type="text" id="offgrid-cmd" placeholder="Command (e.g. lock laptop, mute, volume 40)" />
    </div>
    <div class="grid" style="margin-top:8px">
      <button class="btn quantum" onclick="sendOffGridSms()">Send SMS Packet</button>
      <button class="btn primary" onclick="copyOffGridLoRa()">Copy LoRa Packet</button>
      <button class="btn" onclick="testOffGridLocal()">Test ULT1 Packet</button>
    </div>
  </div>
</div>

<div id="panel-chat" class="panel">
  <div class="card">
    <h3>Talk to ULTIMATE (Online Groq Failover Core + 100% Offline Engine)</h3>
    <div id="chat-log" class="chat-log">
      <div class="msg bot">I am ULTIMATE. I operate both ONLINE (using openai/gpt-oss-120b with automatic multi-model failover) and 100% OFFLINE (via the Zero-Internet Natural Language Command Engine).</div>
    </div>
    <div class="row">
      <input type="text" id="chat-input" placeholder="Command ULTIMATE..." onkeydown="if(event.key==='Enter') sendChat()" />
      <button class="btn quantum" onclick="sendChat()">Send</button>
    </div>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
  (function() {
    const params = new URLSearchParams(window.location.search);
    const key = params.get('api_key') || params.get('token');
    const rsec = params.get('rsec');
    if (key) localStorage.setItem('ult_api_key', key);
    if (rsec) localStorage.setItem('ult_ratchet_secret', rsec);
  })();

  window._ratchetStep = parseInt(localStorage.getItem('ult_ratchet_step') || '1', 10);

  async function sha256Hex(str) {
    const buf = new TextEncoder().encode(str);
    const hash = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('');
  }

  async function hmacSha256Hex(secretStr, messageStr) {
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey(
      'raw', enc.encode(secretStr), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
    );
    const sig = await crypto.subtle.sign('HMAC', key, enc.encode(messageStr));
    return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('');
  }

  function canonicalJson(obj) {
    const keys = Object.keys(obj).filter(k => obj[k] !== undefined && obj[k] !== null).sort();
    const out = {};
    for (const k of keys) out[k] = obj[k];
    return JSON.stringify(out);
  }

  async function getRatchetedHeaders(payloadObj) {
    const headers = { 'Content-Type': 'application/json' };
    const key = localStorage.getItem('ult_api_key') || '';
    if (key) headers['Authorization'] = 'Bearer ' + key;

    const rsec = localStorage.getItem('ult_ratchet_secret') || '';
    if (rsec && payloadObj && window.crypto && window.crypto.subtle) {
      const raw = canonicalJson(payloadObj);
      const bodyHash = await sha256Hex(raw);
      const ts = Math.floor(Date.now() / 1000);
      const step = window._ratchetStep++;
      localStorage.setItem('ult_ratchet_step', String(window._ratchetStep));
      const nonceBytes = new Uint8Array(12);
      window.crypto.getRandomValues(nonceBytes);
      const nonce = Array.from(nonceBytes).map(b => b.toString(16).padStart(2, '0')).join('');
      const msg = `${step}:${ts}:${nonce}:${bodyHash}`;
      const sig = await hmacSha256Hex(rsec, msg);
      headers['X-Ult-Nonce'] = nonce;
      headers['X-Ult-Ts'] = String(ts);
      headers['X-Ult-Step'] = String(step);
      headers['X-Ult-Sig'] = sig;
    }
    return headers;
  }

  function showToast(text, isErr) {
    const t = document.getElementById('toast');
    t.style.borderLeftColor = isErr ? 'var(--danger)' : 'var(--accent)';
    t.textContent = text;
    t.style.display = 'block';
    clearTimeout(window._toastTimer);
    window._toastTimer = setTimeout(() => { t.style.display = 'none'; }, 4000);
  }

  function switchTab(name, el) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('panel-' + name).classList.add('active');
    el.classList.add('active');
  }

  async function testLaptopVoice() {
    const headers = await getRatchetedHeaders(null);
    await fetch('/v1/control/speak', {
      method: 'POST', headers,
      body: JSON.stringify({ text: 'Hello. I am Ultimate. Laptop audio and voice systems are online.' })
    });
    showToast('Spoke greeting on laptop speakers.');
  }

  async function laptopCmd(payload) {
    try {
      const clean = JSON.parse(canonicalJson(payload));
      const headers = await getRatchetedHeaders(clean);
      const r = await fetch('/v1/control/laptop', {
        method: 'POST', headers, body: JSON.stringify(clean)
      });
      const data = await r.json();
      if (data.ratchet_proof) {
        document.getElementById('ratchet-badge').textContent = 'UTA-QRP ' + data.ratchet_proof.slice(0, 6);
      }
      showToast(data.content || data.detail || JSON.stringify(data), !data.success);
      return data;
    } catch (e) {
      try {
        const q = JSON.parse(localStorage.getItem('ult_offline_queue') || '[]');
        q.push({ payload, queued_at: Date.now() });
        localStorage.setItem('ult_offline_queue', JSON.stringify(q));
        showToast(`Offline Vault: Queued '${payload.action}' (${q.length} pending).`);
      } catch (eq) {
        showToast('Offline: ' + e.message, true);
      }
    }
  }

  async function phoneCmd(payload) {
    try {
      const clean = JSON.parse(canonicalJson(payload));
      const headers = await getRatchetedHeaders(clean);
      const r = await fetch('/v1/control/phone', {
        method: 'POST', headers, body: JSON.stringify(clean)
      });
      const data = await r.json();
      if (data.ratchet_proof) {
        document.getElementById('ratchet-badge').textContent = 'UTA-QRP ' + data.ratchet_proof.slice(0, 6);
      }
      showToast(data.content || data.detail || JSON.stringify(data), !data.success);
      return data;
    } catch (e) {
      showToast('Error: ' + e.message, true);
    }
  }

  (function() {
    const pad = document.getElementById('touchpad');
    let lastX = null, lastY = null, moved = false;
    pad.addEventListener('pointerdown', (e) => {
      lastX = e.clientX; lastY = e.clientY; moved = false;
      pad.setPointerCapture(e.pointerId);
    });
    pad.addEventListener('pointermove', (e) => {
      if (lastX === null) return;
      const dx = Math.round((e.clientX - lastX) * 2.2);
      const dy = Math.round((e.clientY - lastY) * 2.2);
      if (Math.abs(dx) > 6 || Math.abs(dy) > 6) {
        moved = true;
        lastX = e.clientX; lastY = e.clientY;
        laptopCmd({action: 'mouse_delta', x: dx, y: dy});
      }
    });
    pad.addEventListener('pointerup', () => {
      if (lastX !== null && !moved) laptopCmd({action: 'mouse_click', value: 'left'});
      lastX = null; lastY = null;
    });
  })();

  async function loadOpenWindows() {
    const data = await laptopCmd({action: 'list_windows'});
    const box = document.getElementById('windows-list');
    try {
      let wins = JSON.parse(data.content || '[]');
      if (!Array.isArray(wins)) wins = [wins];
      if (!wins.length) {
        box.innerHTML = '<div class="item-row"><span>No open desktop windows</span></div>';
        return;
      }
      box.innerHTML = wins.map(w => {
        const title = (w.MainWindowTitle || w.ProcessName || '').replace(/'/g, '');
        const proc = (w.ProcessName || '').replace(/'/g, '');
        return `<div class="item-row">
          <span style="max-width:55%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><b>${proc}</b>: ${title}</span>
          <div style="display:flex;gap:4px">
            <button class="btn primary" style="padding:4px 8px;font-size:0.72rem" onclick="laptopCmd({action:'focus_window',target:'${title}',value:'focus'})">Focus</button>
            <button class="btn" style="padding:4px 8px;font-size:0.72rem" onclick="laptopCmd({action:'focus_window',target:'${title}',value:'minimize'})">Min</button>
            <button class="btn danger" style="padding:4px 8px;font-size:0.72rem" onclick="laptopCmd({action:'close_app',target:'${proc}'})">Close</button>
          </div>
        </div>`;
      }).join('');
    } catch (e) {}
  }

  async function loadFiles(dirPath) {
    const data = await laptopCmd({action: 'list_files', target: dirPath});
    const box = document.getElementById('files-list');
    if (!data || !data.metadata || !data.metadata.items) return;
    const m = data.metadata;
    const parentEsc = (m.parent || '').replace(/\\\\/g, '/');
    let html = `<div class="item-row" style="background:#162238">
      <span><b>${m.directory}</b></span>
      <button class="btn" style="padding:4px 8px;font-size:0.72rem" onclick="loadFiles('${parentEsc}')">Up</button>
    </div>`;
    for (const item of m.items) {
      const p = item.path.replace(/\\\\/g, '/').replace(/'/g, '');
      if (item.is_dir) {
        html += `<div class="item-row"><span>[DIR] ${item.name}</span><button class="btn primary" style="padding:4px 8px;font-size:0.72rem" onclick="loadFiles('${p}')">Browse</button></div>`;
      } else {
        html += `<div class="item-row"><span>${item.name} <small style="color:var(--muted)">(${item.size_kb} KB)</small></span><button class="btn" style="padding:4px 8px;font-size:0.72rem" onclick="laptopCmd({action:'open_app',target:'${p}'})">Open on PC</button></div>`;
      }
    }
    box.innerHTML = html;
  }

  async function toggleAirGap(enable) {
    const headers = await getRatchetedHeaders(null);
    const r = await fetch('/v1/control/airgap', { method: 'POST', headers, body: JSON.stringify({enable}) });
    const d = await r.json();
    showToast(d.message);
    refreshStatus();
  }

  function beamAudioTone(freqHz, label) {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const now = ctx.currentTime;
    const osc1 = ctx.createOscillator(), gain1 = ctx.createGain();
    osc1.type = 'sine'; osc1.frequency.setValueAtTime(2450, now); gain1.gain.setValueAtTime(0.85, now);
    osc1.connect(gain1); gain1.connect(ctx.destination);
    osc1.start(now); osc1.stop(now + 0.35);

    const osc2 = ctx.createOscillator(), gain2 = ctx.createGain();
    osc2.type = 'sine'; osc2.frequency.setValueAtTime(freqHz, now + 0.40); gain2.gain.setValueAtTime(0.85, now + 0.40);
    osc2.connect(gain2); gain2.connect(ctx.destination);
    osc2.start(now + 0.40); osc2.stop(now + 0.85);
    setTimeout(() => ctx.close(), 1000);
    showToast(`Beamed Air-Gap Packet: ${label} (2450Hz -> ${freqHz}Hz)`);
  }

  async function buildUlt1Packet(cmdText) {
    const rsec = localStorage.getItem('ult_ratchet_secret') || '';
    const step = window._ratchetStep++;
    localStorage.setItem('ult_ratchet_step', String(window._ratchetStep));
    const ts = Math.floor(Date.now() / 1000);
    const nb = new Uint8Array(6); window.crypto.getRandomValues(nb);
    const nonce = Array.from(nb).map(b => b.toString(16).padStart(2, '0')).join('');
    const msg = `${step}:${ts}:${nonce}:${cmdText}`;
    const fullSig = await hmacSha256Hex(rsec, msg);
    return `ULT1:${step}:${ts}:${nonce}:${fullSig.slice(0, 16)}:${cmdText}`;
  }

  async function sendOffGridSms() {
    const num = document.getElementById('offgrid-phone').value.trim();
    const cmd = document.getElementById('offgrid-cmd').value.trim() || 'lock laptop';
    const pkt = await buildUlt1Packet(cmd);
    window.location.href = `sms:${num}?body=${encodeURIComponent(pkt)}`;
  }

  async function copyOffGridLoRa() {
    const cmd = document.getElementById('offgrid-cmd').value.trim() || 'lock laptop';
    const pkt = await buildUlt1Packet(cmd);
    try { await navigator.clipboard.writeText(pkt); } catch (e) {}
    showToast('Copied Off-Grid Packet:\\n' + pkt);
  }

  async function testOffGridLocal() {
    const cmd = document.getElementById('offgrid-cmd').value.trim() || 'status';
    const pkt = await buildUlt1Packet(cmd);
    const headers = await getRatchetedHeaders(null);
    const r = await fetch('/v1/control/offgrid-packet', { method: 'POST', headers, body: JSON.stringify({ packet: pkt }) });
    const d = await r.json();
    showToast(`ULT1 Verified [${d.success}]:\\n${d.reply}`, !d.success);
  }

  async function setAutoLock(mins) {
    const headers = await getRatchetedHeaders(null);
    const r = await fetch('/v1/control/guardian', {
      method: 'POST', headers, body: JSON.stringify({ action: 'set_autolock', trigger_value: parseInt(mins, 10) })
    });
    const d = await r.json(); showToast(d.message);
  }

  async function addOfflineMission(cmd, triggerType, val) {
    if (!cmd) return;
    const headers = await getRatchetedHeaders(null);
    const r = await fetch('/v1/control/guardian', {
      method: 'POST', headers,
      body: JSON.stringify({ action: 'add', command: cmd, trigger_type: triggerType, trigger_value: parseInt(val, 10) || 5 })
    });
    const d = await r.json(); showToast(d.message);
  }

  function ringThisPhone() {
    if (navigator.vibrate) navigator.vibrate([500, 200, 500, 200, 800]);
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.type = 'sawtooth'; osc.frequency.setValueAtTime(880, ctx.currentTime); gain.gain.setValueAtTime(0.5, ctx.currentTime);
      osc.connect(gain); gain.connect(ctx.destination); osc.start();
      setTimeout(() => { osc.stop(); ctx.close(); }, 1800);
    } catch (e) {}
    showToast('Phone siren and vibration triggered.');
  }

  async function syncPhoneCompanionBridge() {
    try {
      let battPct = null, charging = null;
      if (navigator.getBattery) {
        const b = await navigator.getBattery(); battPct = Math.round(b.level * 100); charging = b.charging;
      }
      const conn = navigator.connection || {};
      const payload = {
        battery_percent: battPct, charging: charging,
        network: conn.effectiveType ? `${conn.effectiveType.toUpperCase()}` : 'Direct Radio',
        user_agent: navigator.userAgent.slice(0, 80),
        screen: `${window.screen.width}x${window.screen.height}`
      };
      const headers = await getRatchetedHeaders(null);
      const r = await fetch('/v1/control/phone-bridge/sync', { method: 'POST', headers, body: JSON.stringify(payload) });
      const d = await r.json();
      try {
        const q = JSON.parse(localStorage.getItem('ult_offline_queue') || '[]');
        if (q.length > 0) {
          localStorage.setItem('ult_offline_queue', '[]');
          for (const item of q) await laptopCmd(item.payload);
        }
      } catch (eq) {}
      if (d.commands && d.commands.length) {
        for (const cmd of d.commands) {
          if (cmd.type === 'ring' || cmd.type === 'find_phone') ringThisPhone();
          else if (cmd.type === 'open_url' && cmd.url) window.location.href = cmd.url;
        }
      }
    } catch (e) {}
  }

  async function refreshStatus() {
    try {
      const headers = await getRatchetedHeaders(null);
      const r = await fetch('/v1/control/status', { headers });
      const d = await r.json();
      if (d.enclave) {
        const e = d.enclave;
        const links = (e.offline_radio_links || []).map(l => `${l.interface}: ${l.ip}`).join(' | ') || 'Localhost';
        document.getElementById('enclave-stats').innerHTML =
          `<div class="pill"><span>1. Windows Account (DPAPI Sealed)</span>${e.windows_user} | ${e.anchor_fingerprint.slice(0,12)}</div>` +
          `<div class="pill"><span>2. Offline Direct Radio Links</span>${links}</div>` +
          `<div class="pill"><span>3. Air-Gap Audio Receiver</span>${e.airgap_running ? 'Listening' : 'Standby'} (Last: ${e.airgap_last})</div>` +
          `<div class="pill"><span>4. Global 100km+ Tunnel</span>${e.global_tunnel_url || 'Local Direct Mode'}</div>`;
      }
      if (d.laptop) {
        const l = d.laptop;
        document.getElementById('laptop-stats').innerHTML =
          `<div class="pill"><span>CPU / RAM</span>CPU ${l.cpu_percent ?? '?'}% | RAM ${l.ram_used_gb ?? '?'}/${l.ram_total_gb ?? '?'} GB (${l.ram_percent ?? '?'}%)</div>` +
          `<div class="pill"><span>Battery / Active Window</span>${l.battery_percent ?? '?'}% | ${l.active_window || 'Desktop'}</div>`;
      }
    } catch (e) {}
  }

  window._micRecording = false;
  window._mediaRecorder = null;
  window._audioChunks = [];

  async function sendVoiceTranscriptToLaptop(transcriptText, audioBase64) {
    const statusEl = document.getElementById('mic-status-text');
    statusEl.textContent = 'Sending voice command to ULTIMATE...';
    const headers = await getRatchetedHeaders(null);
    try {
      const r = await fetch('/v1/control/voice-audio', {
        method: 'POST', headers,
        body: JSON.stringify({ transcript: transcriptText || null, audio_base64: audioBase64 || null, speak_on_laptop: true })
      });
      const d = await r.json();
      statusEl.textContent = `Heard: "${d.transcript || transcriptText}" -> Laptop spoke reply.`;
      showToast('ULTIMATE: ' + (d.reply || 'Done'), !d.success);
    } catch (e) {
      statusEl.textContent = 'Mic error: ' + e.message;
      showToast('Voice command error: ' + e.message, true);
    }
  }

  async function togglePhoneMic() {
    const btn = document.getElementById('phone-mic-btn');
    const statusEl = document.getElementById('mic-status-text');
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (SpeechRec && !window._micRecording && (!navigator.mediaDevices || !window.isSecureContext)) {
      const rec = new SpeechRec();
      rec.lang = 'en-US'; rec.interimResults = false;
      btn.textContent = 'Listening...'; btn.className = 'btn danger';
      statusEl.textContent = 'Speak into your phone microphone now...';
      rec.onresult = (ev) => sendVoiceTranscriptToLaptop(ev.results[0][0].transcript, null);
      rec.onerror = () => {
        const manual = prompt('Dictate command using your phone keyboard microphone:');
        if (manual) sendVoiceTranscriptToLaptop(manual, null);
      };
      rec.onend = () => { btn.textContent = 'Tap to Speak'; btn.className = 'btn primary'; };
      rec.start();
      return;
    }

    if (window._micRecording && window._mediaRecorder) {
      window._mediaRecorder.stop(); window._micRecording = false;
      btn.textContent = 'Tap to Speak'; btn.className = 'btn primary';
      return;
    }

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        window._audioChunks = [];
        const mr = new MediaRecorder(stream);
        window._mediaRecorder = mr; window._micRecording = true;
        btn.textContent = 'Tap When Done'; btn.className = 'btn danger';
        statusEl.textContent = 'Recording from phone mic... Tap button again to send.';
        mr.ondataavailable = (e) => { if (e.data.size > 0) window._audioChunks.push(e.data); };
        mr.onstop = () => {
          stream.getTracks().forEach(t => t.stop());
          const blob = new Blob(window._audioChunks, { type: 'audio/webm' });
          const reader = new FileReader();
          reader.onloadend = () => sendVoiceTranscriptToLaptop(null, reader.result);
          reader.readAsDataURL(blob);
        };
        mr.start();
        return;
      } catch (err) {}
    }

    const dictated = prompt('Tap your phone keyboard microphone key and speak to ULTIMATE:');
    if (dictated && dictated.trim()) sendVoiceTranscriptToLaptop(dictated.trim(), null);
  }

  async function sendChat() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    const log = document.getElementById('chat-log');
    log.innerHTML += `<div class="msg user">${text.replace(/</g,'&lt;')}</div>`;
    const botDiv = document.createElement('div');
    botDiv.className = 'msg bot'; botDiv.textContent = 'Executing...';
    log.appendChild(botDiv); log.scrollTop = log.scrollHeight;

    const headers = await getRatchetedHeaders(null);
    try {
      const r = await fetch('/v1/chat/completions', {
        method: 'POST', headers,
        body: JSON.stringify({ model: 'openai/gpt-oss-120b', messages: [{ role: 'user', content: text }], stream: false })
      });
      if (!r.ok) throw new Error('Cloud LLM unreachable');
      const data = await r.json();
      const reply = (data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content) || '';
      if (!reply) throw new Error('Empty reply');
      botDiv.textContent = reply;
    } catch (err) {
      try {
        const rOff = await fetch('/v1/control/offline-chat', {
          method: 'POST', headers, body: JSON.stringify({ prompt: text })
        });
        const dOff = await rOff.json();
        botDiv.textContent = dOff.reply || 'Executed offline.';
      } catch (e2) {
        botDiv.textContent = 'Error: ' + e2.message;
      }
    }
    log.scrollTop = log.scrollHeight;
  }

  syncPhoneCompanionBridge();
  setInterval(syncPhoneCompanionBridge, 5000);
  refreshStatus();
</script>
</body>
</html>
"""


@router.get("/remote", response_class=HTMLResponse)
@router.get("/control", response_class=HTMLResponse)
@router.get("/ultimate", response_class=HTMLResponse)
async def remote_control_page() -> HTMLResponse:
    """Serve the Direct Screenshot-Free ULTIMATE Control Center."""
    return HTMLResponse(content=_REMOTE_HTML)


__all__ = ["get_remote_phone_state", "queue_remote_phone_command", "router"]

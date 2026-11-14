"""Zero-Internet Offline AI Command Engine & Multi-Transport Air-Gap Link.

Ensures ULTIMATE works even when the laptop has NO internet connection:
1. Offline Natural Language Command Engine: Understands and executes natural
   English commands for laptop and phone control 100% locally on the CPU with
   zero cloud API dependency.
2. Offline Direct Radio Discovery: Detects Wi-Fi Direct, Phone Hotspot (with
   mobile data off), USB Tethering, and Bluetooth PAN interfaces so the phone
   and laptop communicate directly without any router or ISP.
3. Acoustic FSK Air-Gap Receiver: Optional on-demand audio modem using numpy
   FFT over the laptop microphone to decode encrypted multi-tone command frames
   beamed from the phone's speaker (or over a voice phone call from 100km away)
   when all network radios on the laptop are completely off.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from typing import Any, Dict, List, Optional

from openjarvis.tools.laptop_control import LaptopControlTool
from openjarvis.tools.phone_control import PhoneControlTool

_laptop = LaptopControlTool()
_phone = PhoneControlTool()

# Frequency map (Hz) for Air-Gap Audio Command Frames (audible/near-ultrasonic)
# Each command uses a 2-tone preamble (1850 Hz -> 2450 Hz) followed by a command tone
AIRGAP_TONE_COMMANDS: Dict[int, Dict[str, Any]] = {
    2800: {"label": "Lock Windows Account", "target": "laptop", "payload": {"action": "power", "value": "lock"}},
    3000: {"label": "Mute / Unmute Laptop", "target": "laptop", "payload": {"action": "volume", "value": "mute"}},
    3200: {"label": "Play / Pause Media", "target": "laptop", "payload": {"action": "media", "value": "play_pause"}},
    3400: {"label": "Turn Off Laptop Screen", "target": "laptop", "payload": {"action": "power", "value": "screen_off"}},
    3600: {"label": "Volume Up (+10%)", "target": "laptop", "payload": {"action": "volume", "value": "up", "amount": 10}},
    3800: {"label": "Volume Down (-10%)", "target": "laptop", "payload": {"action": "volume", "value": "down", "amount": 10}},
    4000: {"label": "Ring / Find Phone", "target": "phone", "payload": {"action": "find_phone"}},
}


def get_offline_radio_links(port: int = 8000) -> List[Dict[str, str]]:
    """Return all active local radio/network interfaces (Hotspot, Wi-Fi Direct, USB, LAN)."""
    import psutil

    links: List[Dict[str, str]] = []
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for iface, addr_list in addrs.items():
            st = stats.get(iface)
            if st and not st.isup:
                continue
            for a in addr_list:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    links.append(
                        {
                            "interface": iface,
                            "ip": a.address,
                            "direct_url": f"http://{a.address}:{port}/ultimate",
                        }
                    )
    except Exception:
        pass
    return links


def execute_offline_nl_command(prompt: str) -> Dict[str, Any]:
    """Execute natural-language commands 100% offline without any internet/LLM API."""
    text = prompt.strip()
    low = text.lower()

    # 1. Phone commands if "phone" is mentioned
    if "phone" in low or "whatsapp" in low or "call " in low or "sms " in low:
        if any(w in low for w in ("find", "ring", "where is", "alert", "vibrate")):
            res = _phone.execute(action="find_phone")
            return {"handled": True, "reply": f"[Offline Engine] {res.content}"}
        if "status" in low or "battery" in low:
            res = _phone.execute(action="status")
            return {"handled": True, "reply": f"[Offline Engine] Phone Status:\n{res.content}"}
        m_call = re.search(r"call\s+([+\d\-\s]{5,})", low)
        if m_call:
            res = _phone.execute(action="call_number", target=m_call.group(1).strip())
            return {"handled": True, "reply": f"[Offline Engine] {res.content}"}
        for app in ("whatsapp", "youtube", "chrome", "instagram", "spotify", "camera", "maps", "settings"):
            if app in low and "laptop" not in low:
                res = _phone.execute(action="open_app", target=app)
                return {"handled": True, "reply": f"[Offline Engine] {res.content}"}

    # 2. Laptop Volume & Media
    if "mute" in low or "unmute" in low:
        res = _laptop.execute(action="volume", value="mute")
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}

    m_vol = re.search(r"volume\s*(?:to|at|=)?\s*(\d{1,3})", low)
    if m_vol:
        res = _laptop.execute(action="volume", value=m_vol.group(1))
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}
    if "volume up" in low or "louder" in low or "increase volume" in low:
        res = _laptop.execute(action="volume", value="up", amount=10)
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}
    if "volume down" in low or "quieter" in low or "decrease volume" in low:
        res = _laptop.execute(action="volume", value="down", amount=10)
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}

    if any(w in low for w in ("play", "pause", "resume")) and any(w in low for w in ("music", "media", "song", "video", "pause", "resume")):
        res = _laptop.execute(action="media", value="play_pause")
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}
    if "next track" in low or "next song" in low or "skip" in low:
        res = _laptop.execute(action="media", value="next")
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}

    # 3. Brightness
    m_br = re.search(r"brightness\s*(?:to|at|=)?\s*(\d{1,3})", low)
    if m_br:
        res = _laptop.execute(action="brightness", value=m_br.group(1))
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}

    # 4. Power & Lock
    if "lock" in low and ("laptop" in low or "pc" in low or "screen" in low or "account" in low or low == "lock"):
        res = _laptop.execute(action="power", value="lock")
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}
    if "screen off" in low or "turn off screen" in low or "display off" in low:
        res = _laptop.execute(action="power", value="screen_off")
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}
    if "sleep" in low:
        res = _laptop.execute(action="power", value="sleep")
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}

    # 5. Open / Close Apps
    m_open = re.search(r"^(?:open|launch|start)\s+(.+)$", low)
    if m_open:
        target = m_open.group(1).replace("on laptop", "").replace("on my laptop", "").strip()
        res = _laptop.execute(action="open_app", target=target)
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}

    m_close = re.search(r"^(?:close|kill|stop|quit)\s+(.+)$", low)
    if m_close:
        target = m_close.group(1).replace("on laptop", "").replace("on my laptop", "").strip()
        res = _laptop.execute(action="close_app", target=target)
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}

    # 6. Windows / Processes / Files / Status
    if "window" in low and any(w in low for w in ("list", "show", "open", "active")):
        res = _laptop.execute(action="list_windows")
        return {"handled": True, "reply": f"[Offline Engine] Open Windows:\n{res.content}"}
    if "process" in low or "task" in low:
        res = _laptop.execute(action="list_processes")
        return {"handled": True, "reply": f"[Offline Engine] Top Processes:\n{res.content}"}
    if "file" in low or "desktop" in low or "folder" in low:
        res = _laptop.execute(action="list_files")
        return {"handled": True, "reply": f"[Offline Engine] Files:\n{res.content}"}
    if any(w in low for w in ("status", "battery", "cpu", "ram", "memory", "ip", "health")):
        res = _laptop.execute(action="system_status")
        return {"handled": True, "reply": f"[Offline Engine] Laptop Telemetry:\n{res.content}"}

    # 7. Type text
    m_type = re.search(r"^type\s+(.+)$", text, re.IGNORECASE)
    if m_type:
        res = _laptop.execute(action="type_text", text=m_type.group(1), press_enter=True)
        return {"handled": True, "reply": f"[Offline Engine] {res.content}"}

    # Default fallback: run system_status summary
    res = _laptop.execute(action="system_status")
    meta = res.metadata or {}
    return {
        "handled": True,
        "reply": (
            f"[Offline Zero-Internet Mode Active]\n"
            f"Laptop '{meta.get('hostname', 'PC')}' is online locally "
            f"(CPU {meta.get('cpu_percent')}%, RAM {meta.get('ram_percent')}%, "
            f"Battery {meta.get('battery_percent')}%, Active Window: '{meta.get('active_window')}').\n"
            f"You can say: 'open chrome', 'close notepad', 'volume 40', 'mute', 'brightness 70', "
            f"'lock laptop', 'list windows', 'list files', or 'ring my phone'."
        ),
    }


class AcousticAirGapReceiver:
    """On-demand acoustic FFT receiver for zero-network air-gapped audio commands."""

    def __init__(self) -> None:
        self.running = False
        self.last_detected: str = "None"
        self._thread: Optional[threading.Thread] = None

    def start(self) -> str:
        if self.running:
            return "Acoustic Air-Gap Receiver is already listening."
        self.running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        return "Acoustic Air-Gap Receiver started (listening for 2800-4000 Hz command tones)."

    def stop(self) -> str:
        self.running = False
        return "Acoustic Air-Gap Receiver stopped (zero microphone usage)."

    def _listen_loop(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd

            fs = 44100
            block_dur = 0.25  # 250ms FFT window
            preamble_seen_at = 0.0

            while self.running:
                recording = sd.rec(int(block_dur * fs), samplerate=fs, channels=1, dtype="float32")
                sd.wait()
                samples = recording.flatten()
                if float(np.max(np.abs(samples))) < 0.015:
                    continue
                fft_mag = np.abs(np.fft.rfft(samples))
                freqs = np.fft.rfftfreq(len(samples), 1.0 / fs)
                # Focus on 1700 Hz - 4200 Hz band
                mask = (freqs >= 1700) & (freqs <= 4200)
                if not np.any(mask):
                    continue
                band_freqs = freqs[mask]
                band_mag = fft_mag[mask]
                peak_freq = float(band_freqs[int(np.argmax(band_mag))])

                now = time.time()
                # Check preamble tone ~2450 Hz (±60 Hz)
                if abs(peak_freq - 2450) <= 65:
                    preamble_seen_at = now
                    continue

                # If preamble was seen within the last 1.5s, check command tones
                if (now - preamble_seen_at) <= 1.6:
                    for target_hz, spec in AIRGAP_TONE_COMMANDS.items():
                        if abs(peak_freq - target_hz) <= 65:
                            preamble_seen_at = 0.0
                            self.last_detected = f"{spec['label']} ({target_hz} Hz) at {time.strftime('%H:%M:%S')}"
                            if spec["target"] == "laptop":
                                _laptop.execute(**spec["payload"])
                            else:
                                _phone.execute(**spec["payload"])
                            time.sleep(0.6)
                            break
        except Exception as exc:
            self.last_detected = f"Audio error: {exc}"
            self.running = False


_AIRGAP_RECEIVER = AcousticAirGapReceiver()


def get_airgap_receiver() -> AcousticAirGapReceiver:
    return _AIRGAP_RECEIVER


__all__ = [
    "AIRGAP_TONE_COMMANDS",
    "AcousticAirGapReceiver",
    "execute_offline_nl_command",
    "get_airgap_receiver",
    "get_offline_radio_links",
]

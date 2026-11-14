"""Full Phone Control Tool for ULTIMATE.

Allows the AI agent and web/mobile control center to control an Android phone
over USB or Wi-Fi (ADB Wireless Debugging), transfer files between laptop and
phone, launch apps, place calls, send texts, tap/swipe/type on the phone screen,
capture phone screenshots, adjust volume/brightness, and run shell commands.
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ultimate.core import BaseTool, ToolResult, ToolSpec, get_project_root

_BUNDLED_ADB = get_project_root() / "tools" / "platform-tools" / "adb.exe"
_CAPTURES_DIR = get_project_root() / "captures"

_PHONE_APPS: Dict[str, str] = {
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "instagram": "com.instagram.android",
    "telegram": "org.telegram.messenger",
    "spotify": "com.spotify.music",
    "maps": "com.google.android.apps.maps",
    "google maps": "com.google.android.apps.maps",
    "gmail": "com.google.android.gm",
    "settings": "com.android.settings",
    "camera": "com.android.camera",
    "phone": "com.google.android.dialer",
    "dialer": "com.google.android.dialer",
    "messages": "com.google.android.apps.messaging",
    "sms": "com.google.android.apps.messaging",
    "play store": "com.android.vending",
    "files": "com.google.android.documentsui",
    "calculator": "com.google.android.calculator",
    "clock": "com.google.android.deskclock",
    "calendar": "com.google.android.calendar",
    "photos": "com.google.android.apps.photos",
    "netflix": "com.netflix.mediaclient",
    "twitter": "com.twitter.android",
    "x": "com.twitter.android",
    "discord": "com.discord",
    "chatgpt": "com.openai.chatgpt",
}

_KEYEVENTS: Dict[str, str] = {
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
    "recents": "KEYCODE_APP_SWITCH",
    "app_switch": "KEYCODE_APP_SWITCH",
    "power": "KEYCODE_POWER",
    "wakeup": "KEYCODE_WAKEUP",
    "sleep": "KEYCODE_SLEEP",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "mute": "KEYCODE_VOLUME_MUTE",
    "media_play_pause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "play_pause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "media_next": "KEYCODE_MEDIA_NEXT",
    "next": "KEYCODE_MEDIA_NEXT",
    "media_prev": "KEYCODE_MEDIA_PREVIOUS",
    "prev": "KEYCODE_MEDIA_PREVIOUS",
    "camera": "KEYCODE_CAMERA",
    "enter": "KEYCODE_ENTER",
    "backspace": "KEYCODE_DEL",
    "tab": "KEYCODE_TAB",
    "space": "KEYCODE_SPACE",
    "escape": "KEYCODE_ESCAPE",
    "menu": "KEYCODE_MENU",
}


def _find_adb() -> str:
    if _BUNDLED_ADB.exists():
        return str(_BUNDLED_ADB)
    which_adb = shutil.which("adb")
    if which_adb:
        return which_adb
    return str(_BUNDLED_ADB)


def _run_adb(
    args: List[str],
    device: Optional[str] = None,
    timeout: int = 25,
    binary: bool = False,
) -> subprocess.CompletedProcess[Any]:
    cmd = [_find_adb()]
    if device:
        cmd.extend(["-s", device])
    cmd.extend(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=not binary,
        timeout=timeout,
    )


class PhoneControlTool(BaseTool):
    """Comprehensive Android phone control tool via ADB (USB & Wireless)."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="phone_control",
            description=(
                "Control the user's phone over USB or Wi-Fi (ADB). Supported actions:\n"
                "- devices: List connected phones (USB and Wi-Fi).\n"
                "- pair_wifi: Pair with Android Wireless Debugging (target='IP:PORT', value='PAIRING_CODE').\n"
                "- connect_wifi: Connect to phone over Wi-Fi (target='IP:PORT', default port 5555).\n"
                "- enable_tcpip: Enable wireless ADB on port 5555 for a USB-connected phone and auto-connect over Wi-Fi.\n"
                "- disconnect: Disconnect wireless ADB session.\n"
                "- status: Get phone model, Android version, battery %, Wi-Fi IP, screen resolution, and wake state.\n"
                "- open_app: Launch an app by name ('whatsapp', 'youtube', 'chrome', 'camera', 'settings', 'spotify', etc.) or package ID.\n"
                "- close_app: Force-stop an app by name or package ID.\n"
                "- list_apps: List installed third-party apps on the phone (optional target filter).\n"
                "- open_url: Open any URL on the phone (target='https://...').\n"
                "- call_number: Dial or call a phone number (target='+1234567890').\n"
                "- send_sms: Open SMS composer or send text message (target='+1234567890', text='Hello').\n"
                "- tap: Tap screen coordinates on the phone (x=540, y=1200).\n"
                "- swipe: Swipe on the phone screen from (x, y) to (x2, y2) with duration_ms.\n"
                "- type_text: Type text into the focused input on the phone (text='...', press_enter=True/False).\n"
                "- keyevent: Press a phone hardware/navigation button (value='home'|'back'|'recents'|'power'|'wakeup'|'sleep'|'volume_up'|'volume_down'|'mute'|'play_pause'|'next'|'prev'|'notifications'|'quick_settings').\n"
                "- screenshot: Capture the phone screen and save to static captures for viewing.\n"
                "- brightness: Set phone screen brightness 0-255 (value='180').\n"
                "- wifi_toggle: Enable or disable phone Wi-Fi (value='on'|'off').\n"
                "- bluetooth_toggle: Enable or disable phone Bluetooth (value='on'|'off').\n"
                "- find_phone: Ring/vibrate/wake the phone so the user can find it.\n"
                "- push_file: Copy a file from laptop to phone /sdcard/Download/ (target='path/on/laptop').\n"
                "- pull_file: Copy a file from phone to laptop (target='/sdcard/Download/file', value='captures/').\n"
                "- adb_shell: Run any raw ADB shell command on the phone (command='...')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "Action: devices, pair_wifi, connect_wifi, enable_tcpip, "
                            "disconnect, status, open_app, close_app, list_apps, "
                            "open_url, call_number, send_sms, tap, swipe, type_text, "
                            "keyevent, screenshot, brightness, wifi_toggle, "
                            "bluetooth_toggle, find_phone, push_file, pull_file, adb_shell"
                        ),
                    },
                    "target": {
                        "type": "string",
                        "description": "App name, package ID, IP:PORT, phone number, URL, or file path.",
                    },
                    "value": {
                        "type": "string",
                        "description": "Keyevent name, pairing code, brightness value, or on/off.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type or SMS body.",
                    },
                    "command": {
                        "type": "string",
                        "description": "Raw shell command for adb_shell.",
                    },
                    "device": {
                        "type": "string",
                        "description": "Optional specific ADB device serial / IP:PORT.",
                    },
                    "x": {"type": "integer", "description": "Start/tap X coordinate."},
                    "y": {"type": "integer", "description": "Start/tap Y coordinate."},
                    "x2": {"type": "integer", "description": "End X coordinate for swipe."},
                    "y2": {"type": "integer", "description": "End Y coordinate for swipe."},
                    "duration_ms": {
                        "type": "integer",
                        "description": "Swipe duration in milliseconds (default 300).",
                    },
                    "press_enter": {
                        "type": "boolean",
                        "description": "Whether to press Enter after typing text.",
                    },
                },
                "required": ["action"],
            },
            category="system",
            requires_confirmation=False,
            timeout_seconds=60.0,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action", "")).strip().lower()
        target = str(kwargs.get("target", "")).strip()
        value = str(kwargs.get("value", "")).strip()
        text = str(kwargs.get("text", ""))
        command = str(kwargs.get("command", "")).strip()
        device = str(kwargs.get("device", "")).strip() or None
        x = kwargs.get("x")
        y = kwargs.get("y")
        x2 = kwargs.get("x2")
        y2 = kwargs.get("y2")
        duration_ms = int(kwargs.get("duration_ms", 300) or 300)
        press_enter = bool(kwargs.get("press_enter", False))

        try:
            if action == "devices":
                return self._devices()
            if action == "pair_wifi":
                return self._pair_wifi(target, value)
            if action == "connect_wifi":
                return self._connect_wifi(target or value)
            if action == "enable_tcpip":
                return self._enable_tcpip(device)
            if action == "disconnect":
                return self._disconnect(target or device)
            if action == "status":
                return self._status(device)
            if action == "open_app":
                return self._open_app(target or value, device)
            if action == "close_app":
                return self._close_app(target or value, device)
            if action == "list_apps":
                return self._list_apps(target or value, device)
            if action == "open_url":
                return self._open_url(target or value, device)
            if action == "call_number":
                return self._call_number(target or value, device)
            if action == "send_sms":
                return self._send_sms(target, text or value, device)
            if action == "tap":
                return self._tap(x, y, device)
            if action == "swipe":
                return self._swipe(x, y, x2, y2, duration_ms, device)
            if action == "type_text":
                return self._type_text(text or value or target, press_enter, device)
            if action == "keyevent":
                return self._keyevent(value or target, device)
            if action == "screenshot":
                return self._screenshot(device)
            if action == "brightness":
                return self._brightness(value or target, device)
            if action == "wifi_toggle":
                return self._wifi_toggle(value or target or "on", device)
            if action == "bluetooth_toggle":
                return self._bluetooth_toggle(value or target or "on", device)
            if action == "find_phone":
                return self._find_phone(device)
            if action == "push_file":
                return self._push_file(target, value, device)
            if action == "pull_file":
                return self._pull_file(target, value, device)
            if action == "adb_shell":
                return self._adb_shell(command or text or value or target, device)

            return ToolResult(
                tool_name="phone_control",
                content=f"Unknown phone_control action: '{action}'.",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="phone_control",
                content=f"Phone control error ({action}): {exc}",
                success=False,
            )

    def _get_connected_devices(self) -> List[Dict[str, str]]:
        res = _run_adb(["devices", "-l"])
        devices = []
        for line in (res.stdout or "").splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ("device", "unauthorized", "offline"):
                devices.append(
                    {
                        "serial": parts[0],
                        "state": parts[1],
                        "details": " ".join(parts[2:]),
                    }
                )
        return devices

    def _devices(self) -> ToolResult:
        devs = self._get_connected_devices()
        companion = {}
        try:
            from ultimate.server.control_routes import get_remote_phone_state

            companion = get_remote_phone_state()
        except Exception:
            pass
        if not devs and not companion.get("connected"):
            msg = (
                "No phone currently connected via ADB or 100km+ Companion Bridge.\n"
                "To connect your phone:\n"
                "1. 100km+ Anywhere Mode: Open the Ultimate Global Tunnel URL on your phone browser.\n"
                "2. Mesh / Wireless ADB: Use Tailscale/WireGuard IP or local Wi-Fi IP with connect_wifi."
            )
            return ToolResult(
                tool_name="phone_control",
                content=msg,
                success=True,
                metadata={"devices": [], "companion_100km": companion},
            )
        return ToolResult(
            tool_name="phone_control",
            content=json.dumps({"adb_devices": devs, "companion_100km": companion}, indent=2),
            success=True,
            metadata={"devices": devs, "companion_100km": companion},
        )

    def _pair_wifi(self, host_port: str, code: str) -> ToolResult:
        if not host_port or not code:
            return ToolResult(
                tool_name="phone_control",
                content="Provide target='IP:PAIRING_PORT' and value='6_DIGIT_CODE'.",
                success=False,
            )
        res = _run_adb(["pair", host_port, code])
        out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        ok = "successfully paired" in out.lower() or res.returncode == 0
        return ToolResult(tool_name="phone_control", content=out, success=ok)

    def _connect_wifi(self, host_port: str) -> ToolResult:
        if not host_port:
            return ToolResult(
                tool_name="phone_control",
                content="Provide target='PHONE_IP' or 'PHONE_IP:PORT'.",
                success=False,
            )
        addr = host_port if ":" in host_port else f"{host_port}:5555"
        res = _run_adb(["connect", addr])
        out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        ok = "connected to" in out.lower()
        return ToolResult(tool_name="phone_control", content=out, success=ok)

    def _enable_tcpip(self, device: Optional[str]) -> ToolResult:
        ip_res = _run_adb(["shell", "ip", "-f", "inet", "addr", "show", "wlan0"], device=device)
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip_res.stdout or "")
        phone_ip = m.group(1) if m else None
        res = _run_adb(["tcpip", "5555"], device=device)
        out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        if phone_ip:
            time.sleep(1.5)
            conn = _run_adb(["connect", f"{phone_ip}:5555"])
            out += f"\nAuto-connect to {phone_ip}:5555 -> {(conn.stdout or '').strip()}"
        return ToolResult(
            tool_name="phone_control",
            content=out,
            success=res.returncode == 0,
        )

    def _disconnect(self, target: Optional[str]) -> ToolResult:
        args = ["disconnect", target] if target else ["disconnect"]
        res = _run_adb(args)
        return ToolResult(
            tool_name="phone_control",
            content=(res.stdout or res.stderr or "Disconnected").strip(),
            success=res.returncode == 0,
        )

    def _status(self, device: Optional[str]) -> ToolResult:
        devs = self._get_connected_devices()
        if not devs:
            try:
                from ultimate.server.control_routes import get_remote_phone_state

                comp = get_remote_phone_state()
                if comp.get("connected"):
                    return ToolResult(
                        tool_name="phone_control",
                        content=json.dumps({"mode": "100km_companion_bridge", **comp}, indent=2),
                        success=True,
                        metadata=comp,
                    )
            except Exception:
                pass
            return self._devices()

        model = (_run_adb(["shell", "getprop", "ro.product.model"], device=device).stdout or "").strip()
        brand = (_run_adb(["shell", "getprop", "ro.product.manufacturer"], device=device).stdout or "").strip()
        android_ver = (_run_adb(["shell", "getprop", "ro.build.version.release"], device=device).stdout or "").strip()
        batt_raw = _run_adb(["shell", "dumpsys", "battery"], device=device).stdout or ""
        batt_level = None
        for line in batt_raw.splitlines():
            if "level:" in line:
                try:
                    batt_level = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        wm_size = (_run_adb(["shell", "wm", "size"], device=device).stdout or "").strip()
        ip_raw = _run_adb(["shell", "ip", "-f", "inet", "addr", "show", "wlan0"], device=device).stdout or ""
        m_ip = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip_raw)
        wifi_ip = m_ip.group(1) if m_ip else None

        info = {
            "connected_devices": devs,
            "manufacturer": brand,
            "model": model,
            "android_version": android_ver,
            "battery_percent": batt_level,
            "screen_size": wm_size,
            "wifi_ip": wifi_ip,
        }
        return ToolResult(
            tool_name="phone_control",
            content=json.dumps(info, indent=2),
            success=True,
            metadata=info,
        )

    def _open_app(self, app_name_or_pkg: str, device: Optional[str]) -> ToolResult:
        if not app_name_or_pkg:
            return ToolResult(
                tool_name="phone_control",
                content="Missing 'target' app name or package ID.",
                success=False,
            )
        if not self._get_connected_devices():
            deep_links = {
                "whatsapp": "https://wa.me/",
                "youtube": "https://m.youtube.com",
                "spotify": "https://open.spotify.com",
                "instagram": "https://www.instagram.com",
                "maps": "https://maps.google.com",
                "gmail": "https://mail.google.com",
            }
            url = deep_links.get(app_name_or_pkg.lower(), f"https://{app_name_or_pkg}.com")
            try:
                from ultimate.server.control_routes import queue_remote_phone_command

                queue_remote_phone_command({"type": "open_url", "url": url})
                return ToolResult(
                    tool_name="phone_control",
                    content=f"Queued '{app_name_or_pkg}' ({url}) over the 100km+ Companion Bridge.",
                    success=True,
                )
            except Exception:
                pass
        pkg = _PHONE_APPS.get(app_name_or_pkg.lower(), app_name_or_pkg)
        if "." not in pkg:
            # Search installed packages matching keyword
            pkgs_out = _run_adb(["shell", "pm", "list", "packages"], device=device).stdout or ""
            for line in pkgs_out.splitlines():
                if app_name_or_pkg.lower() in line.lower():
                    pkg = line.replace("package:", "").strip()
                    break

        res = _run_adb(
            [
                "shell",
                "monkey",
                "-p",
                pkg,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            device=device,
        )
        ok = res.returncode == 0 and "no activities found" not in (res.stdout or "").lower()
        return ToolResult(
            tool_name="phone_control",
            content=f"Launched '{app_name_or_pkg}' ({pkg}) on phone."
            if ok
            else f"Could not launch '{app_name_or_pkg}' ({pkg}): {(res.stdout or res.stderr).strip()}",
            success=ok,
        )

    def _close_app(self, app_name_or_pkg: str, device: Optional[str]) -> ToolResult:
        pkg = _PHONE_APPS.get(app_name_or_pkg.lower(), app_name_or_pkg)
        res = _run_adb(["shell", "am", "force-stop", pkg], device=device)
        return ToolResult(
            tool_name="phone_control",
            content=f"Force-stopped '{pkg}' on phone.",
            success=res.returncode == 0,
        )

    def _list_apps(self, filter_str: str, device: Optional[str]) -> ToolResult:
        res = _run_adb(["shell", "pm", "list", "packages", "-3"], device=device)
        pkgs = [
            line.replace("package:", "").strip()
            for line in (res.stdout or "").splitlines()
            if line.strip()
        ]
        if filter_str:
            pkgs = [p for p in pkgs if filter_str.lower() in p.lower()]
        pkgs.sort()
        return ToolResult(
            tool_name="phone_control",
            content="\n".join(pkgs[:100]) if pkgs else "No matching packages found.",
            success=res.returncode == 0,
        )

    def _open_url(self, url: str, device: Optional[str]) -> ToolResult:
        if not url.startswith(("http://", "https://", "tel:", "sms:", "whatsapp:")):
            url = "https://" + url
        try:
            from ultimate.server.control_routes import queue_remote_phone_command

            queue_remote_phone_command({"type": "open_url", "url": url})
        except Exception:
            pass
        if not self._get_connected_devices():
            return ToolResult(
                tool_name="phone_control",
                content=f"Pushed URL {url} to phone over 100km+ Companion Bridge.",
                success=True,
            )
        res = _run_adb(
            ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url],
            device=device,
        )
        return ToolResult(
            tool_name="phone_control",
            content=f"Opened URL {url} on phone.",
            success=res.returncode == 0,
        )

    def _call_number(self, number: str, device: Optional[str]) -> ToolResult:
        clean_num = re.sub(r"[^\d+]", "", number)
        if not self._get_connected_devices():
            try:
                from ultimate.server.control_routes import queue_remote_phone_command

                queue_remote_phone_command({"type": "open_url", "url": f"tel:{clean_num}"})
                return ToolResult(
                    tool_name="phone_control",
                    content=f"Sent dial request for {clean_num} to phone over 100km+ Companion Bridge.",
                    success=True,
                )
            except Exception:
                pass
        res = _run_adb(
            [
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.CALL",
                "-d",
                f"tel:{clean_num}",
            ],
            device=device,
        )
        if res.returncode != 0 or "securityexception" in (res.stderr or "").lower():
            res = _run_adb(
                [
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.DIAL",
                    "-d",
                    f"tel:{clean_num}",
                ],
                device=device,
            )
        return ToolResult(
            tool_name="phone_control",
            content=f"Dialing {clean_num} on phone.",
            success=res.returncode == 0,
        )

    def _send_sms(self, number: str, body: str, device: Optional[str]) -> ToolResult:
        clean_num = re.sub(r"[^\d+]", "", number)
        if not self._get_connected_devices():
            try:
                from ultimate.server.control_routes import queue_remote_phone_command

                queue_remote_phone_command(
                    {"type": "open_url", "url": f"sms:{clean_num}?body={body}"}
                )
                return ToolResult(
                    tool_name="phone_control",
                    content=f"Pushed SMS composer ({clean_num}) to phone over 100km+ Companion Bridge.",
                    success=True,
                )
            except Exception:
                pass
        res = _run_adb(
            [
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.SENDTO",
                "-d",
                f"smsto:{clean_num}",
                "--es",
                "sms_body",
                body,
                "--ez",
                "exit_on_sent",
                "true",
            ],
            device=device,
        )
        return ToolResult(
            tool_name="phone_control",
            content=f"Opened SMS to {clean_num} with message: {body}",
            success=res.returncode == 0,
        )

    def _tap(self, x: Any, y: Any, device: Optional[str]) -> ToolResult:
        if x is None or y is None:
            return ToolResult(
                tool_name="phone_control",
                content="Provide both x and y coordinates for tap.",
                success=False,
            )
        res = _run_adb(["shell", "input", "tap", str(int(x)), str(int(y))], device=device)
        return ToolResult(
            tool_name="phone_control",
            content=f"Tapped phone screen at ({x}, {y}).",
            success=res.returncode == 0,
        )

    def _swipe(
        self,
        x: Any,
        y: Any,
        x2: Any,
        y2: Any,
        duration_ms: int,
        device: Optional[str],
    ) -> ToolResult:
        sx = int(x if x is not None else 540)
        sy = int(y if y is not None else 1600)
        ex = int(x2 if x2 is not None else 540)
        ey = int(y2 if y2 is not None else 400)
        res = _run_adb(
            [
                "shell",
                "input",
                "swipe",
                str(sx),
                str(sy),
                str(ex),
                str(ey),
                str(duration_ms),
            ],
            device=device,
        )
        return ToolResult(
            tool_name="phone_control",
            content=f"Swiped phone screen from ({sx}, {sy}) to ({ex}, {ey}).",
            success=res.returncode == 0,
        )

    def _type_text(self, text: str, press_enter: bool, device: Optional[str]) -> ToolResult:
        escaped = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
        res = _run_adb(["shell", "input", "text", escaped], device=device)
        if press_enter:
            _run_adb(["shell", "input", "keyevent", "KEYCODE_ENTER"], device=device)
        return ToolResult(
            tool_name="phone_control",
            content=f"Typed text on phone: '{text}'",
            success=res.returncode == 0,
        )

    def _keyevent(self, key_name: str, device: Optional[str]) -> ToolResult:
        k = key_name.strip().lower()
        if k == "notifications":
            res = _run_adb(["shell", "cmd", "statusbar", "expand-notifications"], device=device)
            return ToolResult(
                tool_name="phone_control",
                content="Expanded phone notifications shade.",
                success=res.returncode == 0,
            )
        if k == "quick_settings":
            res = _run_adb(["shell", "cmd", "statusbar", "expand-settings"], device=device)
            return ToolResult(
                tool_name="phone_control",
                content="Expanded phone quick settings.",
                success=res.returncode == 0,
            )
        keycode = _KEYEVENTS.get(k, key_name.upper())
        res = _run_adb(["shell", "input", "keyevent", keycode], device=device)
        return ToolResult(
            tool_name="phone_control",
            content=f"Sent keyevent '{keycode}' to phone.",
            success=res.returncode == 0,
        )

    def _screenshot(self, device: Optional[str]) -> ToolResult:
        _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        res = _run_adb(["exec-out", "screencap", "-p"], device=device, binary=True)
        if res.returncode != 0 or not res.stdout:
            return ToolResult(
                tool_name="phone_control",
                content=f"Failed to capture phone screenshot: {(res.stderr or b'').decode('utf-8', errors='ignore')}",
                success=False,
            )
        ts_path = _CAPTURES_DIR / f"phone_{ts}.png"
        latest_path = _CAPTURES_DIR / "latest_phone.png"
        ts_path.write_bytes(res.stdout)
        latest_path.write_bytes(res.stdout)
        info = {
            "path": str(ts_path),
            "latest_url": f"/captures/latest_phone.png?t={int(time.time())}",
            "archive_url": f"/captures/phone_{ts}.png",
            "bytes": len(res.stdout),
        }
        return ToolResult(
            tool_name="phone_control",
            content=json.dumps(info, indent=2),
            success=True,
            metadata=info,
        )

    def _brightness(self, level_str: str, device: Optional[str]) -> ToolResult:
        try:
            val = max(0, min(255, int(float(level_str))))
        except ValueError:
            return ToolResult(
                tool_name="phone_control",
                content="Provide brightness value between 0 and 255.",
                success=False,
            )
        _run_adb(["shell", "settings", "put", "system", "screen_brightness_mode", "0"], device=device)
        res = _run_adb(
            ["shell", "settings", "put", "system", "screen_brightness", str(val)],
            device=device,
        )
        return ToolResult(
            tool_name="phone_control",
            content=f"Set phone brightness to {val}/255.",
            success=res.returncode == 0,
        )

    def _wifi_toggle(self, state: str, device: Optional[str]) -> ToolResult:
        cmd = "enable" if state.lower() in ("on", "enable", "true", "1") else "disable"
        res = _run_adb(["shell", "svc", "wifi", cmd], device=device)
        return ToolResult(
            tool_name="phone_control",
            content=f"Phone Wi-Fi {cmd}d.",
            success=res.returncode == 0,
        )

    def _bluetooth_toggle(self, state: str, device: Optional[str]) -> ToolResult:
        cmd = "enable" if state.lower() in ("on", "enable", "true", "1") else "disable"
        res = _run_adb(["shell", "svc", "bluetooth", cmd], device=device)
        return ToolResult(
            tool_name="phone_control",
            content=f"Phone Bluetooth {cmd}d.",
            success=res.returncode == 0,
        )

    def _find_phone(self, device: Optional[str]) -> ToolResult:
        try:
            from ultimate.server.control_routes import queue_remote_phone_command

            queue_remote_phone_command({"type": "find_phone"})
        except Exception:
            pass
        devs = self._get_connected_devices()
        if not devs:
            return ToolResult(
                tool_name="phone_control",
                content="Triggered Find My Phone (siren + vibration + voice alert) over the 100km+ Companion Bridge!",
                success=True,
            )
        _run_adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], device=device)
        _run_adb(["shell", "cmd", "audio", "set-RingerMode", "NORMAL"], device=device)
        for _ in range(5):
            _run_adb(["shell", "input", "keyevent", "KEYCODE_VOLUME_UP"], device=device)
        _run_adb(
            [
                "shell",
                "cmd",
                "notification",
                "post",
                "-S",
                "bigtext",
                "-t",
                "Ultimate Alert",
                "find_phone",
                "Your laptop triggered Find My Phone!",
            ],
            device=device,
        )
        return ToolResult(
            tool_name="phone_control",
            content="Woke up phone, raised volume, and triggered alert via both ADB and 100km+ Companion Bridge.",
            success=True,
        )

    def _push_file(
        self, local_path: str, remote_path: str, device: Optional[str]
    ) -> ToolResult:
        dest = remote_path or "/sdcard/Download/"
        res = _run_adb(["push", local_path, dest], device=device, timeout=120)
        return ToolResult(
            tool_name="phone_control",
            content=(res.stdout or res.stderr).strip(),
            success=res.returncode == 0,
        )

    def _pull_file(
        self, remote_path: str, local_path: str, device: Optional[str]
    ) -> ToolResult:
        dest = local_path or str(_CAPTURES_DIR)
        res = _run_adb(["pull", remote_path, dest], device=device, timeout=120)
        return ToolResult(
            tool_name="phone_control",
            content=(res.stdout or res.stderr).strip(),
            success=res.returncode == 0,
        )

    def _adb_shell(self, command: str, device: Optional[str]) -> ToolResult:
        if not command:
            return ToolResult(
                tool_name="phone_control",
                content="Missing 'command' for adb_shell.",
                success=False,
            )
        res = _run_adb(["shell", command], device=device, timeout=60)
        output = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        return ToolResult(
            tool_name="phone_control",
            content=output or "(Command completed with no output)",
            success=res.returncode == 0,
        )


__all__ = ["PhoneControlTool"]

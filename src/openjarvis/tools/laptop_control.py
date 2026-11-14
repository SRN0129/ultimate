"""Full Windows Laptop Control Tool for OpenJarvis.

Enables the AI agent (and remote phone dashboard) to control every aspect of the
host laptop: system status, app launching/closing, window management, audio volume
and media playback, screen brightness, power states, screenshots, clipboard,
keyboard/mouse automation, desktop notifications, and PowerShell execution.
"""

from __future__ import annotations

import ctypes
import datetime
import json
import os
import platform
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_CAPTURES_DIR = Path("d:/Ultimate/src/openjarvis/server/static/captures")

# Windows Virtual Key Codes for media and volume
_VK_VOLUME_MUTE = 0xAD
_VK_VOLUME_DOWN = 0xAE
_VK_VOLUME_UP = 0xAF
_VK_MEDIA_NEXT_TRACK = 0xB0
_VK_MEDIA_PREV_TRACK = 0xB1
_VK_MEDIA_STOP = 0xB2
_VK_MEDIA_PLAY_PAUSE = 0xB3

_COMMON_APPS: Dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "cmd": "cmd.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "taskmgr": "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "wifi settings": "ms-settings:network-wifi",
    "bluetooth settings": "ms-settings:bluetooth",
    "display settings": "ms-settings:display",
    "sound settings": "ms-settings:sound",
    "battery settings": "ms-settings:batterysaver",
    "camera": "microsoft.windows.camera:",
    "clock": "ms-clock:",
    "store": "ms-windows-store:",
    "snipping tool": "ms-screenclip:",
    "chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "brave": "brave",
    "spotify": "spotify:",
    "whatsapp": "whatsapp:",
    "vscode": "code",
    "code": "code",
}


def _send_vk(vk_code: int, times: int = 1) -> None:
    """Press a Windows virtual key code via user32.keybd_event."""
    user32 = ctypes.windll.user32
    for _ in range(max(1, times)):
        user32.keybd_event(vk_code, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(vk_code, 0, 2, 0)
        time.sleep(0.02)


def _run_ps(script: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a PowerShell command with UTF-8 output."""
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


@ToolRegistry.register("laptop_control")
class LaptopControlTool(BaseTool):
    """Comprehensive Windows laptop control tool."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="laptop_control",
            description=(
                "Control anything on the user's Windows laptop. Supported actions:\n"
                "- system_status: Get CPU, RAM, disk, battery, local IP, active window, and top processes.\n"
                "- open_app: Open an application, file, folder, URL, or Windows setting (target='chrome', 'notepad', 'settings', 'https://youtube.com', etc.).\n"
                "- close_app: Close/kill an application by process name or window title (target='notepad').\n"
                "- list_processes: List running processes (optional target filter).\n"
                "- list_windows: List all visible open desktop windows.\n"
                "- focus_window: Focus, minimize, maximize, or restore a window by title (target='Chrome', value='focus'|'minimize'|'maximize').\n"
                "- volume: Control audio volume (value='up'|'down'|'mute'|'0'-'100', amount=step count).\n"
                "- media: Control media playback (value='play_pause'|'next'|'prev'|'stop').\n"
                "- brightness: Set laptop screen brightness 0-100 (value='75').\n"
                "- power: System power action (value='lock'|'sleep'|'hibernate'|'screen_off'|'shutdown'|'restart'|'cancel_shutdown').\n"
                "- screenshot: Capture the laptop screen and save to static captures.\n"
                "- clipboard_get: Read current text from the laptop clipboard.\n"
                "- clipboard_set: Copy text into the laptop clipboard (text='...').\n"
                "- type_text: Type text on the laptop keyboard (text='...', press_enter=True/False).\n"
                "- press_key: Press a single key (value='enter'|'esc'|'space'|'tab'|'backspace'|'up'|'down'|'left'|'right'|'win'|'f1'..'f12').\n"
                "- hotkey: Press a keyboard shortcut (value='ctrl+c'|'ctrl+v'|'alt+tab'|'win+d'|'ctrl+shift+esc').\n"
                "- mouse_move: Move mouse cursor to coordinates (x=500, y=500).\n"
                "- mouse_click: Click mouse button (value='left'|'right'|'double', optional x, y).\n"
                "- mouse_scroll: Scroll mouse wheel (amount=5 for up, -5 for down).\n"
                "- notify: Show a popup notification on the laptop screen (title='...', text='...').\n"
                "- powershell: Execute any PowerShell command or script on the laptop (command='...')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "Action to perform: system_status, open_app, close_app, "
                            "list_processes, list_windows, focus_window, volume, media, "
                            "brightness, power, screenshot, clipboard_get, clipboard_set, "
                            "type_text, press_key, hotkey, mouse_move, mouse_click, "
                            "mouse_scroll, notify, powershell"
                        ),
                    },
                    "target": {
                        "type": "string",
                        "description": "App name, process name, window title, URL, or file path.",
                    },
                    "value": {
                        "type": "string",
                        "description": "Value or sub-command (e.g. volume level '50' or 'up', power action 'lock', hotkey 'ctrl+c').",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text content for clipboard_set, type_text, or notify.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Notification title for notify action.",
                    },
                    "command": {
                        "type": "string",
                        "description": "PowerShell script/command for the powershell action.",
                    },
                    "x": {
                        "type": "integer",
                        "description": "X screen coordinate for mouse actions.",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y screen coordinate for mouse actions.",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Step amount for volume up/down or mouse scroll.",
                    },
                    "press_enter": {
                        "type": "boolean",
                        "description": "Whether to press Enter after type_text.",
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
        title = str(kwargs.get("title", "OpenJarvis"))
        command = str(kwargs.get("command", "")).strip()
        x = kwargs.get("x")
        y = kwargs.get("y")
        amount = int(kwargs.get("amount", 5) or 5)
        press_enter = bool(kwargs.get("press_enter", False))

        try:
            if action == "system_status":
                return self._system_status()
            if action == "open_app":
                return self._open_app(target or value)
            if action == "close_app":
                return self._close_app(target or value)
            if action == "list_processes":
                return self._list_processes(target or value)
            if action == "list_windows":
                return self._list_windows()
            if action == "focus_window":
                return self._focus_window(target, value or "focus")
            if action == "volume":
                return self._volume(value or target or "up", amount)
            if action == "media":
                return self._media(value or target or "play_pause")
            if action == "brightness":
                return self._brightness(value or target or str(amount))
            if action == "power":
                return self._power(value or target or "lock")
            if action == "screenshot":
                return self._screenshot()
            if action == "clipboard_get":
                return self._clipboard_get()
            if action == "clipboard_set":
                return self._clipboard_set(text or value or target)
            if action == "type_text":
                return self._type_text(text or value or target, press_enter)
            if action == "press_key":
                return self._press_key(value or target)
            if action == "hotkey":
                return self._hotkey(value or target)
            if action == "mouse_move":
                return self._mouse_move(x, y)
            if action == "mouse_delta":
                return self._mouse_delta(x, y)
            if action == "mouse_click":
                return self._mouse_click(value or "left", x, y)
            if action == "mouse_scroll":
                return self._mouse_scroll(amount)
            if action == "list_files":
                return self._list_files(target or value)
            if action == "notify":
                return self._notify(title, text or value or target)
            if action == "powershell":
                return self._powershell(command or text or value or target)

            return ToolResult(
                tool_name="laptop_control",
                content=f"Unknown laptop_control action: '{action}'.",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="laptop_control",
                content=f"Laptop control error ({action}): {exc}",
                success=False,
            )

    def _system_status(self) -> ToolResult:
        import psutil

        cpu_pct = psutil.cpu_percent(interval=0.4)
        mem = psutil.virtual_memory()
        battery = psutil.sensors_battery()
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append(
                    f"{part.mountpoint} {usage.used // (1024**3)}GB/{usage.total // (1024**3)}GB ({usage.percent}%)"
                )
            except Exception:
                pass

        # Active foreground window title
        active_win = ""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            active_win = buf.value
        except Exception:
            pass

        top_procs = []
        for p in sorted(
            psutil.process_iter(["pid", "name", "memory_info"]),
            key=lambda proc: getattr(proc.info.get("memory_info"), "rss", 0) or 0,
            reverse=True,
        )[:8]:
            rss_mb = (getattr(p.info.get("memory_info"), "rss", 0) or 0) / (1024 * 1024)
            top_procs.append(f"{p.info.get('name')} (PID {p.info.get('pid')}, {rss_mb:.0f} MB)")

        status = {
            "hostname": platform.node(),
            "os": f"Windows {platform.release()} ({platform.version()})",
            "local_ip": _get_local_ip(),
            "cpu_percent": cpu_pct,
            "ram_used_gb": round(mem.used / (1024**3), 2),
            "ram_total_gb": round(mem.total / (1024**3), 2),
            "ram_percent": mem.percent,
            "battery_percent": round(battery.percent, 1) if battery else None,
            "power_plugged": bool(battery.power_plugged) if battery else None,
            "disks": disks,
            "active_window": active_win,
            "top_processes": top_procs,
        }
        return ToolResult(
            tool_name="laptop_control",
            content=json.dumps(status, indent=2),
            success=True,
            metadata=status,
        )

    def _open_app(self, target: str) -> ToolResult:
        if not target:
            return ToolResult(
                tool_name="laptop_control",
                content="Missing 'target' parameter for open_app.",
                success=False,
            )
        resolved = _COMMON_APPS.get(target.lower(), target)
        try:
            os.startfile(resolved)
            return ToolResult(
                tool_name="laptop_control",
                content=f"Opened '{target}' ({resolved}) on laptop.",
                success=True,
            )
        except Exception:
            # Try via PowerShell Start-Process or Start Menu search
            ps_script = f"""
            $t = {json.dumps(resolved)}
            try {{
                Start-Process $t -ErrorAction Stop
                Write-Output "Started process: $t"
            }} catch {{
                $shortcut = Get-ChildItem -Path "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs", "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs" -Recurse -Filter "*$t*.lnk" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($shortcut) {{
                    Start-Process $shortcut.FullName
                    Write-Output "Started shortcut: $($shortcut.Name)"
                }} else {{
                    throw "Could not find application: $t"
                }}
            }}
            """
            res = _run_ps(ps_script)
            if res.returncode == 0:
                return ToolResult(
                    tool_name="laptop_control",
                    content=res.stdout.strip() or f"Opened '{target}'.",
                    success=True,
                )
            return ToolResult(
                tool_name="laptop_control",
                content=f"Failed to open '{target}': {res.stderr.strip()}",
                success=False,
            )

    def _close_app(self, target: str) -> ToolResult:
        if not target:
            return ToolResult(
                tool_name="laptop_control",
                content="Missing 'target' process name or window title for close_app.",
                success=False,
            )
        import psutil

        killed: List[str] = []
        needle = target.lower().replace(".exe", "")
        for proc in psutil.process_iter(["pid", "name"]):
            pname = (proc.info.get("name") or "").lower()
            if needle in pname:
                try:
                    proc.terminate()
                    killed.append(f"{proc.info.get('name')} (PID {proc.info.get('pid')})")
                except Exception:
                    pass
        if killed:
            return ToolResult(
                tool_name="laptop_control",
                content=f"Terminated {len(killed)} process(es): {', '.join(killed)}",
                success=True,
            )
        return ToolResult(
            tool_name="laptop_control",
            content=f"No running process matched '{target}'.",
            success=False,
        )

    def _list_processes(self, filter_str: str = "") -> ToolResult:
        import psutil

        rows = []
        needle = filter_str.lower()
        for p in sorted(
            psutil.process_iter(["pid", "name", "memory_info"]),
            key=lambda proc: getattr(proc.info.get("memory_info"), "rss", 0) or 0,
            reverse=True,
        ):
            name = p.info.get("name") or ""
            if needle and needle not in name.lower():
                continue
            rss_mb = (getattr(p.info.get("memory_info"), "rss", 0) or 0) / (1024 * 1024)
            rows.append(f"{name:<32} PID={p.info.get('pid'):<8} RAM={rss_mb:.1f} MB")
            if len(rows) >= 40:
                break
        return ToolResult(
            tool_name="laptop_control",
            content="\n".join(rows) if rows else "No matching processes found.",
            success=True,
        )

    def _list_windows(self) -> ToolResult:
        ps_script = """
        Get-Process | Where-Object { $_.MainWindowTitle -ne "" } |
            Select-Object Id, ProcessName, MainWindowTitle |
            ConvertTo-Json -Compress
        """
        res = _run_ps(ps_script)
        return ToolResult(
            tool_name="laptop_control",
            content=res.stdout.strip() or "[]",
            success=res.returncode == 0,
        )

    def _focus_window(self, title_filter: str, mode: str = "focus") -> ToolResult:
        if not title_filter:
            return ToolResult(
                tool_name="laptop_control",
                content="Missing 'target' window title for focus_window.",
                success=False,
            )
        show_cmd = {"minimize": 6, "maximize": 3, "restore": 9, "focus": 9}.get(
            mode.lower(), 9
        )
        ps_script = f"""
        Add-Type @"
        using System;
        using System.Runtime.InteropServices;
        public class Win32Window {{
            [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
            [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
        }}
"@
        $proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like "*{title_filter}*" }} | Select-Object -First 1
        if ($proc -and $proc.MainWindowHandle -ne 0) {{
            [Win32Window]::ShowWindowAsync($proc.MainWindowHandle, {show_cmd}) | Out-Null
            [Win32Window]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
            Write-Output "Window '$($proc.MainWindowTitle)' set to {mode}."
        }} else {{
            Write-Error "No open window matching '{title_filter}'"
        }}
        """
        res = _run_ps(ps_script)
        return ToolResult(
            tool_name="laptop_control",
            content=(res.stdout.strip() or res.stderr.strip()),
            success=res.returncode == 0,
        )

    def _volume(self, subcmd: str, amount: int = 5) -> ToolResult:
        sub = subcmd.lower().strip()
        if sub == "mute" or sub == "unmute":
            _send_vk(_VK_VOLUME_MUTE, 1)
            return ToolResult(
                tool_name="laptop_control",
                content="Toggled laptop audio mute.",
                success=True,
            )
        if sub == "up":
            steps = max(1, amount // 2)
            _send_vk(_VK_VOLUME_UP, steps)
            return ToolResult(
                tool_name="laptop_control",
                content=f"Increased laptop volume ({steps} steps).",
                success=True,
            )
        if sub == "down":
            steps = max(1, amount // 2)
            _send_vk(_VK_VOLUME_DOWN, steps)
            return ToolResult(
                tool_name="laptop_control",
                content=f"Decreased laptop volume ({steps} steps).",
                success=True,
            )
        try:
            target_pct = max(0, min(100, int(float(sub.replace("%", "")))))
            # Reset to 0 using 50 steps down, then step up to target_pct // 2
            _send_vk(_VK_VOLUME_DOWN, 50)
            if target_pct > 0:
                _send_vk(_VK_VOLUME_UP, target_pct // 2)
            return ToolResult(
                tool_name="laptop_control",
                content=f"Set laptop volume to ~{target_pct}%.",
                success=True,
            )
        except ValueError:
            return ToolResult(
                tool_name="laptop_control",
                content=f"Invalid volume value '{subcmd}'. Use 'up', 'down', 'mute', or 0-100.",
                success=False,
            )

    def _media(self, subcmd: str) -> ToolResult:
        sub = subcmd.lower().strip()
        mapping = {
            "play": _VK_MEDIA_PLAY_PAUSE,
            "pause": _VK_MEDIA_PLAY_PAUSE,
            "play_pause": _VK_MEDIA_PLAY_PAUSE,
            "toggle": _VK_MEDIA_PLAY_PAUSE,
            "next": _VK_MEDIA_NEXT_TRACK,
            "prev": _VK_MEDIA_PREV_TRACK,
            "previous": _VK_MEDIA_PREV_TRACK,
            "stop": _VK_MEDIA_STOP,
        }
        vk = mapping.get(sub)
        if vk is None:
            return ToolResult(
                tool_name="laptop_control",
                content=f"Unknown media action '{subcmd}'. Use play_pause, next, prev, or stop.",
                success=False,
            )
        _send_vk(vk, 1)
        return ToolResult(
            tool_name="laptop_control",
            content=f"Sent media key '{sub}'.",
            success=True,
        )

    def _brightness(self, level_str: str) -> ToolResult:
        try:
            level = max(0, min(100, int(float(level_str.replace("%", "")))))
        except ValueError:
            return ToolResult(
                tool_name="laptop_control",
                content=f"Invalid brightness level '{level_str}'. Provide 0-100.",
                success=False,
            )
        ps_script = f"""
        $monitors = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop
        foreach ($m in $monitors) {{
            Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={level}}} | Out-Null
        }}
        Write-Output "Set laptop screen brightness to {level}%."
        """
        res = _run_ps(ps_script)
        return ToolResult(
            tool_name="laptop_control",
            content=res.stdout.strip() or res.stderr.strip(),
            success=res.returncode == 0,
        )

    def _power(self, subcmd: str) -> ToolResult:
        sub = subcmd.lower().strip()
        if sub == "lock":
            ctypes.windll.user32.LockWorkStation()
            return ToolResult(
                tool_name="laptop_control",
                content="Locked laptop workstation.",
                success=True,
            )
        if sub == "screen_off":
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
            return ToolResult(
                tool_name="laptop_control",
                content="Turned off laptop display.",
                success=True,
            )
        if sub == "sleep":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
            return ToolResult(
                tool_name="laptop_control",
                content="Putting laptop to sleep.",
                success=True,
            )
        if sub == "hibernate":
            subprocess.Popen(["shutdown.exe", "/h"])
            return ToolResult(
                tool_name="laptop_control",
                content="Hibernating laptop.",
                success=True,
            )
        if sub == "shutdown":
            subprocess.run(["shutdown.exe", "/s", "/t", "10"], check=False)
            return ToolResult(
                tool_name="laptop_control",
                content="Laptop shutdown scheduled in 10 seconds (use power='cancel_shutdown' to abort).",
                success=True,
            )
        if sub == "restart":
            subprocess.run(["shutdown.exe", "/r", "/t", "10"], check=False)
            return ToolResult(
                tool_name="laptop_control",
                content="Laptop restart scheduled in 10 seconds (use power='cancel_shutdown' to abort).",
                success=True,
            )
        if sub == "cancel_shutdown":
            subprocess.run(["shutdown.exe", "/a"], check=False)
            return ToolResult(
                tool_name="laptop_control",
                content="Cancelled scheduled shutdown/restart.",
                success=True,
            )
        return ToolResult(
            tool_name="laptop_control",
            content=f"Unknown power command '{subcmd}'.",
            success=False,
        )

    def _screenshot(self) -> ToolResult:
        from PIL import ImageGrab

        _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        img = ImageGrab.grab(all_screens=True)
        ts_path = _CAPTURES_DIR / f"laptop_{ts}.png"
        latest_path = _CAPTURES_DIR / "latest_laptop.png"
        img.save(ts_path, "PNG")
        img.save(latest_path, "PNG")
        info = {
            "path": str(ts_path),
            "latest_url": f"/captures/latest_laptop.png?t={int(time.time())}",
            "archive_url": f"/captures/laptop_{ts}.png",
            "width": img.width,
            "height": img.height,
        }
        return ToolResult(
            tool_name="laptop_control",
            content=json.dumps(info, indent=2),
            success=True,
            metadata=info,
        )

    def _clipboard_get(self) -> ToolResult:
        import pyperclip

        content = pyperclip.paste()
        return ToolResult(
            tool_name="laptop_control",
            content=content or "(Clipboard is empty)",
            success=True,
        )

    def _clipboard_set(self, text: str) -> ToolResult:
        import pyperclip

        pyperclip.copy(text)
        return ToolResult(
            tool_name="laptop_control",
            content=f"Copied {len(text)} characters to laptop clipboard.",
            success=True,
        )

    def _type_text(self, text: str, press_enter: bool = False) -> ToolResult:
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.write(text, interval=0.01)
        if press_enter:
            pyautogui.press("enter")
        return ToolResult(
            tool_name="laptop_control",
            content=f"Typed {len(text)} characters on laptop"
            + (" and pressed Enter." if press_enter else "."),
            success=True,
        )

    def _press_key(self, key: str) -> ToolResult:
        import pyautogui

        pyautogui.FAILSAFE = False
        k = key.strip().lower()
        pyautogui.press(k)
        return ToolResult(
            tool_name="laptop_control",
            content=f"Pressed key '{k}' on laptop.",
            success=True,
        )

    def _hotkey(self, combo: str) -> ToolResult:
        import pyautogui

        pyautogui.FAILSAFE = False
        keys = [k.strip().lower() for k in combo.replace("-", "+").split("+") if k.strip()]
        if not keys:
            return ToolResult(
                tool_name="laptop_control",
                content="Empty hotkey combination.",
                success=False,
            )
        pyautogui.hotkey(*keys)
        return ToolResult(
            tool_name="laptop_control",
            content=f"Pressed hotkey {'+'.join(keys)} on laptop.",
            success=True,
        )

    def _mouse_move(self, x: Any, y: Any) -> ToolResult:
        import pyautogui

        pyautogui.FAILSAFE = False
        if x is None or y is None:
            pos = pyautogui.position()
            return ToolResult(
                tool_name="laptop_control",
                content=f"Current mouse position: x={pos.x}, y={pos.y}",
                success=True,
            )
        pyautogui.moveTo(int(x), int(y), duration=0.1)
        return ToolResult(
            tool_name="laptop_control",
            content=f"Moved mouse cursor to ({x}, {y}).",
            success=True,
        )

    def _mouse_delta(self, dx: Any, dy: Any) -> ToolResult:
        import pyautogui

        pyautogui.FAILSAFE = False
        rel_x = int(dx or 0)
        rel_y = int(dy or 0)
        pyautogui.moveRel(rel_x, rel_y, duration=0.0)
        pos = pyautogui.position()
        return ToolResult(
            tool_name="laptop_control",
            content=f"Moved cursor by ({rel_x}, {rel_y}) -> now at ({pos.x}, {pos.y}).",
            success=True,
            metadata={"x": pos.x, "y": pos.y},
        )

    def _list_files(self, directory: str = "") -> ToolResult:
        base = Path(directory) if directory else Path.home() / "Desktop"
        if not base.exists():
            base = Path.home()
        items = []
        try:
            for entry in sorted(
                base.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())
            )[:60]:
                try:
                    is_dir = entry.is_dir()
                    size_kb = (
                        round(entry.stat().st_size / 1024, 1) if not is_dir else 0
                    )
                    items.append(
                        {
                            "name": entry.name,
                            "path": str(entry),
                            "is_dir": is_dir,
                            "size_kb": size_kb,
                        }
                    )
                except Exception:
                    pass
        except Exception as exc:
            return ToolResult(
                tool_name="laptop_control",
                content=f"Cannot list {base}: {exc}",
                success=False,
            )
        return ToolResult(
            tool_name="laptop_control",
            content=json.dumps(
                {"directory": str(base), "parent": str(base.parent), "items": items},
                indent=2,
            ),
            success=True,
            metadata={"directory": str(base), "parent": str(base.parent), "items": items},
        )

    def _mouse_click(self, button: str, x: Any = None, y: Any = None) -> ToolResult:
        import pyautogui

        pyautogui.FAILSAFE = False
        tx = int(x) if x is not None else None
        ty = int(y) if y is not None else None
        btn = button.lower().strip()
        if btn == "double":
            pyautogui.doubleClick(x=tx, y=ty)
        elif btn in ("right", "middle", "left"):
            pyautogui.click(x=tx, y=ty, button=btn)
        else:
            pyautogui.click(x=tx, y=ty)
        return ToolResult(
            tool_name="laptop_control",
            content=f"Performed {btn} mouse click"
            + (f" at ({tx}, {ty})." if tx is not None else "."),
            success=True,
        )

    def _mouse_scroll(self, amount: int) -> ToolResult:
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.scroll(int(amount) * 120)
        return ToolResult(
            tool_name="laptop_control",
            content=f"Scrolled mouse wheel by {amount}.",
            success=True,
        )

    def _notify(self, title: str, message: str) -> ToolResult:
        ps_script = f"""
        Add-Type -AssemblyName System.Windows.Forms
        $notify = New-Object System.Windows.Forms.NotifyIcon
        $notify.Icon = [System.Drawing.SystemIcons]::Information
        $notify.Visible = $true
        $notify.ShowBalloonTip(5000, {json.dumps(title)}, {json.dumps(message)}, [System.Windows.Forms.ToolTipIcon]::Info)
        Start-Sleep -Milliseconds 1500
        $notify.Dispose()
        """
        _run_ps(ps_script, timeout=10)
        return ToolResult(
            tool_name="laptop_control",
            content=f"Displayed laptop notification: [{title}] {message}",
            success=True,
        )

    def _powershell(self, command: str) -> ToolResult:
        if not command:
            return ToolResult(
                tool_name="laptop_control",
                content="Missing 'command' for powershell action.",
                success=False,
            )
        res = _run_ps(command, timeout=60)
        output = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
        return ToolResult(
            tool_name="laptop_control",
            content=output.strip() or "(Command completed with no output)",
            success=res.returncode == 0,
        )


__all__ = ["LaptopControlTool"]

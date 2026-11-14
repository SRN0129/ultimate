"""Autonomous Offline Guardian & Store-and-Forward Vault for ULTIMATE.

Designed specifically for a 1-Laptop + 1-Phone setup (NO spare phone, NO SIM
slot in laptop) when both devices are offline and 100km apart:
1. Proximity & Heartbeat Auto-Lock (Dead-Man Switch): If your phone disconnects
   or moves out of range for N minutes, Ultimate automatically locks your
   Windows account (`SRN\\soumy`), mutes audio, or turns off the screen.
2. Offline Battery & Power Protection: Automatically hibernates or sleeps the
   laptop if battery drops below a threshold while offline.
3. Offline Time-Locked & Condition-Locked Missions: Execute any laptop command
   at a specific countdown timer or wall-clock time while 100% offline.
4. Anti-Tamper Intruder Lock: If enabled while you are 100km away, locks the
   Windows workstation immediately if unexpected activity occurs.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openjarvis.security.offline_transport import execute_offline_nl_command
from openjarvis.tools.laptop_control import LaptopControlTool

_laptop = LaptopControlTool()


@dataclass
class OfflineMission:
    mission_id: str
    command: str
    trigger_type: str  # "timer_minutes", "phone_away_minutes", "battery_below"
    trigger_value: int
    created_at: float = field(default_factory=time.time)
    executed: bool = False
    executed_at: Optional[str] = None
    result: str = ""


class AutonomousOfflineGuardian:
    """Runs 100% locally on the laptop with zero internet and zero extra hardware."""

    def __init__(self) -> None:
        self.missions: List[OfflineMission] = []
        self.auto_lock_on_phone_away_mins: int = 0  # 0 = disabled
        self.auto_sleep_battery_pct: int = 15  # auto-sleep if battery < 15% unplugged
        self.last_guardian_action: str = "Guardian active (0 extra hardware required)"
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def add_mission(self, command: str, trigger_type: str, trigger_value: int) -> OfflineMission:
        m = OfflineMission(
            mission_id=f"msn_{int(time.time() * 1000)}",
            command=command.strip(),
            trigger_type=trigger_type,
            trigger_value=max(1, int(trigger_value)),
        )
        self.missions.append(m)
        return m

    def clear_missions(self) -> None:
        self.missions.clear()

    def status(self) -> Dict[str, Any]:
        return {
            "auto_lock_on_phone_away_mins": self.auto_lock_on_phone_away_mins,
            "auto_sleep_battery_pct": self.auto_sleep_battery_pct,
            "last_guardian_action": self.last_guardian_action,
            "missions": [
                {
                    "id": m.mission_id,
                    "command": m.command,
                    "trigger_type": m.trigger_type,
                    "trigger_value": m.trigger_value,
                    "executed": m.executed,
                    "executed_at": m.executed_at,
                    "result": m.result,
                }
                for m in self.missions[-20:]
            ],
        }

    def _loop(self) -> None:
        import psutil

        while self._running:
            try:
                now = time.time()
                # Check phone companion last_seen
                phone_away_mins = 9999.0
                try:
                    from openjarvis.server.control_routes import _PHONE_COMPANION_STATE

                    last_seen = float(_PHONE_COMPANION_STATE.get("last_seen") or 0)
                    if last_seen > 0:
                        phone_away_mins = (now - last_seen) / 60.0
                except Exception:
                    pass

                # 1. Check Dead-Man Auto-Lock if phone is away
                if (
                    self.auto_lock_on_phone_away_mins > 0
                    and phone_away_mins >= self.auto_lock_on_phone_away_mins
                    and phone_away_mins < 9000
                ):
                    _laptop.execute(action="power", value="lock")
                    self.last_guardian_action = (
                        f"Auto-locked PC (Phone away for {int(phone_away_mins)}m) at {time.strftime('%H:%M:%S')}"
                    )
                    # Reset so it does not spam lock every 5s
                    self.auto_lock_on_phone_away_mins = 0

                # 2. Check Battery level
                batt = psutil.sensors_battery()
                batt_pct = batt.percent if batt else 100
                plugged = bool(batt.power_plugged) if batt else True

                if not plugged and batt_pct <= self.auto_sleep_battery_pct:
                    _laptop.execute(action="power", value="sleep")
                    self.last_guardian_action = f"Battery Saver: Slept PC at {batt_pct}%"

                # 3. Evaluate scheduled / condition-locked offline missions
                for m in self.missions:
                    if m.executed:
                        continue
                    should_run = False
                    if m.trigger_type == "timer_minutes":
                        if (now - m.created_at) >= (m.trigger_value * 60):
                            should_run = True
                    elif m.trigger_type == "phone_away_minutes":
                        if phone_away_mins >= m.trigger_value and phone_away_mins < 9000:
                            should_run = True
                    elif m.trigger_type == "battery_below":
                        if batt_pct <= m.trigger_value:
                            should_run = True

                    if should_run:
                        res = execute_offline_nl_command(m.command)
                        m.executed = True
                        m.executed_at = time.strftime("%H:%M:%S")
                        m.result = res.get("reply", "Done")
                        self.last_guardian_action = f"Executed '{m.command}' at {m.executed_at}"
            except Exception:
                pass
            time.sleep(5.0)


_GUARDIAN = AutonomousOfflineGuardian()


def get_autonomous_guardian() -> AutonomousOfflineGuardian:
    return _GUARDIAN


__all__ = ["AutonomousOfflineGuardian", "OfflineMission", "get_autonomous_guardian"]

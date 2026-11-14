"""Audio voice speaker utilities for Windows laptop output."""

from __future__ import annotations

import json
import subprocess


def speak_on_laptop_async(text: str) -> None:
    """Speak text out loud on the laptop speakers asynchronously via PowerShell SAPI."""
    clean = (
        text.replace("*", "")
        .replace("#", "")
        .replace("`", "")
        .replace("\r", " ")
        .replace("\n", ". ")
        .strip()
    )
    if not clean:
        return
    if len(clean) > 650:
        clean = clean[:650] + "... Full response is shown on your screen."

    ps_script = f"""
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.Volume = 100
    $synth.Rate = 1
    try {{
        $voices = $synth.GetInstalledVoices() | Where-Object {{ $_.Enabled }}
        foreach ($v in $voices) {{
            if ($v.VoiceInfo.Name -match "David|George|Mark|Ryan|Hazel|Zira") {{
                $synth.SelectVoice($v.VoiceInfo.Name)
                break
            }}
        }}
    }} catch {{}}
    $synth.Speak({json.dumps(clean)})
    """
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


__all__ = ["speak_on_laptop_async"]

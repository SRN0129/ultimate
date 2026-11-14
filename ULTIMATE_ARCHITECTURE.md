# ULTIMATE Architecture Guide

This repository contains the complete customized OpenJarvis architecture built for **ULTIMATE**, uniting a Windows Laptop Account, an Android Phone, and the ULTIMATE AI Agent.

## Core Modules Added and Customized

### 1. Security, Identity, and Offline Communication
- `src/openjarvis/security/ultimate_enclave.py`: Seals identity secrets using Windows DPAPI bound to the local Windows user SID and machine GUID, and verifies per-request `UTA-QRP` one-time HMAC-SHA256 ratchet signatures.
- `src/openjarvis/security/offline_transport.py`: Provides the Zero-Internet Natural Language Command Engine (`execute_offline_nl_command`), local Wi-Fi/Hotspot/Bluetooth IP scanner (`get_offline_radio_links`), and on-demand Acoustic FFT Air-Gap Receiver (`AcousticAirGapReceiver`).
- `src/openjarvis/security/offgrid_100km.py`: Implements compact `ULT1` ratcheted off-grid command packets for SMS or LoRa links.
- `src/openjarvis/security/autonomous_guardian.py`: Runs local offline timer, battery-threshold, and phone-away dead-man auto-lock rules on the laptop without requiring extra hardware.
- `src/openjarvis/security/capabilities.py`, `rate_limiter.py`, `scanner.py`: Pure-Python fallbacks and capability entries for `laptop_control`, `phone_control`, and `policy_consultant`.

### 2. Resilient Inference and Speech Engine
- `src/openjarvis/engine/litellm.py`: Direct `httpx` multi-model Groq failover engine using `openai/gpt-oss-120b` as primary, automatic failover to `openai/gpt-oss-20b` and `qwen/qwen3.8-27b`, plus `transcribe_audio_bytes` via `whisper-large-v3-turbo`.
- `src/openjarvis/engine/_base.py`: Normalized message serialization for both enum and string roles.

### 3. Direct Device Control and Policy Consultant Suite
- `src/openjarvis/tools/laptop_control.py`: Direct laptop control without screenshots (relative cursor trackpad, window management, file explorer, app launcher/killer, volume, media, brightness, clipboard, keyboard hotkeys, power/lock, and PowerShell execution).
- `src/openjarvis/tools/phone_control.py`: Phone control via ADB (USB/Wireless) and the 100km+ Remote Companion Bridge (`find_phone`, apps, calls, SMS, key events).
- `src/openjarvis/tools/policy_consultant.py`: Policy and Governance Consultant tools (`save_note`, `list_notes`, `draft_email`, `get_clipboard`, `set_clipboard_and_paste`, and Windows SAPI speaker output via `speak_on_laptop_async`).

### 4. Control Server, Phone Mic UI, and Launcher
- `src/openjarvis/server/control_routes.py`: REST API and mobile web interface (`/ultimate`) with tabs for **Policy & Mic**, **Laptop**, **Phone**, **Offline**, and **AI Chat**, including Phone-as-Microphone voice execution (`/v1/control/voice-audio`) and the Policy Consultant Studio (`/v1/control/policy`).
- `configs/openjarvis/ultimate.toml`: Agent, model failover, tool enablement, and executive Policy & Governance system prompt configuration.
- `launch_ultimate.py` and `start-ultimate.bat`: Initializes the enclave, offline links, optional Cloudflare post-quantum tunnel, QR access code, and API server.

## How to Restore on Windows

1. Clone this private repository and create a Python 3.11 virtual environment with `uv venv .venv --python 3.11`.
2. Install dependencies: `uv sync` (or install `fastapi`, `uvicorn`, `httpx`, `psutil`, `pyautogui`, `pyperclip`, `qrcode`, `faster-whisper`, `sounddevice`, `numpy`).
3. Download `cloudflared.exe` into `tools/cloudflared.exe` if 100km+ tunnel mode is desired, and Android `platform-tools` into `tools/platform-tools/` if ADB is desired.
4. Set `GROQ_API_KEY` in your environment and run `.venv\Scripts\python.exe launch_ultimate.py`.

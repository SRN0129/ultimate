"""Ultimate Launcher: Starts the DPAPI Enclave, Offline Radio Links, Ultimate Server, and Post-Quantum 100km+ Tunnel."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path

ROOT_DIR = Path("d:/Ultimate")
CF_BIN = ROOT_DIR / "tools" / "cloudflared.exe"
CONFIG_SRC = ROOT_DIR / "configs" / "openjarvis" / "ultimate.toml"
TUNNEL_URL_FILE = ROOT_DIR / ".ultimate_tunnel_url.txt"
ACCESS_INFO_FILE = ROOT_DIR / "ULTIMATE_ACCESS_LINK.txt"
QR_PNG_FILE = ROOT_DIR / "ULTIMATE_PHONE_QR.png"


def _get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _print_qr(url: str, label: str = "") -> None:
    try:
        import qrcode

        if label:
            print(f"\n  [{label}]")
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(QR_PNG_FILE)
    except Exception as exc:
        print(f"(QR generation skipped: {exc})")


def _start_cloudflared_tunnel(port: int, api_key: str, rsec: str) -> None:
    """Start cloudflared with Post-Quantum X25519MLKEM768 if internet is reachable."""
    if not CF_BIN.exists():
        return

    cmd = [
        str(CF_BIN),
        "tunnel",
        "--url",
        f"http://127.0.0.1:{port}",
        "--post-quantum",
        "--no-autoupdate",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        url_pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
        for line in proc.stdout or []:
            m = url_pattern.search(line)
            if m:
                base_url = m.group(0)
                full_link = f"{base_url}/ultimate?api_key={api_key}&rsec={rsec}"
                TUNNEL_URL_FILE.write_text(base_url, encoding="utf-8")
                with ACCESS_INFO_FILE.open("a", encoding="utf-8") as f:
                    f.write(f"\nGLOBAL 100KM+ POST-QUANTUM LINK:\n{full_link}\n")
                print("\n" + "=" * 76)
                print("  [ONLINE MODE: 100KM+ POST-QUANTUM GLOBAL TUNNEL READY]")
                print(f"  Global URL: {full_link}")
                print("=" * 76)
                _print_qr(full_link, "SCAN FOR 100KM+ GLOBAL ACCESS")
                break
    except Exception:
        pass


def main() -> None:
    user_cfg_dir = Path.home() / ".openjarvis"
    user_cfg_dir.mkdir(parents=True, exist_ok=True)
    if CONFIG_SRC.exists():
        shutil.copyfile(CONFIG_SRC, user_cfg_dir / "config.toml")

    from openjarvis.security.offgrid_100km import get_offgrid_daemon
    from openjarvis.security.offline_transport import get_offline_radio_links
    from openjarvis.security.ultimate_enclave import get_ultimate_enclave

    enclave = get_ultimate_enclave()
    get_offgrid_daemon().start()
    api_key = enclave.api_key
    rsec = enclave.phone_ratchet_secret
    ident = enclave.identity
    port = int(os.environ.get("ULTIMATE_PORT", "8000"))

    radio_links = get_offline_radio_links(port=port)
    primary_ip = radio_links[0]["ip"] if radio_links else _get_local_ip()
    offline_link = f"http://{primary_ip}:{port}/ultimate?api_key={api_key}&rsec={rsec}"

    ACCESS_INFO_FILE.write_text(
        f"OFFLINE / DIRECT RADIO LINK (Works with NO Internet):\n{offline_link}\n",
        encoding="utf-8",
    )

    print("=" * 76)
    print("  ULTIMATE — DIRECT ZERO-TRUST & OFFLINE CONTROL SYSTEM")
    print("=" * 76)
    print(f"  1. Windows Account Enclave : {ident['windows_user']} (DPAPI Sealed)")
    print(f"     Hardware Fingerprint    : {ident['anchor_fingerprint']}")
    print("  2. Direct Offline Radio Links (Works with Zero Internet):")
    for rl in radio_links:
        print(f"     - {rl['interface']}: http://{rl['ip']}:{port}/ultimate?api_key={api_key}&rsec={rsec}")
    print("=" * 76)
    _print_qr(offline_link, "SCAN FOR OFFLINE / LOCAL DIRECT CONTROL")

    # Also attempt 100km+ Post-Quantum Global Tunnel in background if internet is available
    t = threading.Thread(
        target=_start_cloudflared_tunnel,
        args=(port, api_key, rsec),
        daemon=True,
    )
    t.start()

    os.environ["OPENJARVIS_API_KEY"] = api_key
    jarvis_exe = ROOT_DIR / ".venv" / "Scripts" / "jarvis.exe"
    cmd = [
        str(jarvis_exe),
        "serve",
        "--engine",
        "litellm",
        "--model",
        "groq/openai/gpt-oss-120b",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
    ]
    subprocess.run(cmd, check=False)


if __name__ == "__main__":
    main()

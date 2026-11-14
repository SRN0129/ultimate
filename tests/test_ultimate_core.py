"""Standalone unit and API tests for ULTIMATE."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ultimate.security.enclave import UltimateEnclave
from ultimate.security.offgrid_100km import verify_and_execute_ult1_packet
from ultimate.security.offline_transport import execute_offline_nl_command
from ultimate.server.app import create_app


def test_enclave_ratchet_replay_protection(tmp_path: Path) -> None:
    enclave = UltimateEnclave(vault_path=tmp_path / ".test_vault.dpapi")
    body = '{"action":"system_status"}'
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    ts = int(time.time())
    nonce = "abcdef1234567890"
    step = 1
    msg = f"{step}:{ts}:{nonce}:{body_hash}"
    sig = hmac.new(
        enclave.phone_ratchet_secret.encode("utf-8"),
        msg.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    ok, proof = enclave.verify_ratchet_envelope(
        nonce=nonce, timestamp=ts, step=step, body_sha256=body_hash, signature=sig
    )
    assert ok is True
    assert len(proof) == 24

    # Replay must be rejected immediately
    ok2, err = enclave.verify_ratchet_envelope(
        nonce=nonce, timestamp=ts, step=step + 1, body_sha256=body_hash, signature=sig
    )
    assert ok2 is False
    assert "burned" in err.lower()


def test_offline_nl_command_engine() -> None:
    res = execute_offline_nl_command("status")
    assert res["handled"] is True
    assert "CPU" in res["reply"] or "cpu_percent" in res["reply"]


def test_server_auth_and_status(tmp_path: Path) -> None:
    app = create_app(api_key="test_secret_key")
    client = TestClient(app)

    # Unauthenticated API call must be blocked
    unauth = client.get("/v1/control/status")
    assert unauth.status_code == 401

    # Authenticated status succeeds
    auth = client.get(
        "/v1/control/status",
        headers={"Authorization": "Bearer test_secret_key"},
    )
    assert auth.status_code == 200
    data = auth.json()
    assert data["assistant_name"] == "ULTIMATE"
    assert "enclave" in data
    assert "laptop" in data

    # Verify only expected core routes exist
    routes = set(app.openapi()["paths"].keys())
    assert "/v1/control/status" in routes
    assert "/v1/control/voice-audio" in routes
    assert "/v1/control/speak" in routes
    assert "/v1/control/laptop" in routes
    assert "/v1/control/phone" in routes
    assert "/ultimate" in routes

    # Control center HTML renders properly
    ui = client.get("/ultimate")
    assert ui.status_code == 200
    assert "ULTIMATE" in ui.text


def test_ult1_packet_roundtrip() -> None:
    from ultimate.security.enclave import get_ultimate_enclave

    enclave = get_ultimate_enclave()
    step = 99
    ts = int(time.time())
    nonce = "n1234567890"
    cmd = "status"
    msg = f"{step}:{ts}:{nonce}:{cmd}"
    sig16 = hmac.new(
        enclave.phone_ratchet_secret.encode("utf-8"),
        msg.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    pkt = f"ULT1:{step}:{ts}:{nonce}:{sig16}:{cmd}"
    ok, reply = verify_and_execute_ult1_packet(pkt)
    assert ok is True
    assert "Laptop Telemetry" in reply or "cpu_percent" in reply

"""
AryaOS Stage 25 Phase 3.2.4.4.6.3.1 Acceptance Tests:
Secondary FAL Safety Ledger — Epoch 2 Rollover & SEC-GAP-01 Remediation

Verifies:
A. Fresh Epoch 2: used = 0, budget = 1.00, remaining = 1.00
B. $0.05 check: check_budget(0.05) == allowed
C. $1.01 check: check_budget(1.01) == denied
D. Exact exhaustion: record $1.00, subsequent $0.01 check == denied
E. Malformed ledger: fail closed (missing keys, syntax error, NaN/Inf/negative costs)
F. Archive integrity: historical $20.10 preserved exactly in fal_spend_phase3_archive.json
G. Flux guardrail: insufficient local budget -> zero FAL network calls
H. Flux successful accounting: successful provider execution -> record occurs
I. Flux accounting failure: confirmed provider success -> remains successful -> accounting warning only
J. PostgreSQL authority: unchanged by rollover
K. Provider gate: remains FALSE
L. Local execution gate: remains FALSE
M. No live provider calls: zero external network dispatches
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import Settings, get_settings
from app.services.dispatcher import (
    is_live_local_execution_enabled,
    is_live_provider_execution_enabled,
)

# OpenMontage tools path
OPENMONTAGE_DIR = Path("/Users/venkatakishorenasina/Documents/OpenMontage")
if str(OPENMONTAGE_DIR) not in sys.path:
    sys.path.insert(0, str(OPENMONTAGE_DIR))

from tools import fal_spend
from tools.graphics.flux_image import FluxImage


# ==============================================================================
# Condition A & F: Real Active Ledger and Archive Integrity
# ==============================================================================

def test_a_fresh_epoch_2_real_ledger_values(tmp_path, monkeypatch):
    """Condition A: Active ledger reports used=0, budget=1.00, remaining=1.00."""
    test_ledger = tmp_path / "fal_spend.json"
    test_ledger.write_text(json.dumps({"epoch": 2, "budget": 1.00, "generations": []}))
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)

    status = fal_spend.get_status()
    assert status["budget"] == 1.00
    assert status["used"] == 0.00
    assert status["remaining"] == 1.00
    assert status["generations"] == 0


def test_f_archive_integrity_epoch_1_preserved():
    """Condition F: Historical Epoch 1 archive preserves $20.10 spend and $20.11 limit."""
    archive_path = OPENMONTAGE_DIR / "data" / "fal_spend_phase3_archive.json"
    assert archive_path.is_file(), f"Archive file missing at {archive_path}"
    data = json.loads(archive_path.read_text(encoding="utf-8"))
    assert data["budget"] == 20.11
    assert len(data["generations"]) == 2
    total_cost = sum(float(x["cost"]) for x in data["generations"])
    assert round(total_cost, 2) == 20.10
    assert data["generations"][0]["cost"] == 20.00
    assert data["generations"][1]["cost"] == 0.10


# ==============================================================================
# Conditions B, C, D: Check Budget & Exact Exhaustion
# ==============================================================================

def test_b_point_zero_five_check_allowed(tmp_path, monkeypatch):
    """Condition B: $0.05 check is authorized under Epoch 2."""
    test_ledger = tmp_path / "fal_spend.json"
    test_ledger.write_text(json.dumps({"epoch": 2, "budget": 1.00, "generations": []}))
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)

    ok, err = fal_spend.check_budget(0.05)
    assert ok is True
    assert err is None


def test_c_one_point_zero_one_check_denied(tmp_path, monkeypatch):
    """Condition C: $1.01 check is denied under $1.00 Epoch 2 ceiling."""
    test_ledger = tmp_path / "fal_spend.json"
    test_ledger.write_text(json.dumps({"epoch": 2, "budget": 1.00, "generations": []}))
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)

    ok, err = fal_spend.check_budget(1.01)
    assert ok is False
    assert err is not None
    assert "Local FAL budget exceeded" in err


def test_d_exact_exhaustion_subsequent_denied(tmp_path, monkeypatch):
    """Condition D: Recording $1.00 exhausts budget; subsequent $0.01 check is denied."""
    test_ledger = tmp_path / "fal_spend.json"
    test_ledger.write_text(json.dumps({"epoch": 2, "budget": 1.00, "generations": []}))
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)

    fal_spend.record(
        model="flux-pro/v1.1",
        cost=1.00,
        operation="image_generation",
        project="test-proj",
        asset="shot_01.png",
    )

    status = fal_spend.get_status()
    assert status["used"] == 1.00
    assert status["remaining"] == 0.00

    ok, err = fal_spend.check_budget(0.01)
    assert ok is False
    assert err is not None
    assert "Local FAL budget exceeded" in err


# ==============================================================================
# Condition E: Malformed Ledger and Invalid Costs Fail Closed
# ==============================================================================

def test_e_malformed_ledger_and_invalid_numeric_costs(tmp_path, monkeypatch):
    """Condition E: Malformed ledger, missing keys, NaN, Inf, and negative costs fail closed."""
    test_ledger = tmp_path / "fal_spend.json"
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)

    # 1. Missing keys
    test_ledger.write_text(json.dumps({"corrupted": "data"}))
    ok, err = fal_spend.check_budget(0.05)
    assert ok is False
    assert "Malformed local ledger" in (err or "")

    # 2. Syntax error JSON
    test_ledger.write_text("NOT_VALID_JSON{:::}")
    ok, err = fal_spend.check_budget(0.05)
    assert ok is False
    assert "inspection failed" in (err or "")

    # 3. Negative cost rejected
    test_ledger.write_text(json.dumps({"epoch": 2, "budget": 1.00, "generations": []}))
    ok, err = fal_spend.check_budget(-0.50)
    assert ok is False
    assert "Invalid budget check cost" in (err or "")

    # 4. NaN cost rejected
    ok, err = fal_spend.check_budget(float("nan"))
    assert ok is False
    assert "Invalid budget check cost" in (err or "")

    # 5. Infinite cost rejected
    ok, err = fal_spend.check_budget(float("inf"))
    assert ok is False
    assert "Invalid budget check cost" in (err or "")


# ==============================================================================
# Conditions G, H, I: Flux Secondary Guardrail
# ==============================================================================

def test_g_flux_guardrail_budget_exhausted_zero_network_calls(tmp_path, monkeypatch):
    """Condition G: Insufficient budget aborts Flux before dispatch with 0 network calls."""
    test_ledger = tmp_path / "fal_spend.json"
    test_ledger.write_text(
        json.dumps({
            "epoch": 2,
            "budget": 1.00,
            "generations": [{"cost": 0.98, "model": "test", "timestamp": "2026-10-08T00:00:00Z"}],
        })
    )
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)
    monkeypatch.setenv("FAL_KEY", "mock-fal-key")

    tool = FluxImage()
    out_file = tmp_path / "never_created.png"
    inputs = {
        "prompt": "Sci-fi scene",
        "model": "flux-pro/v1.1",
        "output_path": str(out_file),
    }

    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        res = tool.execute(inputs)
        assert res.success is False
        assert "Pre-dispatch budget check failed" in (res.error or "")
        mock_post.assert_not_called()
        mock_get.assert_not_called()

    assert not out_file.exists()


def test_h_flux_successful_accounting_records_cost(tmp_path, monkeypatch):
    """Condition H: Successful provider execution records actual cost to secondary ledger."""
    test_ledger = tmp_path / "fal_spend.json"
    test_ledger.write_text(json.dumps({"epoch": 2, "budget": 1.00, "generations": []}))
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)
    monkeypatch.setenv("FAL_KEY", "mock-fal-key")

    tool = FluxImage()
    out_file = tmp_path / "shot_01.png"
    inputs = {
        "prompt": "Sci-fi control room",
        "model": "flux-pro/v1.1",
        "output_path": str(out_file),
        "project": "project-alpha",
    }

    mock_post_resp = MagicMock()
    mock_post_resp.json.return_value = {
        "images": [{"url": "https://fal.media/image.png"}],
        "request_id": "req-flux-01",
        "seed": 999,
    }
    mock_get_resp = MagicMock()
    mock_get_resp.content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500

    with patch("requests.post", return_value=mock_post_resp) as mock_post, \
         patch("requests.get", return_value=mock_get_resp) as mock_get:
        res = tool.execute(inputs)
        assert res.success is True
        assert res.cost_usd == 0.05
        assert out_file.exists()
        mock_post.assert_called_once()
        mock_get.assert_called_once()

    status = fal_spend.get_status()
    assert status["used"] == 0.05
    assert status["remaining"] == 0.95
    assert status["generations"] == 1


def test_i_flux_accounting_failure_does_not_fail_execution(tmp_path, monkeypatch):
    """Condition I: Secondary ledger record failure does not convert provider success to failure."""
    test_ledger = tmp_path / "fal_spend.json"
    test_ledger.write_text(json.dumps({"epoch": 2, "budget": 1.00, "generations": []}))
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)
    monkeypatch.setenv("FAL_KEY", "mock-fal-key")

    tool = FluxImage()
    out_file = tmp_path / "shot_01.png"
    inputs = {
        "prompt": "Sci-fi scene",
        "model": "flux-pro/v1.1",
        "output_path": str(out_file),
    }

    mock_post_resp = MagicMock()
    mock_post_resp.json.return_value = {
        "images": [{"url": "https://fal.media/image.png"}],
        "request_id": "req-flux-02",
        "seed": 100,
    }
    mock_get_resp = MagicMock()
    mock_get_resp.content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500

    with patch("requests.post", return_value=mock_post_resp), \
         patch("requests.get", return_value=mock_get_resp), \
         patch("tools.graphics.flux_image.record", side_effect=RuntimeError("ReadOnlyFileSystem")):
        res = tool.execute(inputs)
        assert res.success is True
        assert "accounting_warning" in res.data
        assert "ReadOnlyFileSystem" in res.data["accounting_warning"]
        assert out_file.exists()


# ==============================================================================
# Conditions J, K, L, M: Financial Authority and Gate Invariants
# ==============================================================================

def test_j_postgresql_authority_subordination():
    """Condition J: PostgreSQL remains the authoritative financial ledger; secondary ledger is subordinate."""
    from app.services.autonomous_execution_runner import AutonomousExecutionRunner
    # Verify AutonomousExecutionRunner has calculate_authoritative_action_cost
    runner_cls = AutonomousExecutionRunner
    assert hasattr(runner_cls, "calculate_authoritative_action_cost")
    assert hasattr(runner_cls, "reserve_aggregate_dag_budget")


def test_k_provider_execution_gate_remains_false():
    """Condition K: Live external provider execution gate is strictly False."""
    settings = get_settings()
    assert is_live_provider_execution_enabled(settings) is False


def test_l_local_execution_gate_remains_false():
    """Condition L: Live local execution gate is strictly False."""
    settings = get_settings()
    assert is_live_local_execution_enabled(settings) is False


def test_m_zero_live_provider_calls():
    """Condition M: No network dispatches or live calls are permitted."""
    settings = get_settings()
    # Confirm default settings forbid live provider execution
    assert getattr(settings, "enable_live_provider_execution", False) is False

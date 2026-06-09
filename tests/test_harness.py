"""Unit tests for the deterministic agent harness.

Author: A Taylor
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas.models import HaltReason, IntentEnvelope, IntentType
from src.governor import (
    TERMINAL_STATES,
    TRANSITIONS,
    Governor,
    State,
    dry_run_armed,
)
from src.logger import FlightRecorder
from workflows.example_workflow import PERSIST_PATH, build_routing_table

REPO_ROOT = Path(__file__).resolve().parent.parent

GOOD_PAYLOAD = {
    "record_id": "REC-000123",
    "account": "ACCT-AB12CD",
    "amount": "12500.00",
    "currency": "USD",
    "submitted_by": "a.taylor",
}


def make_governor(tmp_path: Path) -> Governor:
    recorder = FlightRecorder(tmp_path / "logs" / "audit.jsonl")
    return Governor(build_routing_table(), recorder)


def good_intent() -> dict:
    return {
        "intent": "submit_compliance_record",
        "confidence": 0.97,
        "payload": dict(GOOD_PAYLOAD),
    }


# ---------------------------------------------------------------- FSM shape


def test_terminal_states_have_no_outgoing_edges():
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == frozenset()
    assert State.COMPLETED in TERMINAL_STATES
    assert State.HALTED in TERMINAL_STATES


def test_every_state_appears_in_transition_table():
    assert set(TRANSITIONS.keys()) == set(State)


# -------------------------------------------------------------- happy path


def test_happy_path_reaches_completed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "false")
    outcome = make_governor(tmp_path).run(good_intent())
    assert outcome.final_state is State.COMPLETED
    assert outcome.halt_reason is None
    assert outcome.output["review_flag"] is True


# ------------------------------------------------------------ DRY_RUN gate


def test_dry_run_defaults_to_armed_when_unset(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert dry_run_armed() is True


@pytest.mark.parametrize("value", ["0", "no", "off", ""])
def test_only_literal_false_disarms_the_gate(monkeypatch, value):
    monkeypatch.setenv("DRY_RUN", value)
    assert dry_run_armed() is True


@pytest.mark.parametrize("value", ["false", "False", "FALSE"])
def test_literal_false_disarms_any_case(monkeypatch, value):
    monkeypatch.setenv("DRY_RUN", value)
    assert dry_run_armed() is False


def test_side_effectful_step_blocked_under_dry_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DRY_RUN", raising=False)
    outcome = make_governor(tmp_path).run(good_intent())
    assert outcome.final_state is State.HALTED
    assert outcome.halt_reason is HaltReason.DRY_RUN_BLOCK
    assert not PERSIST_PATH.exists()


def test_persistence_executes_when_gate_disarmed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "false")
    outcome = make_governor(tmp_path).run(good_intent())
    assert outcome.final_state is State.COMPLETED
    assert PERSIST_PATH.exists()
    row = json.loads(PERSIST_PATH.read_text().splitlines()[0])
    assert row["record_id"] == "REC-000123"
    assert row["review_flag"] is True


# --------------------------------------------------------- schema boundary


def test_injected_unknown_field_halts_before_any_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "false")
    intent = good_intent()
    intent["execute_shell"] = "rm -rf /"
    outcome = make_governor(tmp_path).run(intent)
    assert outcome.final_state is State.HALTED
    assert outcome.halt_reason is HaltReason.SCHEMA_VIOLATION
    assert not PERSIST_PATH.exists()


def test_non_identifier_payload_keys_rejected():
    with pytest.raises(ValidationError):
        IntentEnvelope(
            intent=IntentType.SUBMIT_COMPLIANCE_RECORD,
            confidence=0.9,
            payload={"bad key!": 1},
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_bounds_enforced(confidence):
    with pytest.raises(ValidationError):
        IntentEnvelope(
            intent=IntentType.SUBMIT_COMPLIANCE_RECORD,
            confidence=confidence,
            payload={},
        )


def test_unsupported_intent_halts_safely(tmp_path):
    outcome = make_governor(tmp_path).run(
        {"intent": "unsupported", "confidence": 0.5, "payload": {}}
    )
    assert outcome.final_state is State.HALTED
    assert outcome.halt_reason is HaltReason.UNSUPPORTED_INTENT


def test_invented_verb_is_a_schema_violation(tmp_path):
    outcome = make_governor(tmp_path).run(
        {"intent": "launch_missiles", "confidence": 0.5, "payload": {}}
    )
    assert outcome.final_state is State.HALTED
    assert outcome.halt_reason is HaltReason.SCHEMA_VIOLATION


def test_malformed_domain_record_fails_at_validate_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "false")
    intent = good_intent()
    intent["payload"]["record_id"] = "NOT-A-RECORD"
    outcome = make_governor(tmp_path).run(intent)
    assert outcome.final_state is State.HALTED
    assert outcome.halt_reason is HaltReason.STEP_FAILURE
    assert "validate" in outcome.detail
    assert not PERSIST_PATH.exists()


def test_governor_cannot_be_rerun_from_terminal_state(tmp_path):
    governor = make_governor(tmp_path)
    governor.run({"intent": "unsupported", "confidence": 0.5, "payload": {}})
    outcome = governor.run(good_intent())
    assert outcome.final_state is State.HALTED
    assert outcome.halt_reason is HaltReason.ILLEGAL_TRANSITION


# ----------------------------------------------------------- Flight Recorder


def test_flight_recorder_verifies_clean_log(tmp_path):
    recorder = FlightRecorder(tmp_path / "audit.jsonl")
    for i in range(5):
        recorder.record({"event": "tick", "i": i})
    ok, count = recorder.verify()
    assert ok is True
    assert count == 5


def test_flight_recorder_detects_doctored_line(tmp_path):
    log = tmp_path / "audit.jsonl"
    recorder = FlightRecorder(log)
    for i in range(3):
        recorder.record({"event": "tick", "i": i})
    lines = log.read_text().splitlines()
    doctored = json.loads(lines[1])
    doctored["entry"]["i"] = 999
    lines[1] = json.dumps(doctored, sort_keys=True, separators=(",", ":"))
    log.write_text("\n".join(lines) + "\n")
    ok, bad_line = recorder.verify()
    assert ok is False
    assert bad_line == 2


def test_flight_recorder_chain_resumes_across_restarts(tmp_path):
    log = tmp_path / "audit.jsonl"
    first = FlightRecorder(log)
    first.record({"event": "before_restart"})
    second = FlightRecorder(log)
    second.record({"event": "after_restart"})
    ok, count = second.verify()
    assert ok is True
    assert count == 2


def test_governor_run_produces_verifiable_audit_trail(tmp_path):
    recorder = FlightRecorder(tmp_path / "audit.jsonl")
    governor = Governor(build_routing_table(), recorder)
    governor.run({"intent": "unsupported", "confidence": 0.5, "payload": {}})
    ok, count = recorder.verify()
    assert ok is True
    assert count > 0
    events = [
        json.loads(line)["entry"]["event"]
        for line in recorder.path.read_text().splitlines()
    ]
    assert "input_received" in events
    assert "transition" in events
    assert "halt" in events


# --------------------------------------------------------- static source scan

# Banned strings are assembled from fragments so this test file never
# contains the literal sequences it scans for.
BANNED_SOURCE_STRINGS = [
    "import " + "subprocess",
    "os." + "system",
    "os." + "popen",
    "shell" + "=True",
    "pty." + "spawn",
]


def test_no_shell_or_subprocess_in_execution_layer():
    offenders = []
    for directory in ("src", "workflows"):
        for source_file in sorted((REPO_ROOT / directory).rglob("*.py")):
            text = source_file.read_text(encoding="utf-8")
            for banned in BANNED_SOURCE_STRINGS:
                if banned in text:
                    offenders.append(f"{source_file}: {banned}")
    assert offenders == []

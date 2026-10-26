"""Example 3-step compliance workflow with static routing.

Author: A Taylor

validate -> transform -> persist

Every step re-validates its input at the boundary, returns a typed
StepResult, and fails with an explicit typed fallback. No step repairs,
guesses, or improvises: malformed data is rejected, never patched.
The persist step is the only side-effectful step; it writes to a fixed
constant path under artifacts/ and is blocked by the Governor while the
DRY_RUN gate is armed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import ValidationError

from schemas.models import ComplianceRecord, IntentType, StepResult
from src.governor import WorkflowStep

# Fixed business rule: records at or above this amount are flagged for
# manual review. This threshold is a constant, never model-supplied.
REVIEW_THRESHOLD = Decimal("10000.00")

# Constant persistence target. The workflow can write here and nowhere else.
ARTIFACTS_DIR = Path("artifacts")
PERSIST_PATH = ARTIFACTS_DIR / "compliance_records.jsonl"

_RECORD_KEYS = frozenset(ComplianceRecord.model_fields.keys())
_PERSIST_EXTRA_KEYS = frozenset({"review_flag", "review_threshold"})


def _record_to_dict(record: ComplianceRecord) -> dict[str, Any]:
    data = record.model_dump()
    data["amount"] = str(record.amount)
    return data


def _parse_record(
    data: dict[str, Any],
    allowed_extra: frozenset[str] = frozenset(),
) -> ComplianceRecord:
    """Boundary gate shared by every step: re-validate, never trust."""
    if not isinstance(data, Mapping):
        raise TypeError("step input must be a mapping")
    unexpected = set(data.keys()) - (_RECORD_KEYS | allowed_extra)
    if unexpected:
        raise ValueError(f"unexpected keys in step input: {sorted(unexpected)}")
    fields = {k: data[k] for k in _RECORD_KEYS if k in data}
    return ComplianceRecord.model_validate(fields)


def step_validate(data: dict[str, Any]) -> StepResult:
    """Pydantic gate: the payload must be a well-formed ComplianceRecord."""
    try:
        record = ComplianceRecord.model_validate(data)
    except ValidationError as exc:
        return StepResult(
            step="validate",
            ok=False,
            error=f"compliance record rejected: {exc.error_count()} error(s)",
        )
    return StepResult(step="validate", ok=True, output=_record_to_dict(record))


def step_transform(data: dict[str, Any]) -> StepResult:
    """Fixed business rule: flag records at or above the review threshold."""
    try:
        record = _parse_record(data)
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        return StepResult(
            step="transform",
            ok=False,
            error=f"transform input rejected: {type(exc).__name__}",
        )
    flagged = record.amount >= REVIEW_THRESHOLD
    output = _record_to_dict(record)
    output["review_flag"] = flagged
    output["review_threshold"] = str(REVIEW_THRESHOLD)
    return StepResult(step="transform", ok=True, output=output)


def _already_persisted(record_id: str) -> bool:
    """Idempotency check keyed on the record's natural operation ID."""
    if not PERSIST_PATH.exists():
        return False
    with PERSIST_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                if json.loads(line).get("record_id") == record_id:
                    return True
            except ValueError:
                continue
    return False


def step_persist(data: dict[str, Any]) -> StepResult:
    """Side-effectful: append the reviewed record to the artifacts file.

    The Governor blocks this step before invocation while DRY_RUN is
    armed, so this code only ever runs with the gate explicitly
    disarmed. The write is idempotent: the record_id is the operation
    key, and a record that is already on disk is never appended twice,
    so a replayed run cannot duplicate the side effect. After writing,
    the step reads the line back and verifies it before reporting
    success.
    """
    try:
        record = _parse_record(data, allowed_extra=_PERSIST_EXTRA_KEYS)
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        return StepResult(
            step="persist",
            ok=False,
            error=f"persist input rejected: {type(exc).__name__}",
        )
    expected_flag = record.amount >= REVIEW_THRESHOLD
    if "review_flag" in data and (
        not isinstance(data["review_flag"], bool)
        or data["review_flag"] != expected_flag
    ):
        return StepResult(
            step="persist",
            ok=False,
            error="persist input rejected: review_flag mismatch",
        )
    row = _record_to_dict(record)
    row["review_flag"] = expected_flag
    try:
        if _already_persisted(record.record_id):
            output = dict(row)
            output["persisted_to"] = str(PERSIST_PATH)
            output["idempotent_replay"] = True
            return StepResult(step="persist", ok=True, output=output)
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(row, sort_keys=True)
        with PERSIST_PATH.open("a", encoding="utf-8") as handle:
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Read-after-write verification: trust the disk, not the call.
        with PERSIST_PATH.open("r", encoding="utf-8") as handle:
            written = [line for line in handle if line.strip()]
        if not written or written[-1].strip() != serialized:
            return StepResult(
                step="persist", ok=False, error="read-after-write verification failed"
            )
    except OSError as exc:
        return StepResult(
            step="persist", ok=False, error=f"write failed: {type(exc).__name__}"
        )
    row["persisted_to"] = str(PERSIST_PATH)
    row["idempotent_replay"] = False
    return StepResult(step="persist", ok=True, output=row)


COMPLIANCE_WORKFLOW: Sequence[WorkflowStep] = (
    WorkflowStep(name="validate", run=step_validate, side_effectful=False),
    WorkflowStep(name="transform", run=step_transform, side_effectful=False),
    WorkflowStep(name="persist", run=step_persist, side_effectful=True),
)

ROUTING_TABLE: Mapping[IntentType, Sequence[WorkflowStep]] = MappingProxyType(
    {
        IntentType.SUBMIT_COMPLIANCE_RECORD: COMPLIANCE_WORKFLOW,
        IntentType.UNSUPPORTED: (),
    }
)


def build_routing_table() -> Mapping[IntentType, Sequence[WorkflowStep]]:
    """Complete static intent-to-workflow map.

    UNSUPPORTED deliberately routes to nothing; the Governor halts on it
    with a typed unsupported_intent reason.
    """
    return ROUTING_TABLE

"""Strict data contracts for the deterministic agent harness.

Author: A Taylor

Every boundary in the harness is guarded by one of these models. The
language model is only permitted to emit an IntentEnvelope; everything
past that point is validated, frozen, and routed by static tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IntentType(str, Enum):
    """Closed set of verbs the harness will accept.

    The classifier cannot invent new verbs. Anything that does not map
    cleanly onto a supported value must be classified as UNSUPPORTED,
    which the Governor halts on without executing any step.
    """

    SUBMIT_COMPLIANCE_RECORD = "submit_compliance_record"
    UNSUPPORTED = "unsupported"


class HaltReason(str, Enum):
    """Typed reasons the Governor may halt. No free-text halt causes."""

    SCHEMA_VIOLATION = "schema_violation"
    UNSUPPORTED_INTENT = "unsupported_intent"
    ILLEGAL_TRANSITION = "illegal_transition"
    STEP_FAILURE = "step_failure"
    DRY_RUN_BLOCK = "dry_run_block"


class IntentEnvelope(BaseModel):
    """The only artifact the probabilistic layer may hand to the harness.

    extra="forbid" rejects injected top-level keys (for example a
    smuggled "execute_shell" field) before any routing decision is made.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    payload: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def payload_keys_must_be_identifiers(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        for key in value:
            if not isinstance(key, str) or not key.isidentifier():
                raise ValueError(
                    f"payload key {key!r} is not a valid Python identifier"
                )
        return value


class ComplianceRecord(BaseModel):
    """Domain record for the example compliance workflow.

    Field shapes are pinned with regular expressions so malformed data
    fails loudly at the validation gate instead of drifting downstream.
    """

    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(pattern=r"^REC-[0-9]{6}$")
    account: str = Field(pattern=r"^ACCT-[A-Z0-9]{4,12}$")
    amount: Decimal = Field(ge=Decimal("0.00"), max_digits=14, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    submitted_by: str = Field(pattern=r"^[a-z][a-z0-9_.]{2,31}$")


class StepResult(BaseModel):
    """Immutable outcome of a single workflow step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step: str
    ok: bool
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(BaseModel):
    """Immutable audit record written to the Flight Recorder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: str
    timestamp: datetime = Field(default_factory=_utc_now)
    details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != value.tzinfo.utcoffset(value):
            raise ValueError("timestamp must be timezone-aware UTC")
        if value.utcoffset().total_seconds() != 0:
            raise ValueError("timestamp must be in UTC")
        return value

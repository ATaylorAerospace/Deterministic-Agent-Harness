# Deterministic Agent Harness

> A runtime harness that strips probabilistic behavior out of AI agents: the LLM classifies intent, and a hardcoded finite state machine does everything else.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Pydantic](https://img.shields.io/badge/pydantic-v2-e92063)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen)
![DRY_RUN](https://img.shields.io/badge/DRY__RUN-armed%20by%20default-orange)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

**Author: A Taylor**

---

## Why

Large language models are excellent classifiers and terrible executors. When a model is allowed to choose its own actions at runtime, every run is a roll of the dice. This harness draws a hard line: the model may only map natural language onto a strict JSON schema. From that point on, execution is resolved entirely from static tables frozen at import time. The model never selects a state transition, never names a file path, never invents a verb.

---

## Architecture

### The Pipeline

```text
                PROBABILISTIC ZONE                  DETERMINISTIC ZONE
 .................................................  ...............................................
 :                                               :  :                                             :
 :  +----------------+      +----------------+   :  :   +------------------+                      :
 :  |  Natural       |      |  LLM Intent    |   :  :   |  Validation Gate |                      :
 :  |  Language      | ---> |  Classifier    | --:==:-> |  (Pydantic v2,   | --+                  :
 :  |  Input         |      |  (JSON only)   |   :  :   |  extra="forbid") |   |                  :
 :  +----------------+      +----------------+   :  :   +------------------+   |                  :
 :                                               :  :     |                    v                  :
 :.............................................. :  :     | halt:        +-----------------+      :
                       ^                            :     | schema_      | Static Routing  |      :
                       |                            :     | violation    | Table (frozen   |      :
                TRUST BOUNDARY                      :     v              | at import time) |      :
        nothing crosses except a single             :   [HALTED]         +-----------------+      :
        schema-validated IntentEnvelope             :                      |        |             :
                                                    :     halt:            |        | halt:       :
                                                    :     unsupported_  <--+        | illegal_    :
                                                    :     intent                    | transition  :
                                                    :                      v        v             :
                                                    :   +---------------------------------+      :
                                                    :   |  Governor FSM                   |      :
                                                    :   |  IDLE -> ... -> COMPLETED       |      :
                                                    :   |  halt: step_failure,            |      :
                                                    :   |        dry_run_block            |      :
                                                    :   +---------------------------------+      :
                                                    :                  |                          :
                                                    :                  v                          :
                                                    :   +---------------------------------+      :
                                                    :   |  Flight Recorder                |      :
                                                    :   |  (append-only, hash-chained)    |      :
                                                    :   +---------------------------------+      :
                                                    :.............................................:
```

### The State Machine

```text
                          +-------------------------------------------+
                          |                                           |
   IDLE --> INTENT_RECEIVED --> VALIDATING --> EXECUTING --> COMPLETED
     |            |                  |              |
     |            |                  |              |
     +------------+--------+---------+------+-------+
                           |                |
                           v                v
                        [ HALTED ]  (terminal failure state)
```

`COMPLETED` and `HALTED` are terminal: the transition table assigns them zero outgoing edges, and a unit test enforces it. Every halt carries a typed reason: `schema_violation`, `unsupported_intent`, `illegal_transition`, `step_failure`, or `dry_run_block`. There are no free-text failure modes.

---

## Security Boundaries

> **Zero-liability security model.** The harness ships inert. `DRY_RUN` is armed by default, and while it is armed the Governor blocks every step declared `side_effectful=True` before the step is ever invoked, halting with `dry_run_block`. The host environment cannot be touched by accident, by misconfiguration, or by a model that hallucinated an action. You must explicitly set the literal string `DRY_RUN=false` to allow side effects.

> **No shell, no subprocess, ever.** The execution layer contains no subprocess imports, no shell invocation of any kind, and no pty access. This is not a convention: it is enforced by a unit test that scans every source file in `src/` and `workflows/` for the banned call patterns and fails the build if any appear.

### Environment Variables

| Variable  | Default        | Accepted values                                       | Effect                                                                 |
| --------- | -------------- | ----------------------------------------------------- | ---------------------------------------------------------------------- |
| `DRY_RUN` | armed (unset)  | Only the literal `false` (case-insensitive) disarms   | Armed: side-effectful steps halt with `dry_run_block` before invocation |
|           |                | `0`, `no`, `off`, empty string all keep it armed      | Disarmed: the `persist` step may write to the fixed `artifacts/` path   |

### Type Validation Enforcements

| Boundary              | Contract                              | Enforcement                                        | Failure behavior                          |
| --------------------- | ------------------------------------- | -------------------------------------------------- | ----------------------------------------- |
| LLM output            | `IntentEnvelope`                      | `extra="forbid"`, closed `IntentType` enum         | Halt with `schema_violation`              |
| Intent confidence     | `confidence` in `[0.0, 1.0]`          | Pydantic bounded float                             | Halt with `schema_violation`              |
| Payload keys          | Valid Python identifiers only         | Custom field validator                             | Halt with `schema_violation`              |
| Intent routing        | Static routing table                  | Frozen dict, `UNSUPPORTED` routes to nothing       | Halt with `unsupported_intent`            |
| Each workflow step    | `ComplianceRecord` re-validation      | Regex-constrained fields, re-parsed at every step  | Typed `StepResult` failure, `step_failure` |
| State transitions     | `TRANSITIONS` table                   | Frozen at import time, checked on every move       | Halt with `illegal_transition`            |
| Side effects          | `side_effectful=True` declaration     | Checked against `DRY_RUN` before invocation        | Halt with `dry_run_block`                 |

### Expected Audit Log Outputs

| Event            | When emitted                                   | Key detail fields            |
| ---------------- | ---------------------------------------------- | ---------------------------- |
| `input_received` | Raw intent arrives, before any parsing         | `raw`                        |
| `transition`     | Before every state change takes effect         | `from`, `to`                 |
| `step_input`     | Before each workflow step is invoked           | `step`, `input`              |
| `step_output`    | After each workflow step returns               | `step`, `ok`, `error`        |
| `halt`           | Before the machine moves to `HALTED`           | `reason`, `detail`           |
| `completed`      | On successful arrival at `COMPLETED`           | `output`                     |

Sample audit log line (append-only JSONL, SHA-256 hash chain per line):

```json
{"entry":{"details":{"from":"IDLE","to":"INTENT_RECEIVED"},"event":"transition","timestamp":"2026-01-15T12:00:00.000000+00:00"},"hash":"9f2c...e41a","prev":"0000...0000"}
```

Each line's `hash` is computed over the previous line's hash plus a canonical serialization of the entry, so editing, deleting, or reordering any line breaks the chain. `FlightRecorder.verify()` detects the first broken line, and the chain resumes correctly across process restarts.

---

## Repository Structure

```text
deterministic-agent-harness/
├── README.md
├── LICENSE
├── requirements.txt
├── pytest.ini
├── .gitignore
├── schemas/
│   ├── __init__.py
│   └── models.py              # Pydantic v2 contracts: IntentEnvelope, ComplianceRecord, StepResult, AuditEvent
├── src/
│   ├── __init__.py
│   ├── governor.py            # FSM execution engine with static TRANSITIONS table
│   └── logger.py              # Flight Recorder: append-only, hash-chained JSONL audit trail
├── workflows/
│   ├── __init__.py
│   └── example_workflow.py    # validate -> transform -> persist, with build_routing_table()
└── tests/
    ├── __init__.py
    └── test_harness.py        # FSM shape, DRY_RUN gate, schema boundary, audit chain, source scan
```

---

## Quick Start

1. Clone and enter the repository:

   ```sh
   git clone https://github.com/ATaylorAerospace/Deterministic-Agent-Harness.git
   cd Deterministic-Agent-Harness
   ```

2. Install the two dependencies:

   ```sh
   pip install -r requirements.txt
   ```

3. Run the test suite:

   ```sh
   pytest -v
   ```

4. Drive the example workflow. With the gate armed (the default), the side-effectful persist step is blocked and the run halts with `dry_run_block`:

   ```sh
   python -c "from src.governor import Governor; from src.logger import FlightRecorder; from workflows.example_workflow import build_routing_table; g = Governor(build_routing_table(), FlightRecorder('logs/audit.jsonl')); print(g.run({'intent': 'submit_compliance_record', 'confidence': 0.97, 'payload': {'record_id': 'REC-000123', 'account': 'ACCT-AB12CD', 'amount': '12500.00', 'currency': 'USD', 'submitted_by': 'a.taylor'}}))"
   ```

5. Run the same command with the gate explicitly disarmed and the workflow completes, writing to `artifacts/compliance_records.jsonl`:

   ```sh
   DRY_RUN=false python -c "from src.governor import Governor; from src.logger import FlightRecorder; from workflows.example_workflow import build_routing_table; g = Governor(build_routing_table(), FlightRecorder('logs/audit.jsonl')); print(g.run({'intent': 'submit_compliance_record', 'confidence': 0.97, 'payload': {'record_id': 'REC-000123', 'account': 'ACCT-AB12CD', 'amount': '12500.00', 'currency': 'USD', 'submitted_by': 'a.taylor'}}))"
   ```

---

## Components

1. **`schemas/models.py`**: Pydantic v2 contracts. A closed `IntentType` enum (unsupported requests map to `unsupported`), an `IntentEnvelope` with `extra="forbid"`, a confidence field bounded to `[0.0, 1.0]`, payload keys restricted to valid Python identifiers, a regex-constrained `ComplianceRecord`, an immutable `StepResult`, and a frozen `AuditEvent` with UTC timestamps.
2. **`src/governor.py`**: The Governor FSM. A static `TRANSITIONS` table frozen at import time maps each state to its legal successors, with `COMPLETED` and `HALTED` terminal. Every exception converts to a typed halt, every transition and halt is written to the Flight Recorder before execution proceeds, and side-effectful steps are blocked under `DRY_RUN` before they are invoked.
3. **`src/logger.py`**: The Flight Recorder. Append-only JSONL with a SHA-256 hash chain per line, canonical JSON serialization so record and verify are symmetric, flush plus fsync on every write, a `verify()` method, chain resumption across restarts, and no deletion or rewrite API.
4. **`workflows/example_workflow.py`**: A 3-step compliance workflow: `validate` (Pydantic gate), `transform` (a fixed business rule flagging records at or above the static 10,000.00 review threshold), and `persist` (side-effectful, fixed `artifacts/` path, blocked under dry run). Each step re-validates its input, returns a typed `StepResult`, and fails with an explicit typed fallback. `build_routing_table()` returns the complete static intent-to-workflow map.
5. **`tests/test_harness.py`**: The verification suite covering FSM shape, the happy path, every `DRY_RUN` arming rule, schema injection, payload key constraints, unsupported intents, malformed domain records, the full Flight Recorder tamper-detection cycle, and a static source scan asserting no shell or subprocess facility exists anywhere in the execution layer.

---

## Verification

```text
$ pytest -v
tests/test_harness.py::test_terminal_states_have_no_outgoing_edges PASSED
tests/test_harness.py::test_every_state_appears_in_transition_table PASSED
tests/test_harness.py::test_happy_path_reaches_completed PASSED
tests/test_harness.py::test_dry_run_defaults_to_armed_when_unset PASSED
tests/test_harness.py::test_only_literal_false_disarms_the_gate[0] PASSED
tests/test_harness.py::test_only_literal_false_disarms_the_gate[no] PASSED
tests/test_harness.py::test_only_literal_false_disarms_the_gate[off] PASSED
tests/test_harness.py::test_only_literal_false_disarms_the_gate[] PASSED
tests/test_harness.py::test_literal_false_disarms_any_case[false] PASSED
tests/test_harness.py::test_literal_false_disarms_any_case[False] PASSED
tests/test_harness.py::test_literal_false_disarms_any_case[FALSE] PASSED
tests/test_harness.py::test_side_effectful_step_blocked_under_dry_run PASSED
tests/test_harness.py::test_persistence_executes_when_gate_disarmed PASSED
tests/test_harness.py::test_injected_unknown_field_halts_before_any_step PASSED
tests/test_harness.py::test_non_identifier_payload_keys_rejected PASSED
tests/test_harness.py::test_confidence_bounds_enforced[-0.1] PASSED
tests/test_harness.py::test_confidence_bounds_enforced[1.1] PASSED
tests/test_harness.py::test_unsupported_intent_halts_safely PASSED
tests/test_harness.py::test_invented_verb_is_a_schema_violation PASSED
tests/test_harness.py::test_malformed_domain_record_fails_at_validate_gate PASSED
tests/test_harness.py::test_governor_cannot_be_rerun_from_terminal_state PASSED
tests/test_harness.py::test_flight_recorder_verifies_clean_log PASSED
tests/test_harness.py::test_flight_recorder_detects_doctored_line PASSED
tests/test_harness.py::test_flight_recorder_chain_resumes_across_restarts PASSED
tests/test_harness.py::test_governor_run_produces_verifiable_audit_trail PASSED
tests/test_harness.py::test_no_shell_or_subprocess_in_execution_layer PASSED

26 passed
```

---

## License

MIT License, Copyright (c) 2026 A Taylor. See [LICENSE](LICENSE).

---

## Author

**A Taylor**

# Contributing to Deterministic Agent Harness

Thank you for your interest in contributing! This guide covers the workflow
for submitting changes.

## Development Setup

1. Fork the repository and clone your fork.
2. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Verify your environment:

   ```bash
   pytest -v
   ```

## Branching Strategy

- Create a feature branch from `main`: `git checkout -b feature/your-feature`
- Use descriptive branch names: `fix/halt-reason-edge-case`,
  `docs/add-api-reference`, `feat/add-workflow-step`

## Before Submitting a PR

1. Run the test suite: `pytest -v`
2. Ensure your changes do not break existing tests.
3. Add tests for any new functionality.
4. Update documentation if behavior changes.
5. Never introduce subprocess imports, shell invocation, or pty access in
   `src/` or `workflows/`; the static source scan test will fail the build.
6. Keep the FSM deterministic: new transitions belong in the static
   `TRANSITIONS` table, new failure modes belong in the typed `HaltReason`
   enum, and side-effectful steps must declare `side_effectful=True`.

## PR Guidelines

- Keep PRs focused - one issue per PR.
- Write a clear description referencing the issue number.
- Include before/after logs or audit trail excerpts if applicable.

## Code Style

- Python 3.10+ type hints on all public functions.
- Docstrings on all public classes and functions.
- Validate at every boundary with the Pydantic v2 models in `schemas/models.py`.

## Questions?

Open a discussion or issue on the repository if anything is unclear.

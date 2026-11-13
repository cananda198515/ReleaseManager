---
mode: agent
description: Evaluate implementation against all requirements
---
Evaluate the current implementation against every BR-, NFR- and AC-RM identifier in
specs/business-requirements.md. Run deterministic tests first. For each item cite an exact
test or code artifact. Reject unsupported claims. Previously passing security, approval,
state-transition and idempotency tests are ratchets: any regression is FAIL.
Output: ID | PASS/FAIL/BLOCKED | evidence | remediation.

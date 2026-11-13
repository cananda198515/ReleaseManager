---
mode: agent
description: Strict review of the current diff
---
Act as a strict reviewer. Review the uncommitted diff (git diff) against AGENTS.md and specs/.
Check: spec compliance, missing or weakened tests, SQL injection, authorization, secrets in
code/logs, prompt-injection paths, idempotency, approval bypass, state-machine bypass,
domain layer importing API/MCP/LLM code.
Output a table: severity | file:line | issue | required fix. Do not change any files.

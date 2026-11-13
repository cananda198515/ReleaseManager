---
mode: agent
description: Implement an approved slice test-first
---
Implement the approved plan for slice ${input:sliceId}.
1. Write tests first; run them and confirm they fail for the right reason.
2. Write the minimum code to make them pass.
3. Run: pytest -q && ruff check . && mypy .
4. Iterate until all gates are green.
5. NEVER modify, skip or delete existing tests, policies or specs. If a spec looks wrong, stop and explain.
6. Never add tools outside specs/tool-contracts.md.
7. No secrets in code, config, tests or logs.
Finish with: files changed, test output summary, BR/NFR/AC traceability table.

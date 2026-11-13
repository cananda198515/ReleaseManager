"""Registry of MCP tools exposed to agents.

Only names from policies/tool-allowlist.yaml may appear here; the 10 tools are implemented in Slice 6.
"""

from __future__ import annotations

REGISTERED_TOOLS: tuple[str, ...] = ()

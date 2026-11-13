"""Release MCP scaffold imports; tool registry starts empty until Slice 6 (NFR-03)."""

from __future__ import annotations


def test_package_imports() -> None:
    import release_mcp
    from release_mcp.tools import REGISTERED_TOOLS

    assert release_mcp.__name__ == "release_mcp"
    assert isinstance(REGISTERED_TOOLS, tuple)

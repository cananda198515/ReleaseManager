"""Configuration is externalized; services contain no product-specific values (NFR-09, BR-15 support)."""

from __future__ import annotations

from typing import Any

from tests._repo import REPO_ROOT, files_under, load_yaml, read_text, rel, text_files


def _strings(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return [node] if isinstance(node, str) else []


def _product_markers() -> set[str]:
    markers: set[str] = set()
    for path in sorted((REPO_ROOT / "config/products").glob("*.yaml")):
        data = load_yaml(path.relative_to(REPO_ROOT).as_posix())
        markers.add(path.stem.lower())
        markers.add(str(data["product"]).lower())
        markers.update(s.lower() for s in _strings(data) if "@" in s)
    return markers


def test_product_config_exists() -> None:
    assert _product_markers(), "no product configuration found under config/products"


ENVIRONMENTS = ("dev", "test", "prod")


def _leaves(node: Any, path: str = "") -> list[tuple[str, Any]]:
    if isinstance(node, dict) and set(node) not in ({"env"}, {"secretRef"}):
        return [item for k, v in node.items() for item in _leaves(v, f"{path}.{k}" if path else str(k))]
    return [(path, node)]


def test_environment_configs_are_minimal_overlays() -> None:
    default_paths = {p for p, _ in _leaves(load_yaml("config/default.yaml"))}
    for name in ENVIRONMENTS:
        overlay = load_yaml(f"config/environments/{name}.yaml")
        assert overlay["environment"]["appEnv"] == name
        for key_path, value in _leaves(overlay):
            assert key_path in default_paths, f"{name}.yaml: {key_path} is not a key of config/default.yaml"
            if key_path != "environment.appEnv":
                assert isinstance(value, dict) and set(value) == {"env"}, (
                    f"{name}.yaml: {key_path} must be an {{env: NAME}} reference"
                )


def test_environment_configs_contain_no_secrets() -> None:
    for name in ENVIRONMENTS:
        for key_path, value in _leaves(load_yaml(f"config/environments/{name}.yaml")):
            assert not (isinstance(value, dict) and "secretRef" in value), (
                f"{name}.yaml: {key_path} - secrets belong in default.yaml as secretRef names only"
            )


def test_no_product_values_in_service_code() -> None:
    markers = _product_markers()
    files = text_files(files_under("services"))
    assert files, "services/ has no files"
    violations = {
        rel(p): sorted(m for m in markers if m in read_text(p).lower()) for p in files
    }
    assert not {k: v for k, v in violations.items() if v}, f"product values hard-coded in services: {violations}"

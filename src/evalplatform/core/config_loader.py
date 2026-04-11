"""Load and validate an eval YAML config file."""

from __future__ import annotations

from pathlib import Path

import yaml

from evalplatform.core.schemas import EvalConfig, ProviderConfig


def _build_eval_config(raw: object) -> EvalConfig:
    """Build an EvalConfig from a parsed YAML dict."""
    if not isinstance(raw, dict) or "eval" not in raw:
        raise ValueError("YAML config must contain a top-level 'eval' key")
    eval_block: dict[str, object] = raw["eval"]
    providers_raw: dict[str, dict[str, object]] = raw.get("providers", {})
    providers = {name: ProviderConfig(**cfg) for name, cfg in providers_raw.items()}
    return EvalConfig(
        model=eval_block["model"],  # type: ignore[arg-type]
        dataset=eval_block["dataset"],  # type: ignore[arg-type]
        timeout_seconds=eval_block.get("timeout_seconds", 30),  # type: ignore[arg-type]
        judges=eval_block["judges"],  # type: ignore[arg-type]
        providers=providers,
        max_concurrency=eval_block.get("max_concurrency", 10),  # type: ignore[arg-type]
    )


def load_config(path: str | Path) -> EvalConfig:
    """Read a YAML config file and return a validated EvalConfig.

    The YAML is expected to have a top-level ``eval`` key and an optional
    ``providers`` key (see docs/specs/eval-system.md §1).
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    return _build_eval_config(raw)


def load_config_from_string(yaml_str: str) -> EvalConfig:
    """Parse a YAML string and return a validated EvalConfig."""
    raw = yaml.safe_load(yaml_str)
    return _build_eval_config(raw)

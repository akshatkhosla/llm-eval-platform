"""Tests for YAML config loader."""

import textwrap
from pathlib import Path

import pytest

from evalplatform.core.config_loader import load_config
from evalplatform.core.schemas import (
    ContainsKeywordJudgeConfig,
    LLMJudgeConfig,
    RegexMatchJudgeConfig,
)


@pytest.fixture()
def config_yaml(tmp_path: Path) -> Path:
    yaml_text = textwrap.dedent("""\
        eval:
          model: gemini/gemini-2.5-flash
          dataset: data/prompts.jsonl
          timeout_seconds: 45
          judges:
            - type: llm
              model: gemini/gemini-2.5-pro
              rubric: "Is the response accurate?"
            - type: contains_keyword
              keyword: python
            - type: regex_match
              pattern: "^[A-Z]"
        providers:
          gemini:
            max_concurrency: 5
          ollama:
            base_url: http://localhost:11434
            max_concurrency: 20
    """)
    p = tmp_path / "eval.yaml"
    p.write_text(yaml_text)
    return p


def test_load_config_full(config_yaml: Path) -> None:
    config = load_config(config_yaml)
    assert config.model == "gemini/gemini-2.5-flash"
    assert config.dataset == "data/prompts.jsonl"
    assert config.timeout_seconds == 45
    assert len(config.judges) == 3
    assert isinstance(config.judges[0], LLMJudgeConfig)
    assert isinstance(config.judges[1], ContainsKeywordJudgeConfig)
    assert isinstance(config.judges[2], RegexMatchJudgeConfig)
    assert config.providers["gemini"].max_concurrency == 5
    assert config.providers["ollama"].base_url == "http://localhost:11434"


def test_load_config_defaults(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent("""\
        eval:
          model: ollama/llama3
          dataset: data/test.jsonl
          judges:
            - type: contains_keyword
              keyword: hello
    """)
    p = tmp_path / "minimal.yaml"
    p.write_text(yaml_text)
    config = load_config(p)
    assert config.timeout_seconds == 30
    assert config.providers == {}


def test_load_config_missing_eval_key(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("something: true\n")
    with pytest.raises(ValueError, match="top-level 'eval' key"):
        load_config(p)

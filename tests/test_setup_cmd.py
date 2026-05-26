"""Tests for reki setup command (issue #144)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from rekipedia.cli.setup import _REQUIRED_PRESET_KEYS, PROVIDERS, setup_cmd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_setup(runner, args=None, input_lines=None, env=None):
    """Invoke setup_cmd with optional piped input."""
    text = "\n".join(input_lines or []) + "\n" if input_lines else None
    return runner.invoke(setup_cmd, args or [], input=text, env=env, catch_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_setup_writes_global_config(tmp_path):
    """OpenAI provider → global config YAML written with correct model and api_key."""
    runner = CliRunner()
    config_path = tmp_path / "rekipedia" / "config.yml"

    # Inputs: provider=OpenAI, api_key=sk-test, model=gpt-4o, no test
    input_lines = ["OpenAI", "sk-test", "gpt-4o"]

    with patch("rekipedia.cli.setup.get_global_config_path", return_value=config_path):
        result = runner.invoke(
            setup_cmd,
            ["--no-test"],
            input="\n".join(input_lines) + "\n",
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    assert config_path.exists()
    data = yaml.safe_load(config_path.read_text())
    assert data["llm"]["model"] == "openai/gpt-4o"
    assert data["llm"]["api_key"] == "sk-test"


def test_setup_ollama_no_api_key(tmp_path):
    """Ollama provider: no api_key prompt, base_url set correctly."""
    runner = CliRunner()
    config_path = tmp_path / "rekipedia" / "config.yml"

    # Inputs: provider=Ollama (local), model=llama4, no test
    input_lines = ["Ollama (local)", "llama4"]

    with patch("rekipedia.cli.setup.get_global_config_path", return_value=config_path):
        result = runner.invoke(
            setup_cmd,
            ["--no-test"],
            input="\n".join(input_lines) + "\n",
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    data = yaml.safe_load(config_path.read_text())
    assert data["llm"]["model"] == "ollama/llama4"
    assert data["llm"].get("base_url") == "http://localhost:11434"
    assert "api_key" not in data["llm"]


def test_setup_custom_provider(tmp_path):
    """Custom provider: prompts for model string and base_url."""
    runner = CliRunner()
    config_path = tmp_path / "rekipedia" / "config.yml"

    # Inputs: provider=Custom, api_key=mykey, base_url=http://myhost/v1, model=my-model
    input_lines = ["Custom", "mykey", "http://myhost/v1", "my-model"]

    with patch("rekipedia.cli.setup.get_global_config_path", return_value=config_path):
        result = runner.invoke(
            setup_cmd,
            ["--no-test"],
            input="\n".join(input_lines) + "\n",
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    data = yaml.safe_load(config_path.read_text())
    assert data["llm"]["model"] == "my-model"
    assert data["llm"]["base_url"] == "http://myhost/v1"
    assert data["llm"]["api_key"] == "mykey"


def test_setup_force_flag(tmp_path):
    """--force proceeds without asking even if global config exists."""
    runner = CliRunner()
    config_path = tmp_path / "rekipedia" / "config.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(yaml.dump({"llm": {"model": "old/model"}}))

    input_lines = ["OpenAI", "sk-new", "gpt-4o-mini"]

    with patch("rekipedia.cli.setup.get_global_config_path", return_value=config_path):
        result = runner.invoke(
            setup_cmd,
            ["--force", "--no-test"],
            input="\n".join(input_lines) + "\n",
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    data = yaml.safe_load(config_path.read_text())
    assert data["llm"]["model"] == "openai/gpt-4o-mini"


def test_setup_no_test_flag(tmp_path):
    """--no-test skips connection test entirely."""
    runner = CliRunner()
    config_path = tmp_path / "rekipedia" / "config.yml"

    input_lines = ["OpenAI", "sk-test", "gpt-4o"]

    mock_client = MagicMock()
    mock_client.call.return_value = "OK"

    with patch("rekipedia.cli.setup.get_global_config_path", return_value=config_path):
        with patch("rekipedia.llm.client.LLMClient", return_value=mock_client) as mock_cls:
            result = runner.invoke(
                setup_cmd,
                ["--no-test"],
                input="\n".join(input_lines) + "\n",
                catch_exceptions=False,
            )

    assert result.exit_code == 0, result.output
    # LLMClient should NOT have been called
    mock_cls.assert_not_called()
    assert "Testing" not in result.output


def test_provider_presets_complete():
    """All PROVIDERS entries have required keys."""
    for name, preset in PROVIDERS.items():
        missing = _REQUIRED_PRESET_KEYS - set(preset.keys())
        assert not missing, f"Provider '{name}' is missing keys: {missing}"
        assert isinstance(preset["models"], list)
        assert isinstance(preset["needs_key"], bool)
        assert isinstance(preset["base_url"], str)
        assert isinstance(preset["model_prefix"], str)

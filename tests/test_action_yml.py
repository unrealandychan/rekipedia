"""Tests for GitHub Actions action.yml definition (#127)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ACTION_YML = Path(__file__).parent.parent / "action.yml"
EXAMPLE_WF = Path(__file__).parent.parent / "examples" / "wiki.yml"


@pytest.fixture(scope="module")
def action():
    return yaml.safe_load(ACTION_YML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def example_wf():
    return yaml.safe_load(EXAMPLE_WF.read_text(encoding="utf-8"))


# ── action.yml structure ──────────────────────────────────────────────────────

class TestActionYml:
    def test_file_exists(self):
        assert ACTION_YML.exists(), "action.yml not found at repo root"

    def test_required_top_level_keys(self, action):
        for key in ("name", "description", "inputs", "outputs", "runs"):
            assert key in action, f"Missing top-level key: {key}"

    def test_runs_using_composite(self, action):
        assert action["runs"]["using"] == "composite"

    def test_runs_has_steps(self, action):
        steps = action["runs"]["steps"]
        assert isinstance(steps, list)
        assert len(steps) >= 4

    def test_branding_present(self, action):
        assert "branding" in action
        assert "icon" in action["branding"]
        assert "color" in action["branding"]


# ── inputs ────────────────────────────────────────────────────────────────────

class TestInputs:
    def test_required_inputs_present(self, action):
        inputs = action["inputs"]
        for key in ("repo-path", "output-dir", "model", "api-key",
                    "focus", "export-html", "upload-artifact",
                    "python-version", "rekipedia-version"):
            assert key in inputs, f"Missing input: {key}"

    def test_repo_path_default(self, action):
        assert action["inputs"]["repo-path"]["default"] == "."

    def test_output_dir_default(self, action):
        assert action["inputs"]["output-dir"]["default"] == ".rekipedia"

    def test_python_version_default(self, action):
        assert action["inputs"]["python-version"]["default"] == "3.11"

    def test_export_html_default_false(self, action):
        assert action["inputs"]["export-html"]["default"] == "false"

    def test_upload_artifact_default_true(self, action):
        assert action["inputs"]["upload-artifact"]["default"] == "true"

    def test_artifact_name_default(self, action):
        assert action["inputs"]["artifact-name"]["default"] == "rekipedia-wiki"

    def test_no_required_inputs(self, action):
        """All inputs should be optional (required: false or no required key)."""
        for name, spec in action["inputs"].items():
            assert spec.get("required", False) is False, \
                f"Input '{name}' should not be required"

    def test_all_inputs_have_description(self, action):
        for name, spec in action["inputs"].items():
            assert spec.get("description"), f"Input '{name}' missing description"


# ── outputs ───────────────────────────────────────────────────────────────────

class TestOutputs:
    def test_required_outputs_present(self, action):
        outputs = action["outputs"]
        for key in ("output-dir", "wiki-pages", "html-path"):
            assert key in outputs, f"Missing output: {key}"

    def test_outputs_have_descriptions(self, action):
        for name, spec in action["outputs"].items():
            assert spec.get("description"), f"Output '{name}' missing description"

    def test_output_dir_value_references_scan_step(self, action):
        val = action["outputs"]["output-dir"]["value"]
        assert "scan" in val

    def test_html_path_value_references_html_step(self, action):
        val = action["outputs"]["html-path"]["value"]
        assert "html" in val


# ── steps ─────────────────────────────────────────────────────────────────────

class TestSteps:
    def _step_names(self, action):
        return [s.get("name", "") for s in action["runs"]["steps"]]

    def _step_by_id(self, action, step_id):
        for s in action["runs"]["steps"]:
            if s.get("id") == step_id:
                return s
        return None

    def test_setup_python_step_present(self, action):
        names = self._step_names(action)
        assert any("python" in n.lower() or "setup" in n.lower() for n in names)

    def test_install_rekipedia_step_present(self, action):
        names = self._step_names(action)
        assert any("install" in n.lower() or "rekipedia" in n.lower() for n in names)

    def test_scan_step_has_id(self, action):
        assert self._step_by_id(action, "scan") is not None

    def test_html_step_has_id(self, action):
        assert self._step_by_id(action, "html") is not None

    def test_html_step_conditional(self, action):
        html_step = self._step_by_id(action, "html")
        assert html_step is not None
        cond = html_step.get("if", "")
        assert "export-html" in str(cond)

    def test_upload_artifact_step_present(self, action):
        names = self._step_names(action)
        assert any("upload" in n.lower() or "artifact" in n.lower() for n in names)

    def test_scan_step_uses_reki_scan(self, action):
        scan_step = self._step_by_id(action, "scan")
        run_script = scan_step.get("run", "")
        assert "reki scan" in run_script

    def test_scan_step_sets_github_output(self, action):
        scan_step = self._step_by_id(action, "scan")
        run_script = scan_step.get("run", "")
        assert "GITHUB_OUTPUT" in run_script

    def test_provider_step_handles_anthropic(self, action):
        steps = action["runs"]["steps"]
        provider_step = next(
            (s for s in steps if "provider" in s.get("name", "").lower()
             or "api key" in s.get("name", "").lower()
             or "configure" in s.get("name", "").lower()),
            None,
        )
        assert provider_step is not None
        assert "anthropic" in provider_step.get("run", "").lower() or \
               "anthropic" in str(provider_step).lower()

    def test_all_shell_steps_specify_bash(self, action):
        for step in action["runs"]["steps"]:
            if "run" in step:
                assert step.get("shell") == "bash", \
                    f"Step '{step.get('name')}' missing shell: bash"


# ── example workflow ──────────────────────────────────────────────────────────

class TestExampleWorkflow:
    def test_example_workflow_valid_yaml(self):
        assert EXAMPLE_WF.exists()
        wf = yaml.safe_load(EXAMPLE_WF.read_text(encoding="utf-8"))
        assert wf is not None

    def test_example_uses_rekipedia_action(self, example_wf):
        jobs = example_wf.get("jobs", {})
        found = False
        for job in jobs.values():
            for step in job.get("steps", []):
                if "unrealandychan/rekipedia" in str(step.get("uses", "")):
                    found = True
        assert found, "Example workflow does not reference unrealandychan/rekipedia"

    def test_example_has_workflow_dispatch(self, example_wf):
        # PyYAML parses YAML 'on' key as Python True (boolean)
        triggers = example_wf.get("on") or example_wf.get(True, {})
        assert "workflow_dispatch" in triggers

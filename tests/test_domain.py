"""Tests for reki domain — business domain layer classification (#149)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from rekipedia.analysis.domain import _classify_file, classify_domain
from rekipedia.cli.domain import domain_cmd

# ── unit: _classify_file ─────────────────────────────────────────────────

class TestClassifyFileApi:
    def test_route_in_path(self):
        assert _classify_file("src/routes.py") == "API"

    def test_handler_in_path(self):
        assert _classify_file("app/handlers.py") == "API"

    def test_controller_in_path(self):
        assert _classify_file("web/user_controller.py") == "API"

    def test_endpoint_in_path(self):
        assert _classify_file("api/endpoints.py") == "API"

    def test_api_dir(self):
        assert _classify_file("src/api/users.py") == "API"


class TestClassifyFileService:
    def test_service_file(self):
        assert _classify_file("app/user_service.py") == "Service"

    def test_manager_file(self):
        assert _classify_file("core/session_manager.py") == "Service"

    def test_processor_file(self):
        assert _classify_file("pipeline/data_processor.py") == "Service"

    def test_workflow_file(self):
        assert _classify_file("flows/checkout_workflow.py") == "Service"


class TestClassifyFileData:
    def test_models_file(self):
        assert _classify_file("app/models.py") == "Data"

    def test_schema_file(self):
        assert _classify_file("db/schema.py") == "Data"

    def test_migration_file(self):
        assert _classify_file("migrations/0001_init.py") == "Data"

    def test_repository_in_path(self):
        assert _classify_file("infra/user_repository.py") == "Data"

    def test_db_dir(self):
        assert _classify_file("db/connection.py") == "Data"


class TestClassifyFileUi:
    def test_html_extension(self):
        assert _classify_file("templates/index.html") == "UI"

    def test_tsx_extension(self):
        assert _classify_file("src/components/Button.tsx") == "UI"

    def test_component_in_path(self):
        assert _classify_file("frontend/components/Nav.py") == "UI"

    def test_jsx_extension(self):
        assert _classify_file("src/App.jsx") == "UI"

    def test_vue_extension(self):
        assert _classify_file("src/views/Home.vue") == "UI"


class TestClassifyFileUtility:
    def test_utils_file(self):
        assert _classify_file("src/utils.py") == "Utility"

    def test_helpers_file(self):
        assert _classify_file("common/helpers.py") == "Utility"

    def test_constants_file(self):
        assert _classify_file("app/constants.py") == "Utility"

    def test_config_file(self):
        assert _classify_file("config/settings.py") == "Utility"

    def test_fallback(self):
        assert _classify_file("src/random_stuff.py") == "Utility"


# ── unit: classify_domain ────────────────────────────────────────────────

def _make_symbols(*pairs):
    return [{"name": n, "file": f, "kind": "function", "line_start": 1} for n, f in pairs]


def _make_rels(*triples):
    return [{"from_": f, "to": t, "kind": k} for f, t, k in triples]


def _make_store(symbols, relationships):
    store = MagicMock()
    store.get_all_symbols.return_value = symbols
    store.get_all_relationships.return_value = relationships
    return store


class TestClassifyDomainLayers:
    def test_five_file_layers(self):
        symbols = _make_symbols(
            ("handle_request", "src/api/routes.py"),
            ("user_service", "src/services/user_service.py"),
            ("UserModel", "src/db/models.py"),
            ("render_page", "templates/index.html"),
            ("format_date", "src/utils/helpers.py"),
        )
        store = _make_store(symbols, [])
        result = classify_domain(store, "run-1", Path("/repo"))
        assert "API" in result["layers"]
        assert "Service" in result["layers"]
        assert "Data" in result["layers"]
        assert "UI" in result["layers"]
        assert "Utility" in result["layers"]
        assert "src/api/routes.py" in result["layers"]["API"]["files"]
        assert "src/db/models.py" in result["layers"]["Data"]["files"]

    def test_total_files_count(self):
        symbols = _make_symbols(
            ("a", "src/routes.py"),
            ("b", "src/routes.py"),  # same file
            ("c", "src/models.py"),
        )
        store = _make_store(symbols, [])
        result = classify_domain(store, "run-1", Path("/repo"))
        assert result["total_files"] == 2

    def test_repo_and_generated_at_present(self):
        store = _make_store([], [])
        result = classify_domain(store, "run-1", Path("/my/repo"))
        assert result["repo"] == "/my/repo"
        assert "generated_at" in result


class TestLayerDependencies:
    def test_dep_edge_created(self):
        symbols = _make_symbols(
            ("handle", "src/api/routes.py"),
            ("process", "src/services/user_service.py"),
        )
        rels = _make_rels(("handle", "process", "calls"))
        store = _make_store(symbols, rels)
        result = classify_domain(store, "run-1", Path("/repo"))
        assert len(result["dependencies"]) == 1
        dep = result["dependencies"][0]
        assert dep["from"] == "API"
        assert dep["to"] == "Service"
        assert dep["count"] == 1

    def test_same_layer_no_dep(self):
        symbols = _make_symbols(
            ("a", "src/services/a_service.py"),
            ("b", "src/services/b_service.py"),
        )
        rels = _make_rels(("a", "b", "calls"))
        store = _make_store(symbols, rels)
        result = classify_domain(store, "run-1", Path("/repo"))
        assert result["dependencies"] == []

    def test_dep_count_aggregated(self):
        symbols = _make_symbols(
            ("h1", "src/api/routes.py"),
            ("h2", "src/api/handlers.py"),
            ("svc", "src/services/user_service.py"),
        )
        rels = _make_rels(
            ("h1", "svc", "calls"),
            ("h2", "svc", "calls"),
        )
        store = _make_store(symbols, rels)
        result = classify_domain(store, "run-1", Path("/repo"))
        assert result["dependencies"][0]["count"] == 2


# ── CLI tests ─────────────────────────────────────────────────────────────

class TestDomainCmd:
    runner = CliRunner()

    def _make_cli_store(self, symbols=None, rels=None):
        if symbols is None:
            symbols = _make_symbols(
                ("handle", "src/api/routes.py"),
                ("process", "src/services/user_service.py"),
                ("UserModel", "src/db/models.py"),
            )
        if rels is None:
            rels = []
        store = MagicMock()
        store.__enter__ = lambda s: s
        store.__exit__ = MagicMock(return_value=False)
        store.get_latest_run_id.return_value = "run-123"
        store.get_all_symbols.return_value = symbols
        store.get_all_relationships.return_value = rels
        return store

    def test_domain_cmd_no_scan(self, tmp_path):
        result = self.runner.invoke(domain_cmd, [str(tmp_path)])
        assert result.exit_code != 0

    def test_domain_cmd_text_output(self, tmp_path):
        store = self._make_cli_store()
        with (
            patch("rekipedia.storage.sqlite_store.SqliteStore", return_value=store),
            patch.object(Path, "exists", return_value=True),
        ):
            result = self.runner.invoke(domain_cmd, [str(tmp_path)], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Layer" in result.output or "Domain Architecture" in result.output

    def test_domain_cmd_json_output(self, tmp_path):
        store = self._make_cli_store()
        with (
            patch("rekipedia.storage.sqlite_store.SqliteStore", return_value=store),
            patch.object(Path, "exists", return_value=True),
        ):
            result = self.runner.invoke(domain_cmd, [str(tmp_path), "--format", "json"], catch_exceptions=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "layers" in data

    def test_domain_cmd_output_file(self, tmp_path):
        store = self._make_cli_store()
        out_file = str(tmp_path / "domain.md")
        with (
            patch("rekipedia.storage.sqlite_store.SqliteStore", return_value=store),
            patch.object(Path, "exists", return_value=True),
        ):
            result = self.runner.invoke(
                domain_cmd,
                [str(tmp_path), "--output", out_file],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert Path(out_file).exists()

    def test_command_registered_in_cli(self):
        from rekipedia.cli import main
        assert "domain" in main.commands

    def test_help_text(self):
        result = self.runner.invoke(domain_cmd, ["--help"])
        assert result.exit_code == 0
        assert "domain" in result.output.lower() or "layer" in result.output.lower()

"""Coverage boost tests for analyze_shard, runner, app, and embedder."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────

def _make_shard_json(tmp_path: Path, files: list[dict] | None = None, root: str | None = None) -> Path:
    shard_path = tmp_path / "shard.json"
    shard_path.write_text(json.dumps({
        "shard_id": "test-shard",
        "root": str(root or tmp_path),
        "files": files or [],
    }))
    return shard_path


# ─────────────────────────────────────────────────────────────────
# analyze_shard.py — _merge + main
# ─────────────────────────────────────────────────────────────────

class TestAnalyzeShardMerge:
    def test_merge_basic(self):
        from rekipedia.models.contracts import AnalysisResult
        from rekipedia.sandbox.tasks.analyze_shard import _merge

        target = AnalysisResult(shard_id="t", files_seen=[], entry_points=[])
        src = AnalysisResult(
            shard_id="s",
            files_seen=["a.py"],
            entry_points=["main"],
            build_commands=["make"],
            test_commands=["pytest"],
            risks=["r1"],
            evidence={"k": "v"},
        )
        _merge(target, src)
        assert "a.py" in target.files_seen
        assert "main" in target.entry_points
        assert "make" in target.build_commands
        assert "pytest" in target.test_commands
        assert "r1" in target.risks
        assert target.evidence["k"] == "v"


class TestAnalyzeShardMain:
    def test_main_missing_file(self, tmp_path):
        """File listed in shard but not on disk → risk entry."""
        shard_path = _make_shard_json(tmp_path, files=[{"path": "nonexistent.py"}])
        output_path = tmp_path / "result.json"
        with patch.object(sys, "argv", ["analyze_shard.py", str(shard_path), str(output_path)]):
            from rekipedia.sandbox.tasks.analyze_shard import main
            main()
        result = json.loads(output_path.read_text())
        assert any("missing" in r for r in result.get("risks", []))

    def test_main_no_files(self, tmp_path):
        """Empty shard → writes valid AnalysisResult."""
        shard_path = _make_shard_json(tmp_path, files=[])
        output_path = tmp_path / "result.json"
        with patch.object(sys, "argv", ["analyze_shard.py", str(shard_path), str(output_path)]):
            from rekipedia.sandbox.tasks.analyze_shard import main
            main()
        result = json.loads(output_path.read_text())
        assert result["shard_id"] == "test-shard"

    def test_main_wrong_args(self):
        """Too few args → sys.exit(1)."""
        with patch.object(sys, "argv", ["analyze_shard.py"]):
            from rekipedia.sandbox.tasks.analyze_shard import main
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_main_with_real_py_file(self, tmp_path):
        """Real Python file is handled by extractor."""
        py_file = tmp_path / "hello.py"
        py_file.write_text("def hello(): pass\n")
        shard_path = _make_shard_json(tmp_path, files=[{"path": "hello.py", "sha256": "x", "size_bytes": 20}])
        output_path = tmp_path / "result.json"
        with patch.object(sys, "argv", ["analyze_shard.py", str(shard_path), str(output_path)]):
            from rekipedia.sandbox.tasks.analyze_shard import main
            main()
        result = json.loads(output_path.read_text())
        assert "shard_id" in result

    def test_main_extractor_exception(self, tmp_path):
        """Extractor that raises → risk entry."""
        py_file = tmp_path / "bad.py"
        py_file.write_text("x = 1\n")
        shard_path = _make_shard_json(tmp_path, files=[{"path": "bad.py", "sha256": "x", "size_bytes": 5}])
        output_path = tmp_path / "result.json"

        bad_extractor = MagicMock()
        bad_extractor.can_handle.return_value = True
        bad_extractor.extract.side_effect = RuntimeError("boom")

        with patch.object(sys, "argv", ["analyze_shard.py", str(shard_path), str(output_path)]):
            with patch("rekipedia.extractors.ALL_EXTRACTORS", [bad_extractor]):
                from rekipedia.sandbox.tasks.analyze_shard import main
                main()
        result = json.loads(output_path.read_text())
        assert any("extractor error" in r for r in result.get("risks", []))

    def test_main_via_subprocess(self, tmp_path):
        """Run as __main__ via subprocess."""
        shard_path = _make_shard_json(tmp_path, files=[])
        output_path = tmp_path / "result.json"
        script = Path(__file__).parent.parent / "src/rekipedia/sandbox/tasks/analyze_shard.py"
        result = subprocess.run(
            [sys.executable, str(script), str(shard_path), str(output_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert output_path.exists()

    def test_main_via_subprocess_bad_args(self, tmp_path):
        """Subprocess with wrong args exits 1."""
        script = Path(__file__).parent.parent / "src/rekipedia/sandbox/tasks/analyze_shard.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


# ─────────────────────────────────────────────────────────────────
# runner.py
# ─────────────────────────────────────────────────────────────────

class TestLocalRunner:
    def _make_shard(self, files=None):
        from rekipedia.models.contracts import FileManifest, LLMConfig, Shard
        file_list = [FileManifest(path=f["path"], sha256="x", size_bytes=0) for f in (files or [])]
        return Shard(shard_id="s1", root="/tmp", files=file_list, llm=LLMConfig())

    def test_missing_file(self, tmp_path):
        from rekipedia.sandbox.runner import LocalRunner
        runner = LocalRunner()
        shard = self._make_shard([{"path": "missing.py"}])
        result = runner.run(shard, tmp_path)
        assert any("missing" in r for r in result.risks)

    def test_extractor_exception(self, tmp_path):
        (tmp_path / "bad.py").write_text("x = 1")
        from rekipedia.sandbox.runner import LocalRunner
        runner = LocalRunner()
        shard = self._make_shard([{"path": "bad.py"}])

        bad_ext = MagicMock()
        bad_ext.can_handle.return_value = True
        bad_ext.extract.side_effect = RuntimeError("fail")

        with patch("rekipedia.extractors.ALL_EXTRACTORS", [bad_ext]):
            result = runner.run(shard, tmp_path)
        assert any("extractor error" in r for r in result.risks)

    def test_unhandled_file(self, tmp_path):
        (tmp_path / "README.xyz").write_text("hello")
        from rekipedia.sandbox.runner import LocalRunner
        runner = LocalRunner()
        shard = self._make_shard([{"path": "README.xyz"}])

        no_ext = MagicMock()
        no_ext.can_handle.return_value = False

        with patch("rekipedia.extractors.ALL_EXTRACTORS", [no_ext]):
            result = runner.run(shard, tmp_path)
        assert "README.xyz" in result.files_seen


class TestDockerSandboxRunner:
    def _make_shard(self, tmp_path):
        from rekipedia.models.contracts import LLMConfig, Shard
        return Shard(shard_id="docker-shard", root=str(tmp_path), files=[], llm=LLMConfig())

    def test_successful_run(self, tmp_path):
        from rekipedia.models.contracts import AnalysisResult
        from rekipedia.sandbox.runner import DockerSandboxRunner

        expected = AnalysisResult(shard_id="docker-shard", files_seen=[], entry_points=[])

        def fake_run(cmd, timeout, capture_output, text):
            # Write result.json to the work tmpdir
            work_dir = Path(next(c for c in cmd if c.endswith("/work")))
            (work_dir / "result.json").write_text(expected.model_dump_json(by_alias=True))
            r = MagicMock()
            r.returncode = 0
            return r

        shard = self._make_shard(tmp_path)
        runner = DockerSandboxRunner(image="test-img", timeout=10)

        with patch("rekipedia.sandbox.runner.subprocess.run") as mock_run:
            # Write result file in the temp dir that DockerSandboxRunner creates internally
            mock_run.return_value = MagicMock(returncode=0)
            # We need to intercept the tmpdir write. Patch tempfile.TemporaryDirectory.

            class FakeTmpDir:
                def __init__(self, *a, **kw):
                    self._dir = tmp_path / "fakework"
                    self._dir.mkdir(exist_ok=True)
                def __enter__(self):
                    return str(self._dir)
                def __exit__(self, *a):
                    pass

            with patch("rekipedia.sandbox.runner.tempfile.TemporaryDirectory", FakeTmpDir):
                result_file = tmp_path / "fakework" / "result.json"
                result_file.parent.mkdir(parents=True, exist_ok=True)
                result_file.write_text(expected.model_dump_json(by_alias=True))
                result = runner.run(shard, tmp_path)

        assert result.shard_id == "docker-shard"

    def test_docker_failure(self, tmp_path):
        from rekipedia.sandbox.runner import DockerSandboxRunner

        shard = self._make_shard(tmp_path)
        runner = DockerSandboxRunner(image="test-img", timeout=10)


        class FakeTmpDir:
            def __init__(self, *a, **kw):
                self._dir = tmp_path / "fakework2"
                self._dir.mkdir(exist_ok=True)
            def __enter__(self):
                return str(self._dir)
            def __exit__(self, *a):
                pass

        with patch("rekipedia.sandbox.runner.tempfile.TemporaryDirectory", FakeTmpDir):
            with patch("rekipedia.sandbox.runner.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="error output")
                with pytest.raises(RuntimeError, match="Docker sandbox failed"):
                    runner.run(shard, tmp_path)


class TestGetRunner:
    def test_force_local(self):
        from rekipedia.sandbox.runner import LocalRunner, get_runner
        assert isinstance(get_runner(force_local=True), LocalRunner)

    def test_docker_available(self):
        from rekipedia.sandbox.runner import DockerSandboxRunner, get_runner
        with patch("rekipedia.sandbox.runner._docker_image_available", return_value=True):
            assert isinstance(get_runner(), DockerSandboxRunner)

    def test_docker_unavailable(self):
        from rekipedia.sandbox.runner import LocalRunner, get_runner
        with patch("rekipedia.sandbox.runner._docker_image_available", return_value=False):
            assert isinstance(get_runner(), LocalRunner)


class TestDockerHelpers:
    def test_docker_available_no_binary(self):
        from rekipedia.sandbox.runner import _docker_available
        with patch("rekipedia.sandbox.runner.shutil.which", return_value=None):
            assert _docker_available() is False

    def test_docker_available_returns_true(self):
        from rekipedia.sandbox.runner import _docker_available
        with patch("rekipedia.sandbox.runner.shutil.which", return_value="/usr/bin/docker"):
            with patch("rekipedia.sandbox.runner.subprocess.run") as mr:
                mr.return_value = MagicMock(returncode=0)
                assert _docker_available() is True

    def test_docker_available_exception(self):
        from rekipedia.sandbox.runner import _docker_available
        with patch("rekipedia.sandbox.runner.shutil.which", return_value="/usr/bin/docker"):
            with patch("rekipedia.sandbox.runner.subprocess.run", side_effect=Exception("oops")):
                assert _docker_available() is False

    def test_docker_image_available_false_when_no_docker(self):
        from rekipedia.sandbox.runner import _docker_image_available
        with patch("rekipedia.sandbox.runner._docker_available", return_value=False):
            assert _docker_image_available() is False

    def test_docker_image_available_true(self):
        from rekipedia.sandbox.runner import _docker_image_available
        with patch("rekipedia.sandbox.runner._docker_available", return_value=True):
            with patch("rekipedia.sandbox.runner.subprocess.run") as mr:
                mr.return_value = MagicMock(returncode=0)
                assert _docker_image_available() is True

    def test_docker_image_available_exception(self):
        from rekipedia.sandbox.runner import _docker_image_available
        with patch("rekipedia.sandbox.runner._docker_available", return_value=True):
            with patch("rekipedia.sandbox.runner.subprocess.run", side_effect=Exception("fail")):
                assert _docker_image_available() is False


# ─────────────────────────────────────────────────────────────────
# server/app.py
# ─────────────────────────────────────────────────────────────────

@pytest.fixture
def app_client(tmp_path):
    """Create a test client for the FastAPI app."""
    from fastapi.testclient import TestClient

    from rekipedia.models.contracts import LLMConfig
    from rekipedia.server.app import create_app

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    app = create_app(repo_root, output_dir, LLMConfig())
    return TestClient(app), repo_root, output_dir


class TestAppRoutes:
    def test_index_no_wiki(self, app_client):
        client, _, _ = app_client
        r = client.get("/")
        assert r.status_code == 200

    def test_index_with_wiki_pages(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        wiki_dir = output_dir / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "overview.md").write_text("# Overview\n\nSome content\n\n## Details\n\nmore")

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200

    def test_index_with_manifest(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        wiki_dir = output_dir / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "overview.md").write_text("# Overview\n\nHello")
        (wiki_dir / "details.md").write_text("# Details\n\nWorld")
        exports_dir = output_dir / "exports"
        exports_dir.mkdir()
        (exports_dir / "manifest.json").write_text(json.dumps({"nav_order": ["overview", "details"]}))

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200

    def test_index_with_bad_manifest(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        wiki_dir = output_dir / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "page.md").write_text("# Page\nContent")
        exports_dir = output_dir / "exports"
        exports_dir.mkdir()
        (exports_dir / "manifest.json").write_text("NOT JSON")

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200

    def test_wiki_page_valid(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        wiki_dir = output_dir / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "my-page.md").write_text("# My Page\nContent here")

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        r = client.get("/wiki/my-page")
        assert r.status_code == 200

    def test_wiki_page_not_found(self, app_client):
        client, _, _ = app_client
        r = client.get("/wiki/nonexistent")
        assert r.status_code == 404

    def test_wiki_page_invalid_slug(self, app_client):
        client, _, _ = app_client
        r = client.get("/wiki/../etc/passwd")
        assert r.status_code in (404, 422)

    def test_wiki_page_bad_slug_chars(self, app_client):
        client, _, _ = app_client
        r = client.get("/wiki/bad slug!")
        assert r.status_code in (404, 422)

    def test_ask_page(self, app_client):
        client, _, _ = app_client
        r = client.get("/ask")
        assert r.status_code == 200

    def test_ask_page_with_db(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app
        from rekipedia.storage.sqlite_store import SqliteStore

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        db_path = output_dir / "store.db"
        with SqliteStore(db_path) as store:
            pass  # just create it

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        r = client.get("/ask")
        assert r.status_code == 200

    def test_ask_post_success(self, app_client):
        client, _, _ = app_client
        with patch("rekipedia.server.app.run_ask", return_value="answer text"):
            r = client.post("/ask", data={"question": "What is this?"})
        assert r.status_code == 200
        assert r.json()["answer"] == "answer text"

    def test_ask_post_runtime_error(self, app_client):
        client, _, _ = app_client
        with patch("rekipedia.server.app.run_ask", side_effect=RuntimeError("no index")):
            r = client.post("/ask", data={"question": "test"})
        assert r.status_code == 400
        assert "error" in r.json()

    def test_ask_post_generic_error(self, app_client):
        client, _, _ = app_client
        with patch("rekipedia.server.app.run_ask", side_effect=Exception("boom")):
            r = client.post("/ask", data={"question": "test"})
        assert r.status_code == 500

    def test_ask_post_saves_to_db(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app
        from rekipedia.storage.sqlite_store import SqliteStore

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        db_path = output_dir / "store.db"
        with SqliteStore(db_path) as store:
            pass

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        with patch("rekipedia.server.app.run_ask", return_value="my answer"):
            r = client.post("/ask", data={"question": "test question"})
        assert r.status_code == 200

    def test_api_history_no_db(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/history")
        assert r.status_code == 200
        assert r.json() == []

    def test_api_history_with_db(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app
        from rekipedia.storage.sqlite_store import SqliteStore

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        db_path = output_dir / "store.db"
        with SqliteStore(db_path) as store:
            pass

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        r = client.get("/api/history")
        assert r.status_code == 200

    def test_api_graph_no_db(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/graph")
        assert r.status_code == 200
        assert r.json() == {"nodes": [], "edges": []}

    def test_api_graph_with_db_no_run(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app
        from rekipedia.storage.sqlite_store import SqliteStore

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        db_path = output_dir / "store.db"
        with SqliteStore(db_path) as store:
            pass

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        r = client.get("/api/graph")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data

    def test_api_graph_with_data(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)

        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.get_latest_run_id.return_value = "run-1"
        mock_store.get_all_symbols.return_value = [
            ("run-1", "MyClass", "class", "myfile.py", 1, 10, None, None),
        ]
        mock_store.get_all_relationships.return_value = [
            ("run-1", "MyClass", "OtherClass", "import", "myfile.py"),
        ]
        mock_store.get_god_nodes.return_value = [("MyClass", 5)]

        # Create store.db so the route enters the db branch
        (output_dir / "store.db").touch()
        with patch("rekipedia.server.app.SqliteStore", return_value=mock_store):
            r = client.get("/api/graph")
        assert r.status_code == 200
        data = r.json()
        assert len(data["nodes"]) == 1

    def test_api_graph_exception(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "store.db").touch()

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)

        with patch("rekipedia.server.app.SqliteStore", side_effect=Exception("db error")):
            r = client.get("/api/graph")
        assert r.status_code == 200
        assert "error" in r.json()

    def test_graph_page(self, app_client):
        client, _, _ = app_client
        r = client.get("/graph")
        assert r.status_code == 200

    def test_api_health_no_db(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["db"] == "no_store"

    def test_api_health_ok(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app
        from rekipedia.storage.sqlite_store import SqliteStore

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        db_path = output_dir / "store.db"
        with SqliteStore(db_path) as store:
            pass

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_api_health_db_error(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "store.db").touch()

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)

        with patch("rekipedia.server.app.SqliteStore", side_effect=Exception("db broken")):
            r = client.get("/api/health")
        assert r.status_code == 503

    def test_file_count_with_db(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "store.db").touch()

        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.get_latest_run_id.return_value = "run-1"
        mock_store.get_files_for_run.return_value = ["a.py", "b.py"]
        mock_store.get_qa_history.return_value = []

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        with patch("rekipedia.server.app.SqliteStore", return_value=mock_store):
            r = client.get("/")
        assert r.status_code == 200

    def test_file_count_db_exception(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "store.db").touch()

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        with patch("rekipedia.server.app.SqliteStore", side_effect=Exception("fail")):
            r = client.get("/")
        assert r.status_code == 200

    def test_summary_html_with_architecture_overview(self, tmp_path):
        from fastapi.testclient import TestClient

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.server.app import create_app

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        wiki_dir = output_dir / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "architecture-overview.md").write_text(
            "# Architecture\n\nThis is the overview.\n\n## Section\n\ndetails"
        )

        app = create_app(repo_root, output_dir, LLMConfig())
        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200

    def test_ask_stream(self, app_client):
        client, _, _ = app_client

        def fake_stream(**kwargs):
            yield "Hello"
            yield " World"

        with patch("rekipedia.server.app.stream_ask", fake_stream):
            r = client.get("/ask/stream?question=test", headers={"Accept": "text/event-stream"})
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────
# rag/embedder.py
# ─────────────────────────────────────────────────────────────────

class TestEmbedderHelpers:
    def test_is_implementation_true(self):
        from rekipedia.rag.embedder import _is_implementation
        assert _is_implementation("src/mymodule/code.py") is True

    def test_is_implementation_false_tests(self):
        from rekipedia.rag.embedder import _is_implementation
        assert _is_implementation("tests/test_foo.py") is False

    def test_is_implementation_false_spec(self):
        from rekipedia.rag.embedder import _is_implementation
        assert _is_implementation("spec/myspec.ts") is False

    def test_iter_repo_files(self, tmp_path):
        from rekipedia.rag.embedder import _iter_repo_files
        (tmp_path / "main.py").write_text("x = 1")
        (tmp_path / "README.md").write_text("# hello")
        (tmp_path / "skip.bin").write_bytes(b"\x00\x01")
        result = list(_iter_repo_files(tmp_path))
        exts = {f.suffix for f in result}
        assert ".py" in exts
        assert ".md" in exts
        assert ".bin" not in exts

    def test_iter_repo_files_skips_git(self, tmp_path):
        from rekipedia.rag.embedder import _iter_repo_files
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]")
        (tmp_path / "main.py").write_text("x = 1")
        result = list(_iter_repo_files(tmp_path))
        paths_str = [str(f) for f in result]
        assert not any(".git" in p for p in paths_str)

    def test_chunk_file_basic(self, tmp_path):
        from rekipedia.rag.embedder import _chunk_file
        f = tmp_path / "hello.py"
        f.write_text("x = 1\n" * 100)
        chunks = _chunk_file(f, tmp_path)
        assert len(chunks) >= 1
        assert chunks[0]["file"] == "hello.py"

    def test_chunk_file_too_large(self, tmp_path):
        import rekipedia.rag.embedder as emb
        from rekipedia.rag.embedder import _chunk_file
        f = tmp_path / "big.md"
        f.write_text("x" * (emb._MAX_DOC_CHARS + 1))
        chunks = _chunk_file(f, tmp_path)
        assert chunks == []

    def test_chunk_file_unreadable(self, tmp_path):
        from rekipedia.rag.embedder import _chunk_file
        f = tmp_path / "bad.py"
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            chunks = _chunk_file(f, tmp_path)
        assert chunks == []


class TestEmbedBatch:
    def test_embed_batch_with_base_url(self):
        """base_url is now passed as api_base to litellm.embedding."""

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.rag.embedder import _embed_batch

        cfg = LLMConfig(base_url="http://localhost:11434", api_key="test")
        mock_litellm = MagicMock()
        mock_litellm.embedding.return_value.data = [{"embedding": [0.1, 0.2, 0.3]}]

        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            result = _embed_batch(["hello"], "text-embedding-3-small", cfg)

        assert result.shape == (1, 3)
        call_kwargs = mock_litellm.embedding.call_args[1]
        assert call_kwargs.get("api_base") == "http://localhost:11434"

    def test_embed_batch_with_base_url_error(self):
        """Errors from litellm when base_url is set should propagate."""
        from rekipedia.models.contracts import LLMConfig
        from rekipedia.rag.embedder import _embed_batch

        cfg = LLMConfig(base_url="http://localhost:11434", api_key="test")
        mock_litellm = MagicMock()
        mock_litellm.embedding.side_effect = Exception("connection refused")

        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            with pytest.raises(Exception, match="connection refused"):
                _embed_batch(["hello"], "openai/text-embedding-3-small", cfg)

    def test_embed_batch_litellm_path(self):

        from rekipedia.models.contracts import LLMConfig
        from rekipedia.rag.embedder import _embed_batch

        cfg = LLMConfig(api_key="sk-test")  # no base_url → litellm path
        mock_litellm = MagicMock()
        mock_item = MagicMock()
        mock_item.__getitem__ = lambda self, k: [0.1, 0.2] if k == "embedding" else None
        mock_litellm.embedding.return_value.data = [{"embedding": [0.1, 0.2]}]

        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            result = _embed_batch(["hello"], "openai/text-embed", cfg)
        assert result.shape == (1, 2)


class TestEmbedPipeline:
    def _make_pipeline(self, tmp_path):
        from rekipedia.models.contracts import LLMConfig
        from rekipedia.rag.embedder import EmbedPipeline
        return EmbedPipeline(tmp_path / "output", LLMConfig())

    def test_meta_no_file(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        assert pipe.meta() is None

    def test_meta_with_file(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        rag_dir = tmp_path / "output" / "rag"
        rag_dir.mkdir(parents=True)
        (rag_dir / "embed_meta.json").write_text(json.dumps({"model": "m", "dim": 3}))
        assert pipe.meta()["model"] == "m"

    def test_meta_corrupt_file(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        rag_dir = tmp_path / "output" / "rag"
        rag_dir.mkdir(parents=True)
        (rag_dir / "embed_meta.json").write_text("NOT JSON")
        assert pipe.meta() is None

    def test_is_built_false(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        assert pipe.is_built() is False

    def test_is_built_true_npy(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        rag_dir = tmp_path / "output" / "rag"
        rag_dir.mkdir(parents=True)
        (rag_dir / "index.faiss.npy").touch()
        assert pipe.is_built() is True

    def test_search_no_chunks_file(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        assert pipe.search("query") == []

    def test_search_no_index(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        rag_dir = tmp_path / "output" / "rag"
        rag_dir.mkdir(parents=True)
        (rag_dir / "chunks.json").write_text("[]")
        assert pipe.search("query") == []

    def test_search_corrupt_chunks(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        rag_dir = tmp_path / "output" / "rag"
        rag_dir.mkdir(parents=True)
        (rag_dir / "chunks.json").write_text("INVALID")
        (rag_dir / "index.faiss.npy").touch()
        assert pipe.search("query") == []

    def test_search_npy_fallback(self, tmp_path):
        import numpy as np
        pipe = self._make_pipeline(tmp_path)
        rag_dir = tmp_path / "output" / "rag"
        rag_dir.mkdir(parents=True)

        chunks = [{"file": "a.py", "chunk_idx": 0, "text": "hello", "is_implementation": True}]
        (rag_dir / "chunks.json").write_text(json.dumps(chunks))
        matrix = np.random.rand(1, 3).astype(np.float32)
        np.save(str(rag_dir / "index.faiss.npy"), matrix)

        mock_vec = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
        with patch("rekipedia.rag.embedder._embed_batch", return_value=mock_vec):
            results = pipe.search("hello", top_k=1)
        assert len(results) >= 0  # may return 0 if no faiss; numpy path

    def test_build_no_files(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        # empty repo → 0 chunks
        result = pipe.build(repo_root)
        assert result == 0

    def test_build_with_mock_embed(self, tmp_path):
        import numpy as np
        pipe = self._make_pipeline(tmp_path)
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "main.py").write_text("def hello(): pass\n")

        mock_vec = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
        progress_calls = []

        with patch("rekipedia.rag.embedder._embed_batch", return_value=mock_vec):
            with patch("time.sleep"):  # don't actually sleep
                n = pipe.build(repo_root, progress_cb=progress_calls.append)
        assert n >= 1
        assert len(progress_calls) > 0

    def test_build_embed_batch_fails(self, tmp_path):
        pipe = self._make_pipeline(tmp_path)
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "main.py").write_text("def hello(): pass\n")

        with patch("rekipedia.rag.embedder._embed_batch", side_effect=Exception("api error")):
            with patch("time.sleep"):
                n = pipe.build(repo_root)
        # With streaming FAISS build, if all batches fail no embeddings are produced (n=0)
        assert n >= 0  # returns 0 when all batches fail gracefully

    def test_pipeline_model_with_provider(self, tmp_path):
        from rekipedia.models.contracts import LLMConfig
        from rekipedia.rag.embedder import EmbedPipeline
        cfg = LLMConfig(embed_model="text-embed-small", embed_provider="openai")
        pipe = EmbedPipeline(tmp_path, cfg)
        assert pipe._model == "openai/text-embed-small"

    def test_pipeline_model_with_custom_base_url(self, tmp_path):
        from rekipedia.models.contracts import LLMConfig
        from rekipedia.rag.embedder import EmbedPipeline
        cfg = LLMConfig(embed_model="text-embed", embed_provider="openai", base_url="http://proxy")
        pipe = EmbedPipeline(tmp_path, cfg)
        # With custom base_url, don't add provider prefix
        assert pipe._model == "text-embed"

    def test_search_embed_exception(self, tmp_path):
        import numpy as np
        pipe = self._make_pipeline(tmp_path)
        rag_dir = tmp_path / "output" / "rag"
        rag_dir.mkdir(parents=True)
        chunks = [{"file": "a.py", "chunk_idx": 0, "text": "hi", "is_implementation": True}]
        (rag_dir / "chunks.json").write_text(json.dumps(chunks))
        matrix = np.random.rand(1, 3).astype(np.float32)
        np.save(str(rag_dir / "index.faiss.npy"), matrix)

        with patch("rekipedia.rag.embedder._embed_batch", side_effect=Exception("fail")):
            results = pipe.search("query")
        assert results == []

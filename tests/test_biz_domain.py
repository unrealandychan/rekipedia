"""Tests for LLM-driven Business Domain Analyzer (#155)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from rekipedia.analysis.biz_domain import (
    BizDomainAnalyzer,
    BizDomainGraph,
    DomainNode,
    FlowNode,
    StepNode,
    _parse_response,
)
from rekipedia.cli.domain import domain_cmd
from rekipedia.models.contracts import AnalysisResult, Relationship, Symbol

# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_step(**kw) -> StepNode:
    defaults = dict(
        id="step:create-order:validate-cart",
        name="Validate cart",
        summary="Check cart is non-empty",
        tags=["validation"],
        complexity="simple",
    )
    return StepNode(**(defaults | kw))


def _make_flow(**kw) -> FlowNode:
    defaults = dict(
        id="flow:create-order",
        name="Create Order",
        summary="End-to-end order creation",
        tags=["order"],
        complexity="moderate",
        steps=[_make_step()],
    )
    return FlowNode(**(defaults | kw))


def _make_domain(**kw) -> DomainNode:
    defaults = dict(
        id="domain:payment",
        name="Payment Processing",
        summary="Handles payment lifecycle",
        tags=["payment"],
        complexity="complex",
        flows=[_make_flow()],
    )
    return DomainNode(**(defaults | kw))


def _make_graph(**kw) -> BizDomainGraph:
    defaults = dict(
        project_name="myapp",
        analyzed_at="2025-01-01T00:00:00+00:00",
        domains=[_make_domain()],
    )
    return BizDomainGraph(**(defaults | kw))


def _sample_analysis_result() -> AnalysisResult:
    return AnalysisResult(
        shard_id="test",
        files_seen=["src/payments.py"],
        entry_points=["src/main.py:main"],
        symbols=[
            Symbol(name="charge_card", kind="function", file="src/payments.py", line_start=88,
                   docstring="Charge the customer card."),
            Symbol(name="Order", kind="class", file="src/models.py", line_start=12),
        ],
        relationships=[
            Relationship(**{"from": "checkout", "to": "charge_card", "kind": "call"}),
        ],
    )


# ── TestBizDomainModels ───────────────────────────────────────────────────────

class TestBizDomainModels:
    def test_step_node_creation(self):
        step = _make_step()
        assert step.id == "step:create-order:validate-cart"
        assert step.complexity == "simple"
        assert step.line_range == (0, 0)

    def test_flow_node_creation(self):
        flow = _make_flow()
        assert flow.entry_type == "manual"
        assert len(flow.steps) == 1

    def test_domain_node_creation(self):
        domain = _make_domain()
        assert domain.id == "domain:payment"
        assert len(domain.flows) == 1

    def test_graph_defaults(self):
        g = BizDomainGraph()
        assert g.version == "1.0.0"
        assert g.domains == []

    def test_graph_json_roundtrip(self):
        g = _make_graph()
        raw = g.model_dump_json()
        g2 = BizDomainGraph.model_validate_json(raw)
        assert g2.project_name == g.project_name
        assert g2.domains[0].name == g.domains[0].name
        assert g2.domains[0].flows[0].steps[0].name == "Validate cart"

    def test_step_with_file_path(self):
        step = _make_step(file_path="src/cart.py", line_range=(45, 60))
        assert step.file_path == "src/cart.py"
        assert step.line_range == (45, 60)

    def test_complexity_values(self):
        for val in ("simple", "moderate", "complex"):
            s = _make_step(complexity=val)
            assert s.complexity == val

    def test_entry_type_values(self):
        for val in ("http", "cli", "event", "cron", "manual"):
            f = _make_flow(entry_type=val)
            assert f.entry_type == val


# ── TestBizDomainAnalyzer ─────────────────────────────────────────────────────

class TestBizDomainAnalyzer:
    def _graph_payload(self) -> dict:
        return _make_graph().model_dump(mode="json")

    def test_analyze_calls_llm(self):
        fake_client = MagicMock()
        fake_client.call.return_value = json.dumps(self._graph_payload())

        analyzer = BizDomainAnalyzer(llm_client=fake_client)
        ar = _sample_analysis_result()
        graph = analyzer.analyze(ar, project_name="myapp")

        assert fake_client.call.called
        assert graph.project_name == "myapp"
        assert len(graph.domains) == 1

    def test_prompt_contains_symbols(self):
        fake_client = MagicMock()
        fake_client.call.return_value = json.dumps(self._graph_payload())

        analyzer = BizDomainAnalyzer(llm_client=fake_client)
        ar = _sample_analysis_result()
        analyzer.analyze(ar, project_name="testproj")

        prompt_arg = fake_client.call.call_args[0][0]
        assert "charge_card" in prompt_arg
        assert "testproj" in prompt_arg

    def test_prompt_contains_entry_points(self):
        fake_client = MagicMock()
        fake_client.call.return_value = json.dumps(self._graph_payload())

        analyzer = BizDomainAnalyzer(llm_client=fake_client)
        ar = _sample_analysis_result()
        analyzer.analyze(ar)

        prompt_arg = fake_client.call.call_args[0][0]
        assert "src/main.py:main" in prompt_arg

    def test_parse_response_strips_markdown(self):
        payload = json.dumps(self._graph_payload())
        raw = f"```json\n{payload}\n```"
        graph = _parse_response(raw, "proj")
        assert graph.domains[0].name == "Payment Processing"

    def test_parse_response_empty_returns_empty_graph(self):
        graph = _parse_response("no json here", "proj")
        assert graph.domains == []
        assert graph.project_name == "proj"

    def test_save_writes_file(self, tmp_path: Path):
        fake_client = MagicMock()
        fake_client.call.return_value = json.dumps(self._graph_payload())

        analyzer = BizDomainAnalyzer(llm_client=fake_client)
        graph = _make_graph()
        dest = analyzer.save(graph, tmp_path)

        assert dest.exists()
        assert dest.name == "domain-graph.json"
        data = json.loads(dest.read_text())
        assert data["project_name"] == "myapp"

    def test_analyzer_default_project_name(self):
        fake_client = MagicMock()
        payload = _make_graph(project_name="").model_dump(mode="json")
        fake_client.call.return_value = json.dumps(payload)

        analyzer = BizDomainAnalyzer(llm_client=fake_client)
        graph = analyzer.analyze(_sample_analysis_result())
        assert isinstance(graph, BizDomainGraph)


# ── TestDomainCmdBiz ──────────────────────────────────────────────────────────

class TestDomainCmdBiz:
    def _mock_store(self, tmp_path: Path):
        """Create a minimal store mock and fake DB file."""
        db_path = tmp_path / ".rekipedia" / "store.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.touch()
        return db_path

    def _make_mock_store_obj(self):
        store_mock = MagicMock()
        store_mock.__enter__ = MagicMock(return_value=store_mock)
        store_mock.__exit__ = MagicMock(return_value=False)
        store_mock.latest_run_id.return_value = "run-1"
        store_mock.get_all_symbols.return_value = []
        store_mock.get_all_relationships.return_value = []
        store_mock.get_entry_points = MagicMock(return_value=[])
        return store_mock

    def test_biz_flag_invokes_analyzer(self, tmp_path: Path):
        self._mock_store(tmp_path)
        store_mock = self._make_mock_store_obj()
        graph = _make_graph()

        runner = CliRunner()
        with patch("rekipedia.storage.sqlite_store.SqliteStore", return_value=store_mock), \
             patch("rekipedia.analysis.biz_domain.BizDomainAnalyzer") as MockAnalyzer:
            instance = MockAnalyzer.return_value
            instance.analyze.return_value = graph
            instance.save.return_value = tmp_path / ".rekipedia" / "domain-graph.json"

            result = runner.invoke(domain_cmd, ["--biz", str(tmp_path)])

        assert result.exit_code == 0, result.output
        instance.analyze.assert_called_once()

    def test_biz_json_flag_outputs_json(self, tmp_path: Path):
        self._mock_store(tmp_path)
        store_mock = self._make_mock_store_obj()
        graph = _make_graph()

        runner = CliRunner()
        with patch("rekipedia.storage.sqlite_store.SqliteStore", return_value=store_mock), \
             patch("rekipedia.analysis.biz_domain.BizDomainAnalyzer") as MockAnalyzer:
            instance = MockAnalyzer.return_value
            instance.analyze.return_value = graph
            instance.save.return_value = tmp_path / ".rekipedia" / "domain-graph.json"

            result = runner.invoke(domain_cmd, ["--biz", "--json", str(tmp_path)])

        assert result.exit_code == 0, result.output
        # Strip any leading console output before the JSON object
        json_start = result.output.find("{")
        data = json.loads(result.output[json_start:])
        assert data["project_name"] == "myapp"

    def test_biz_no_db_aborts(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(domain_cmd, ["--biz", str(tmp_path)])
        assert result.exit_code != 0

    def test_biz_shows_domain_tree(self, tmp_path: Path):
        self._mock_store(tmp_path)
        store_mock = self._make_mock_store_obj()
        graph = _make_graph()

        runner = CliRunner()
        with patch("rekipedia.storage.sqlite_store.SqliteStore", return_value=store_mock), \
             patch("rekipedia.analysis.biz_domain.BizDomainAnalyzer") as MockAnalyzer:
            instance = MockAnalyzer.return_value
            instance.analyze.return_value = graph
            instance.save.return_value = tmp_path / ".rekipedia" / "domain-graph.json"

            result = runner.invoke(domain_cmd, ["--biz", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "Payment Processing" in result.output
        assert "Create Order" in result.output

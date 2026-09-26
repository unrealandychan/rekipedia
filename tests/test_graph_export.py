from rekipedia.analysis.graph_export import export_cypher, export_graphml, export_interactive_html, export_obsidian

SYMS = [{'name': 'MyClass', 'kind': 'class', 'file': 'src/myclass.py'},
        {'name': 'my_func', 'kind': 'function', 'file': 'src/myclass.py'}]
RELS = [{'from_': 'MyClass', 'to': 'my_func', 'kind': 'calls'}]


def test_graphml_contains_nodes():
    xml = export_graphml(SYMS, RELS)
    assert 'MyClass' in xml
    assert 'my_func' in xml


def test_graphml_is_valid_xml():
    from xml.etree import ElementTree as ET
    xml = export_graphml(SYMS, RELS)
    ET.fromstring(xml)  # should not raise


def test_cypher_contains_create():
    cql = export_cypher(SYMS, RELS)
    assert 'CREATE' in cql
    assert 'MyClass' in cql


def test_cypher_contains_relationship():
    cql = export_cypher(SYMS, RELS)
    assert 'MATCH' in cql
    assert 'CALLS' in cql


def test_obsidian_creates_files(tmp_path):
    written = export_obsidian(SYMS, RELS, tmp_path)
    assert len(written) == 2
    content = (tmp_path / 'MyClass.md').read_text()
    assert '# MyClass' in content
    assert '[[my_func]]' in content


def test_obsidian_with_wiki_and_diagrams(tmp_path):
    wiki_dir = tmp_path / "mock_wiki"
    wiki_dir.mkdir()
    (wiki_dir / "onboarding.md").write_text("# Onboarding\n\nRead more at [Project Overview](index.md#summary).", encoding="utf-8")

    diags_dir = tmp_path / "mock_diags"
    diags_dir.mkdir()
    (diags_dir / "flow.md").write_text("# Flow\n\nRefer to [Onboarding](../wiki/onboarding.md).", encoding="utf-8")

    out_dir = tmp_path / "output_vault"
    written = export_obsidian(SYMS, RELS, out_dir, wiki_dir=wiki_dir, diagrams_dir=diags_dir)

    # Symbol files should be in "symbols" subdirectory when wiki_dir is provided
    assert (out_dir / "symbols" / "MyClass.md").exists()
    assert (out_dir / "symbols" / "my_func.md").exists()

    # Wiki files should be copied to the root and converted
    wiki_copied = out_dir / "onboarding.md"
    assert wiki_copied.exists()
    wiki_content = wiki_copied.read_text(encoding="utf-8")
    assert "[[index#summary|Project Overview]]" in wiki_content

    # Diagram files should be copied and converted
    diag_copied = out_dir / "diagrams" / "flow.md"
    assert diag_copied.exists()
    diag_content = diag_copied.read_text(encoding="utf-8")
    assert "[[onboarding|Onboarding]]" in diag_content


def test_export_interactive_html_embeds_data():
    nodes = [{"id": "App", "name": "App", "kind": "class", "file": "src/app.py"}]
    edges = [{"source": "App", "target": "DB", "kind": "calls"}]
    god_nodes = [{"name": "App", "degree": 5}]
    hypers = [{"id": "p1", "concept": "Repo Pattern", "nodes": ["A", "B", "C"]}]

    html = export_interactive_html(nodes, edges, god_nodes, hypers, title="Test Graph")
    assert "<!DOCTYPE html>" in html
    assert "Test Graph" in html
    assert "d3.forceSimulation" in html
    assert '"nodes": [' in html
    assert '"App"' in html
    assert '"Repo Pattern"' in html


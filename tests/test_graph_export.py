from rekipedia.analysis.graph_export import export_cypher, export_graphml, export_obsidian

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

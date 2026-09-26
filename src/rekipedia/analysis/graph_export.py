"""Graph export to GraphML, Neo4j Cypher, Obsidian wikilinks."""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET


def export_graphml(symbols: list, relationships: list) -> str:
    """Export graph as GraphML XML string."""
    root = ET.Element('graphml', xmlns='http://graphml.graphdrawing.org/graphml')
    for attr, typ in [('kind', 'string'), ('file', 'string')]:
        ET.SubElement(root, 'key', id=f'k_{attr}', **{'for': 'node', 'attr.name': attr, 'attr.type': typ})
    ET.SubElement(root, 'key', id='k_kind_e', **{'for': 'edge', 'attr.name': 'kind', 'attr.type': 'string'})

    graph = ET.SubElement(root, 'graph', id='G', edgedefault='directed')

    for s in symbols:
        name = s.name if hasattr(s, 'name') else s.get('name', '')
        file = s.file if hasattr(s, 'file') else s.get('file', '')
        kind = s.kind if hasattr(s, 'kind') else s.get('kind', '')
        if not name:
            continue
        node = ET.SubElement(graph, 'node', id=name)
        d1 = ET.SubElement(node, 'data', key='k_kind'); d1.text = kind
        d2 = ET.SubElement(node, 'data', key='k_file'); d2.text = file

    for i, r in enumerate(relationships):
        frm = r.get('from_', '') or r.get('from', '') if isinstance(r, dict) else (r.from_ or '')
        to = r.get('to', '') if isinstance(r, dict) else r.to
        kind = r.get('kind', '') if isinstance(r, dict) else r.kind
        if not frm or not to:
            continue
        edge = ET.SubElement(graph, 'edge', id=f'e{i}', source=frm, target=to)
        d = ET.SubElement(edge, 'data', key='k_kind_e'); d.text = kind

    return ET.tostring(root, encoding='unicode', xml_declaration=False)


def export_cypher(symbols: list, relationships: list) -> str:
    """Export graph as Neo4j Cypher CREATE statements."""
    lines = ['// rekipedia graph export — Neo4j Cypher']
    for s in symbols:
        name = s.name if hasattr(s, 'name') else s.get('name', '')
        kind = s.kind if hasattr(s, 'kind') else s.get('kind', '')
        file = s.file if hasattr(s, 'file') else s.get('file', '')
        if not name:
            continue
        safe = name.replace("'", "\\'")
        safe_file = file.replace("'", "\\'")
        lines.append(f"CREATE (:`Symbol` {{name: '{safe}', kind: '{kind}', file: '{safe_file}'}})")
    lines.append('')
    for r in relationships:
        frm = r.get('from_', '') or r.get('from', '') if isinstance(r, dict) else (r.from_ or '')
        to = r.get('to', '') if isinstance(r, dict) else r.to
        kind = (r.get('kind', '') if isinstance(r, dict) else r.kind).upper().replace('-', '_')
        if not frm or not to:
            continue
        sf = frm.replace("'", "\\'")
        st = to.replace("'", "\\'")
        lines.append(f"MATCH (a:Symbol {{name: '{sf}'}}), (b:Symbol {{name: '{st}'}}) CREATE (a)-[:{kind}]->(b);")
    return '\n'.join(lines)


def export_obsidian(
    symbols: list,
    relationships: list,
    output_dir: Path,
    wiki_dir: Path | None = None,
    diagrams_dir: Path | None = None,
) -> list[Path]:
    """Write one .md file per symbol with wikilinks, and copy/convert wiki pages & diagrams."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    import re

    # 1. Build Inbound and Outbound relationships
    callees: dict[str, list[tuple[str, str]]] = {}  # frm -> [(to, kind)]
    callers: dict[str, list[tuple[str, str]]] = {}  # to -> [(frm, kind)]

    for r in relationships:
        frm = r.get('from_', '') or r.get('from', '') if isinstance(r, dict) else getattr(r, 'from_', '') or getattr(r, 'from', '')
        to = r.get('to', '') if isinstance(r, dict) else getattr(r, 'to', '')
        kind = r.get('kind', '') if isinstance(r, dict) else getattr(r, 'kind', '')
        if frm and to and kind in ('calls', 'imports', 'inherits'):
            callees.setdefault(frm, []).append((to, kind))
            callers.setdefault(to, []).append((frm, kind))

    # Determine symbol target directory
    # If wiki_dir is provided, we organize symbols under a "symbols" folder to keep root clean
    sym_dir = output_dir / "symbols" if wiki_dir else output_dir
    if wiki_dir:
        sym_dir.mkdir(parents=True, exist_ok=True)

    # 2. Write Symbol Notes
    for s in symbols:
        name = s.name if hasattr(s, 'name') else s.get('name', '')
        kind = s.kind if hasattr(s, 'kind') else s.get('kind', '')
        file = s.file if hasattr(s, 'file') else s.get('file', '')
        if not name:
            continue
        safe_name = name.replace('/', '_').replace(':', '_')
        md_path = sym_dir / f'{safe_name}.md'

        # Fetch relations
        out_rels = callees.get(name, [])
        in_rels = callers.get(name, [])

        # Build card content with frontmatter
        lines = [
            '---',
            f'kind: {kind}',
            f'file: {file}',
            'tags:',
            '  - codebase/symbol',
            f'  - codebase/{kind}',
            '---',
            '',
            f'# {name}',
            '',
            f'**Kind:** {kind}  ',
            f'**File:** `{file}`',
            '',
        ]

        if out_rels or in_rels:
            lines.append('## References')
            
            if out_rels:
                lines.append('### Outgoing')
                for target, rel_kind in out_rels[:50]:  # Up to 50
                    safe_target = target.replace('/', '_').replace(':', '_')
                    lines.append(f'- [[{safe_target}]] ({rel_kind})')
                lines.append('')
                
            if in_rels:
                lines.append('### Incoming')
                for source, rel_kind in in_rels[:50]:  # Up to 50
                    safe_source = source.replace('/', '_').replace(':', '_')
                    lines.append(f'- [[{safe_source}]] (called by {rel_kind})')
                lines.append('')

        md_path.write_text('\n'.join(lines), encoding='utf-8')
        written.append(md_path)

    # 3. Helper function for link conversion
    def convert_md_links_to_wikilinks(text: str) -> str:
        # Converts [Display](file.md#anchor) -> [[file#anchor|Display]]
        pattern = r'\[([^\]]+)\]\(([^)]+?)\.md(#?[^)]*)\)'
        def replace(match):
            display = match.group(1)
            path_part = match.group(2)
            anchor = match.group(3)
            stem = Path(path_part).name
            if anchor:
                return f"[[{stem}{anchor}|{display}]]"
            return f"[[{stem}|{display}]]"
        return re.sub(pattern, replace, text)

    # 4. Copy and Convert Wiki Pages
    if wiki_dir and wiki_dir.exists():
        for p in sorted(wiki_dir.glob("*.md")):
            content = p.read_text(encoding="utf-8")
            converted_content = convert_md_links_to_wikilinks(content)
            
            # Put wiki pages at the root of the output directory
            dest_path = output_dir / p.name
            dest_path.write_text(converted_content, encoding="utf-8")
            written.append(dest_path)

    # 5. Copy and Convert Diagrams
    if diagrams_dir and diagrams_dir.exists():
        diag_out = output_dir / "diagrams"
        diag_out.mkdir(parents=True, exist_ok=True)
        for p in sorted(diagrams_dir.glob("*.md")):
            content = p.read_text(encoding="utf-8")
            converted_content = convert_md_links_to_wikilinks(content)
            
            dest_path = diag_out / p.name
            dest_path.write_text(converted_content, encoding="utf-8")
            written.append(dest_path)

    return written


def export_interactive_html(
    nodes: list[dict],
    edges: list[dict],
    god_nodes: list[dict] | None = None,
    hyperedges: list[dict] | None = None,
    title: str = "rekipedia codebase graph",
) -> str:
    """Generate a self-contained, interactive HTML force-directed dependency graph (zero-server offline viewer)."""
    import json

    god_nodes = god_nodes or []
    hyperedges = hyperedges or []

    graph_payload = {
        "title": title,
        "nodes": nodes,
        "edges": edges,
        "god_nodes": god_nodes,
        "hyperedges": hyperedges,
    }
    json_data = json.dumps(graph_payload, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
<style>
  :root {{
    --bg: #0d1117;
    --panel-bg: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
    --accent: #58a6ff;
    --accent-hover: #79c0ff;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    overflow: hidden;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }}
  header {{
    height: 52px;
    background: var(--panel-bg);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 1.25rem;
    z-index: 10;
  }}
  .brand {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }}
  .brand h1 {{
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--text);
    letter-spacing: -0.01em;
  }}
  .badge {{
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    background: rgba(88, 166, 255, 0.15);
    color: var(--accent);
    border-radius: 999px;
    font-weight: 500;
  }}
  .controls {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }}
  input[type="text"], select {{
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 6px;
    padding: 0.35rem 0.65rem;
    font-size: 0.82rem;
    outline: none;
    transition: border-color 0.2s;
  }}
  input[type="text"]:focus, select:focus {{
    border-color: var(--accent);
  }}
  button {{
    background: var(--panel-bg);
    border: 1px solid var(--border);
    color: var(--muted);
    border-radius: 6px;
    padding: 0.35rem 0.75rem;
    font-size: 0.82rem;
    cursor: pointer;
    transition: all 0.2s;
  }}
  button:hover {{
    color: var(--text);
    border-color: var(--accent);
  }}
  #canvas-container {{
    flex: 1;
    position: relative;
    width: 100%;
    height: 100%;
  }}
  svg {{
    width: 100%;
    height: 100%;
    display: block;
  }}
  .node circle {{
    stroke: #ffffff;
    stroke-width: 1.5px;
    cursor: pointer;
    transition: r 0.2s, stroke-width 0.2s;
  }}
  .node:hover circle {{
    stroke-width: 3px;
    stroke: var(--accent);
  }}
  .node text {{
    font-family: monospace;
    font-size: 10px;
    fill: #c9d1d9;
    pointer-events: none;
    text-shadow: 0 1px 2px rgba(0,0,0,0.8);
  }}
  .link {{
    stroke: #30363d;
    stroke-opacity: 0.6;
    stroke-width: 1.2px;
  }}
  .link.highlight {{
    stroke: var(--accent);
    stroke-opacity: 1;
    stroke-width: 2.2px;
  }}
  #sidebar {{
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
    width: 340px;
    background: var(--panel-bg);
    border-left: 1px solid var(--border);
    padding: 1.25rem;
    transform: translateX(100%);
    transition: transform 0.25s ease;
    overflow-y: auto;
    z-index: 20;
  }}
  #sidebar.open {{
    transform: translateX(0);
  }}
  .close-btn {{
    float: right;
    background: none;
    border: none;
    color: var(--muted);
    font-size: 1.2rem;
    cursor: pointer;
  }}
  .close-btn:hover {{ color: var(--text); }}
  .sidebar-title {{
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 0.3rem;
    word-break: break-all;
  }}
  .sidebar-meta {{
    font-size: 0.8rem;
    color: var(--muted);
    margin-bottom: 1rem;
  }}
  .section-label {{
    font-size: 0.75rem;
    text-transform: uppercase;
    color: var(--muted);
    letter-spacing: 0.05em;
    margin: 1rem 0 0.4rem;
    font-weight: 600;
  }}
  .ref-list {{
    list-style: none;
    font-size: 0.82rem;
  }}
  .ref-list li {{
    padding: 0.25rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    color: #c9d1d9;
  }}
  .stats-bar {{
    position: absolute;
    bottom: 1rem;
    left: 1rem;
    background: rgba(22, 27, 34, 0.85);
    backdrop-filter: blur(8px);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.4rem 0.8rem;
    font-size: 0.78rem;
    color: var(--muted);
    z-index: 5;
    pointer-events: none;
  }}
</style>
</head>
<body>
<header>
  <div class="brand">
    <h1>rekipedia</h1>
    <span class="badge">Knowledge Graph</span>
  </div>
  <div class="controls">
    <input type="text" id="search" placeholder="Search node or file…"/>
    <select id="kind-filter">
      <option value="">All Kinds</option>
    </select>
    <button id="btn-reset">Reset View</button>
  </div>
</header>
<div id="canvas-container">
  <svg id="graph-svg"></svg>
  <div id="sidebar">
    <button class="close-btn" id="btn-close-sidebar">&times;</button>
    <h2 class="sidebar-title" id="side-name">Select a node</h2>
    <div class="sidebar-meta" id="side-meta"></div>
    <div id="side-content"></div>
  </div>
  <div class="stats-bar" id="stats-bar">Loading graph…</div>
</div>

<script>
const DATA = {json_data};

(function() {{
  const nodes = DATA.nodes || [];
  const edges = DATA.edges || [];
  const godNodes = DATA.god_nodes || [];
  const hyperedges = DATA.hyperedges || [];

  document.getElementById("stats-bar").textContent =
    `${{nodes.length}} nodes · ${{edges.length}} edges · ${{godNodes.length}} god nodes`;

  // Populate kind filter
  const kinds = [...new Set(nodes.map(n => n.kind || "module"))].sort();
  const select = document.getElementById("kind-filter");
  kinds.forEach(k => {{
    const opt = document.createElement("option");
    opt.value = k;
    opt.textContent = k;
    select.appendChild(opt);
  }});

  const width = window.innerWidth;
  const height = window.innerHeight - 52;

  const svg = d3.select("#graph-svg")
    .attr("viewBox", [0, 0, width, height]);

  const g = svg.append("g");

  const zoom = d3.zoom()
    .scaleExtent([0.1, 8])
    .on("zoom", (event) => g.attr("transform", event.transform));
  svg.call(zoom);

  // Community / kind color scale
  const color = d3.scaleOrdinal(d3.schemeCategory10);

  // Lookup node degrees
  const inDegree = {{}};
  const outDegree = {{}};
  const callersMap = {{}};
  const calleesMap = {{}};

  edges.forEach(e => {{
    const s = e.source, t = e.target;
    outDegree[s] = (outDegree[s] || 0) + 1;
    inDegree[t] = (inDegree[t] || 0) + 1;
    (calleesMap[s] = calleesMap[s] || []).push(e);
    (callersMap[t] = callersMap[t] || []).push(e);
  }});

  // Arrow markers
  svg.append("defs").append("marker")
    .attr("id", "arrow")
    .attr("viewBox", "0 -5 10 10")
    .attr("refX", 18)
    .attr("refY", 0)
    .attr("markerWidth", 6)
    .attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path")
    .attr("fill", "#58a6ff")
    .attr("d", "M0,-5L10,0L0,5");

  const simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id(d => d.id || d.name).distance(75))
    .force("charge", d3.forceManyBody().strength(-140))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide().radius(22));

  const link = g.append("g")
    .attr("class", "links")
    .selectAll("line")
    .data(edges)
    .join("line")
    .attr("class", "link")
    .attr("marker-end", "url(#arrow)");

  const node = g.append("g")
    .attr("class", "nodes")
    .selectAll("g")
    .data(nodes)
    .join("g")
    .attr("class", "node")
    .call(d3.drag()
      .on("start", dragstarted)
      .on("drag", dragged)
      .on("end", dragended));

  node.append("circle")
    .attr("r", d => 5 + Math.min(12, ((inDegree[d.id || d.name] || 0) + (outDegree[d.id || d.name] || 0)) * 0.8))
    .attr("fill", d => color(d.community || d.kind || "module"));

  node.append("text")
    .attr("x", 8)
    .attr("y", 3)
    .text(d => d.label || d.name || d.id);

  node.on("click", (event, d) => showDetails(d));

  simulation.on("tick", () => {{
    link
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);

    node
      .attr("transform", d => `translate(${{d.x}},${{d.y}})`);
  }});

  function dragstarted(event) {{
    if (!event.active) simulation.alphaTarget(0.3).restart();
    event.subject.fx = event.subject.x;
    event.subject.fy = event.subject.y;
  }}
  function dragged(event) {{
    event.subject.fx = event.x;
    event.subject.fy = event.y;
  }}
  function dragended(event) {{
    if (!event.active) simulation.alphaTarget(0);
    event.subject.fx = null;
    event.subject.fy = null;
  }}

  // Filter & Search
  function applyFilter() {{
    const q = document.getElementById("search").value.toLowerCase();
    const k = document.getElementById("kind-filter").value;

    node.style("display", d => {{
      const name = (d.name || d.id || "").toLowerCase();
      const file = (d.file || "").toLowerCase();
      const matchesQ = !q || name.includes(q) || file.includes(q);
      const matchesK = !k || (d.kind || "module") === k;
      return (matchesQ && matchesK) ? "" : "none";
    }});
  }}

  document.getElementById("search").addEventListener("input", applyFilter);
  document.getElementById("kind-filter").addEventListener("change", applyFilter);
  document.getElementById("btn-reset").addEventListener("click", () => {{
    svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
    document.getElementById("search").value = "";
    document.getElementById("kind-filter").value = "";
    applyFilter();
  }});

  // Details drawer
  const sidebar = document.getElementById("sidebar");
  document.getElementById("btn-close-sidebar").addEventListener("click", () => {{
    sidebar.classList.remove("open");
  }});

  function showDetails(d) {{
    const id = d.id || d.name;
    document.getElementById("side-name").textContent = d.name || id;
    document.getElementById("side-meta").textContent = `Kind: ${{d.kind || "module"}} | File: ${{d.file || "n/a"}}`;

    const ins = callersMap[id] || [];
    const outs = calleesMap[id] || [];

    let html = `<p style="font-size:0.8rem;color:var(--muted);margin-bottom:0.8rem;">Degree: ${{ins.length + outs.length}} (In: ${{ins.length}}, Out: ${{outs.length}})</p>`;

    if (ins.length > 0) {{
      html += `<div class="section-label">Callers (${{ins.length}})</div><ul class="ref-list">`;
      ins.slice(0, 15).forEach(e => {{
        const src = typeof e.source === "object" ? (e.source.id || e.source.name) : e.source;
        html += `<li>← ${{src}} <span style="color:var(--muted)">(${{e.kind || "calls"}})</span></li>`;
      }});
      html += `</ul>`;
    }}

    if (outs.length > 0) {{
      html += `<div class="section-label">Callees (${{outs.length}})</div><ul class="ref-list">`;
      outs.slice(0, 15).forEach(e => {{
        const tgt = typeof e.target === "object" ? (e.target.id || e.target.name) : e.target;
        html += `<li>→ ${{tgt}} <span style="color:var(--muted)">(${{e.kind || "calls"}})</span></li>`;
      }});
      html += `</ul>`;
    }}

    document.getElementById("side-content").innerHTML = html;
    sidebar.classList.add("open");
  }}
}})();
</script>
</body>
</html>
"""


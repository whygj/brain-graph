#!/usr/bin/env python3
"""graph.agentmj.vip — BrainGraph for AgentMJ.

Data sources:
1. AI记忆 = fact_store (memory_store.db) — structured entities & relations
2. Team-A (team-a/) — AI漫剧项目文件
3. Team-B (team-b/) — MobileClaw天机阁项目文件
4. Team-C (team-c/) — 电商项目文件
5. 共享资源 (shared/) — 跨团队共享知识
"""

import json
import sqlite3
import os
import re
import sys
from collections import Counter

# Add parent dir for auth_helper import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from flask import Flask, jsonify, send_from_directory, request, redirect, url_for
from auth_helper import auth_bp, login_required, set_site_branding

DB_PATH = "/home/ubuntu/.hermes/memory_store.db"
PROJECTS_PATH = "/home/ubuntu/projects"

# Directories to scan as knowledge graph sources
PROJECT_SOURCES = {
    "Team-A 漫剧": os.path.join(PROJECTS_PATH, "team-a"),
    "Team-B 天机阁": os.path.join(PROJECTS_PATH, "team-b"),
    "Team-C 电商": os.path.join(PROJECTS_PATH, "team-c"),
    "共享资源": os.path.join(PROJECTS_PATH, "shared"),
}

app = Flask(__name__, static_folder=os.path.dirname(__file__))
app.register_blueprint(auth_bp)
set_site_branding("🕸️", "知识图谱")

SOURCES = {}


def _load_sqlite(db_path):
    """Load entities and relations from fact_store."""
    if not os.path.exists(db_path):
        return {"nodes": [], "edges": [], "entity_facts": {}, "stats": {}}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cur = conn.execute("""
        SELECT e.name, e.entity_type, COUNT(fe.fact_id) AS fact_count
        FROM entities e LEFT JOIN fact_entities fe ON fe.entity_id = e.entity_id
        GROUP BY e.entity_id ORDER BY fact_count DESC
    """)
    nodes = [{"id": r[0], "type": r[1] or "unknown", "facts": r[2]} for r in cur.fetchall()]

    cur = conn.execute("""
        SELECT e1.name AS src, e2.name AS tgt, COUNT(*) AS shared,
               GROUP_CONCAT(f.content, '|||') AS contents
        FROM fact_entities fe1
        JOIN fact_entities fe2 ON fe1.fact_id = fe2.fact_id AND fe1.entity_id < fe2.entity_id
        JOIN entities e1 ON fe1.entity_id = e1.entity_id
        JOIN entities e2 ON fe2.entity_id = e2.entity_id
        JOIN facts f ON fe1.fact_id = f.fact_id
        GROUP BY e1.entity_id, e2.entity_id
    """)
    edges = [{
        "source": r[0], "target": r[1],
        "weight": r[2],
        "label": r[3].split("|||")[0][:80] if r[3] else "",
        "shared_facts": r[3].split("|||") if r[3] else []
    } for r in cur.fetchall()]

    cur = conn.execute("""
        SELECT e.name, GROUP_CONCAT(f.content, '|||') AS all_facts
        FROM entities e JOIN fact_entities fe ON fe.entity_id = e.entity_id
        JOIN facts f ON fe.fact_id = f.fact_id GROUP BY e.entity_id
    """)
    entity_facts = {r[0]: r[1].split("|||") for r in cur.fetchall()}

    types = Counter(n["type"] for n in nodes)
    stats = {
        "total_nodes": len(nodes), "total_edges": len(edges),
        "total_facts": sum(n["facts"] for n in nodes),
        "types": dict(types.most_common()),
        "isolated": sum(1 for n in nodes if n["facts"] == 0),
    }
    conn.close()
    return {"nodes": nodes, "edges": edges, "entity_facts": entity_facts, "stats": stats}


def _load_projects(name, dir_path):
    """Load markdown files from a project directory as graph nodes.
    
    Edge generation strategies (in priority order):
    1. [[wikilinks]] — explicit manual links in content
    2. Same-directory grouping — files in same subdir are lightly connected
    3. Tag/title keyword overlap — files sharing significant keywords are connected
    
    This ensures rich graphs even without manual wikilinks.
    """
    if not os.path.isdir(dir_path):
        return {"nodes": [], "edges": [], "entity_facts": {}, "stats": {}}

    link_re = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
    tag_re = re.compile(r"^tags:\s*\[(.+?)\]", re.MULTILINE)

    # Skip hidden dirs, node_modules, .git, __pycache__, .venv
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", ".cache"}

    files = {}
    for root, dirs, fnames in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for fn in fnames:
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(root, fn)
            node_id = fn[:-3]
            rel = os.path.relpath(root, dir_path)
            group = rel if rel != "." else name
            try:
                text = open(fp, encoding="utf-8", errors="ignore").read()
            except:
                continue
            links = list(set(link_re.findall(text)))
            first_line = text.split("\n")[0][:120] if text else ""
            
            # Extract keywords from title and headings for auto-linking
            headings = re.findall(r"^#+\s+(.+)$", text, re.MULTILINE)
            title_words = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", first_line))
            heading_words = set()
            for h in headings[:5]:
                heading_words.update(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", h))
            keywords = title_words | heading_words
            # Filter common stopwords
            stopwords = {"the", "and", "for", "that", "this", "with", "from", "are", "was", "not", "but", "all", "can", "has", "have", "will", "you", "your", "into", "how", "what", "why", "when", "than", "then", "them", "they", "been", "some", "more", "very", "also", "just", "like", "about"}
            keywords = keywords - stopwords
            
            files[node_id] = {
                "content": first_line,
                "links": links,
                "group": group,
                "path": os.path.relpath(fp, dir_path),
                "size": len(text),
                "keywords": keywords,
            }

    # Deduplicate node IDs by appending parent dir if collision
    seen = {}
    final_files = {}
    for nid, f in files.items():
        if nid in seen:
            old_nid = nid
            old_f = seen[nid]
            new_old = f"[{old_f['group']}] {old_nid}"
            final_files[new_old] = old_f
            new_curr = f"[{f['group']}] {nid}"
            final_files[new_curr] = f
        else:
            final_files[nid] = f
            seen[nid] = f

    nodes = [{
        "id": n,
        "type": "note",
        "facts": len(f["links"]),
        "group": f["group"],
        "size": f.get("size", 0),
    } for n, f in final_files.items()]

    edge_set = set()
    edges = []
    
    def add_edge(src, tgt, weight, label):
        key = tuple(sorted([src, tgt]))
        if key not in edge_set and src != tgt:
            edge_set.add(key)
            edges.append({"source": src, "target": tgt, "weight": weight, "label": label})

    # Strategy 1: [[wikilinks]] (strongest, weight=3)
    for name_, f in final_files.items():
        for link in f["links"]:
            if link in final_files:
                add_edge(name_, link, 3, "[[" + link + "]]")

    # Strategy 2: Keyword overlap (weight=2 for 3+ shared keywords)
    node_list = list(final_files.items())
    for i in range(len(node_list)):
        name_a, fa = node_list[i]
        kwa = fa.get("keywords", set())
        if len(kwa) < 2:
            continue
        for j in range(i + 1, len(node_list)):
            name_b, fb = node_list[j]
            kwb = fb.get("keywords", set())
            if len(kwb) < 2:
                continue
            shared = kwa & kwb
            if len(shared) >= 3:
                sample = list(shared)[:3]
                add_edge(name_a, name_b, 2, f"关键词: {', '.join(sample)}")

    entity_facts = {n: [f["content"][:200]] for n, f in final_files.items()}

    dir_counts = Counter(f["group"] for f in final_files.values())
    total_size = sum(f.get("size", 0) for f in final_files.values())
    edge_types = Counter(
        "wikilink" if e["weight"] == 3 else "keyword" for e in edges
    )
    stats = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "types": {"note": len(nodes)},
        "edge_types": dict(edge_types),
        "directories": dict(dir_counts.most_common(20)),
        "total_size_kb": round(total_size / 1024, 1),
    }
    return {"nodes": nodes, "edges": edges, "entity_facts": entity_facts, "stats": stats}


# Init all sources
SOURCES["AI记忆"] = _load_sqlite(DB_PATH)
for src_name, src_path in PROJECT_SOURCES.items():
    if os.path.isdir(src_path):
        SOURCES[src_name] = _load_projects(src_name, src_path)

for name, data in SOURCES.items():
    n_nodes = data["stats"].get("total_nodes", 0)
    n_edges = data["stats"].get("total_edges", 0)
    dirs = data["stats"].get("directories", {})
    print(f"[Graph] {name}: {n_nodes} nodes, {n_edges} edges"
          + (f", top dirs: {list(dirs.keys())[:5]}" if dirs else ""))


@app.route("/")
@login_required
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/graph-data")
@login_required
def graph_data():
    source = request.args.get("source")
    if source and source in SOURCES:
        d = SOURCES[source]
    else:
        d = next(iter(SOURCES.values()), {"nodes": [], "edges": [], "entity_facts": {}, "stats": {}})
    return jsonify(d)


@app.route("/api/sources")
@login_required
def list_sources():
    return jsonify({"sources": [
        {"name": n, "type": "builtin", "nodes": d["stats"].get("total_nodes", 0), "edges": d["stats"].get("total_edges", 0)}
        for n, d in SOURCES.items()
    ]})


@app.route("/api/stats")
@login_required
def stats():
    source = request.args.get("source")
    d = SOURCES.get(source, next(iter(SOURCES.values()), {}))
    return jsonify(d.get("stats", {}))


@app.route("/api/search")
@login_required
def search():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify({"results": []})
    source = request.args.get("source")
    d = SOURCES.get(source, next(iter(SOURCES.values()), {}))
    results = [n for n in d.get("nodes", [])
               if q in n.get("id", "").lower() or q in n.get("type", "").lower()]
    return jsonify({"results": results[:50]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9121, debug=False)

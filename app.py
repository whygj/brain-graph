#!/usr/bin/env python3
"""BrainGraph - Knowledge Graph Visualizer for AI Memory and More.

Turns your AI agent's memory, wiki, or any structured data into a beautiful
interactive knowledge graph. Zero config, one command.
"""

import json
import os
import sys
import yaml
import argparse
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

from adapters import get_adapter

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "config.yaml"

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")

CONFIG = {}
SOURCES = {}
AUTH_PASSWORD = None


def load_config(path):
    p = Path(path).expanduser()
    if not p.exists():
        print(f"[BrainGraph] Config not found: {p} -- using defaults")
        return _default_config()
    with open(p) as f:
        return yaml.safe_load(f) or {}


def _default_config():
    return {
        "server": {"host": "0.0.0.0", "port": 9121, "debug": False},
        "sources": [
            {"name": "Hermes Memory", "type": "sqlite", "path": "~/.hermes/memory_store.db"}
        ],
    }


def init_sources(config):
    sources_cfg = config.get("sources", [])
    if not sources_cfg:
        hermes_db = Path("~/.hermes/memory_store.db").expanduser()
        if hermes_db.exists():
            sources_cfg = [{"name": "Hermes Memory", "type": "sqlite", "path": str(hermes_db)}]
    for sc in sources_cfg:
        name = sc.get("name", "unnamed")
        try:
            adapter = get_adapter(sc)
            SOURCES[name] = adapter
            print(f"[BrainGraph] Source '{name}' loaded -- {len(adapter.nodes)} nodes, {len(adapter.edges)} edges")
        except Exception as e:
            print(f"[BrainGraph] Failed to load source '{name}': {e}")


def _get_source(name=None):
    if name and name in SOURCES:
        return SOURCES[name]
    if SOURCES:
        return next(iter(SOURCES.values()))
    return None


def check_auth():
    if not AUTH_PASSWORD:
        return True
    token = request.cookies.get("bg_token") or request.args.get("token")
    return token == AUTH_PASSWORD


@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/api/graph-data")
def graph_data():
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401
    source_name = request.args.get("source")
    adapter = _get_source(source_name)
    if not adapter:
        return jsonify({"nodes": [], "edges": [], "entity_facts": {}, "stats": {}})
    return jsonify({
        "nodes": adapter.nodes,
        "edges": adapter.edges,
        "entity_facts": adapter.entity_facts,
        "stats": adapter.stats,
    })


@app.route("/api/sources")
def list_sources():
    return jsonify({
        "sources": [{"name": name, "type": src.source_type} for name, src in SOURCES.items()]
    })


@app.route("/api/stats")
def stats():
    source_name = request.args.get("source")
    adapter = _get_source(source_name)
    if not adapter:
        return jsonify({})
    return jsonify(adapter.stats)


@app.route("/api/search", methods=["GET", "POST"])
def search():
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401
    q = request.args.get("q", "").strip()
    if not q and request.is_json:
        q = request.json.get("q", "").strip()
    if not q:
        return jsonify({"results": []})
    source_name = request.args.get("source")
    adapter = _get_source(source_name)
    if not adapter:
        return jsonify({"results": []})
    ql = q.lower()
    results = [n for n in adapter.nodes if ql in n.get("id", "").lower() or ql in n.get("type", "").lower()]
    for name, facts in adapter.entity_facts.items():
        for fact in facts:
            if ql in fact.lower():
                if not any(r["id"] == name for r in results):
                    results.append({"id": name, "type": "search_match", "facts": 1})
    return jsonify({"results": results[:50]})


def _detect_source_type(path):
    path = Path(path).expanduser()
    if path.is_dir():
        if (path / ".obsidian").exists():
            return "obsidian"
        if list(path.glob("*.md")):
            return "markdown"
        return "markdown"
    suffix = path.suffix.lower()
    if suffix in (".db", ".sqlite", ".sqlite3"):
        return "sqlite"
    if suffix in (".json", ".csv"):
        return "json"
    return "sqlite"


def main():
    global AUTH_PASSWORD, CONFIG

    parser = argparse.ArgumentParser(description="BrainGraph - Knowledge Graph Visualizer")
    parser.add_argument("--config", "-c", default=str(DEFAULT_CONFIG), help="Path to config.yaml")
    parser.add_argument("--source", "-s", help="Single data source path (auto-detect type)")
    parser.add_argument("--port", "-p", type=int, help="Override port")
    parser.add_argument("--host", type=str, help="Override host")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    if args.source:
        src_path = Path(args.source).expanduser()
        src_type = _detect_source_type(src_path)
        CONFIG = {
            "server": {"host": "0.0.0.0", "port": args.port or 9121, "debug": args.debug},
            "sources": [{"name": src_path.stem, "type": src_type, "path": str(src_path)}],
        }
    else:
        CONFIG = load_config(args.config)

    auth_cfg = CONFIG.get("auth", {})
    if auth_cfg and auth_cfg.get("password"):
        AUTH_PASSWORD = auth_cfg["password"]

    init_sources(CONFIG)

    server = CONFIG.get("server", {})
    host = args.host or server.get("host", "0.0.0.0")
    port = args.port or server.get("port", 9121)
    debug = args.debug or server.get("debug", False)

    print(f"\n{'='*50}")
    print(f"  BrainGraph running at http://{host}:{port}")
    print(f"  Sources: {list(SOURCES.keys()) or 'none configured'}")
    print(f"{'='*50}\n")

    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()

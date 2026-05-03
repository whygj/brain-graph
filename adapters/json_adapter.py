#!/usr/bin/env python3
"""JSON/CSV adapter — reads structured data files."""

import json
import csv
from pathlib import Path


class JSONAdapter:
    source_type = "json"

    def __init__(self, config):
        self.config = config
        self.path = Path(config.get("path", "")).expanduser()
        self._nodes = None
        self._edges = None
        self._entity_facts = None
        self._stats = None

    @property
    def nodes(self):
        if self._nodes is None: self._load()
        return self._nodes

    @property
    def edges(self):
        if self._edges is None: self._load()
        return self._edges

    @property
    def entity_facts(self):
        if self._entity_facts is None: self._load()
        return self._entity_facts

    @property
    def stats(self):
        if self._stats is None: self._load()
        return self._stats

    def _load(self):
        if not self.path.exists():
            self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}
            return

        suffix = self.path.suffix.lower()
        if suffix == ".csv":
            self._load_csv()
        else:
            self._load_json()

    def _load_json(self):
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)

        # Format 1: {nodes: [...], edges: [...]}
        if isinstance(data, dict) and "nodes" in data:
            self._nodes = [
                {"id": n.get("id", str(i)), "type": n.get("type", "node"), "facts": n.get("facts", 0)}
                for i, n in enumerate(data["nodes"])
            ]
            self._edges = [
                {
                    "source": e.get("source", ""),
                    "target": e.get("target", ""),
                    "weight": e.get("weight", 1),
                    "label": e.get("label", ""),
                }
                for e in data.get("edges", [])
            ]
        # Format 2: flat array
        elif isinstance(data, list):
            id_field = self.config.get("id_field", "id")
            type_field = self.config.get("type_field", "type")
            self._nodes = [
                {"id": str(item.get(id_field, i)), "type": str(item.get(type_field, "item")), "facts": 1}
                for i, item in enumerate(data)
            ]
            self._edges = []
            src_f = self.config.get("source_field")
            tgt_f = self.config.get("target_field")
            if src_f and tgt_f:
                for item in data:
                    if src_f in item and tgt_f in item:
                        self._edges.append({
                            "source": str(item[src_f]),
                            "target": str(item[tgt_f]),
                            "weight": 1,
                            "label": item.get("label", ""),
                        })
        else:
            self._nodes, self._edges = [], []

        self._entity_facts = {n["id"]: [f"Type: {n['type']}"] for n in self._nodes}
        self._stats = {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "total_facts": len(self._nodes),
            "types": list(set(n["type"] for n in self._nodes)),
            "source": str(self.path),
        }

    def _load_csv(self):
        node_col = self.config.get("node_column", "name")
        src_col = self.config.get("source_column", "source")
        tgt_col = self.config.get("target_column", "target")

        nodes_set = set()
        edges = []
        with open(self.path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if src_col in row and tgt_col in row:
                    src, tgt = row[src_col], row[tgt_col]
                    nodes_set.add(src)
                    nodes_set.add(tgt)
                    edges.append({"source": src, "target": tgt, "weight": 1, "label": ""})
                elif node_col in row:
                    nodes_set.add(row[node_col])

        self._nodes = [{"id": n, "type": "node", "facts": 1} for n in sorted(nodes_set)]
        self._edges = edges
        self._entity_facts = {n: [] for n in nodes_set}
        self._stats = {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "total_facts": len(self._nodes),
            "types": ["node"],
            "source": str(self.path),
        }

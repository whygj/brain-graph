#!/usr/bin/env python3
"""Markdown adapter — scans folders of .md files, builds graph from [[links]]."""

import re
import os
from pathlib import Path
from collections import Counter


class MarkdownAdapter:
    source_type = "markdown"

    def __init__(self, config):
        self.config = config
        self.path = Path(config.get("path", "")).expanduser()
        self.link_pattern = config.get("link_pattern", r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
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

    def _parse_frontmatter(self, text):
        """Extract YAML frontmatter tags."""
        tags = []
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = parts[1]
                for line in fm.split("\n"):
                    line = line.strip()
                    if line.startswith("tags:") or line.startswith("tag:"):
                        tag_val = line.split(":", 1)[1].strip()
                        if tag_val.startswith("["):
                            tags.extend(re.findall(r'"([^"]+)"|(\w+)', tag_val))
                            tags = [t[0] or t[1] for t in re.findall(r'"([^"]+)"|(\w+)', tag_val)]
                        else:
                            tags.append(tag_val.strip('"').strip("'"))
                    elif line.startswith("- ") and tags:
                        tags.append(line[2:].strip().strip('"').strip("'"))
        return tags

    def _load(self):
        if not self.path.exists() or not self.path.is_dir():
            self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}
            return

        link_re = re.compile(self.link_pattern)
        files = {}  # id -> {content, links, tags, group}

        for md_file in sorted(self.path.rglob("*.md")):
            rel = md_file.relative_to(self.path)
            node_id = md_file.stem
            group = str(rel.parent) if str(rel.parent) != "." else ""
            text = md_file.read_text(encoding="utf-8", errors="ignore")
            tags = self._parse_frontmatter(text)
            links = list(set(link_re.findall(text)))
            # Resolve links to file stems
            resolved = []
            for link in links:
                link = link.strip()
                resolved.append(link)
            files[node_id] = {
                "content": text[:500],
                "links": resolved,
                "tags": tags,
                "group": group,
            }

        # Build nodes
        all_tags = set()
        for f in files.values():
            all_tags.update(f["tags"])

        self._nodes = [
            {
                "id": name,
                "type": "note",
                "facts": len(f["links"]) + len(f["tags"]),
                "group": f["group"],
                "tags": f["tags"],
            }
            for name, f in files.items()
        ]

        # Build edges
        edge_set = set()
        self._edges = []
        for name, f in files.items():
            for link in f["links"]:
                if link in files and link != name:
                    key = tuple(sorted([name, link]))
                    if key not in edge_set:
                        edge_set.add(key)
                        self._edges.append({
                            "source": name,
                            "target": link,
                            "weight": 1,
                            "label": f"[[{link}]]",
                        })

        # Shared tags also create edges
        tag_map = {}
        for name, f in files.items():
            for tag in f["tags"]:
                tag_map.setdefault(tag, []).append(name)
        for tag, node_ids in tag_map.items():
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    key = tuple(sorted([node_ids[i], node_ids[j]]))
                    if key not in edge_set:
                        edge_set.add(key)
                        self._edges.append({
                            "source": key[0],
                            "target": key[1],
                            "weight": 1,
                            "label": f"tag: {tag}",
                        })

        # Entity facts (file preview)
        self._entity_facts = {name: [f["content"][:200]] for name, f in files.items()}

        # Stats
        groups = Counter(n.get("group", "") for n in self._nodes)
        self._stats = {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "total_facts": sum(n["facts"] for n in self._nodes),
            "types": {"note": len(self._nodes)},
            "groups": dict(groups.most_common(10)),
            "source": str(self.path),
        }

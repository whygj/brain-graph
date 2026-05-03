#!/usr/bin/env python3
"""Obsidian adapter — reads vault folders, parses [[wikilinks]] and frontmatter."""

import re
from pathlib import Path
from adapters.markdown_adapter import MarkdownAdapter


class ObsidianAdapter(MarkdownAdapter):
    source_type = "obsidian"

    def __init__(self, config):
        config.setdefault("link_pattern", r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
        super().__init__(config)

    def _load(self):
        if not self.path.exists() or not self.path.is_dir():
            self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}
            return

        link_re = re.compile(self.link_pattern)
        files = {}

        for md_file in sorted(self.path.rglob("*.md")):
            # Skip .obsidian folder
            try:
                rel = md_file.relative_to(self.path)
            except ValueError:
                continue
            if str(rel).startswith(".obsidian"):
                continue

            node_id = md_file.stem
            group = str(rel.parent) if str(rel.parent) != "." else ""
            text = md_file.read_text(encoding="utf-8", errors="ignore")
            tags = self._parse_frontmatter(text)

            # Also extract #inline tags
            inline_tags = re.findall(r'(?:^|\s)#([a-zA-Z\u4e00-\u9fff][\w\u4e00-\u9fff]*)', text)
            tags.extend(inline_tags)
            tags = list(set(tags))

            # Parse [[links]]
            links = list(set(link_re.findall(text)))

            # Resolve links: strip alias after |, try to match existing file stems
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

        # Build edges from [[links]]
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

        # Edges from shared tags
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
                            "label": f"#{tag}",
                        })

        self._entity_facts = {name: [f["content"][:200]] for name, f in files.items()}

        from collections import Counter
        groups = Counter(n.get("group", "") for n in self._nodes)
        self._stats = {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "total_facts": sum(n["facts"] for n in self._nodes),
            "types": {"note": len(self._nodes)},
            "groups": dict(groups.most_common(10)),
            "tags": len(tag_map),
            "source": str(self.path),
            "is_vault": (self.path / ".obsidian").exists(),
        }

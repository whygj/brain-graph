#!/usr/bin/env python3
"""Obsidian adapter — reads vault folders, parses [[wikilinks]], frontmatter, and inline tags.

Inherits auto-linking strategies from MarkdownAdapter:
- [[wikilinks]]
- Tag overlap (frontmatter + inline #tags)
- Keyword overlap from headings
- Same-directory grouping
"""

import re
from pathlib import Path
from collections import Counter
from adapters.markdown_adapter import MarkdownAdapter


class ObsidianAdapter(MarkdownAdapter):
    """Obsidian vault adapter with extended tag extraction."""

    source_type = "obsidian"

    def __init__(self, config: dict) -> None:
        config.setdefault("link_pattern", r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
        super().__init__(config)

    def _load(self) -> None:
        if not self.path.exists() or not self.path.is_dir():
            self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}
            return

        link_re = re.compile(self.link_pattern)
        files: dict = {}

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

            try:
                text = md_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            tags = self._parse_frontmatter(text)

            # Extract #inline tags (Obsidian-style)
            inline_tags = re.findall(
                r'(?:^|\s)#([a-zA-Z\u4e00-\u9fff][\w\u4e00-\u9fff]*)', text
            )
            tags.extend(inline_tags)
            tags = list(set(tags))

            # Parse [[links]]
            links = list(set(link_re.findall(text)))
            links = [l.strip() for l in links]

            # Extract keywords from headings
            keywords = self._extract_keywords(text)

            files[node_id] = {
                "content": text[:500],
                "links": links,
                "tags": tags,
                "group": group,
                "keywords": keywords,
                "size": len(text),
            }

        # Build nodes
        self._nodes = [
            {
                "id": name,
                "type": "note",
                "facts": len(f["links"]) + len(f["tags"]) + len(f.get("keywords", set())),
                "group": f["group"],
                "tags": f["tags"],
                "size": f.get("size", 0),
            }
            for name, f in files.items()
        ]

        # Build edges
        edge_set: set = set()
        self._edges = []

        def add_edge(src: str, tgt: str, weight: int, label: str, etype: str) -> None:
            key = tuple(sorted([src, tgt]))
            if key not in edge_set and src != tgt:
                edge_set.add(key)
                self._edges.append({
                    "source": src,
                    "target": tgt,
                    "weight": weight,
                    "label": label,
                    "type": etype,
                })

        # Strategy 1: [[wikilinks]]
        for name, f in files.items():
            for link in f["links"]:
                if link in files and link != name:
                    add_edge(name, link, 3, f"[[{link}]]", "wikilink")

        # Strategy 2: Tag overlap (frontmatter + inline)
        tag_map: dict[str, list[str]] = {}
        for name, f in files.items():
            for tag in f["tags"]:
                tag_map.setdefault(tag, []).append(name)

        for tag, node_ids in tag_map.items():
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    add_edge(node_ids[i], node_ids[j], 2, f"#{tag}", "wikilink")

        # Strategy 3: Keyword overlap
        node_list = list(files.items())
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
                    sample = sorted(shared)[:3]
                    add_edge(name_a, name_b, 2, f"关键词: {', '.join(sample)}", "keyword")

        # Strategy 4: Same-directory grouping
        dir_map: dict[str, list[str]] = {}
        for name, f in files.items():
            g = f.get("group", "")
            if g:
                dir_map.setdefault(g, []).append(name)

        for dir_name, node_ids in dir_map.items():
            if len(node_ids) > 50:
                continue
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    add_edge(node_ids[i], node_ids[j], 1, f"dir: {dir_name}", "keyword")

        # Entity facts
        self._entity_facts = {name: [f["content"][:200]] for name, f in files.items()}

        # Stats
        groups = Counter(n.get("group", "") for n in self._nodes)
        edge_types = Counter(e.get("type", "unknown") for e in self._edges)
        degree: Counter = Counter()
        for e in self._edges:
            degree[e["source"]] += 1
            degree[e["target"]] += 1
        top5 = [{"id": n, "degree": d} for n, d in degree.most_common(5)]
        connected = set()
        for e in self._edges:
            connected.add(e["source"])
            connected.add(e["target"])

        self._stats = {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "total_facts": sum(n["facts"] for n in self._nodes),
            "types": {"note": len(self._nodes)},
            "edge_types": dict(edge_types),
            "groups": dict(groups.most_common(10)),
            "tags": len(tag_map),
            "top5": top5,
            "isolated": sum(1 for n in self._nodes if n["id"] not in connected),
            "source": str(self.path),
            "is_vault": (self.path / ".obsidian").exists(),
        }

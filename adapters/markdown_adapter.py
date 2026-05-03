#!/usr/bin/env python3
"""Markdown adapter — scans folders of .md files, builds graph from multiple strategies.

Edge generation strategies (in priority order):
1. [[wikilinks]] — explicit manual links in content
2. Tag overlap — files sharing YAML frontmatter tags
3. Keyword overlap — files sharing 3+ title/heading keywords
4. Same-directory grouping — files in same subdir get weak connections
"""

import re
import os
from pathlib import Path
from collections import Counter
from typing import Optional


class MarkdownAdapter:
    """Markdown folder adapter with auto-linking."""

    source_type = "markdown"

    # Stopwords to filter from keyword extraction
    STOPWORDS = frozenset({
        "the", "and", "for", "that", "this", "with", "from", "are", "was",
        "not", "but", "all", "can", "has", "have", "will", "you", "your",
        "into", "how", "what", "why", "when", "than", "then", "them", "they",
        "been", "some", "more", "very", "also", "just", "like", "about",
        "its", "his", "her", "she", "him", "our", "out", "get", "got",
        "one", "two", "new", "now", "way", "may", "use", "used", "using",
        "make", "made", "can", "could", "would", "should", "does", "don",
        "did", "was", "who", "which", "where", "here", "there", "been",
        "being", "were", "over", "such", "each", "only", "come", "than",
    })

    def __init__(self, config: dict) -> None:
        self.config = config
        self.path = Path(config.get("path", "")).expanduser()
        self.link_pattern = config.get(
            "link_pattern", r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]"
        )
        self._nodes: Optional[list] = None
        self._edges: Optional[list] = None
        self._entity_facts: Optional[dict] = None
        self._stats: Optional[dict] = None

    @property
    def nodes(self) -> list:
        if self._nodes is None:
            self._load()
        return self._nodes  # type: ignore

    @property
    def edges(self) -> list:
        if self._edges is None:
            self._load()
        return self._edges  # type: ignore

    @property
    def entity_facts(self) -> dict:
        if self._entity_facts is None:
            self._load()
        return self._entity_facts  # type: ignore

    @property
    def stats(self) -> dict:
        if self._stats is None:
            self._load()
        return self._stats  # type: ignore

    # ------------------------------------------------------------------
    # Frontmatter parsing
    # ------------------------------------------------------------------

    def _parse_frontmatter(self, text: str) -> list[str]:
        """Extract tags from YAML frontmatter."""
        tags: list[str] = []
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = parts[1]
                in_tags_block = False
                for line in fm.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("tags:") or stripped.startswith("tag:"):
                        tag_val = stripped.split(":", 1)[1].strip()
                        if tag_val.startswith("["):
                            tags.extend(
                                t[0] or t[1]
                                for t in re.findall(r'"([^"]+)"|(\w+)', tag_val)
                            )
                        elif tag_val:
                            tags.append(tag_val.strip('"').strip("'"))
                        in_tags_block = True
                    elif stripped.startswith("- ") and in_tags_block:
                        tags.append(stripped[2:].strip().strip('"').strip("'"))
                    else:
                        in_tags_block = False
        return tags

    # ------------------------------------------------------------------
    # Keyword extraction
    # ------------------------------------------------------------------

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract keywords from title (H1) and first 5 headings.

        Chinese words: 2+ chars
        English words: 3+ chars
        Stopwords are filtered.
        """
        headings = re.findall(r"^#+\s+(.+)$", text, re.MULTILINE)
        first_line = text.split("\n")[0][:120] if text else ""

        # Title words from H1 / first line
        title_words = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", first_line))
        # Heading words
        heading_words: set[str] = set()
        for h in headings[:5]:
            heading_words.update(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", h))

        keywords = (title_words | heading_words) - self.STOPWORDS
        return keywords

    # ------------------------------------------------------------------
    # Main loader
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists() or not self.path.is_dir():
            self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}
            return

        link_re = re.compile(self.link_pattern)

        files: dict[str, dict] = {}

        for md_file in sorted(self.path.rglob("*.md")):
            rel = md_file.relative_to(self.path)
            node_id = md_file.stem
            group = str(rel.parent) if str(rel.parent) != "." else ""

            try:
                text = md_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            tags = self._parse_frontmatter(text)
            links = list(set(link_re.findall(text)))
            links = [l.strip() for l in links]
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
                "facts": len(f["links"]) + len(f["tags"]) + len(f["keywords"]),
                "group": f["group"],
                "tags": f["tags"],
                "size": f.get("size", 0),
            }
            for name, f in files.items()
        ]

        # Build edges
        edge_set: set[tuple] = set()
        self._edges = []

        def add_edge(src: str, tgt: str, weight: int, label: str, etype: str) -> None:
            """Add a unique edge, deduplicating by sorted pair."""
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

        # Strategy 1: [[wikilinks]] (strongest, weight=3)
        for name, f in files.items():
            for link in f["links"]:
                if link in files and link != name:
                    add_edge(name, link, 3, f"[[{link}]]", "wikilink")

        # Strategy 2: Tag overlap (weight=2)
        tag_map: dict[str, list[str]] = {}
        for name, f in files.items():
            for tag in f["tags"]:
                tag_map.setdefault(tag, []).append(name)

        for tag, node_ids in tag_map.items():
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    add_edge(
                        node_ids[i], node_ids[j], 2,
                        f"tag: {tag}", "wikilink"
                    )

        # Strategy 3: Keyword overlap (weight=2 for 3+ shared keywords)
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
                    add_edge(
                        name_a, name_b, 2,
                        f"关键词: {', '.join(sample)}",
                        "keyword"
                    )

        # Strategy 4: Same-directory grouping (weak, weight=1)
        dir_map: dict[str, list[str]] = {}
        for name, f in files.items():
            g = f.get("group", "")
            if g:
                dir_map.setdefault(g, []).append(name)

        for dir_name, node_ids in dir_map.items():
            # Limit to prevent combinatorial explosion in large dirs
            if len(node_ids) > 50:
                continue
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    add_edge(
                        node_ids[i], node_ids[j], 1,
                        f"dir: {dir_name}", "keyword"
                    )

        # Entity facts (file preview)
        self._entity_facts = {
            name: [f["content"][:200]]
            for name, f in files.items()
        }

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
            "top5": top5,
            "isolated": sum(1 for n in self._nodes if n["id"] not in connected),
            "source": str(self.path),
        }

#!/usr/bin/env python3
"""SQLite adapter — reads Hermes Agent memory_store.db and similar schemas."""

import sqlite3
from pathlib import Path
from collections import Counter


class SQLiteAdapter:
    source_type = "sqlite"

    def __init__(self, config):
        self.config = config
        self.path = Path(config.get("path", "")).expanduser()
        self.tables = config.get("tables", {})
        self.field_map = config.get("field_map", {})
        self._nodes = None
        self._edges = None
        self._entity_facts = None
        self._stats = None

    @property
    def nodes(self):
        if self._nodes is None:
            self._load()
        return self._nodes

    @property
    def edges(self):
        if self._edges is None:
            self._load()
        return self._edges

    @property
    def entity_facts(self):
        if self._entity_facts is None:
            self._load()
        return self._entity_facts

    @property
    def stats(self):
        if self._stats is None:
            self._load()
        return self._stats

    def _load(self):
        if not self.path.exists():
            self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}
            return

        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row

        # Table names
        t_entities = self.tables.get("entities", "entities")
        t_facts = self.tables.get("facts", "facts")
        t_fe = self.tables.get("fact_entities", "fact_entities")

        # Field names
        f_eid = self.field_map.get("entity_id", "entity_id")
        f_ename = self.field_map.get("entity_name", "name")
        f_etype = self.field_map.get("entity_type", "entity_type")
        f_fid = self.field_map.get("fact_id", "fact_id")
        f_fcontent = self.field_map.get("fact_content", "content")

        # Nodes
        cur = conn.execute(f"""
            SELECT e.{f_eid}, e.{f_ename}, e.{f_etype}, COUNT(fe.{f_fid}) AS fact_count
            FROM {t_entities} e
            LEFT JOIN {t_fe} fe ON fe.{f_eid} = e.{f_eid}
            GROUP BY e.{f_eid}
            ORDER BY fact_count DESC
        """)
        self._nodes = [
            {"id": r[1], "type": r[2] or "unknown", "facts": r[3]}
            for r in cur.fetchall()
        ]

        # Edges (entities sharing facts)
        cur = conn.execute(f"""
            SELECT e1.{f_ename} AS src, e2.{f_ename} AS tgt,
                   COUNT(*) AS shared,
                   GROUP_CONCAT(f.{f_fcontent}, '|||') AS contents
            FROM {t_fe} fe1
            JOIN {t_fe} fe2 ON fe1.{f_fid} = fe2.{f_fid}
                 AND fe1.{f_eid} < fe2.{f_eid}
            JOIN {t_entities} e1 ON fe1.{f_eid} = e1.{f_eid}
            JOIN {t_entities} e2 ON fe2.{f_eid} = e2.{f_eid}
            JOIN {t_facts} f ON fe1.{f_fid} = f.{f_fid}
            GROUP BY e1.{f_eid}, e2.{f_eid}
        """)
        self._edges = [
            {
                "source": r[0], "target": r[1],
                "weight": r[2],
                "label": r[3].split("|||")[0][:80] if r[3] else "",
                "shared_facts": r[3].split("|||") if r[3] else []
            }
            for r in cur.fetchall()
        ]

        # Entity facts
        cur = conn.execute(f"""
            SELECT e.{f_ename}, GROUP_CONCAT(f.{f_fcontent}, '|||') AS all_facts
            FROM {t_entities} e
            JOIN {t_fe} fe ON fe.{f_eid} = e.{f_eid}
            JOIN {t_facts} f ON fe.{f_fid} = f.{f_fid}
            GROUP BY e.{f_eid}
        """)
        self._entity_facts = {r[0]: r[1].split("|||") for r in cur.fetchall()}

        # Stats
        types = Counter(n["type"] for n in self._nodes)
        self._stats = {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "total_facts": sum(n["facts"] for n in self._nodes),
            "types": dict(types.most_common()),
            "isolated": sum(1 for n in self._nodes if n["facts"] == 0),
            "source": str(self.path),
        }

        conn.close()

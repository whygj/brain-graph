#!/usr/bin/env python3
"""SQLite adapter — auto-detects schema, reads any SQLite DB as a knowledge graph.

Supported patterns:
1. Hermes Agent memory_store (entities + facts + fact_entities)
2. Generic two-table (entity table + fact table with foreign keys)
3. Single-table (table with name + content columns)

Uses PRAGMA table_info at load time to discover schema automatically.
"""

import sqlite3
import logging
from pathlib import Path
from collections import Counter
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SQLiteAdapter:
    """Auto-detecting SQLite adapter for BrainGraph."""

    source_type = "sqlite"

    def __init__(self, config: dict) -> None:
        self.config = config
        self.path = Path(config.get("path", "")).expanduser()
        self._nodes: Optional[list] = None
        self._edges: Optional[list] = None
        self._entity_facts: Optional[dict] = None
        self._stats: Optional[dict] = None
        self._warnings: list[str] = []

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
    # Schema introspection
    # ------------------------------------------------------------------

    @staticmethod
    def _get_table_info(conn: sqlite3.Connection, table_name: str) -> list[dict]:
        """Return column info for a table via PRAGMA table_info."""
        cur = conn.execute(f"PRAGMA table_info([{table_name}])")
        return [
            {"cid": r[0], "name": r[1], "type": r[2],
             "notnull": r[3], "default": r[4], "pk": r[5]}
            for r in cur.fetchall()
        ]

    @staticmethod
    def _list_tables(conn: sqlite3.Connection) -> list[str]:
        """Return all user table names."""
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return [r[0] for r in cur.fetchall()]

    @classmethod
    def _detect_schema(cls, conn: sqlite3.Connection) -> dict:
        """Probe all tables and return a schema descriptor.

        Returns dict with keys:
            mode: "hermes" | "two_table" | "single_table" | "empty"
            entity_table, entity_pk, entity_name_col, entity_type_col
            fact_table, fact_pk, fact_content_col
            link_table, link_entity_col, link_fact_col
            warnings: list[str]
        """
        tables = cls._list_tables(conn)
        result: dict[str, Any] = {"warnings": [], "mode": "empty"}

        if not tables:
            result["warnings"].append("Database has no user tables.")
            return result

        table_cols: dict[str, list[dict]] = {}
        for t in tables:
            table_cols[t] = cls._get_table_info(conn, t)

        # ---- Strategy 1: Hermes / three-table pattern ----
        # entities(id/name/entity_type) + facts(id/content) + fact_entities(fact_id/entity_id)
        t_lower = {t.lower(): t for t in tables}
        entity_tbl_name = t_lower.get("entities")
        fact_tbl_name = t_lower.get("facts")
        link_tbl_name = t_lower.get("fact_entities")

        if entity_tbl_name and fact_tbl_name:
            ec = {c["name"].lower(): c["name"] for c in table_cols[entity_tbl_name]}
            fc = {c["name"].lower(): c["name"] for c in table_cols[fact_tbl_name]}

            name_col = ec.get("name")
            type_col = ec.get("entity_type") or ec.get("type")
            eid_col = ec.get("id") or ec.get("entity_id")
            content_col = fc.get("content") or fc.get("body") or fc.get("text") or fc.get("fact")
            fid_col = fc.get("id") or fc.get("fact_id")

            if name_col and eid_col:
                result["mode"] = "two_table"
                result["entity_table"] = entity_tbl_name
                result["entity_pk"] = eid_col
                result["entity_name_col"] = name_col
                result["entity_type_col"] = type_col
                result["fact_table"] = fact_tbl_name
                result["fact_pk"] = fid_col
                result["fact_content_col"] = content_col

                # Check for link table
                if link_tbl_name:
                    lc = {c["name"].lower(): c["name"] for c in table_cols[link_tbl_name]}
                    link_eid = lc.get("entity_id") or lc.get("eid")
                    link_fid = lc.get("fact_id") or lc.get("fid")
                    if link_eid and link_fid:
                        result["mode"] = "hermes"
                        result["link_table"] = link_tbl_name
                        result["link_entity_col"] = link_eid
                        result["link_fact_col"] = link_fid
                        return result
                    # Try to auto-detect link columns by matching types
                    if len(lc) >= 2:
                        cols = list(lc.values())
                        # Heuristic: first int-col referencing entity pk, second referencing fact pk
                        result["mode"] = "hermes"
                        result["link_table"] = link_tbl_name
                        result["link_entity_col"] = cols[0]
                        result["link_fact_col"] = cols[1]
                        result["warnings"].append(
                            f"Link table '{link_tbl_name}' column names unclear; "
                            f"guessed ({cols[0]}, {cols[1]})."
                        )
                        return result

                # No link table — try to find a foreign-key column in fact table
                if fid_col:
                    for col_info in table_cols[fact_tbl_name]:
                        cn = col_info["name"].lower()
                        if cn in ("entity_id", "eid", "owner_id", "subject_id") and cn != fid_col.lower():
                            result["mode"] = "two_table_fk"
                            result["fact_fk_entity"] = col_info["name"]
                            return result

                # Two separate tables, no FK — we'll still return entity nodes with fact counts
                result["warnings"].append(
                    "Found entity and fact tables but no link/join table; "
                    "showing entities only."
                )
                return result

        # ---- Strategy 2: Single-table pattern ----
        for t in tables:
            cols = {c["name"].lower(): c["name"] for c in table_cols[t]}
            if "name" in cols and ("content" in cols or "text" in cols or "body" in cols or "fact" in cols):
                content_col = cols.get("content") or cols.get("text") or cols.get("body") or cols.get("fact")
                type_col = cols.get("type") or cols.get("entity_type") or cols.get("category")
                pk_col = cols.get("id") or cols.get("rowid") or list(cols.values())[0]
                result["mode"] = "single_table"
                result["entity_table"] = t
                result["entity_pk"] = pk_col
                result["entity_name_col"] = cols["name"]
                result["entity_type_col"] = type_col
                result["fact_content_col"] = content_col
                result["warnings"].append(
                    f"Using single-table mode on '{t}' (name + content columns detected)."
                )
                return result

        # ---- Strategy 3: Fallback — pick table with most rows ----
        best_table = None
        best_count = 0
        for t in tables:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
                if cnt > best_count:
                    best_count = cnt
                    best_table = t
            except Exception:
                continue

        if best_table:
            cols = {c["name"].lower(): c["name"] for c in table_cols[best_table]}
            name_col = (
                cols.get("name") or cols.get("title") or cols.get("label")
                or cols.get("key") or cols.get("id")
            )
            content_col = (
                cols.get("content") or cols.get("text") or cols.get("body")
                or cols.get("value") or cols.get("description")
            )
            if name_col:
                result["mode"] = "single_table"
                result["entity_table"] = best_table
                result["entity_pk"] = cols.get("id") or name_col
                result["entity_name_col"] = name_col
                result["entity_type_col"] = cols.get("type") or cols.get("category")
                result["fact_content_col"] = content_col
                result["warnings"].append(
                    f"No standard schema detected; using table '{best_table}' with "
                    f"name='{name_col}'" + (f", content='{content_col}'" if content_col else "")
                )
                return result

        result["warnings"].append(
            "Could not detect a usable schema in this database."
        )
        return result

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load graph data with auto-detected schema."""
        if not self.path.exists():
            logger.warning("SQLite file not found: %s", self.path)
            self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}
            self._warnings = ["File not found."]
            return

        try:
            conn = sqlite3.connect(str(self.path))
            conn.row_factory = sqlite3.Row
        except Exception as exc:
            logger.error("Cannot open SQLite DB %s: %s", self.path, exc)
            self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}
            self._warnings = [f"Cannot open database: {exc}"]
            return

        try:
            schema = self._detect_schema(conn)
            self._warnings = schema.get("warnings", [])

            if schema["mode"] == "hermes":
                self._load_hermes(conn, schema)
            elif schema["mode"] == "two_table":
                self._load_two_table(conn, schema)
            elif schema["mode"] == "two_table_fk":
                self._load_two_table_fk(conn, schema)
            elif schema["mode"] == "single_table":
                self._load_single_table(conn, schema)
            else:
                logger.warning("No usable schema detected in %s", self.path)
                self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}

            # Add warnings to stats
            if self._stats:
                self._stats["warnings"] = self._warnings
                self._stats["schema_mode"] = schema["mode"]
        except Exception as exc:
            logger.error("Error loading SQLite %s: %s", self.path, exc)
            self._nodes, self._edges, self._entity_facts, self._stats = [], [], {}, {}
            self._warnings.append(f"Load error: {exc}")
        finally:
            conn.close()

    def _load_hermes(self, conn: sqlite3.Connection, schema: dict) -> None:
        """Load Hermes-style three-table schema (entities + facts + fact_entities)."""
        et = schema["entity_table"]
        ft = schema["fact_table"]
        lt = schema["link_table"]
        eid = schema["entity_pk"]
        ename = schema["entity_name_col"]
        etype = schema["entity_type_col"]
        fid = schema["fact_pk"]
        fcontent = schema["fact_content_col"]
        leid = schema["link_entity_col"]
        lfid = schema["link_fact_col"]

        type_sel = f", e.[{etype}]" if etype else ", 'unknown'"

        # Nodes
        cur = conn.execute(f"""
            SELECT e.[{eid}], e.[{ename}] {type_sel},
                   COUNT(fe.[{lfid}]) AS fact_count
            FROM [{et}] e
            LEFT JOIN [{lt}] fe ON fe.[{leid}] = e.[{eid}]
            GROUP BY e.[{eid}]
            ORDER BY fact_count DESC
        """)
        rows = cur.fetchall()
        self._nodes = [
            {"id": r[1], "type": r[2] or "unknown", "facts": r[3]}
            for r in rows
        ]

        # Edges — entities sharing facts
        cur = conn.execute(f"""
            SELECT e1.[{ename}] AS src, e2.[{ename}] AS tgt,
                   COUNT(*) AS shared,
                   GROUP_CONCAT(f.[{fcontent}], '|||') AS contents
            FROM [{lt}] fe1
            JOIN [{lt}] fe2 ON fe1.[{lfid}] = fe2.[{lfid}]
                 AND fe1.[{leid}] < fe2.[{leid}]
            JOIN [{et}] e1 ON fe1.[{leid}] = e1.[{eid}]
            JOIN [{et}] e2 ON fe2.[{leid}] = e2.[{eid}]
            JOIN [{ft}] f ON fe1.[{lfid}] = f.[{fid}]
            GROUP BY e1.[{eid}], e2.[{eid}]
        """)
        self._edges = [
            {
                "source": r[0], "target": r[1],
                "weight": r[2],
                "label": r[3].split("|||")[0][:80] if r[3] else "",
                "type": "entity",
                "shared_facts": r[3].split("|||") if r[3] else [],
            }
            for r in cur.fetchall()
        ]

        # Entity facts map
        cur = conn.execute(f"""
            SELECT e.[{ename}], GROUP_CONCAT(f.[{fcontent}], '|||') AS all_facts
            FROM [{et}] e
            JOIN [{lt}] fe ON fe.[{leid}] = e.[{eid}]
            JOIN [{ft}] f ON fe.[{lfid}] = f.[{fid}]
            GROUP BY e.[{eid}]
        """)
        self._entity_facts = {r[0]: r[1].split("|||") for r in cur.fetchall()}

        self._compute_stats()

    def _load_two_table(self, conn: sqlite3.Connection, schema: dict) -> None:
        """Load two-table schema (entity + fact, no link table)."""
        et = schema["entity_table"]
        eid = schema["entity_pk"]
        ename = schema["entity_name_col"]
        etype = schema["entity_type_col"]

        type_sel = f", e.[{etype}]" if etype else ", 'unknown'"

        cur = conn.execute(f"""
            SELECT e.[{eid}], e.[{ename}] {type_sel}
            FROM [{et}] e
            ORDER BY e.[{eid}]
        """)
        self._nodes = [
            {"id": r[1], "type": r[2] or "unknown", "facts": 0}
            for r in cur.fetchall()
        ]
        self._edges = []
        self._entity_facts = {n["id"]: [] for n in self._nodes}
        self._compute_stats()

    def _load_two_table_fk(self, conn: sqlite3.Connection, schema: dict) -> None:
        """Load two-table schema where fact table has a FK to entity table."""
        et = schema["entity_table"]
        ft = schema["fact_table"]
        eid = schema["entity_pk"]
        ename = schema["entity_name_col"]
        etype = schema["entity_type_col"]
        fcontent = schema["fact_content_col"]
        ffk = schema["fact_fk_entity"]

        type_sel = f", e.[{etype}]" if etype else ", 'unknown'"

        # Nodes with fact counts
        cur = conn.execute(f"""
            SELECT e.[{eid}], e.[{ename}] {type_sel},
                   COUNT(f.rowid) AS fact_count
            FROM [{et}] e
            LEFT JOIN [{ft}] f ON f.[{ffk}] = e.[{eid}]
            GROUP BY e.[{eid}]
            ORDER BY fact_count DESC
        """)
        self._nodes = [
            {"id": r[1], "type": r[2] or "unknown", "facts": r[3]}
            for r in cur.fetchall()
        ]

        # Edges — entities sharing fact references
        cur = conn.execute(f"""
            SELECT e1.[{ename}] AS src, e2.[{ename}] AS tgt,
                   COUNT(*) AS shared,
                   GROUP_CONCAT(f.[{fcontent}], '|||') AS contents
            FROM [{ft}] f
            JOIN [{et}] e1 ON f.[{ffk}] = e1.[{eid}]
            JOIN [{et}] e2 ON f.[{ffk}] = e2.[{eid}]
            WHERE e1.[{eid}] < e2.[{eid}]
            GROUP BY e1.[{eid}], e2.[{eid}]
        """)
        self._edges = [
            {
                "source": r[0], "target": r[1],
                "weight": r[2],
                "label": r[3].split("|||")[0][:80] if r[3] else "",
                "type": "entity",
                "shared_facts": r[3].split("|||") if r[3] else [],
            }
            for r in cur.fetchall()
        ]

        # Entity facts map
        cur = conn.execute(f"""
            SELECT e.[{ename}], GROUP_CONCAT(f.[{fcontent}], '|||') AS all_facts
            FROM [{et}] e
            JOIN [{ft}] f ON f.[{ffk}] = e.[{eid}]
            GROUP BY e.[{eid}]
        """)
        self._entity_facts = {r[0]: r[1].split("|||") for r in cur.fetchall()}

        self._compute_stats()

    def _load_single_table(self, conn: sqlite3.Connection, schema: dict) -> None:
        """Load single-table schema — each row is a node, content is its fact."""
        et = schema["entity_table"]
        ename = schema["entity_name_col"]
        etype = schema["entity_type_col"]
        fcontent = schema.get("fact_content_col")

        type_sel = f", [{etype}]" if etype else ", 'unknown' AS _type"

        cur = conn.execute(f"SELECT [{ename}] {type_sel} FROM [{et}]")
        self._nodes = [
            {"id": r[0], "type": r[1] or "unknown", "facts": 1}
            for r in cur.fetchall()
        ]

        # Build edges from name overlap (entities with similar names)
        names = [n["id"] for n in self._nodes]
        edge_set: set[tuple] = set()
        self._edges = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                # Connect if one name contains the other (partial match)
                if a in b or b in a:
                    key = tuple(sorted([a, b]))
                    if key not in edge_set and a != b:
                        edge_set.add(key)
                        self._edges.append({
                            "source": a, "target": b,
                            "weight": 1,
                            "label": "name similarity",
                            "type": "keyword",
                        })

        # Entity facts
        if fcontent:
            cur = conn.execute(f"SELECT [{ename}], [{fcontent}] FROM [{et}]")
            self._entity_facts = {}
            for r in cur.fetchall():
                self._entity_facts[r[0]] = [r[1]] if r[1] else []
        else:
            self._entity_facts = {n["id"]: [] for n in self._nodes}

        self._compute_stats()

    def _compute_stats(self) -> None:
        """Compute stats from loaded nodes/edges."""
        types = Counter(n["type"] for n in self._nodes)
        connected = set()
        for e in self._edges:
            connected.add(e["source"])
            connected.add(e["target"])

        # Top-5 most connected nodes
        degree: Counter = Counter()
        for e in self._edges:
            degree[e["source"]] += 1
            degree[e["target"]] += 1
        top5 = [{"id": n, "degree": d} for n, d in degree.most_common(5)]

        self._stats = {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "total_facts": sum(n["facts"] for n in self._nodes),
            "types": dict(types.most_common()),
            "isolated": sum(1 for n in self._nodes if n["id"] not in connected),
            "top5": top5,
            "source": str(self.path),
        }

"""Coverage reporting: which region × category × provider combinations have been scanned."""
from __future__ import annotations

from typing import Any

from ..regions import REGIONS
from ..taxonomy import OSM_DISCOVERY_QUERIES
from .common import loads, now_iso
from .context import AppContext


class CoverageService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def start_run(self, provider: str, query: str | None, region_key: str | None, category: str | None, job_id: int | None = None, config_snapshot: dict | None = None) -> int:
        from .common import dumps

        with self.ctx.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO discovery_runs (provider, query, region_key, category, job_id, config_snapshot_json) VALUES (?,?,?,?,?,?)",
                (provider, query, region_key, category, job_id, dumps(config_snapshot or {})),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, result_count: int = 0, new_place_count: int = 0, error: str | None = None, cursor: dict | None = None) -> None:
        from .common import dumps

        with self.ctx.db.transaction() as conn:
            conn.execute(
                "UPDATE discovery_runs SET finished_at=?, status=?, result_count=?, new_place_count=?, error_summary=?, cursor_json=? WHERE id=?",
                (now_iso(), status, result_count, new_place_count, error, dumps(cursor) if cursor else None, run_id),
            )
            conn.execute(
                """INSERT INTO provider_state (provider, last_run_at, last_success_at, last_error, request_count)
                   VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(provider) DO UPDATE SET last_run_at=excluded.last_run_at,
                     last_success_at=CASE WHEN ?='succeeded' THEN excluded.last_run_at ELSE provider_state.last_success_at END,
                     last_error=CASE WHEN ?='succeeded' THEN NULL ELSE excluded.last_error END,
                     request_count=provider_state.request_count+1""",
                (self._provider_key(run_id), now_iso(), now_iso() if status == "succeeded" else None, error, status, status),
            )

    def _provider_key(self, run_id: int) -> str:
        row = self.ctx.db.conn().execute("SELECT provider FROM discovery_runs WHERE id=?", (run_id,)).fetchone()
        return row["provider"] if row else "unknown"

    def matrix(self) -> dict[str, Any]:
        conn = self.ctx.db.conn()
        rows = conn.execute(
            """SELECT provider, region_key, category, status, MAX(finished_at) AS last_finished, SUM(result_count) AS results,
                      SUM(new_place_count) AS new_places, COUNT(*) AS runs
               FROM discovery_runs GROUP BY provider, region_key, category, status"""
        ).fetchall()
        cells: dict[str, dict[str, Any]] = {}
        for r in rows:
            key = f"{r['provider']}|{r['region_key'] or '*'}|{r['category'] or '*'}"
            cell = cells.setdefault(key, {"provider": r["provider"], "region_key": r["region_key"], "category": r["category"], "statuses": {}, "results": 0, "new_places": 0, "last_finished": None})
            cell["statuses"][r["status"]] = r["runs"]
            cell["results"] += r["results"] or 0
            cell["new_places"] += r["new_places"] or 0
            if r["last_finished"] and (cell["last_finished"] is None or r["last_finished"] > cell["last_finished"]):
                cell["last_finished"] = r["last_finished"]
        # Which OSM category groups have never been attempted for the whole island?
        attempted = {(c["provider"], c["category"]) for c in cells.values()}
        not_run = [cat for cat in OSM_DISCOVERY_QUERIES if ("osm", cat) not in attempted]
        by_region = {}
        for region in REGIONS:
            by_region[region.key] = {
                "name": region.name,
                "places": conn.execute("SELECT COUNT(*) FROM places WHERE county=? AND merged_into_place_id IS NULL AND discovery_status!='seed'", (region.name,)).fetchone()[0],
                "with_images": conn.execute("SELECT COUNT(*) FROM places WHERE county=? AND merged_into_place_id IS NULL AND discovery_status!='seed' AND image_count>0", (region.name,)).fetchone()[0],
                "undecided": conn.execute("SELECT COUNT(*) FROM places WHERE county=? AND merged_into_place_id IS NULL AND discovery_status!='seed' AND interest_status='undecided'", (region.name,)).fetchone()[0],
                "researched": conn.execute("SELECT COUNT(*) FROM places WHERE county=? AND merged_into_place_id IS NULL AND research_status='done'", (region.name,)).fetchone()[0],
            }
        providers = [dict(r) for r in conn.execute("SELECT * FROM provider_state ORDER BY provider").fetchall()]
        failed = [dict(r) for r in conn.execute("SELECT id, provider, query, region_key, category, finished_at, error_summary FROM discovery_runs WHERE status IN ('failed','partial') ORDER BY id DESC LIMIT 50").fetchall()]
        return {"cells": list(cells.values()), "osm_categories_not_run": not_run, "by_region": by_region, "providers": providers, "recent_failures": failed}

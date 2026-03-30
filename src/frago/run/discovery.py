"""Run Instance Auto-discovery

Uses RapidFuzz fuzzy matching to find similar run instances.
Provides keyword search across run IDs/themes and log step fields.
Extracts and aggregates _insights from run logs.
"""

from typing import Dict, List, Optional

from rapidfuzz import fuzz

from .logger import RunLogger
from .manager import RunManager


class RunDiscovery:
    """Run Instance Discovery"""

    def __init__(self, manager: RunManager):
        """Initialize discovery

        Args:
            manager: RunManager instance
        """
        self.manager = manager

    def discover_similar_runs(
        self, task_description: str, threshold: int = 60, max_results: int = 5
    ) -> List[Dict]:
        """Discover similar run instances

        Args:
            task_description: user task description
            threshold: similarity threshold (0-100)
            max_results: maximum number of results

        Returns:
            list of similar runs (including similarity scores)
        """
        all_runs = self.manager.list_runs()

        # Calculate similarity
        results = []
        for run in all_runs:
            # Use multiple algorithms and take maximum to improve matching accuracy
            theme = run["theme_description"]
            similarity = max(
                fuzz.token_sort_ratio(task_description, theme),  # Ignore word order
                fuzz.partial_ratio(task_description, theme),     # Partial matching
                fuzz.token_set_ratio(task_description, theme)    # Set matching
            )

            if similarity >= threshold:
                results.append(
                    {
                        **run,
                        "similarity": similarity,
                    }
                )

        # Sort by similarity in descending order (higher similarity first), then by time in descending order (later time first)
        # ISO 8601 strings can be compared directly, later timestamps have higher string values
        results.sort(key=lambda r: (r["similarity"], r["last_accessed"]), reverse=True)

        return results[:max_results]

    def _read_metadata(self, run_id: str) -> Dict:
        """Read .metadata.json for a run, returns empty dict on failure"""
        import json
        meta_file = self.manager.projects_dir / run_id / ".metadata.json"
        if meta_file.exists():
            try:
                return json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def search_runs(self, keyword: str, max_results: int = 10) -> List[Dict]:
        """Two-layer search: fuzzy match run ID/theme + grep log step fields

        Args:
            keyword: search keyword
            max_results: maximum number of results

        Returns:
            list of matching runs with match_source, similarity, matched_steps, purpose
        """
        if not keyword.strip():
            return []

        # Layer 1: fuzzy match on run ID/theme (low threshold for wide recall)
        fuzzy_matches = self.discover_similar_runs(
            keyword, threshold=40, max_results=max_results * 2
        )
        matched_ids = {m["run_id"] for m in fuzzy_matches}
        results = [
            {**m, "match_source": "id", "matched_steps": []}
            for m in fuzzy_matches
        ]

        # Layer 2: grep logs for keyword in step field
        keyword_lower = keyword.lower()
        for run in self.manager.list_runs():
            if run["run_id"] in matched_ids:
                continue
            try:
                run_dir = self.manager.projects_dir / run["run_id"]
                logger = RunLogger(run_dir)
                matched_steps = []
                for entry in logger.read_logs(skip_corrupted=True):
                    if keyword_lower in entry.step.lower():
                        matched_steps.append(entry.step)
                if matched_steps:
                    results.append({
                        **run,
                        "match_source": "log",
                        "similarity": 50,
                        "matched_steps": matched_steps[:3],
                    })
            except Exception:
                continue

        results.sort(
            key=lambda r: (r["similarity"], r.get("last_accessed", "")),
            reverse=True,
        )
        results = results[:max_results]

        # Attach purpose from metadata
        for r in results:
            meta = self._read_metadata(r["run_id"])
            r["purpose"] = meta.get("purpose")

        return results

    def extract_insights(
        self,
        run_id: Optional[str] = None,
        insight_type: Optional[str] = None,
    ) -> List[Dict]:
        """Extract _insights from run logs, supports single run and cross-run aggregation

        Args:
            run_id: specific run ID, None for all runs
            insight_type: pitfall | lesson | key_factor | workaround, None for all

        Returns:
            list of insight dicts with run_id, type, summary, timestamp, step
        """
        if run_id:
            runs = [{"run_id": run_id}]
        else:
            runs = self.manager.list_runs()

        insights = []
        for run in runs:
            try:
                run_dir = self.manager.projects_dir / run["run_id"]

                # Source 1: .metadata.json insights field
                import json
                meta_file = run_dir / ".metadata.json"
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    if "insights" in meta and isinstance(meta["insights"], list):
                        created_at = meta.get("created_at", "")
                        for raw in meta["insights"]:
                            if not isinstance(raw, dict):
                                continue
                            itype = raw.get("type", raw.get("insight_type", "unknown"))
                            if insight_type and itype != insight_type:
                                continue
                            insights.append({
                                "run_id": run["run_id"],
                                "type": itype,
                                "summary": raw.get("summary", ""),
                                "detail": raw.get("detail"),
                                "source": "metadata",
                                "timestamp": created_at,
                                "step": "(run summary)",
                            })

                # Source 2: log entries — top-level insights + data._insights
                logger = RunLogger(run_dir)
                for entry in logger.read_logs(skip_corrupted=True):
                    # Schema 1.1 top-level insights field
                    if entry.insights:
                        for insight in entry.insights:
                            itype = insight.insight_type.value
                            if insight_type and itype != insight_type:
                                continue
                            insights.append({
                                "run_id": run["run_id"],
                                "type": itype,
                                "summary": insight.summary,
                                "detail": insight.detail,
                                "source": "log",
                                "timestamp": entry.timestamp.isoformat(),
                                "step": entry.step,
                            })

                    # Legacy data._insights field
                    if entry.data and "_insights" in entry.data:
                        for raw in entry.data["_insights"]:
                            if not isinstance(raw, dict):
                                continue
                            itype = raw.get("type", raw.get("insight_type", "unknown"))
                            if insight_type and itype != insight_type:
                                continue
                            insights.append({
                                "run_id": run["run_id"],
                                "type": itype,
                                "summary": raw.get("summary", ""),
                                "detail": raw.get("detail"),
                                "source": "log",
                                "timestamp": entry.timestamp.isoformat(),
                                "step": entry.step,
                            })
            except Exception:
                continue

        insights.sort(key=lambda i: i["timestamp"], reverse=True)
        return insights

    def get_run_experience(self, run_id: str) -> Dict:
        """Get complete experience view for a single run

        Aggregates purpose/method/reuse_guidance/recipe_potential from metadata
        plus all insights from three sources.

        Args:
            run_id: run instance ID

        Returns:
            experience dict with purpose, method, reuse_guidance, recipe_potential, insights
        """
        meta = self._read_metadata(run_id)

        experience = {
            "run_id": run_id,
            "purpose": meta.get("purpose"),
            "method": meta.get("method"),
            "reuse_guidance": meta.get("reuse_guidance"),
            "recipe_potential": meta.get("recipe_potential"),
            "created_at": meta.get("created_at"),
            "insights": self.extract_insights(run_id=run_id),
        }

        return experience

    def find_best_match(self, task_description: str, threshold: int = 80) -> Dict | None:
        """Find best matching run instance

        Args:
            task_description: user task description
            threshold: similarity threshold (high threshold, only returns very similar matches)

        Returns:
            best matching run or None
        """
        matches = self.discover_similar_runs(task_description, threshold=threshold, max_results=1)
        return matches[0] if matches else None

"""Run Instance Auto-discovery

Uses RapidFuzz fuzzy matching to find similar run instances
"""

from pathlib import Path
from typing import Dict, List

from rapidfuzz import fuzz

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

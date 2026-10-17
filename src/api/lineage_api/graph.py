"""Steps of one root target column, linked by endpoint instead of path_id."""
import sqlite3
from typing import Iterable


class StepGraph:
    """The children of a step are the steps one level deeper, in the same Business Process,
    whose target endpoint is this step's source endpoint. A step flagged terminal has none."""

    def __init__(self, steps: Iterable[sqlite3.Row]) -> None:
        self.steps = list(steps)
        self.by_id = {s["step_id"]: s for s in self.steps}
        self._index: dict[tuple, list[str]] = {}
        for s in self.steps:
            key = (s["business_process_id"], s["lineage_level"], s["target_object_id"], s["target_column_id"])
            self._index.setdefault(key, []).append(s["step_id"])

    def kids_of(self, step: sqlite3.Row) -> list[str]:
        if step["is_terminal"]:
            return []
        key = (step["business_process_id"], step["lineage_level"] + 1, step["source_object_id"], step["source_column_id"])
        return self._index.get(key, [])

    def root_ids(self) -> list[str]:
        return [s["step_id"] for s in self.steps if s["lineage_level"] == 0]

    def reachable(self) -> set[str]:
        """Steps reachable from a root; a step flagged terminal hides its descendants."""
        seen: set[str] = set()
        stack = self.root_ids()
        while stack:
            step_id = stack.pop()
            if step_id not in seen:
                seen.add(step_id)
                stack.extend(self.kids_of(self.by_id[step_id]))
        return seen

"""
A tiny, dependency-ordered pipeline runner.

Why hand-rolled instead of Airflow/Prefect/Dagster?
-----------------------------------------------------
This toolkit's pipeline has five sequential-ish stages (connect -> validate
-> chunk -> enrich -> index) that run in-process, in a single CLI
invocation, with no need for distributed scheduling, a web UI, or a
persistent scheduler daemon. Pulling in a full orchestration framework for
that would be architectural overkill and a heavy dependency for a reviewer
to install. This module is deliberately small (~80 lines) and does exactly
three things an orchestrator needs to do at this scale:

1. Register named stages with explicit dependencies.
2. Topologically sort them (Kahn/DFS-style) so each stage runs after its
   dependencies, and detect cycles.
3. Support **partial re-run**: pass ``only=["chunk"]`` and the runner will
   also pull in and re-run "chunk"'s transitive dependencies (so its inputs
   are valid) without re-running unrelated stages.

At real production scale (cross-day scheduling, retries-as-a-service, a
shared UI across many pipelines) you would graduate to Airflow/Dagster --
this module is intentionally not trying to be that.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: A stage function receives the shared run context and returns its result;
#: the runner stores that result back into the context under the stage name
#: before running the next stage, so later stages can read earlier outputs.
StageFunc = Callable[[dict[str, Any]], Any]


class DagError(Exception):
    """Raised for invalid DAG definitions (unknown dependency, cycle) or duplicate stage names."""


@dataclass
class Stage:
    name: str
    func: StageFunc
    depends_on: list[str] = field(default_factory=list)


class DagRunner:
    """Registers stages and executes them in dependency order."""

    def __init__(self) -> None:
        self._stages: dict[str, Stage] = {}

    def add_stage(self, name: str, func: StageFunc, depends_on: list[str] | None = None) -> DagRunner:
        if name in self._stages:
            raise DagError(f"stage already registered: {name}")
        self._stages[name] = Stage(name=name, func=func, depends_on=list(depends_on or []))
        return self

    def _validate_dependencies(self) -> None:
        for stage in self._stages.values():
            for dep in stage.depends_on:
                if dep not in self._stages:
                    raise DagError(f"stage '{stage.name}' depends on unknown stage '{dep}'")

    def _expand_with_dependencies(self, targets: set[str]) -> set[str]:
        """Pull in transitive dependencies of the requested target stages.

        This is what makes ``only=[...]`` a safe *partial re-run* rather
        than a foot-gun: re-running "chunk" alone with stale "validate"
        output would silently chunk documents that should've been rejected.
        """
        expanded: set[str] = set()

        def expand(name: str) -> None:
            if name in expanded:
                return
            expanded.add(name)
            for dep in self._stages[name].depends_on:
                expand(dep)

        for name in targets:
            if name not in self._stages:
                raise DagError(f"unknown stage requested: '{name}'")
            expand(name)
        return expanded

    def _topological_order(self, scope: set[str]) -> list[str]:
        order: list[str] = []
        visited: set[str] = set()
        in_progress: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in in_progress:
                raise DagError(f"cycle detected involving stage '{name}'")
            in_progress.add(name)
            for dep in self._stages[name].depends_on:
                visit(dep)
            in_progress.discard(name)
            visited.add(name)
            order.append(name)

        for name in scope:
            visit(name)
        return order

    def run(self, context: dict[str, Any] | None = None, only: list[str] | None = None) -> dict[str, Any]:
        """Execute the DAG (or a sub-scope of it) in dependency order.

        Returns the shared context dict, which after running contains one
        entry per executed stage keyed by stage name -> that stage's
        return value.
        """
        self._validate_dependencies()
        context = context if context is not None else {}
        scope = self._expand_with_dependencies(set(only)) if only else set(self._stages)
        for name in self._topological_order(scope):
            context[name] = self._stages[name].func(context)
        return context

"""Tests for the small hand-rolled DAG runner."""

from __future__ import annotations

import pytest

from toolkit.dag import DagError, DagRunner


def test_stages_run_in_dependency_order() -> None:
    order: list[str] = []
    dag = DagRunner()
    dag.add_stage("a", lambda ctx: order.append("a"))
    dag.add_stage("b", lambda ctx: order.append("b"), depends_on=["a"])
    dag.add_stage("c", lambda ctx: order.append("c"), depends_on=["b"])

    dag.run()
    assert order == ["a", "b", "c"]


def test_context_propagates_stage_results() -> None:
    dag = DagRunner()
    dag.add_stage("produce", lambda ctx: 41)
    dag.add_stage("consume", lambda ctx: ctx["produce"] + 1, depends_on=["produce"])

    result = dag.run()
    assert result["consume"] == 42


def test_duplicate_stage_name_raises() -> None:
    dag = DagRunner()
    dag.add_stage("a", lambda ctx: None)
    with pytest.raises(DagError):
        dag.add_stage("a", lambda ctx: None)


def test_unknown_dependency_raises_on_run() -> None:
    dag = DagRunner()
    dag.add_stage("a", lambda ctx: None, depends_on=["ghost"])
    with pytest.raises(DagError):
        dag.run()


def test_cycle_detection_raises() -> None:
    dag = DagRunner()
    dag.add_stage("a", lambda ctx: None, depends_on=["b"])
    dag.add_stage("b", lambda ctx: None, depends_on=["a"])
    with pytest.raises(DagError):
        dag.run()


def test_partial_rerun_only_expands_transitive_dependencies() -> None:
    calls: list[str] = []
    dag = DagRunner()
    dag.add_stage("connect", lambda ctx: calls.append("connect"))
    dag.add_stage("validate", lambda ctx: calls.append("validate"), depends_on=["connect"])
    dag.add_stage("chunk", lambda ctx: calls.append("chunk"), depends_on=["validate"])
    dag.add_stage("unrelated", lambda ctx: calls.append("unrelated"))

    dag.run(only=["chunk"])

    # "chunk" pulls in its transitive deps (connect, validate) but not the
    # independent "unrelated" stage.
    assert calls == ["connect", "validate", "chunk"]


def test_unknown_target_stage_in_only_raises() -> None:
    dag = DagRunner()
    dag.add_stage("a", lambda ctx: None)
    with pytest.raises(DagError):
        dag.run(only=["ghost"])

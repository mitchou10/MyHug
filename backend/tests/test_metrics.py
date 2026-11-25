import typing

from app.metrics import METRICS, default_shown, metrics_for
from app.schemas.model import Task


def test_every_task_a_model_can_have_has_its_metrics() -> None:
    tasks = set(typing.get_args(Task))
    assert tasks <= set(METRICS), f"no metrics for {sorted(tasks - set(METRICS))}"
    assert set(METRICS) <= tasks, f"metrics for a task that does not exist: {sorted(set(METRICS) - tasks)}"


def test_each_task_has_one_main_metric_and_no_metric_twice() -> None:
    for task, metrics in METRICS.items():
        ids = [m.id for m in metrics]
        assert len(ids) == len(set(ids)), task
        assert sum(m.primary for m in metrics) == 1 and metrics[0].primary, task
        assert all(m.id == m.id.lower() and m.id.replace("_", "").isalnum() for m in metrics), task


def test_the_metrics_shown_by_default_are_the_main_one_and_the_next() -> None:
    assert default_shown("classification") == ["accuracy", "precision"]
    assert default_shown("qa") == ["exact_match", "f1"]
    assert default_shown("nothing") == ["accuracy"]  # a task that is not known has accuracy only
    assert [m.id for m in metrics_for("nothing")] == ["accuracy"]


def test_an_error_is_a_metric_where_lower_is_better() -> None:
    assert not {m.id: m for m in metrics_for("regression")}["mae"].higher
    assert not {m.id: m for m in metrics_for("audio_transcription")}["wer"].higher
    assert {m.id: m for m in metrics_for("regression")}["r2"].higher

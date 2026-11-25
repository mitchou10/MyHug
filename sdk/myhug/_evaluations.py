"""Sending the result of an evaluation: what is checked here, before anything is sent, and the body that goes."""

import math
from collections.abc import Mapping, Sequence
from typing import Any

MAX_METRICS = 50


def checked_results(results: Mapping[str, float]) -> dict[str, float]:
    """The result as numbers: what is not one (a boolean, a text, nan, infinity) is refused here, with a sentence,
    instead of being a cryptic error of the encoder or of the platform."""
    if not results:
        raise ValueError("A result needs at least one metric")
    if len(results) > MAX_METRICS:
        raise ValueError(f"A result has at most {MAX_METRICS} metrics")
    checked: dict[str, float] = {}
    for key, value in results.items():
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise ValueError(f"The value of {key!r} must be a finite number, not {value!r}")
        checked[key] = float(value)
    return checked


def body(
    *,
    version: int,
    task: str,
    results: Mapping[str, float],
    shown: Sequence[str] | None,
    dataset: str | None,
    dataset_version: int | None,
    split: str | None,
    input_column: str | None,
    target_column: str | None,
    items: int | None,
    note: str,
) -> dict[str, Any]:
    """What is sent: only what is given, the platform has a default for the rest."""
    given = {
        "shown": list(shown) if shown is not None else None,
        "dataset": dataset,
        "dataset_version": dataset_version,
        "split": split,
        "input_column": input_column,
        "target_column": target_column,
        "items": items,
    }
    return {
        "version": version,
        "task": task,
        "results": checked_results(results),
        "note": note,
        **{k: v for k, v in given.items() if v is not None},
    }

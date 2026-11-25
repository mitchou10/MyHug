"""The metrics of an evaluation, computed as the rows go by: nothing is held but the sums they need, so a split of any
size takes the same memory.

Only what a column can hold and plain Python can compute is here: the classification of a label, a number, a short
answer (`app/metrics.py` of the API says which tasks and which metrics). The values are the platform's, not the
author's: they are computed here from the predictions, never taken from the person who sent them.

The definitions:

- **classification**: `accuracy` is the part of the rows whose label is predicted; `precision`, `recall` and `f1` are
  **macro** averages (each class counts the same, however many rows it has) over the labels of the truth and of the
  predictions together, a class with nothing to divide by counting 0, as scikit-learn does with `zero_division=0`.
- **regression**: `mae` (mean absolute error), `rmse` (root of the mean squared error), `r2` (1 - squared error /
  variance of the truth, left out when the truth does not vary), `mape` (mean of |error| / |truth| in percent, over
  the rows whose truth is not 0, left out when there is none).
- **qa**: `exact_match` and `f1` of words after the usual SQuAD clean-up (lower case, no punctuation, no a/an/the)."""

import math
import re
import string
from collections import Counter
from typing import Any, Protocol

from worker.errors import EvaluationProblem

CLASSIFICATION_TASKS = frozenset(
    {
        "classification",
        "row_label",
        "image_classification",
        "audio_classification",
        "video_classification",
        "timeseries_classification",
    }
)


def label_of(value: Any) -> str:
    """A label as a text: `1`, `1.0` and `"1"` are the same label."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def number_of(value: Any, where: str, what: str) -> float:
    if isinstance(value, bool) or value is None:
        raise EvaluationProblem(f"{where}: the {what} {value!r} is not a number")
    try:
        found = float(value)
    except (TypeError, ValueError):
        raise EvaluationProblem(f"{where}: the {what} {value!r} is not a number") from None
    if not math.isfinite(found):
        raise EvaluationProblem(f"{where}: the {what} {value!r} is not a finite number")
    return found


class Scorer(Protocol):
    def add(self, truth: Any, prediction: Any, where: str) -> None: ...

    def result(self) -> dict[str, float]: ...


class Classification:
    def __init__(self) -> None:
        self.n = 0
        self.correct = 0
        self.tp: Counter[str] = Counter()
        self.fp: Counter[str] = Counter()
        self.fn: Counter[str] = Counter()
        self.labels: set[str] = set()

    def add(self, truth: Any, prediction: Any, where: str) -> None:
        if prediction is None or label_of(prediction) == "":
            raise EvaluationProblem(f"{where} has an empty prediction")
        expected, found = label_of(truth), label_of(prediction)
        self.n += 1
        self.labels.update((expected, found))
        if expected == found:
            self.correct += 1
            self.tp[expected] += 1
        else:
            self.fp[found] += 1
            self.fn[expected] += 1

    def result(self) -> dict[str, float]:
        precision, recall, f1 = [], [], []
        for label in self.labels:
            p = self.tp[label] / (self.tp[label] + self.fp[label]) if self.tp[label] + self.fp[label] else 0.0
            r = self.tp[label] / (self.tp[label] + self.fn[label]) if self.tp[label] + self.fn[label] else 0.0
            precision.append(p)
            recall.append(r)
            f1.append(2 * p * r / (p + r) if p + r else 0.0)
        classes = len(self.labels) or 1
        return {
            "accuracy": self.correct / self.n,
            "precision": sum(precision) / classes,
            "recall": sum(recall) / classes,
            "f1": sum(f1) / classes,
        }


class Regression:
    def __init__(self) -> None:
        self.n = 0
        self.absolute = 0.0
        self.squared = 0.0
        # The mean and the sum of squares around it of the truth, as they go (Welford): stable for any number of rows.
        self.mean = 0.0
        self.spread = 0.0
        self.percent = 0.0
        self.percent_rows = 0

    def add(self, truth: Any, prediction: Any, where: str) -> None:
        expected = number_of(truth, where, "truth")
        found = number_of(prediction, where, "prediction")
        error = found - expected
        self.n += 1
        self.absolute += abs(error)
        self.squared += error * error
        delta = expected - self.mean
        self.mean += delta / self.n
        self.spread += delta * (expected - self.mean)
        if expected != 0:
            self.percent += abs(error / expected)
            self.percent_rows += 1

    def result(self) -> dict[str, float]:
        found = {"mae": self.absolute / self.n, "rmse": math.sqrt(self.squared / self.n)}
        if self.spread > 0:
            found["r2"] = 1 - self.squared / self.spread
        if self.percent_rows:
            found["mape"] = 100 * self.percent / self.percent_rows
        return found


_ARTICLES = re.compile(r"\b(a|an|the)\b")
_PUNCTUATION = set(string.punctuation)


def clean_answer(text: Any) -> str:
    lowered = str(text).lower()
    without = "".join(char for char in lowered if char not in _PUNCTUATION)
    return " ".join(_ARTICLES.sub(" ", without).split())


class Answers:
    def __init__(self) -> None:
        self.n = 0
        self.exact = 0.0
        self.f1 = 0.0

    def add(self, truth: Any, prediction: Any, where: str) -> None:
        if prediction is None:
            raise EvaluationProblem(f"{where} has an empty prediction")
        expected, found = clean_answer(truth).split(), clean_answer(prediction).split()
        self.n += 1
        self.exact += float(expected == found)
        shared = sum((Counter(expected) & Counter(found)).values())
        if not expected or not found:
            self.f1 += float(expected == found)
        elif shared:
            precision, recall = shared / len(found), shared / len(expected)
            self.f1 += 2 * precision * recall / (precision + recall)

    def result(self) -> dict[str, float]:
        return {"exact_match": self.exact / self.n, "f1": self.f1 / self.n}


def scorer_for(task: str) -> Scorer:
    """What computes the metrics of a task, or EvaluationProblem when the worker does not compute them."""
    if task in CLASSIFICATION_TASKS:
        return Classification()
    if task == "regression":
        return Regression()
    if task == "qa":
        return Answers()
    raise EvaluationProblem(f"The worker does not compute the metrics of {task}")

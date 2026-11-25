import math

import pytest

from worker.errors import EvaluationProblem
from worker.metrics import Answers, Classification, Regression, clean_answer, label_of, scorer_for


def classify(pairs: list[tuple[object, object]]) -> dict[str, float]:
    scorer = Classification()
    for i, (truth, prediction) in enumerate(pairs):
        scorer.add(truth, prediction, f"Row {i}")
    return scorer.result()


def test_a_classification_worked_out_by_hand() -> None:
    # a: 1 right of 2, never wrongly predicted -> precision 1, recall 1/2, f1 2/3
    # b: 2 right of 2, once wrongly predicted  -> precision 2/3, recall 1, f1 4/5
    found = classify([("a", "a"), ("a", "b"), ("b", "b"), ("b", "b")])
    assert found["accuracy"] == pytest.approx(0.75)
    assert found["precision"] == pytest.approx((1 + 2 / 3) / 2)
    assert found["recall"] == pytest.approx((0.5 + 1) / 2)
    assert found["f1"] == pytest.approx((2 / 3 + 4 / 5) / 2)


def test_a_perfect_and_a_hopeless_classification() -> None:
    assert classify([("a", "a"), ("b", "b")]) == {"accuracy": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert classify([("a", "b"), ("b", "a")]) == {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_a_class_that_is_only_predicted_counts_as_zero_in_the_average() -> None:
    found = classify([("a", "a"), ("a", "c")])  # c is never right, a is half right
    assert found["accuracy"] == pytest.approx(0.5)
    assert found["precision"] == pytest.approx((1.0 + 0.0) / 2)  # a: 1, c: 0
    assert found["recall"] == pytest.approx((0.5 + 0.0) / 2)


def test_one_and_one_point_zero_and_the_text_one_are_the_same_label() -> None:
    assert [label_of(v) for v in (1, 1.0, "1", " 1 ")] == ["1", "1", "1", "1"]
    assert label_of(True) == "true" and label_of(1.5) == "1.5"
    assert classify([(1, "1"), (2.0, 2)])["accuracy"] == 1.0


def test_an_empty_prediction_is_the_data_s_fault() -> None:
    with pytest.raises(EvaluationProblem, match="Row 4 has an empty prediction"):
        Classification().add("a", "", "Row 4")
    with pytest.raises(EvaluationProblem, match="empty prediction"):
        Classification().add("a", None, "Row 4")


def regress(pairs: list[tuple[object, object]]) -> dict[str, float]:
    scorer = Regression()
    for i, (truth, prediction) in enumerate(pairs):
        scorer.add(truth, prediction, f"Row {i}")
    return scorer.result()


def test_a_regression_worked_out_by_hand() -> None:
    found = regress([(1, 1), (2, 2), (3, 3), (4, 6)])  # one error of 2
    assert found["mae"] == pytest.approx(0.5)
    assert found["rmse"] == pytest.approx(1.0)  # sqrt(4 / 4)
    assert found["r2"] == pytest.approx(1 - 4 / 5)  # the truth varies by 5 around its mean 2.5
    assert found["mape"] == pytest.approx(12.5)  # |2 / 4| on one row of four


def test_r2_and_mape_are_left_out_when_they_mean_nothing() -> None:
    assert set(regress([(3, 3), (3, 4)])) == {"mae", "rmse", "mape"}  # the truth does not vary
    assert set(regress([(0, 1), (0, 2)])) == {"mae", "rmse"}  # the truth is 0: no percentage, and it does not vary


def test_a_regression_over_many_rows_does_not_lose_its_precision() -> None:
    scorer = Regression()
    for i in range(100_000):
        scorer.add(1e9 + i % 10, 1e9 + i % 10 + 1, "Row")
    found = scorer.result()
    assert found["mae"] == pytest.approx(1.0) and found["rmse"] == pytest.approx(1.0)
    assert found["r2"] == pytest.approx(1 - 100_000 / (100_000 * 8.25), rel=1e-6)  # the variance of 0..9 is 8.25


@pytest.mark.parametrize(
    ("truth", "prediction", "message"),
    [
        (1, "abc", "Row 2: the prediction 'abc' is not a number"),
        (1, None, "the prediction None is not a number"),
        (1, True, "the prediction True is not a number"),
        (1, float("nan"), "is not a finite number"),
        (1, float("inf"), "is not a finite number"),
        ("high", 1, "the truth 'high' is not a number"),
    ],
)
def test_what_is_not_a_number_is_the_data_s_fault(truth, prediction, message) -> None:
    with pytest.raises(EvaluationProblem, match=message):
        Regression().add(truth, prediction, "Row 2")


def test_the_answers_are_cleaned_like_squad() -> None:
    assert clean_answer("The Eiffel Tower!") == "eiffel tower"
    assert clean_answer("  an   apple, a day ") == "apple day"


def test_exact_match_and_f1_of_answers() -> None:
    scorer = Answers()
    scorer.add("The Eiffel Tower", "eiffel tower!", "Row 0")  # the same after the clean-up
    scorer.add("new york city", "new york", "Row 1")  # 2 words shared: precision 1, recall 2/3, f1 4/5
    scorer.add("paris", "london", "Row 2")  # nothing in common
    found = scorer.result()
    assert found["exact_match"] == pytest.approx(1 / 3)
    assert found["f1"] == pytest.approx((1 + 0.8 + 0) / 3)


def test_two_empty_answers_are_the_same_and_one_empty_is_wrong() -> None:
    scorer = Answers()
    scorer.add("", "", "Row 0")
    scorer.add("paris", "", "Row 1")
    assert scorer.result() == {"exact_match": 0.5, "f1": 0.5}


def test_the_worker_knows_which_tasks_it_computes() -> None:
    for task in ("classification", "row_label", "image_classification", "audio_classification", "regression", "qa"):
        assert scorer_for(task) is not None
    for task in ("ner", "image_detection", "audio_transcription", "nothing"):
        with pytest.raises(EvaluationProblem, match="does not compute"):
            scorer_for(task)


def test_nothing_is_nan() -> None:
    found = classify([("a", "a")])
    assert all(math.isfinite(v) for v in found.values())

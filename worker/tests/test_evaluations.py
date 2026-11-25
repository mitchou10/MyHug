import io
import json
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from celery.exceptions import Retry

from tests.conftest import FakePlatform
from worker import tasks
from worker.backend import Backend
from worker.errors import EvaluationProblem, FileMissing
from worker.evaluator import compute

TRUTH = b"id,text,label\n1,a,pos\n2,b,neg\n3,c,pos\n4,d,neg\n"


EXTRA = b'{"id": 9, "prediction": "x"}\n' + b"".join(b'{"id": %d, "prediction": "x"}\n' % i for i in (1, 2, 3, 4))


def jsonl(*values: object, column: str = "prediction") -> bytes:
    return b"".join(json.dumps({column: v}).encode() + b"\n" for v in values)


def run(platform: FakePlatform, evaluation: uuid.UUID | None = None):
    return tasks.evaluate.apply(args=[str(evaluation or uuid.uuid4())])


def posted(platform: FakePlatform, what: str) -> dict:
    return platform.bodies[next(path for path in platform.bodies if path.endswith(f"/{what}"))]


def computed(platform: FakePlatform, backend, **options):
    job = platform.add_evaluation(**options)
    return compute(backend(platform), backend(platform).claim_evaluation(uuid.UUID(job["id"])))


# ---- the task


def test_the_metrics_are_computed_and_the_api_is_told(platform: FakePlatform) -> None:
    platform.add_evaluation([("test.csv", TRUTH)], ("p.jsonl", jsonl("pos", "neg", "neg", "neg")))
    result = run(platform)
    assert result.successful() and result.result == "done"
    body = posted(platform, "result")
    assert body["items"] == 4
    assert body["results"]["accuracy"] == pytest.approx(0.75)
    assert set(body["results"]) == {"accuracy", "precision", "recall", "f1"}


def test_only_the_metrics_the_api_names_are_given_back(platform: FakePlatform) -> None:
    platform.add_evaluation([("test.csv", TRUTH)], ("p.jsonl", jsonl("pos", "neg", "pos", "neg")), metrics=["accuracy"])
    run(platform)
    assert posted(platform, "result")["results"] == {"accuracy": 1.0}


def test_there_is_nothing_to_do_when_the_evaluation_is_not_up_for_the_taking(platform: FakePlatform) -> None:
    platform.evaluation = None
    assert run(platform).result is None
    assert [method for method, _ in platform.calls] == ["POST"]


def test_predictions_that_do_not_match_fail_the_evaluation_with_the_reason(platform: FakePlatform) -> None:
    platform.add_evaluation([("test.csv", TRUTH)], ("p.jsonl", jsonl("pos", "neg")))
    assert run(platform).result == "failed"
    assert "Row 2 of test has no prediction: the file has only 2 lines" in posted(platform, "failure")["error"]
    assert not any(path.endswith("/result") for _, path in platform.calls)


def test_a_file_that_cannot_be_read_fails_it_too(platform: FakePlatform) -> None:
    platform.add_evaluation([("test.csv", TRUTH)], ("p.parquet", b"not parquet"), fmt="parquet")
    assert run(platform).result == "failed"
    assert "p.parquet" in posted(platform, "failure")["error"]


def test_a_file_missing_from_the_storage_fails_it(platform: FakePlatform) -> None:
    job = platform.add_evaluation([("test.csv", TRUTH)], ("p.jsonl", jsonl("pos")))
    del platform.files[job["truth"][0]["url"]]
    assert run(platform).result == "failed"
    assert "test.csv is missing" in posted(platform, "failure")["error"]


def test_a_storage_that_is_down_gives_it_back_and_the_job_is_tried_again(platform: FakePlatform, monkeypatch) -> None:
    platform.add_evaluation([("test.csv", TRUTH)], ("p.jsonl", jsonl("pos", "neg", "pos", "neg")))
    platform.storage_failure = 503
    monkeypatch.setattr(tasks.evaluate, "retry", lambda *a, **k: (_ for _ in ()).throw(Retry()))
    result = run(platform)
    assert not result.successful()
    assert any(path.endswith("/release") for _, path in platform.calls)
    assert not any(path.endswith("/failure") or path.endswith("/result") for _, path in platform.calls)


def test_the_key_goes_to_the_api_and_never_to_the_storage(platform: FakePlatform) -> None:
    platform.add_evaluation([("test.csv", TRUTH)], ("p.jsonl", jsonl("pos", "neg", "pos", "neg")))
    run(platform)
    from tests.conftest import KEY

    storage = len(platform.keys) - len(platform.calls)
    assert storage == 2 and platform.keys.count(KEY) == len(platform.calls)  # the truth and the predictions


def test_the_sweep_queues_the_evaluations_that_wait(platform: FakePlatform, monkeypatch) -> None:
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    platform.waiting_evaluation_ids = ids
    queued: list[str] = []
    monkeypatch.setattr(tasks.evaluate, "apply_async", lambda args: queued.append(args[0]))
    assert tasks.process_waiting.apply().result == 2 and queued == ids


# ---- joining the predictions and the truth


def test_the_line_of_the_predictions_is_the_position_of_the_item(platform: FakePlatform, backend) -> None:
    found = computed(
        platform, backend, truth=[("t.csv", TRUTH)], predictions=("p.jsonl", jsonl("pos", "neg", "neg", "pos"))
    )
    assert found.items == 4 and found.results["accuracy"] == 0.5


def test_the_files_of_the_split_follow_each_other(platform: FakePlatform, backend) -> None:
    truth = [("a.csv", b"label\npos\nneg\n"), ("b.csv", b"label\npos\n")]
    found = computed(platform, backend, truth=truth, predictions=("p.jsonl", jsonl("pos", "neg", "pos")))
    assert found.items == 3 and found.results["accuracy"] == 1.0


def test_an_item_is_found_by_its_key_whatever_the_order(platform: FakePlatform, backend) -> None:
    rows = [
        {"id": 4, "prediction": "neg"},
        {"id": 1, "prediction": "pos"},
        {"id": 3, "prediction": "pos"},
        {"id": 2, "prediction": "neg"},
    ]
    predictions = b"".join(json.dumps(r).encode() + b"\n" for r in rows)
    found = computed(platform, backend, truth=[("t.csv", TRUTH)], predictions=("p.jsonl", predictions), key_column="id")
    assert found.results["accuracy"] == 1.0  # the lines were not in the order of the split


def test_a_key_of_1_and_of_1_point_0_are_the_same_item(platform: FakePlatform, backend) -> None:
    predictions = b'{"id": 1.0, "prediction": "pos"}\n{"id": "2", "prediction": "neg"}\n'
    found = computed(
        platform,
        backend,
        truth=[("t.csv", b"id,label\n1,pos\n2,neg\n")],
        predictions=("p.jsonl", predictions),
        key_column="id",
    )
    assert found.results["accuracy"] == 1.0


def test_csv_and_parquet_predictions_are_read_too(platform: FakePlatform, backend) -> None:
    csv = computed(
        platform,
        backend,
        truth=[("t.csv", TRUTH)],
        predictions=("p.csv", b"prediction\npos\nneg\npos\nneg\n"),
        fmt="csv",
    )
    assert csv.results["accuracy"] == 1.0
    sink = io.BytesIO()
    pq.write_table(pa.table({"prediction": ["pos", "neg", "pos", "pos"]}), sink)
    parquet = computed(
        platform, backend, truth=[("t.csv", TRUTH)], predictions=("p.parquet", sink.getvalue()), fmt="parquet"
    )
    assert parquet.results["accuracy"] == 0.75


def test_the_truth_may_be_a_jsonl_or_a_parquet_file(platform: FakePlatform, backend) -> None:
    lines = b'{"label": "pos"}\n{"label": "neg"}\n'
    assert (
        computed(platform, backend, truth=[("t.jsonl", lines)], predictions=("p.jsonl", jsonl("pos", "neg"))).items == 2
    )
    sink = io.BytesIO()
    pq.write_table(pa.table({"label": ["pos", "neg"]}), sink)
    assert (
        computed(
            platform, backend, truth=[("t.parquet", sink.getvalue())], predictions=("p.jsonl", jsonl("pos", "pos"))
        ).results["accuracy"]
        == 0.5
    )


def test_the_column_of_the_predictions_and_of_the_truth_are_the_ones_that_were_asked(
    platform: FakePlatform, backend
) -> None:
    found = computed(
        platform, backend, truth=[("t.csv", b"text,gold\na,x\nb,y\n")],
        predictions=("p.jsonl", jsonl("x", "y", column="answer")),
        target_column="gold", prediction_column="answer",
    )  # fmt: skip
    assert found.results["accuracy"] == 1.0


def test_a_row_with_no_ground_truth_is_not_compared_but_keeps_its_line(platform: FakePlatform, backend) -> None:
    truth = b"label\npos\n\nneg\n"  # the second row has no answer
    found = computed(
        platform, backend, truth=[("t.csv", truth)], predictions=("p.jsonl", jsonl("pos", "whatever", "neg"))
    )
    assert found.items == 2 and found.results["accuracy"] == 1.0  # the third line is for the third row


def test_an_item_without_ground_truth_that_has_a_prediction_is_not_an_extra(platform: FakePlatform, backend) -> None:
    predictions = b'{"id": 1, "prediction": "pos"}\n{"id": 2, "prediction": "x"}\n'
    found = computed(
        platform,
        backend,
        truth=[("t.csv", b"id,label\n1,pos\n2,\n")],
        predictions=("p.jsonl", predictions),
        key_column="id",
    )
    assert found.items == 1


@pytest.mark.parametrize(
    ("truth", "predictions", "options", "message"),
    [
        (TRUTH, jsonl("pos", "neg", "pos"), {}, "Row 3 of test has no prediction: the file has only 3 lines"),
        (TRUTH, jsonl("pos", "neg", "pos", "neg", "pos"), {}, "more lines than test has rows"),
        (TRUTH, jsonl("pos", "neg", "pos", "neg", column="label"), {}, "Line 0 of the predictions has no prediction"),
        (TRUTH, jsonl("", "neg", "pos", "neg"), {}, "Row 0 of test has an empty prediction"),
        (b"label\n\n\n", jsonl("a", "b"), {}, "no row of test with a label to compare to"),
        (
            TRUTH,
            b'{"id": 1, "prediction": "pos"}\n{"id": 1, "prediction": "neg"}\n',
            {"key_column": "id"},
            "the item 1 has two predictions",
        ),
        (
            TRUTH,
            b'{"id": 1, "prediction": "pos"}\n',
            {"key_column": "id"},
            r"Row 1 of test \(item 2\) has no prediction",
        ),
        (
            TRUTH,
            b'{"id": 9, "prediction": "x"}\n' + b"".join(b'{"id": %d, "prediction": "x"}\n' % i for i in (1, 2, 3, 4)),
            {"key_column": "id"},
            "1 predictions are about items that are not in test",
        ),
        (TRUTH, b'{"prediction": "x"}\n', {"key_column": "id"}, "has no id"),
    ],
)
def test_predictions_that_do_not_match_the_split_say_where(
    platform, backend, truth, predictions, options, message
) -> None:
    with pytest.raises(EvaluationProblem, match=message):
        computed(platform, backend, truth=[("t.csv", truth)], predictions=("p.jsonl", predictions), **options)


def test_a_regression_and_an_answer_task_are_computed_from_a_column(platform: FakePlatform, backend) -> None:
    regression = computed(
        platform, backend, task="regression", metrics=["mae", "rmse", "r2", "mape"],
        truth=[("t.csv", b"label\n1\n2\n3\n4\n")], predictions=("p.jsonl", jsonl(1, 2, 3, 6)),
    )  # fmt: skip
    assert regression.results["mae"] == pytest.approx(0.5)
    answers = computed(
        platform, backend, task="qa", metrics=["exact_match", "f1"],
        truth=[("t.csv", b"label\nThe Eiffel Tower\nparis\n")],
        predictions=("p.jsonl", jsonl("eiffel tower", "london")),
    )  # fmt: skip
    assert answers.results == {"exact_match": 0.5, "f1": 0.5}


def test_a_task_the_worker_does_not_compute_is_the_data_s_fault_not_a_crash(platform: FakePlatform, backend) -> None:
    with pytest.raises(EvaluationProblem, match="does not compute the metrics of ner"):
        computed(platform, backend, task="ner", truth=[("t.csv", TRUTH)], predictions=("p.jsonl", jsonl("a")))


def test_a_missing_file_is_a_file_problem(platform: FakePlatform, backend) -> None:
    job = platform.add_evaluation([("t.csv", TRUTH)], ("p.jsonl", jsonl("pos")))
    del platform.files[job["predictions"]["url"]]
    with pytest.raises(FileMissing, match="p.jsonl is missing"):
        compute(backend(platform), backend(platform).claim_evaluation(uuid.UUID(job["id"])))


def test_the_predictions_by_key_are_limited(platform: FakePlatform, backend, monkeypatch) -> None:
    monkeypatch.setattr("worker.evaluator.settings.EVALUATION_MAX_KEYS", 2)
    predictions = b"".join(b'{"id": %d, "prediction": "x"}\n' % i for i in (1, 2, 3))
    with pytest.raises(EvaluationProblem, match="more than 2 items"):
        computed(platform, backend, truth=[("t.csv", TRUTH)], predictions=("p.jsonl", predictions), key_column="id")


def test_the_backend_client_reads_what_the_api_gives(platform: FakePlatform, backend) -> None:
    job = platform.add_evaluation([("t.csv", TRUTH)], ("p.jsonl", jsonl("pos")), key_column="id")
    taken = backend(platform).claim_evaluation(uuid.UUID(job["id"]))
    assert isinstance(backend(platform), Backend) and taken is not None
    assert (taken.task, taken.split, taken.key_column, taken.metrics) == (
        "classification",
        "test",
        "id",
        ["accuracy", "precision", "recall", "f1"],
    )
    assert [f.path for f in taken.truth] == ["t.csv"] and taken.predictions.path == "p.jsonl"

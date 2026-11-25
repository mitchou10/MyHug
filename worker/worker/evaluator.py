"""Computing an evaluation: reads the predictions and the ground truth side by side, as the rows go by, and gives the
metrics. Nothing of a file is held but a row (and, when the items are told apart by a key, the predictions by key)."""

import tempfile
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO

import pyarrow.parquet as pq

from worker import tables
from worker.backend import Backend, EvaluationToCompute, FileToCompute
from worker.config import settings
from worker.errors import EvaluationProblem, FileMissing, UnreadableFile
from worker.metrics import label_of, scorer_for


@dataclass(frozen=True)
class Computed:
    results: dict[str, float]
    items: int


def rows_of(path: str, handle: BinaryIO, fmt: str | None = None) -> Generator[dict[str, Any]]:
    """The rows of a csv, tsv, jsonl or parquet file, one dict by row, as the platform's preview reads the cells."""
    kind = {"csv": ".csv", "jsonl": ".jsonl", "parquet": ".parquet"}.get(fmt or "", tables.suffix_of(path))
    handle.seek(0)
    if kind == tables.PARQUET:
        try:
            for batch in pq.ParquetFile(handle).iter_batches():
                yield from batch.to_pylist()
        except Exception as error:  # noqa: BLE001 - pyarrow has several error types for a file that is not Parquet
            raise UnreadableFile(f"{path} is not a Parquet file") from error
    elif kind in (tables.CSV, tables.TSV):
        reader = tables.csv_rows(handle, "\t" if kind == tables.TSV else ",", path)
        header = next(reader, None)
        if not header or not any(name.strip() for name in header):
            raise UnreadableFile(f"{path} has no header")
        names = [name.strip() for name in header]
        for row in reader:
            cells = [tables.convert_cell(cell) for cell in row[: len(names)]]
            yield dict(zip(names, cells + [None] * (len(names) - len(cells)), strict=True))
    else:
        yield from tables.jsonl_objects(handle, path)


def _spooled(api: Backend, file: FileToCompute) -> BinaryIO:
    """The file on the disk, as it comes: never whole in memory."""
    handle = tempfile.TemporaryFile(dir=settings.WORKER_TEMP_DIR or None)  # noqa: SIM115 - closed by the caller
    try:
        for chunk in api.download(file.url):
            handle.write(chunk)
    except FileMissing:
        handle.close()
        raise FileMissing(f"{file.path} is missing from the storage") from None
    except Exception:
        handle.close()
        raise
    handle.flush()
    return handle


def _key(value: Any) -> str:
    return label_of(value)


def _truth_rows(api: Backend, job: EvaluationToCompute) -> Iterator[dict[str, Any]]:
    for file in job.truth:
        handle = _spooled(api, file)
        try:
            yield from rows_of(file.path, handle)
        finally:
            handle.close()


def compute(api: Backend, job: EvaluationToCompute) -> Computed:
    """The metrics of an evaluation. Raises EvaluationProblem when the predictions do not match the split, with a
    sentence that says where (the row, or the item), and FileProblem when a file cannot be read."""
    scorer = scorer_for(job.task)
    predictions = _spooled(api, job.predictions)
    lines: Generator[dict[str, Any]] | None = None
    try:
        by_key: dict[str, Any] | None = None
        if job.key_column:
            by_key = _by_key(predictions, job)
        else:
            lines = rows_of(job.predictions.path, predictions, job.predictions_format)
        items = used = 0
        for position, truth in enumerate(_truth_rows(api, job)):
            where = f"Row {position} of {job.split}"
            key = _key(truth.get(job.key_column)) if by_key is not None else None
            has_prediction = key in by_key if by_key is not None and key is not None else False
            used += has_prediction
            line = next(lines, None) if lines is not None else None  # its line is its line, whether it counts or not
            expected = truth.get(job.target_column)
            if expected is None or label_of(expected) == "":
                continue  # no ground truth for this row: it is not compared
            if by_key is not None and key is not None:
                if not has_prediction:
                    raise EvaluationProblem(f"{where} (item {key}) has no prediction")
                predicted = by_key[key]
            else:
                if line is None:
                    raise EvaluationProblem(f"{where} has no prediction: the file has only {position} lines")
                predicted = _prediction(line, job, position)
            scorer.add(expected, predicted, where)
            items += 1
        if by_key is not None and len(by_key) > used:
            raise EvaluationProblem(f"{len(by_key) - used} predictions are about items that are not in {job.split}")
        if lines is not None and next(lines, None) is not None:
            raise EvaluationProblem(f"The predictions have more lines than {job.split} has rows")
        if items == 0:
            raise EvaluationProblem(f"There is no row of {job.split} with a {job.target_column} to compare to")
        return Computed({k: v for k, v in scorer.result().items() if k in job.metrics}, items)
    finally:
        if lines is not None:
            lines.close()  # the reader must be done before its file is closed
        predictions.close()


def _prediction(line: dict[str, Any], job: EvaluationToCompute, position: int) -> Any:
    if job.prediction_column not in line:
        raise EvaluationProblem(f"Line {position} of the predictions has no {job.prediction_column}")
    return line[job.prediction_column]


def _by_key(predictions: BinaryIO, job: EvaluationToCompute) -> dict[str, Any]:
    """The predictions by the key of their item. Two for the same item are not told apart: it is refused."""
    found: dict[str, Any] = {}
    key_column = job.key_column or ""
    for number, line in enumerate(rows_of(job.predictions.path, predictions, job.predictions_format)):
        where = f"Line {number} of the predictions"
        if key_column not in line or job.prediction_column not in line:
            raise EvaluationProblem(f"{where} has no {key_column if key_column not in line else job.prediction_column}")
        key = _key(line[key_column])
        if key in found:
            raise EvaluationProblem(f"{where}: the item {key} has two predictions")
        if len(found) >= settings.EVALUATION_MAX_KEYS:
            raise EvaluationProblem(f"The predictions are about more than {settings.EVALUATION_MAX_KEYS} items")
        found[key] = line[job.prediction_column]
    return found


__all__ = ["Computed", "compute", "rows_of"]

import tempfile
import uuid

from worker import converter
from worker.backend import Backend, CopyToMake
from worker.config import settings
from worker.errors import FileMissing
from worker.tables import Column

SIGN_BATCH = 100  # signed addresses asked at a time


def make_copy(backend: Backend, copy: CopyToMake) -> tuple[int, list[Column]]:
    """Downloads the source to the disk, writes its Parquet copy to the disk, sends it to the storage in parts, and
    returns what the copy holds (rows, columns). Neither file is ever in memory whole."""
    with (
        tempfile.TemporaryFile(dir=settings.WORKER_TEMP_DIR or None) as source,
        tempfile.TemporaryFile(dir=settings.WORKER_TEMP_DIR or None) as target,
    ):
        try:
            for chunk in backend.download(copy.source_url):
                source.write(chunk)
        except FileMissing:
            raise FileMissing(f"{copy.source_path} is missing from the storage") from None
        source.flush()
        done = converter.convert(
            source,
            copy.source_path,
            target,
            row_group_rows=settings.ROW_GROUP_ROWS,
            batch_bytes=settings.BATCH_BYTES,
        )
        target.flush()
        _send(backend, copy.id, target, copy.part_bytes)
        return done.rows, done.columns


def _send(backend: Backend, derivative_id: uuid.UUID, target, part_bytes: int) -> None:
    size = target.seek(0, 2)
    total = max(1, -(-size // part_bytes))
    for first in range(1, total + 1, SIGN_BATCH):
        numbers = list(range(first, min(first + SIGN_BATCH, total + 1)))
        urls = backend.sign_copy_parts(derivative_id, numbers)
        for number in numbers:
            target.seek((number - 1) * part_bytes)
            backend.upload_part(urls[number], target.read(part_bytes))

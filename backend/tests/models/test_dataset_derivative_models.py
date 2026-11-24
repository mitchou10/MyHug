import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DatasetFileDerivative


def make(key: str = "datasets/x/abc", **fields) -> DatasetFileDerivative:
    return DatasetFileDerivative(
        source_storage_key=key, source_path="train.csv", source_size_bytes=10, params_hash="h" * 64, **fields
    )


async def test_the_defaults_make_a_copy_that_waits(db: AsyncSession) -> None:
    copy = make()
    db.add(copy)
    await db.commit()
    await db.refresh(copy)
    assert (copy.kind, copy.status, copy.attempts, copy.columns) == ("parquet", "pending", 0, [])
    assert copy.created_at and copy.updated_at and copy.storage_key is None and copy.rows is None


async def test_a_source_is_copied_once_for_a_way_of_copying(db: AsyncSession) -> None:
    db.add_all([make(), make()])
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_the_same_source_can_have_a_copy_made_another_way(db: AsyncSession) -> None:
    other = make()
    other.params_hash = "g" * 64
    db.add_all([make(), other])
    await db.commit()


@pytest.mark.parametrize("fields", [{"status": "done"}, {"kind": "csv"}, {"attempts": -1}])
async def test_a_value_that_means_nothing_is_refused(db: AsyncSession, fields: dict) -> None:
    db.add(make(**fields))
    with pytest.raises(IntegrityError):
        await db.commit()

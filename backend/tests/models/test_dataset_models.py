import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, DatasetLike, DatasetMember, DatasetVersion


def make(name: str = "movie-reviews", owner: str = "ada", **fields) -> Dataset:
    return Dataset(owner=owner, name=name, modality="text", created_by="u1", created_by_username="ada", **fields)


async def test_the_defaults_make_an_empty_public_dataset(db: AsyncSession) -> None:
    dataset = make()
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    assert dataset.id and dataset.created_at and dataset.updated_at
    assert (dataset.description, dataset.language, dataset.license, dataset.card) == ("", "", "", "")
    assert (dataset.tags, dataset.visibility, dataset.downloads, dataset.likes_count) == ([], "public", 0, 0)


async def test_the_tags_are_kept_as_a_list(db: AsyncSession) -> None:
    db.add(make(tags=["nlp", "sentiment"]))
    await db.commit()
    assert (await db.execute(select(Dataset.tags))).scalar_one() == ["nlp", "sentiment"]


async def test_an_address_is_unique_but_two_people_can_use_the_same_name(db: AsyncSession) -> None:
    db.add_all([make(owner="ada"), make(owner="grace")])
    await db.commit()
    db.add(make(owner="ada"))
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.parametrize(
    "fields", [{"modality": "model"}, {"visibility": "secret"}, {"downloads": -1}, {"likes_count": -1}]
)
async def test_the_database_refuses_what_makes_no_sense(db: AsyncSession, fields: dict) -> None:
    dataset = make()
    for field, value in fields.items():
        setattr(dataset, field, value)
    db.add(dataset)
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_a_member_has_one_role_among_the_known_ones(db: AsyncSession) -> None:
    dataset = make()
    db.add(dataset)
    await db.commit()
    db.add(DatasetMember(dataset_id=dataset.id, user_id="u2", role="king", added_by="u1"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_a_person_is_member_and_likes_once(db: AsyncSession) -> None:
    dataset = make()
    db.add(dataset)
    await db.commit()
    db.add_all(
        [
            DatasetMember(dataset_id=dataset.id, user_id="u2", role="reader", added_by="u1"),
            DatasetLike(dataset_id=dataset.id, user_id="u2"),
        ]
    )
    await db.commit()
    db.add(DatasetLike(dataset_id=dataset.id, user_id="u2"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_deleting_a_dataset_takes_its_members_and_likes_with_it(db: AsyncSession) -> None:
    dataset = make()
    db.add(dataset)
    await db.commit()
    db.add_all(
        [
            DatasetMember(dataset_id=dataset.id, user_id="u2", role="annotator", added_by="u1"),
            DatasetLike(dataset_id=dataset.id, user_id="u2"),
        ]
    )
    await db.commit()
    await db.delete(dataset)
    await db.commit()
    assert (await db.execute(select(DatasetMember))).first() is None
    assert (await db.execute(select(DatasetLike))).first() is None


async def test_a_version_waits_to_be_read_and_its_rows_are_not_known(db: AsyncSession) -> None:
    dataset = make()
    db.add(dataset)
    await db.commit()
    version = DatasetVersion(dataset_id=dataset.id, number=1, created_by="u1", created_by_username="ada")
    db.add(version)
    await db.commit()
    await db.refresh(version)
    assert (version.status, version.rows, version.error, version.columns, version.size_bytes) == (
        "pending",
        None,
        None,
        [],
        0,
    )
    assert (await db.execute(select(Dataset.rows))).scalar_one() is None


async def test_a_version_has_one_of_the_known_statuses(db: AsyncSession) -> None:
    dataset = make()
    db.add(dataset)
    await db.commit()
    db.add(
        DatasetVersion(dataset_id=dataset.id, number=1, status="halfway", created_by="u1", created_by_username="ada")
    )
    with pytest.raises(IntegrityError):
        await db.commit()

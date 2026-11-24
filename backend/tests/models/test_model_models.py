import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Model, ModelFile, ModelLike, ModelMember, ModelVersion

SHA1 = "a" * 40
SHA256 = "b" * 64


def make(name: str = "sentiment-fr", owner: str = "ada", **fields) -> Model:
    return Model(owner=owner, name=name, created_by="u1", created_by_username="ada", **fields)


def version(model: Model | uuid.UUID, number: int = 1, **fields) -> ModelVersion:
    """A version of a model, given as the model or as its id: after a rollback a model has to be reloaded to give it."""
    model_id = model if isinstance(model, uuid.UUID) else model.id
    return ModelVersion(model_id=model_id, number=number, created_by="u1", created_by_username="ada", **fields)


async def saved(db: AsyncSession, *items):
    db.add_all(items)
    await db.commit()
    return items[0] if len(items) == 1 else items


# ---- the model


async def test_the_defaults_make_an_empty_public_model(db: AsyncSession) -> None:
    model = await saved(db, make())
    await db.refresh(model)
    assert model.id and model.created_at and model.updated_at
    assert (model.description, model.library, model.license, model.card) == ("", "", "", "")
    assert (model.tasks, model.inputs, model.languages, model.tags, model.trained_on) == ([], [], [], [], [])
    assert (model.visibility, model.downloads, model.likes_count, model.version, model.size_bytes) == (
        "public",
        0,
        0,
        0,
        0,
    )
    assert (model.code_url, model.parameters) == (None, None)


async def test_the_lists_are_kept_as_lists(db: AsyncSession) -> None:
    await saved(
        db,
        make(
            tasks=["classification", "ner"],
            inputs=["text", "tabular"],
            languages=["fr", "en"],
            tags=["nlp"],
            trained_on=["ada/movie-reviews"],
        ),
    )
    row = (await db.execute(select(Model))).scalar_one()
    assert (row.tasks, row.inputs, row.languages, row.tags, row.trained_on) == (
        ["classification", "ner"],
        ["text", "tabular"],
        ["fr", "en"],
        ["nlp"],
        ["ada/movie-reviews"],
    )


async def test_an_address_is_unique_but_two_people_can_use_the_same_name(db: AsyncSession) -> None:
    await saved(db, make(owner="ada"), make(owner="grace"))
    db.add(make(owner="ada"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_a_model_and_a_dataset_can_have_the_same_address(db: AsyncSession) -> None:
    from app.models import Dataset

    await saved(
        db, Dataset(owner="ada", name="sentiment-fr", modality="text", created_by="u1", created_by_username="a")
    )
    await saved(db, make())  # models and datasets have their own spaces


@pytest.mark.parametrize(
    "fields",
    [
        {"visibility": "secret"},
        {"inputs": ["text", "hologram"]},
        {"downloads": -1},
        {"likes_count": -1},
        {"version": -1},
        {"size_bytes": -1},
        {"parameters": -1},
    ],
)
async def test_the_database_refuses_what_makes_no_sense(db: AsyncSession, fields: dict) -> None:
    db.add(make(**fields))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_a_model_may_take_every_kind_of_data(db: AsyncSession) -> None:
    await saved(db, make(inputs=["text", "image", "audio", "video", "tabular", "timeseries"]))


# ---- who has access


async def test_a_member_is_a_reader_or_a_maintainer_and_nothing_else(db: AsyncSession) -> None:
    model = await saved(db, make())
    model_id = model.id
    await saved(
        db,
        ModelMember(model_id=model_id, user_id="u2", role="reader", added_by="u1"),
        ModelMember(model_id=model_id, user_id="u3", role="maintainer", added_by="u1"),
    )
    for role in ("owner", "admin", "annotator", "king"):  # the owner and the admins are worked out, not members
        db.add(ModelMember(model_id=model_id, user_id=f"x-{role}", role=role, added_by="u1"))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_a_person_is_member_and_likes_once(db: AsyncSession) -> None:
    model_id = (await saved(db, make())).id
    await saved(
        db,
        ModelMember(model_id=model_id, user_id="u2", role="reader", added_by="u1"),
        ModelLike(model_id=model_id, user_id="u2"),
    )
    db.add(ModelLike(model_id=model_id, user_id="u2"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    db.add(ModelMember(model_id=model_id, user_id="u2", role="maintainer", added_by="u1"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_deleting_a_model_takes_everything_that_belongs_to_it(db: AsyncSession) -> None:
    model = await saved(db, make())
    await saved(
        db,
        ModelMember(model_id=model.id, user_id="u2", role="reader", added_by="u1"),
        ModelLike(model_id=model.id, user_id="u2"),
    )
    first = await saved(db, version(model))
    await saved(db, ModelFile(version_id=first.id, path="w.bin", size_bytes=1, content_type="x", storage_key="k"))
    await db.delete(model)
    await db.commit()
    for table in (ModelMember, ModelLike, ModelVersion, ModelFile):
        assert (await db.execute(select(table))).first() is None


# ---- the versions


async def test_a_version_waits_and_has_no_code_unless_it_is_told(db: AsyncSession) -> None:
    model = await saved(db, make())
    item = await saved(db, version(model))
    await db.refresh(item)
    assert (item.status, item.error, item.attempts, item.servable, item.size_bytes) == ("pending", None, 0, False, 0)
    assert (item.mlflow_name, item.mlflow_version, item.mlflow_run_id) == (None, None, None)
    assert (item.code_url, item.code_ref, item.code_ref_kind, item.code_sha, item.code_state) == (
        None,
        None,
        "unknown",
        None,
        "none",
    )
    assert item.created_at


async def test_a_number_is_used_once_by_a_model_and_by_each_model(db: AsyncSession) -> None:
    first, second = await saved(db, make(), make(name="other"))
    await saved(db, version(first), version(second))
    db.add(version(first))
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.parametrize("fields", [{"number": 0}, {"status": "halfway"}, {"size_bytes": -1}, {"attempts": -1}])
async def test_a_version_refuses_what_makes_no_sense(db: AsyncSession, fields: dict) -> None:
    model = await saved(db, make())
    db.add(version(model, **{"number": 1, **fields}))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_a_version_can_be_an_artifact_some_code_or_both(db: AsyncSession) -> None:
    model = await saved(db, make())
    await saved(
        db,
        version(model, 1, mlflow_name="ada/sentiment-fr", mlflow_version="1", servable=True),  # the artifact alone
        version(
            model,
            2,
            code_url="https://github.com/ada/code",
            code_ref="main",
            code_ref_kind="branch",
            code_state="unresolved",
        ),
        version(
            model,
            3,
            mlflow_name="ada/sentiment-fr",
            mlflow_version="3",
            mlflow_run_id="r" * 32,
            code_url="https://github.com/ada/code",
            code_ref=SHA1,
            code_ref_kind="commit",
            code_path="src",
            entrypoint="src/predict.py",
            code_sha=SHA1,
            code_state="pinned",
        ),
    )


async def test_the_reference_to_mlflow_is_whole_or_absent(db: AsyncSession) -> None:
    model_id = (await saved(db, make())).id
    for fields in ({"mlflow_name": "ada/x"}, {"mlflow_version": "1"}):
        db.add(ModelVersion(model_id=model_id, number=1, created_by="u1", created_by_username="ada", **fields))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_a_version_of_mlflow_belongs_to_one_version_here(db: AsyncSession) -> None:
    first, second = await saved(db, make(), make(name="other"))
    first_id, second_id = first.id, second.id
    await saved(db, version(first_id, mlflow_name="m", mlflow_version="1"))
    db.add(version(second_id, mlflow_name="m", mlflow_version="1"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    await saved(db, version(second_id, mlflow_name="m", mlflow_version="2"))  # another one is fine
    await saved(db, version(second_id, 2), version(first_id, 2))  # and many versions have none


@pytest.mark.parametrize(
    "fields",
    [
        {"code_state": "thinking", "code_url": "https://github.com/a/b"},
        {"code_ref_kind": "release", "code_url": "https://github.com/a/b", "code_state": "unresolved"},
        {"code_url": "https://github.com/a/b"},  # a link and no state: the state is `none`
        {"code_state": "unresolved"},  # a state and no link
        {"code_state": "unverified"},
        {
            "code_url": "https://github.com/a/b",
            "code_state": "unresolved",
            "code_sha": SHA1,
        },  # a commit before it is pinned
        {"code_url": "https://github.com/a/b", "code_state": "pinned"},  # pinned without its commit
        {"code_url": "https://github.com/a/b", "code_state": "pinned", "code_sha": "abc123"},  # not a commit
        {"code_url": "https://github.com/a/b", "code_state": "pinned", "code_sha": "A" * 40},  # not lowercase
        {"code_url": "https://github.com/a/b", "code_state": "pinned", "code_sha": "g" * 40},  # not hexadecimal
        {"code_url": "https://github.com/a/b", "code_state": "pinned", "code_sha": "a" * 41},
    ],
)
async def test_the_code_of_a_version_is_followed_coherently(db: AsyncSession, fields: dict) -> None:
    model = await saved(db, make())
    db.add(version(model, **fields))
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.parametrize("state", ["unresolved", "resolving", "unverified", "failed"])
async def test_every_state_of_the_code_that_is_not_pinned_has_no_commit(db: AsyncSession, state: str) -> None:
    model = await saved(db, make())
    await saved(
        db,
        version(
            model, code_url="https://gitlab.com/a/b", code_state=state, code_error="no" if state == "failed" else None
        ),
    )


@pytest.mark.parametrize("sha", [SHA1, SHA256])
async def test_a_commit_is_forty_or_sixty_four_hexadecimal_characters(db: AsyncSession, sha: str) -> None:
    model = await saved(db, make())
    await saved(db, version(model, code_url="https://github.com/a/b", code_state="pinned", code_sha=sha))


async def test_the_partial_indexes_for_the_worker_exist(db: AsyncSession) -> None:
    rows = (
        (await db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'model_versions'"))).scalars().all()
    )
    assert {"ix_model_versions_pending", "ix_model_versions_code_unresolved", "uq_model_versions_mlflow"} <= set(rows)


# ---- the files


async def test_a_path_is_used_once_by_a_version(db: AsyncSession) -> None:
    model = await saved(db, make())
    first, second = await saved(db, version(model, 1), version(model, 2))
    first_id, second_id = first.id, second.id
    await saved(db, ModelFile(version_id=first_id, path="w.bin", size_bytes=1, content_type="x", storage_key="k"))
    db.add(ModelFile(version_id=first_id, path="w.bin", size_bytes=2, content_type="x", storage_key="k2"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    # A file kept from a version to the next is the same object of the storage under the same path.
    await saved(db, ModelFile(version_id=second_id, path="w.bin", size_bytes=1, content_type="x", storage_key="k"))


async def test_a_file_has_no_fingerprint_until_it_is_read_and_no_negative_size(db: AsyncSession) -> None:
    model = await saved(db, make())
    item = await saved(db, version(model))
    stored = await saved(
        db, ModelFile(version_id=item.id, path="w.bin", size_bytes=0, content_type="x", storage_key="k")
    )
    assert stored.sha256 is None
    db.add(ModelFile(version_id=item.id, path="x.bin", size_bytes=-1, content_type="x", storage_key="k"))
    with pytest.raises(IntegrityError):
        await db.commit()

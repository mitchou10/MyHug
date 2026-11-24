import logging

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Model, ModelVersion
from app.registry import registered_name
from app.registry.compensation import registered_model, registered_run, registered_version
from app.services.errors import RegistryConflict, RegistryRejected, RegistryUnavailable
from tests.conftest import MemoryRegistry

NAME = registered_name("ada", "sentiment-fr")


def a_model(**fields) -> Model:
    return Model(owner="ada", name="sentiment-fr", created_by="u1", created_by_username="ada", **fields)


async def count(db: AsyncSession, table) -> int:
    return len((await db.execute(select(table))).scalars().all())


# ---- the model: MLflow first, the database last


async def test_the_model_is_made_in_mlflow_then_in_the_database(db: AsyncSession, registry: MemoryRegistry) -> None:
    async with registered_model(registry, NAME):
        db.add(a_model())
        await db.commit()
    assert registry.models == {NAME} and await count(db, Model) == 1
    assert registry.calls == ["create_model"]  # nothing is undone when all goes well


async def test_when_mlflow_is_down_nothing_is_written_to_the_database(
    db: AsyncSession, registry: MemoryRegistry
) -> None:
    registry.down = True
    reached = False
    with pytest.raises(RegistryUnavailable):
        async with registered_model(registry, NAME):
            reached = True  # the database is only touched in here
            db.add(a_model())
            await db.commit()
    assert not reached and await count(db, Model) == 0 and registry.models == set()


async def test_when_the_database_fails_the_registered_model_is_deleted(
    db: AsyncSession, registry: MemoryRegistry
) -> None:
    with pytest.raises(IntegrityError):
        async with registered_model(registry, NAME):
            db.add(a_model(visibility="secret"))  # the database refuses it
            await db.commit()
    await db.rollback()
    assert registry.models == set() and registry.calls == ["create_model", "delete_model"]
    assert await count(db, Model) == 0


async def test_a_name_that_is_taken_in_mlflow_stops_before_the_database(
    db: AsyncSession, registry: MemoryRegistry
) -> None:
    registry.models.add(NAME)
    with pytest.raises(RegistryConflict):
        async with registered_model(registry, NAME):
            db.add(a_model())
    assert registry.models == {NAME} and await count(db, Model) == 0  # and the one that was there is not deleted
    assert "delete_model" not in registry.calls


async def test_a_name_mlflow_refuses_stops_before_the_database(db: AsyncSession, registry: MemoryRegistry) -> None:
    with pytest.raises(RegistryRejected):
        async with registered_model(registry, "ada/sentiment-fr"):
            db.add(a_model())
    assert await count(db, Model) == 0


async def test_a_failure_to_undo_is_logged_and_does_not_hide_the_real_error(
    db: AsyncSession, registry: MemoryRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR), pytest.raises(IntegrityError):
        async with registered_model(registry, NAME):
            registry.fail_on = "delete_model"  # MLflow goes down just when it has to be undone
            db.add(a_model(visibility="secret"))
            await db.commit()
    assert "delete it by hand" in caplog.text and NAME in caplog.text
    assert registry.models == {NAME}  # what is left is known and findable


async def test_an_error_that_is_not_the_database_undoes_it_too(registry: MemoryRegistry) -> None:
    with pytest.raises(RuntimeError):
        async with registered_model(registry, NAME):
            raise RuntimeError("something else")
    assert registry.models == set()


# ---- the run and the version


async def test_a_run_is_finished_when_the_block_ends_and_deleted_when_it_fails(registry: MemoryRegistry) -> None:
    async with registered_run(registry, NAME) as run:
        assert registry.runs[run.run_id]["status"] == "RUNNING"
    assert registry.runs[run.run_id]["status"] == "FINISHED"
    with pytest.raises(RuntimeError):
        async with registered_run(registry, NAME) as failed:
            raise RuntimeError("the upload broke")
    assert failed.run_id not in registry.runs


async def test_when_mlflow_is_down_a_run_is_not_made(registry: MemoryRegistry) -> None:
    registry.down = True
    with pytest.raises(RegistryUnavailable):
        async with registered_run(registry, NAME):
            raise AssertionError("not reached")


async def test_a_version_is_registered_and_kept_when_the_database_agrees(
    db: AsyncSession, registry: MemoryRegistry
) -> None:
    registry.models.add(NAME)
    model = a_model()
    db.add(model)
    await db.commit()
    async with registered_run(registry, NAME) as run, registered_version(registry, NAME, run, "model") as version:
        db.add(
            ModelVersion(
                model_id=model.id,
                number=1,
                mlflow_name=NAME,
                mlflow_version=version.version,
                created_by="u1",
                created_by_username="ada",
            )
        )
        await db.commit()
    assert (NAME, "1") in registry.versions and await count(db, ModelVersion) == 1


async def test_when_the_database_fails_the_version_is_deleted_in_mlflow(
    db: AsyncSession, registry: MemoryRegistry
) -> None:
    registry.models.add(NAME)
    model = a_model()
    db.add(model)
    await db.commit()
    model_id = model.id
    with pytest.raises(IntegrityError):
        async with registered_run(registry, NAME) as run, registered_version(registry, NAME, run) as version:
            db.add(ModelVersion(model_id=model_id, number=0, created_by="u1", created_by_username="a"))  # number >= 1
            await db.commit()
    await db.rollback()
    assert (NAME, version.version) not in registry.versions and run.run_id not in registry.runs
    assert await count(db, ModelVersion) == 0


async def test_a_version_of_a_model_that_is_not_in_mlflow_is_not_found(registry: MemoryRegistry) -> None:
    from app.services.errors import RegistryNotFound

    run = await registry.create_run(NAME)
    with pytest.raises(RegistryNotFound):
        async with registered_version(registry, NAME, run):
            raise AssertionError("not reached")


async def test_a_failure_to_undo_a_version_is_logged(
    registry: MemoryRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    registry.models.add(NAME)
    run = await registry.create_run(NAME)
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="real"):
        async with registered_version(registry, NAME, run):
            registry.fail_on = "delete_version"
            raise RuntimeError("the real error")
    assert "delete it by hand" in caplog.text


async def test_a_run_whose_delete_fails_is_logged_and_the_error_goes_on(
    registry: MemoryRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="real"):
        async with registered_run(registry, NAME):
            registry.fail_on = "delete_run"
            raise RuntimeError("the real error")
    assert "delete it by hand" in caplog.text


# ---- the double of the tests behaves like MLflow


async def test_the_double_refuses_what_mlflow_refuses(registry: MemoryRegistry) -> None:
    for bad in ("a/b", "a:b", "", "x" * 257):
        with pytest.raises(RegistryRejected):
            await registry.create_model(bad)
    await registry.create_model("a")
    with pytest.raises(RegistryConflict):
        await registry.create_model("a")
    run = await registry.create_run("a")
    assert (await registry.create_version("a", run, "m")).version == "1"
    assert (await registry.create_version("a", run)).version == "2"
    await registry.set_alias("a", "production", "2")
    assert registry.aliases[("a", "production")] == "2"
    assert await registry.artifact_key_prefix("a", "1") == f"mlflow/{run.experiment_id}/{run.run_id}/artifacts/m/"
    await registry.delete_model("a")
    assert not await registry.model_exists("a") and registry.versions == {}

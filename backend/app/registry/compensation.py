"""The order of the calls when a request needs both MLflow and the database, so that nothing is left half made.

MLflow and the database cannot be in one transaction. The rule is: **MLflow first, the database last, and undo MLflow
if the database fails.**

- If MLflow does not answer, the call raises before anything is written to the database: nothing exists anywhere.
- If MLflow answers and the database then fails (the commit, a constraint), what MLflow made is deleted, and the
  original error goes on. If that delete fails too, it is logged (it leaves a registered model or a version that nobody
  points to, which a person can delete) and it does not hide the error of the database.

Each helper is used as `async with registered_model(registry, name): <write and commit>`."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from app.registry.base import ModelRegistry, RegistryRun, RegistryVersion

logger = logging.getLogger(__name__)


@asynccontextmanager
async def registered_model(registry: ModelRegistry, name: str) -> AsyncGenerator[None]:
    """The registered model exists inside the block, and is deleted if the block raises."""
    await registry.create_model(name)
    try:
        yield
    except BaseException:
        try:
            await registry.delete_model(name)
        except Exception:
            logger.exception("The registered model %s could not be deleted after a failure: delete it by hand", name)
        raise


@asynccontextmanager
async def registered_run(registry: ModelRegistry, model_name: str) -> AsyncGenerator[RegistryRun]:
    """A run to put the artifacts in. It is finished when the block ends, and deleted if the block raises."""
    run = await registry.create_run(model_name)
    try:
        yield run
    except BaseException:
        try:
            await registry.delete_run(run.run_id)
        except Exception:
            logger.exception("The run %s could not be deleted after a failure: delete it by hand", run.run_id)
        raise
    await registry.finish_run(run.run_id)


@asynccontextmanager
async def registered_version(
    registry: ModelRegistry, name: str, run: RegistryRun, path: str = ""
) -> AsyncGenerator[RegistryVersion]:
    """The version is registered inside the block, and deleted if the block raises."""
    version = await registry.create_version(name, run, path)
    try:
        yield version
    except BaseException:
        try:
            await registry.delete_version(name, version.version)
        except Exception:
            logger.exception(
                "The version %s of %s could not be deleted after a failure: delete it by hand", version.version, name
            )
        raise

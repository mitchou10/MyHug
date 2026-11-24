import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DatasetMember
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.routers.deps import get_dataset_service
from app.services.actor import Actor
from app.services.dataset_access import ADMIN, OWNER, DatasetAccess
from app.services.dataset_versions import DatasetVersionService, NamedUpload
from app.services.datasets import DatasetService, namespace_of
from app.services.errors import DatasetNameTaken, DatasetNotFound, NotAllowed
from tests.conftest import MemoryStore

ADA = Actor(user_id="u1", username="ada")
GRACE = Actor(user_id="u2", username="grace")
ROOT = Actor(user_id="a1", username="root", is_admin=True)
FIELDS = {
    "description": "",
    "modality": "text",
    "language": "",
    "license": "",
    "tags": [],
    "visibility": "public",
    "card": "",
}


def service(db: AsyncSession) -> DatasetService:
    return get_dataset_service(db, MemoryStore())


@pytest.mark.parametrize(
    ("username", "namespace"),
    [
        ("ada", "ada"),
        ("Ada Lovelace", "ada-lovelace"),
        ("ada@example.com", "ada-example.com"),
        ("  --Ada--  ", "ada"),
        ("é", "user"),
        ("", "user"),
    ],
)
def test_the_namespace_is_what_an_address_allows(username: str, namespace: str) -> None:
    assert namespace_of(Actor(user_id="u", username=username)) == namespace


async def test_the_role_is_the_creator_the_admin_or_the_role_of_a_member(db: AsyncSession) -> None:
    datasets = DatasetRepository(db)
    access = DatasetAccess(datasets)
    view = await service(db).create(ADA, name="reviews", **FIELDS)
    dataset = view.dataset
    assert await access.role(ADA, dataset) == OWNER
    assert await access.role(ROOT, dataset) == ADMIN
    assert await access.role(GRACE, dataset) is None
    datasets.add_member(DatasetMember(dataset_id=dataset.id, user_id="u2", role="annotator", added_by="u1"))
    await datasets.commit()
    assert await access.role(GRACE, dataset) == "annotator"


async def test_a_private_dataset_is_hidden_from_a_person_without_access_and_a_public_one_is_not_editable(
    db: AsyncSession,
) -> None:
    await service(db).create(ADA, name="hidden", **{**FIELDS, "visibility": "private"})
    await service(db).create(ADA, name="shown", **FIELDS)
    access = DatasetAccess(DatasetRepository(db))
    with pytest.raises(DatasetNotFound):
        await access.get_readable(GRACE, "ada", "hidden")
    with pytest.raises(DatasetNotFound):
        await access.get_editable(GRACE, "ada", "hidden")
    assert (await access.get_readable(GRACE, "ada", "shown"))[1] is None
    with pytest.raises(NotAllowed):
        await access.get_editable(GRACE, "ada", "shown")


async def test_the_database_decides_when_two_requests_create_the_same_name(db: AsyncSession) -> None:
    """The check before writing cannot see a dataset that another request has not committed yet."""

    class Blind(DatasetRepository):
        async def get_by_name(self, owner: str, name: str):  # the check finds nothing, as with a request in flight
            return None

    await service(db).create(ADA, name="reviews", **FIELDS)
    blind = Blind(db)
    with pytest.raises(DatasetNameTaken):
        await DatasetService(blind, DatasetAccess(blind), DatasetVersionRepository(db), MemoryStore()).create(
            ADA, name="reviews", **FIELDS
        )


# ---- when the storage or the database breaks halfway


class BreaksAfter(MemoryStore):
    """A storage that fails on its n-th write."""

    def __init__(self, working_writes: int) -> None:
        super().__init__()
        self.remaining = working_writes

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        if self.remaining == 0:
            raise ConnectionError("storage down")
        self.remaining -= 1
        await super().put(key, data, content_type)


def versions(db: AsyncSession, store: MemoryStore) -> DatasetVersionService:
    datasets = DatasetRepository(db)
    return DatasetVersionService(
        datasets, DatasetVersionRepository(db), DatasetAccess(datasets), store, max_bytes=1_000_000, max_files=10
    )


def two_files() -> list[NamedUpload]:
    return [NamedUpload(path="a.csv", data=b"n\n1\n"), NamedUpload(path="b.csv", data=b"n\n2\n")]


async def test_when_the_storage_breaks_halfway_nothing_is_left_behind(db: AsyncSession) -> None:
    await service(db).create(ADA, name="reviews", **FIELDS)
    store = BreaksAfter(working_writes=1)
    with pytest.raises(ConnectionError):
        await versions(db, store).create(ADA, "ada", "reviews", uploads=two_files(), remove=[], message="")
    assert store.objects == {}  # the file that was stored is taken back
    assert (await service(db).get(ADA, "ada", "reviews")).dataset.version == 0


async def test_when_the_database_breaks_after_the_storage_the_new_files_are_taken_back(db: AsyncSession) -> None:
    class Breaks(DatasetVersionRepository):
        async def commit(self) -> None:
            raise ConnectionError("database down")

    await service(db).create(ADA, name="reviews", **FIELDS)
    store = MemoryStore()
    datasets = DatasetRepository(db)
    broken = DatasetVersionService(
        datasets, Breaks(db), DatasetAccess(datasets), store, max_bytes=1_000_000, max_files=10
    )
    with pytest.raises(ConnectionError):
        await broken.create(ADA, "ada", "reviews", uploads=two_files(), remove=[], message="")
    assert store.objects == {}


async def test_a_file_already_stored_by_an_older_version_is_not_taken_back_when_a_new_version_fails(
    db: AsyncSession,
) -> None:
    await service(db).create(ADA, name="reviews", **FIELDS)
    store = MemoryStore()
    await versions(db, store).create(ADA, "ada", "reviews", uploads=two_files()[:1], remove=[], message="")
    stored = dict(store.objects)

    class Breaks(DatasetVersionRepository):
        async def commit(self) -> None:
            raise ConnectionError("database down")

    datasets = DatasetRepository(db)
    broken = DatasetVersionService(
        datasets, Breaks(db), DatasetAccess(datasets), store, max_bytes=1_000_000, max_files=10
    )
    with pytest.raises(ConnectionError):
        # the same content as version 1, under another name, and a new file
        await broken.create(
            ADA,
            "ada",
            "reviews",
            uploads=[two_files()[0].model_copy(update={"path": "again.csv"}), two_files()[1]],
            remove=[],
            message="",
        )
    assert set(store.objects) == set(stored)  # what version 1 uses is still there

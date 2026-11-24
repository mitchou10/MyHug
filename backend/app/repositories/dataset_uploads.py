import uuid
from datetime import datetime

from sqlalchemy import select

from app.models import DatasetUpload, DatasetUploadFile
from app.models.dataset_upload import OPEN
from app.repositories.base import Repository


class DatasetUploadRepository(Repository):
    def add(self, upload: DatasetUpload) -> None:
        self._db.add(upload)

    def add_file(self, file: DatasetUploadFile) -> None:
        self._db.add(file)

    async def get(self, upload_id: uuid.UUID) -> DatasetUpload | None:
        return await self._db.get(DatasetUpload, upload_id)

    async def files(self, upload_id: uuid.UUID) -> list[DatasetUploadFile]:
        result = await self._db.execute(
            select(DatasetUploadFile).where(DatasetUploadFile.upload_id == upload_id).order_by(DatasetUploadFile.path)
        )
        return list(result.scalars())

    async def open_files(self, dataset_id: uuid.UUID) -> list[DatasetUploadFile]:
        """The files of the uploads of a dataset that are still going on: their parts are in the storage."""
        result = await self._db.execute(
            select(DatasetUploadFile)
            .join(DatasetUpload)
            .where(DatasetUpload.dataset_id == dataset_id, DatasetUpload.status == OPEN)
        )
        return list(result.scalars())

    async def open_until(self, moment: datetime) -> list[DatasetUpload]:
        """The uploads still open whose time is over."""
        result = await self._db.execute(
            select(DatasetUpload).where(DatasetUpload.status == OPEN, DatasetUpload.expires_at <= moment)
        )
        return list(result.scalars())

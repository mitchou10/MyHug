import uuid
from datetime import datetime

from sqlalchemy import select

from app.models import ModelUpload, ModelUploadFile
from app.models.model_upload import OPEN
from app.repositories.base import Repository


class ModelUploadRepository(Repository):
    def add(self, upload: ModelUpload) -> None:
        self._db.add(upload)

    def add_file(self, file: ModelUploadFile) -> None:
        self._db.add(file)

    async def get(self, upload_id: uuid.UUID) -> ModelUpload | None:
        return await self._db.get(ModelUpload, upload_id)

    async def files(self, upload_id: uuid.UUID) -> list[ModelUploadFile]:
        result = await self._db.execute(
            select(ModelUploadFile).where(ModelUploadFile.upload_id == upload_id).order_by(ModelUploadFile.path)
        )
        return list(result.scalars())

    async def announced_fingerprints(self, file_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """The fingerprints the browser announced for files it sent in parts, to compare with what is really there."""
        if not file_ids:
            return {}
        result = await self._db.execute(
            select(ModelUploadFile.id, ModelUploadFile.sha256).where(
                ModelUploadFile.id.in_(file_ids),
                ModelUploadFile.sha256.is_not(None),
                ModelUploadFile.multipart_id.is_not(None),
            )
        )
        return {file_id: sha for file_id, sha in result.all() if sha}

    async def open_files(self, model_id: uuid.UUID) -> list[ModelUploadFile]:
        """The files of the uploads of a model that are still going on: their parts are in the storage."""
        result = await self._db.execute(
            select(ModelUploadFile)
            .join(ModelUpload)
            .where(ModelUpload.model_id == model_id, ModelUpload.status == OPEN)
        )
        return list(result.scalars())

    async def open_until(self, moment: datetime) -> list[ModelUpload]:
        """The uploads still open whose time is over."""
        result = await self._db.execute(
            select(ModelUpload).where(ModelUpload.status == OPEN, ModelUpload.expires_at <= moment)
        )
        return list(result.scalars())

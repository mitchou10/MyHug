from fastapi import UploadFile

from app.config import settings
from app.services.dataset_versions import NamedUpload
from app.services.errors import FileTooLarge, InvalidFilePath, TooManyAttachments, TooManyFiles
from app.services.uploads import Upload


async def read_uploads(files: list[UploadFile] | None) -> list[Upload]:
    """The files of a request, read, never more than the limit per file (a huge one must not end up in memory)."""
    files = files or []
    if len(files) > settings.FEEDBACK_MAX_ATTACHMENTS:
        raise TooManyAttachments
    return [
        Upload(filename=file.filename or "", data=await file.read(settings.FEEDBACK_ATTACHMENT_MAX_BYTES + 1))
        for file in files
    ]


async def read_dataset_files(files: list[UploadFile] | None, paths: list[str] | None) -> list[NamedUpload]:
    """The files of a new version, read, with the path each one has in the dataset: the one sent beside it, or its name.

    Never more than the limit per file: a huge one must not end up in memory."""
    files = files or []
    if len(files) > settings.DATASET_VERSION_MAX_FILES:
        raise TooManyFiles
    if paths and len(paths) != len(files):
        raise InvalidFilePath("Send one path for each file, or none")
    uploads = []
    for index, file in enumerate(files):
        data = await file.read(settings.DATASET_FILE_MAX_BYTES + 1)
        if len(data) > settings.DATASET_FILE_MAX_BYTES:
            raise FileTooLarge
        uploads.append(NamedUpload(path=paths[index] if paths else (file.filename or ""), data=data))
    return uploads

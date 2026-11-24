import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.repositories.datasets import DatasetRow
from app.services.dataset_uploads import UploadView
from app.services.dataset_versions import RowsPage, SplitInfo
from app.services.datasets import DatasetView

Modality = Literal["text", "image", "audio", "video", "tabular", "timeseries"]
Visibility = Literal["public", "private"]
# What can be in an address: lowercase letters, digits, dots, dashes and underscores, starting with a letter or a digit.
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]*$", min_length=1, max_length=100)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=50)]


def _distinct(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tags))


class DatasetIn(BaseModel):
    """A dataset to create. Its address is `{your name}/{name}`; the name and the modality can never be changed."""

    name: Slug
    description: str = Field("", max_length=1000)
    modality: Modality
    language: str = Field("", max_length=50)
    license: str = Field("", max_length=100)
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    visibility: Visibility = "public"
    card: str = Field("", max_length=100_000)

    _distinct_tags = field_validator("tags")(_distinct)


class DatasetChange(BaseModel):
    """What to change: the fields that are not sent stay as they are, and at least one is needed."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(None, max_length=1000)
    language: str | None = Field(None, max_length=50)
    license: str | None = Field(None, max_length=100)
    tags: list[Tag] | None = Field(None, max_length=20)
    visibility: Visibility | None = None
    card: str | None = Field(None, max_length=100_000)

    _distinct_tags = field_validator("tags")(lambda tags: None if tags is None else _distinct(tags))

    @model_validator(mode="after")
    def something_to_change(self) -> "DatasetChange":
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("A field that is sent cannot be null")
        return self


class DatasetSummaryOut(BaseModel):
    """A line of the list: no card."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner: str
    name: str
    description: str
    modality: Modality
    language: str
    license: str
    tags: list[str]
    visibility: Visibility
    downloads: int
    likes: int = Field(validation_alias="likes_count")
    liked: bool = False
    # What the latest version holds: 0 for a dataset with no file. `rows` is None until a worker has read the files.
    version: int
    rows: int | None
    size_bytes: int
    created_by: str
    created_by_username: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: DatasetRow) -> "DatasetSummaryOut":
        return cls.model_validate(row.dataset).model_copy(update={"liked": row.liked})


class DatasetOut(DatasetSummaryOut):
    card: str
    # Whether the person who asks may change or delete it.
    can_edit: bool = False
    # Where the latest version is: `pending`, `processing`, `ready` or `failed`; None for a dataset without files.
    processing: str | None = None
    splits: list["SplitOut"] = Field(default_factory=list)
    columns: list["ColumnOut"] = Field(default_factory=list)

    @classmethod
    def from_view(cls, view: DatasetView) -> "DatasetOut":
        return cls.model_validate(view.dataset).model_copy(
            update={
                "liked": view.liked,
                "can_edit": view.can_edit,
                "splits": [SplitOut.from_info(info) for info in view.splits],
                "columns": [ColumnOut(**column) for column in view.columns],
                "processing": view.processing,
            }
        )


class SplitOut(BaseModel):
    name: str
    rows: int
    files: int

    @classmethod
    def from_info(cls, info: SplitInfo) -> "SplitOut":
        return cls(name=info.name, rows=info.rows, files=info.files)


class ColumnOut(BaseModel):
    name: str
    dtype: str


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path: str
    size_bytes: int
    # None until a worker has read a file that came in parts.
    sha256: str | None
    content_type: str
    # Only the files that hold rows (csv, tsv, jsonl, parquet) have a split and a number of rows.
    split: str | None
    rows: int | None


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    # `pending` until a worker has read the files, then `ready` (or `failed`, and `error` says why).
    status: str
    error: str | None
    rows: int | None
    size_bytes: int
    message: str
    created_by: str
    created_by_username: str
    created_at: datetime
    columns: list[ColumnOut]


class RowsOut(BaseModel):
    """A page of the rows of a split, in the order of the columns."""

    split: str
    splits: list[str]
    columns: list[ColumnOut]
    rows: list[list[Any]]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: RowsPage, limit: int, offset: int) -> "RowsOut":
        return cls(
            split=page.split,
            splits=page.splits,
            columns=[ColumnOut(name=c.name, dtype=c.dtype) for c in page.columns],
            rows=page.rows,
            total=page.total,
            limit=limit,
            offset=offset,
        )


class LikeOut(BaseModel):
    liked: bool
    likes: int


class UploadFileIn(BaseModel):
    """A file the browser is going to send."""

    path: str = Field(max_length=512)
    size: int = Field(gt=0, description="Its size in bytes")
    content_type: str | None = Field(None, max_length=100)
    sha256: str | None = Field(
        None,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="Its fingerprint, if the browser knows it: a file the dataset already holds is not sent again",
    )

    @field_validator("sha256")
    @classmethod
    def _lowercase(cls, value: str | None) -> str | None:
        return value.lower() if value else value


class UploadIn(BaseModel):
    """The files of a version, announced before they are sent. `remove` takes paths out in the same version."""

    files: list[UploadFileIn] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list, max_length=1000)
    message: str = Field("", max_length=500)


class PartOut(BaseModel):
    number: int
    size: int


class UploadFileOut(BaseModel):
    id: uuid.UUID
    path: str
    size_bytes: int
    # The browser cuts the file in parts of this size (the last one is shorter) and numbers them from 1.
    part_size: int
    parts_count: int
    # True when the dataset already holds exactly this file: nothing is sent (no parts), and `complete` is enough.
    already_stored: bool = False
    # The parts that reached the storage: only when asked for, to resume.
    received: list[PartOut] | None = None


class UploadOut(BaseModel):
    id: uuid.UUID
    status: str
    expires_at: datetime
    version: int | None = Field(None, description="The version it made, once it is complete")
    files: list[UploadFileOut]

    @classmethod
    def from_view(cls, view: "UploadView", version: int | None = None) -> "UploadOut":
        return cls(
            id=view.upload.id,
            status=view.upload.status,
            expires_at=view.upload.expires_at,
            version=version,
            files=[
                UploadFileOut(
                    id=file.id,
                    path=file.path,
                    size_bytes=file.size_bytes,
                    part_size=file.part_size,
                    parts_count=file.parts_count,
                    already_stored=file.already_stored,
                    received=None
                    if view.received is None
                    else [PartOut(number=p.number, size=p.size) for p in view.received[file.id]],
                )
                for file in view.files
            ],
        )


class PartsIn(BaseModel):
    file_id: uuid.UUID
    numbers: list[int] = Field(min_length=1, max_length=100, description="The numbers of the parts, from 1")


class SignedPartOut(BaseModel):
    number: int
    # Where to send the part, with PUT and the bytes of the part as the body. Nothing else is needed: it is signed.
    url: str


class PartsOut(BaseModel):
    parts: list[SignedPartOut]
    expires_in: int

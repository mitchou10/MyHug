import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.models import ModelFile
from app.repositories.models import ModelRow
from app.schemas.dataset import Modality, Slug, Tag, UploadFileIn, Visibility, _distinct
from app.services.model_versions import VersionView
from app.services.models import ModelView

# What a model can do: the kinds of annotation task, the same as the datasets have.
Task = Literal[
    "classification",
    "ner",
    "qa",
    "regression",
    "row_label",
    "cell_review",
    "column_schema",
    "image_detection",
    "image_segmentation",
    "image_polyline",
    "image_keypoints",
    "image_classification",
    "image_caption",
    "image_vqa",
    "audio_classification",
    "audio_segments",
    "audio_transcription",
    "audio_caption",
    "video_classification",
    "video_segments",
    "video_tracking",
    "video_caption",
    "timeseries_classification",
    "timeseries_segments",
    "timeseries_caption",
]
Role = Literal["reader", "maintainer"]
Library = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]
Language = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
# The address of a dataset: `owner/name`.
DatasetAddress = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$", max_length=201)
]


class ModelIn(BaseModel):
    """A model to create. Its address is `{your name}/{name}`; the name, tasks and inputs can never be changed."""

    name: Slug
    description: str = Field("", max_length=1000)
    tasks: list[Task] = Field(min_length=1, max_length=10)
    inputs: list[Modality] = Field(min_length=1, max_length=6)
    library: Library = ""
    languages: list[Language] = Field(default_factory=list, max_length=50)
    license: str = Field("", max_length=100)
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    visibility: Visibility = "public"
    card: str = Field("", max_length=100_000)
    code_url: str | None = Field(None, max_length=512, description="A GitHub or GitLab address")
    parameters: int | None = Field(None, ge=0)
    trained_on: list[DatasetAddress] = Field(default_factory=list, max_length=50)

    _distinct_all = field_validator("tasks", "inputs", "languages", "tags", "trained_on")(_distinct)


class ModelChange(BaseModel):
    """What to change: the fields that are not sent stay as they are, and at least one is needed. `code_url` and
    `parameters` can be sent as null to take them off."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(None, max_length=1000)
    library: Library | None = None
    languages: list[Language] | None = Field(None, max_length=50)
    license: str | None = Field(None, max_length=100)
    tags: list[Tag] | None = Field(None, max_length=20)
    visibility: Visibility | None = None
    card: str | None = Field(None, max_length=100_000)
    code_url: str | None = Field(None, max_length=512)
    parameters: int | None = Field(None, ge=0)
    trained_on: list[DatasetAddress] | None = Field(None, max_length=50)

    _distinct_all = field_validator("languages", "tags", "trained_on")(lambda v: None if v is None else _distinct(v))

    @model_validator(mode="after")
    def something_to_change(self) -> "ModelChange":
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        if any(getattr(self, field) is None for field in self.model_fields_set - {"code_url", "parameters"}):
            raise ValueError("A field that is sent cannot be null")
        return self


class ModelSummaryOut(BaseModel):
    """A line of the list: no card."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner: str
    name: str
    description: str
    tasks: list[str]
    inputs: list[str]
    library: str
    languages: list[str]
    license: str
    tags: list[str]
    visibility: Visibility
    code_url: str | None
    parameters: int | None
    trained_on: list[str]
    downloads: int
    likes: int = Field(validation_alias="likes_count")
    liked: bool = False
    # What the latest version holds: 0 for a model with no version.
    version: int
    size_bytes: int
    created_by: str
    created_by_username: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: ModelRow) -> "ModelSummaryOut":
        return cls.model_validate(row.model).model_copy(update={"liked": row.liked})


class ModelOut(ModelSummaryOut):
    card: str
    # Whether the person who asks may change or delete it.
    can_edit: bool = False
    # The page of the model in MLflow. Not in the answer at all (not even null) unless the person may edit the model and
    # MLflow knows something of it.
    mlflow_url: str | None = Field(None, exclude_if=lambda value: value is None)

    @classmethod
    def from_view(cls, view: ModelView) -> "ModelOut":
        return cls.model_validate(view.model).model_copy(
            update={"liked": view.liked, "can_edit": view.can_edit, "mlflow_url": view.mlflow_url}
        )


class MemberIn(BaseModel):
    role: Role


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    role: Role
    added_by: str
    created_at: datetime


class CodeIn(BaseModel):
    """The code a version points to: a repository on an allowed host (GitHub, GitLab), and where to start in it. Only a
    link: nothing is fetched or cloned when it is sent."""

    url: str = Field(max_length=512, description="`https://github.com/{owner}/{repository}`")
    ref: str | None = Field(None, max_length=255, description="A commit, a tag or a branch")
    ref_kind: Literal["commit", "tag", "branch", "unknown"] | None = Field(
        None, description="A commit is recognised by itself; a tag and a branch cannot be told apart"
    )
    path: str | None = Field(None, max_length=512, description="A folder of the repository")
    entrypoint: str | None = Field(None, max_length=512, description="The file that runs the model, `src/predict.py`")


class CodeOut(BaseModel):
    """The code reference as it was written, and what a worker found of it."""

    url: str
    ref: str | None
    ref_kind: str
    path: str | None
    entrypoint: str | None
    # The commit it was pinned to, once it is: never changed afterwards (a new commit makes a new version).
    sha: str | None
    # `unresolved` (not looked at yet), `resolving`, `pinned`, `unverified` (private or not found), `failed`.
    state: str
    error: str | None


class ModelUploadIn(BaseModel):
    """The files of a version, announced before they are sent. `remove` takes paths out in the same version."""

    files: list[UploadFileIn] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list, max_length=1000)
    message: str = Field("", max_length=500)
    code: CodeIn | None = None


class CodeVersionIn(BaseModel):
    """A version that is only a link to the code."""

    code: CodeIn
    message: str = Field("", max_length=500)


class ModelFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path: str
    size_bytes: int
    # None until a worker has read a file that came in parts.
    sha256: str | None
    content_type: str


class ModelVersionOut(BaseModel):
    number: int
    # `pending` until a worker has read the files, then `ready` (or `failed`, and `error` says why).
    status: str
    error: str | None
    size_bytes: int
    message: str
    # Whether MLflow can serve it (it has a flavor): a model that is only files is stored and downloaded, not served.
    servable: bool
    # None for a version that has no code reference.
    code: CodeOut | None
    created_by: str
    created_by_username: str
    created_at: datetime
    # The page of the version in MLflow. Not in the answer at all (not even null) unless the person may edit the model
    # and MLflow knows the version.
    mlflow_url: str | None = Field(None, exclude_if=lambda value: value is None)

    @classmethod
    def from_view(cls, view: VersionView) -> "ModelVersionOut":
        version = view.version
        code = (
            CodeOut(
                url=version.code_url,
                ref=version.code_ref,
                ref_kind=version.code_ref_kind,
                path=version.code_path,
                entrypoint=version.entrypoint,
                sha=version.code_sha,
                state=version.code_state,
                error=version.code_error,
            )
            if version.code_url
            else None
        )
        return cls(
            number=version.number,
            status=version.status,
            error=version.error,
            size_bytes=version.size_bytes,
            message=version.message,
            servable=version.servable,
            code=code,
            created_by=version.created_by,
            created_by_username=version.created_by_username,
            created_at=version.created_at,
            mlflow_url=view.mlflow_url,
        )


class ModelVersionDetailOut(ModelVersionOut):
    files: list[ModelFileOut]

    @classmethod
    def from_files(cls, view: VersionView, files: list[ModelFile]) -> "ModelVersionDetailOut":
        return cls(
            **ModelVersionOut.from_view(view).model_dump(), files=[ModelFileOut.model_validate(f) for f in files]
        )

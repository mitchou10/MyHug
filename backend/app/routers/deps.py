"""How the services are built for a request. The only place that wires a database session and a store together."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.config import settings
from app.db import get_db
from app.jobs import CeleryJobs, Jobs, NoJobs
from app.registry import MlflowLinks, ModelRegistry, NoRegistry, get_links, get_registry
from app.repositories.access_tokens import AccessTokenRepository
from app.repositories.feedback import FeedbackRepository
from app.repositories.feedback_attachments import FeedbackAttachmentRepository
from app.repositories.feedback_messages import FeedbackMessageRepository
from app.repositories.feedback_statuses import FeedbackStatusRepository
from app.repositories.feedback_types import FeedbackTypeRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.user_profile import UserProfileRepository
from app.services.access import FeedbackAccess
from app.services.access_tokens import AccessTokenService
from app.services.actor import Actor
from app.services.attachments import AttachmentService
from app.services.dataset_derivatives import DatasetDerivatives
from app.services.dataset_processing import DatasetProcessing
from app.services.dataset_uploads import DatasetUploadService
from app.services.dataset_versions import DatasetVersionService
from app.services.datasets import DatasetService
from app.services.factory import (
    build_dataset_derivatives,
    build_dataset_processing,
    build_dataset_uploads,
    build_dataset_versions,
    build_datasets,
    build_model_code,
    build_model_members,
    build_model_processing,
    build_model_serving,
    build_model_uploads,
    build_model_versions,
    build_models,
    build_storage_garbage,
)
from app.services.feedback import FeedbackService
from app.services.feedback_statuses import FeedbackStatusService
from app.services.feedback_types import FeedbackTypeService
from app.services.messages import MessageService
from app.services.model_code import ModelCodeResolution
from app.services.model_members import ModelMemberService
from app.services.model_processing import ModelProcessing
from app.services.model_serving import ModelServingService
from app.services.model_uploads import ModelUploadService
from app.services.model_versions import ModelVersionService
from app.services.models import ModelService
from app.services.notifications import NotificationService
from app.services.profile import ProfileService
from app.services.storage_garbage import StorageGarbage
from app.services.workflow import FeedbackWorkflow
from app.serving import RateLimiter, ServingClient, get_rate_limiter, get_serving_client
from app.storage import ObjectStore, get_store


def get_profile_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    store: Annotated[ObjectStore, Depends(get_store)],
) -> ProfileService:
    return ProfileService(UserProfileRepository(db), store, settings.AVATAR_MAX_BYTES)


ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


def get_actor(user: CurrentUser) -> Actor:
    """The logged-in user as the services see them. The name falls back on what the provider gives."""
    return Actor(user_id=user.user_id, username=user.username or user.name or user.user_id, is_admin=user.is_admin)


ActorDep = Annotated[Actor, Depends(get_actor)]


def get_type_service(db: Annotated[AsyncSession, Depends(get_db)]) -> FeedbackTypeService:
    return FeedbackTypeService(FeedbackTypeRepository(db))


def get_status_service(db: Annotated[AsyncSession, Depends(get_db)]) -> FeedbackStatusService:
    return FeedbackStatusService(FeedbackStatusRepository(db))


TypeServiceDep = Annotated[FeedbackTypeService, Depends(get_type_service)]
StatusServiceDep = Annotated[FeedbackStatusService, Depends(get_status_service)]


DB = Annotated[AsyncSession, Depends(get_db)]
Store = Annotated[ObjectStore, Depends(get_store)]


def _attachments(db: AsyncSession, store: ObjectStore) -> AttachmentService:
    return AttachmentService(
        FeedbackAttachmentRepository(db),
        store,
        max_files=settings.FEEDBACK_MAX_ATTACHMENTS,
        max_bytes=settings.FEEDBACK_ATTACHMENT_MAX_BYTES,
    )


def get_feedback_service(db: DB, store: Store) -> FeedbackService:
    feedbacks = FeedbackRepository(db)
    return FeedbackService(
        feedbacks,
        FeedbackAccess(feedbacks),
        FeedbackTypeService(FeedbackTypeRepository(db)),
        FeedbackStatusService(FeedbackStatusRepository(db)),
        _attachments(db, store),
    )


def get_workflow(db: DB) -> FeedbackWorkflow:
    feedbacks = FeedbackRepository(db)
    return FeedbackWorkflow(
        FeedbackAccess(feedbacks),
        feedbacks,
        FeedbackMessageRepository(db),
        FeedbackTypeService(FeedbackTypeRepository(db)),
        FeedbackStatusService(FeedbackStatusRepository(db)),
    )


def get_message_service(db: DB, store: Store) -> MessageService:
    return MessageService(
        FeedbackAccess(FeedbackRepository(db)), FeedbackMessageRepository(db), _attachments(db, store)
    )


FeedbackServiceDep = Annotated[FeedbackService, Depends(get_feedback_service)]
WorkflowDep = Annotated[FeedbackWorkflow, Depends(get_workflow)]
MessageServiceDep = Annotated[MessageService, Depends(get_message_service)]


def get_access_token_service(db: DB) -> AccessTokenService:
    return AccessTokenService(AccessTokenRepository(db))


AccessTokenServiceDep = Annotated[AccessTokenService, Depends(get_access_token_service)]


def get_notification_service(db: DB) -> NotificationService:
    return NotificationService(NotificationRepository(db))


NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


def get_jobs() -> Jobs:
    return CeleryJobs()


JobsDep = Annotated[Jobs, Depends(get_jobs)]


def get_dataset_service(db: DB, store: Store) -> DatasetService:
    return build_datasets(db, store)


def get_dataset_version_service(db: DB, store: Store, jobs: JobsDep) -> DatasetVersionService:
    return build_dataset_versions(db, store, jobs)


def get_dataset_upload_service(db: DB, store: Store, jobs: JobsDep) -> DatasetUploadService:
    return build_dataset_uploads(db, store, jobs)


DatasetServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]
DatasetVersionServiceDep = Annotated[DatasetVersionService, Depends(get_dataset_version_service)]
DatasetUploadServiceDep = Annotated[DatasetUploadService, Depends(get_dataset_upload_service)]


def get_dataset_processing(db: DB, store: Store, jobs: JobsDep) -> DatasetProcessing:
    return build_dataset_processing(db, store, jobs)


def get_dataset_derivatives(db: DB, store: Store) -> DatasetDerivatives:
    return build_dataset_derivatives(db, store)


def get_upload_expiry(db: DB, store: Store) -> DatasetUploadService:
    return build_dataset_uploads(db, store, NoJobs())


DatasetProcessingDep = Annotated[DatasetProcessing, Depends(get_dataset_processing)]
UploadExpiryDep = Annotated[DatasetUploadService, Depends(get_upload_expiry)]
DatasetDerivativesDep = Annotated[DatasetDerivatives, Depends(get_dataset_derivatives)]


def get_storage_garbage(db: DB, store: Store) -> StorageGarbage:
    return build_storage_garbage(db, store)


StorageGarbageDep = Annotated[StorageGarbage, Depends(get_storage_garbage)]


RegistryDep = Annotated[ModelRegistry, Depends(get_registry)]
LinksDep = Annotated[MlflowLinks, Depends(get_links)]


def get_model_service(db: DB, store: Store, registry: RegistryDep, links: LinksDep) -> ModelService:
    return build_models(db, store, registry, links)


def get_model_member_service(db: DB) -> ModelMemberService:
    return build_model_members(db)


ModelServiceDep = Annotated[ModelService, Depends(get_model_service)]
ModelMemberServiceDep = Annotated[ModelMemberService, Depends(get_model_member_service)]


def get_model_version_service(
    db: DB, store: Store, registry: RegistryDep, links: LinksDep, jobs: JobsDep
) -> ModelVersionService:
    return build_model_versions(db, store, registry, links, jobs)


def get_model_upload_service(
    db: DB, store: Store, registry: RegistryDep, links: LinksDep, jobs: JobsDep
) -> ModelUploadService:
    return build_model_uploads(db, store, registry, links, jobs)


ModelVersionServiceDep = Annotated[ModelVersionService, Depends(get_model_version_service)]
ModelUploadServiceDep = Annotated[ModelUploadService, Depends(get_model_upload_service)]


def get_model_upload_expiry(db: DB, store: Store) -> ModelUploadService:
    """Giving up the uploads that took too long needs no MLflow."""
    return build_model_uploads(db, store, NoRegistry(), MlflowLinks(""))  # ty: ignore[invalid-argument-type]


ModelUploadExpiryDep = Annotated[ModelUploadService, Depends(get_model_upload_expiry)]


def get_model_processing(db: DB, store: Store) -> ModelProcessing:
    return build_model_processing(db, store)


ModelProcessingDep = Annotated[ModelProcessing, Depends(get_model_processing)]


def get_model_code(db: DB) -> ModelCodeResolution:
    return build_model_code(db)


ModelCodeDep = Annotated[ModelCodeResolution, Depends(get_model_code)]


def get_model_serving(
    db: DB,
    client: Annotated[ServingClient, Depends(get_serving_client)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> ModelServingService:
    return build_model_serving(db, client, limiter)


ModelServingDep = Annotated[ModelServingService, Depends(get_model_serving)]

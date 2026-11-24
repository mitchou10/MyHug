from app.config import settings
from app.registry.base import ModelRegistry, RegistryArtifact, RegistryRun, RegistryVersion
from app.registry.links import MlflowLinks
from app.registry.mlflow import MlflowRegistry
from app.registry.names import registered_name, split_registered_name
from app.services.errors import RegistryUnavailable


class NoRegistry:
    """What the models use when no MLflow is configured: every call says the service is not available."""

    def __getattr__(self, name: str):
        async def unavailable(*_, **__):
            raise RegistryUnavailable("The models service is not configured")

        return unavailable


def get_registry() -> ModelRegistry:
    """The registry of the models, from the settings. Used as a FastAPI dependency; tests replace it."""
    if not settings.MLFLOW_TRACKING_URI:
        return NoRegistry()  # ty: ignore[invalid-explicit-return]
    return MlflowRegistry(
        settings.MLFLOW_TRACKING_URI,
        api_key=settings.MLFLOW_API_KEY,
        timeout=settings.MLFLOW_TIMEOUT_SECONDS,
        artifacts_prefix=settings.MLFLOW_ARTIFACTS_PREFIX,
    )


def get_links() -> MlflowLinks:
    return MlflowLinks(settings.MLFLOW_PUBLIC_URL)


__all__ = [
    "MlflowLinks",
    "MlflowRegistry",
    "ModelRegistry",
    "NoRegistry",
    "RegistryArtifact",
    "RegistryRun",
    "RegistryVersion",
    "get_links",
    "get_registry",
    "registered_name",
    "split_registered_name",
]

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")

    APP_NAME: str = "app"

    # PostgreSQL, through asyncpg.
    DATABASE_URL: str = "postgresql+asyncpg://app:app@localhost:5432/app"

    # Object storage: RustFS here, any S3-compatible service works. The usual AWS_* variables, like the SDKs read them.
    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    # The address of the same storage as the browser reaches it, for the signed addresses of uploads and downloads.
    # Empty: the same as AWS_ENDPOINT_URL (when the browser and the API see the storage at the same address).
    AWS_PUBLIC_ENDPOINT_URL: str = ""
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_REGION: str = "us-east-1"
    AWS_BUCKET: str = "app"
    AVATAR_MAX_BYTES: int = 2 * 1024 * 1024

    # Feedback: the screenshots of a feedback or of an answer, and the biggest page a list can ask for.
    FEEDBACK_MAX_ATTACHMENTS: int = 5
    FEEDBACK_ATTACHMENT_MAX_BYTES: int = 5 * 1024 * 1024
    PAGE_SIZE_MAX: int = 50
    # The files of a dataset come through the API for now, so each one is read in memory: bigger ones will go
    # straight to the storage with a signed address.
    DATASET_FILE_MAX_BYTES: int = 100 * 1024 * 1024
    DATASET_VERSION_MAX_FILES: int = 100
    # An upload goes straight from the browser to the storage, in parts, each one with its own signed address.
    DATASET_UPLOAD_MAX_BYTES: int = 50 * 1024**3
    UPLOAD_PART_BYTES: int = 64 * 1024**2  # the size of a part, unless the file is so large that it needs bigger ones
    UPLOAD_SESSION_HOURS: int = 24  # how long an upload can take before it is given up
    SIGNED_ADDRESS_SECONDS: int = 3600

    # The worker is a service of its own (see `worker/`): the API queues jobs for it in Redis, by the name of the task,
    # the worker calls back `/api/internal` with this key (16 characters at least; empty: it is refused).
    REDIS_URL: str = "redis://localhost:6379/0"
    WORKER_API_KEY: str = ""
    # A version being read for longer than this is taken to belong to a worker that died: another one takes it over.
    PROCESSING_STALE_MINUTES: int = 30
    # How many times a version is taken in hand before it is given up as failed.
    PROCESSING_MAX_ATTEMPTS: int = 3

    # MLflow keeps the versions and the artifacts of the models. It has no login of its own and is never published: only
    # the backend calls it, from inside the compose. Empty address: the models are not available. The key, if a proxy in
    # front of MLflow asks for one, is sent as a bearer token.
    MLFLOW_TRACKING_URI: str = ""
    MLFLOW_API_KEY: str = ""
    MLFLOW_TIMEOUT_SECONDS: float = 30.0
    # Where MLflow keeps its artifacts in the bucket (its `--artifacts-destination`): the key of an artifact is this
    # prefix followed by its path in MLflow.
    MLFLOW_ARTIFACTS_PREFIX: str = "mlflow/"
    # Where a person opens MLflow to see the detail of a model (its runs, metrics, artifacts). The platform links there,
    # **only for the people who can edit the model**: MLflow has no rights of its own, whoever reaches it can change
    # everything. In production it must be behind a proxy that signs people in. Empty: no link.
    MLFLOW_PUBLIC_URL: str = ""
    # The hosts the code of a model may be linked at. The platform never clones or runs that code: it keeps the link.
    MODEL_CODE_HOSTS: list[str] = ["github.com", "gitlab.com"]

    # A tabular file (csv, tsv, jsonl) at least this big gets a copy in Parquet, made by the worker: below it the copy
    # would gain nothing. A source over the maximum is left as it is.
    DERIVATIVE_MIN_BYTES: int = 8 * 1024**2
    DERIVATIVE_MAX_SOURCE_BYTES: int = 20 * 1024**3
    DERIVATIVE_PART_BYTES: int = 16 * 1024**2  # the size of the parts the worker sends the copy in

    # The collector of the objects that nothing points to (the worker asks for it every day). It starts as a dry run: it
    # says what it would delete, and deletes nothing, until STORAGE_GC_DRY_RUN is turned off.
    STORAGE_GC_ENABLED: bool = True
    STORAGE_GC_DRY_RUN: bool = True
    # An object younger than this is never touched. 0: the length of an upload session plus 12 hours, so that an
    # object waiting for its row to be committed is never taken for garbage. Never less than that.
    STORAGE_GC_GRACE_HOURS: int = 0
    STORAGE_GC_MAX_SCANNED: int = 20_000  # objects looked at in one pass
    STORAGE_GC_MAX_DELETIONS: int = 5_000  # objects deleted in one pass
    STORAGE_GC_CHECK_ROWS: int = 200  # files of versions whose object is checked to be there, in the first pass

    # Notifications: the applications allowed to emit them, as `name=key` pairs separated by commas. The name becomes
    # the `source` of what they emit; a key shorter than 16 characters is ignored. Empty: nobody can emit.
    NOTIFICATION_API_KEYS: str = ""

    # "oidc": real authentication. "full-access": no identity provider, a fixed dev identity for every request
    # (local development without Keycloak, unit tests).
    AUTH_MODE: Literal["oidc", "full-access"] = "oidc"

    # OpenID Connect. Any compliant provider works (Keycloak, Entra ID, Auth0, Dex...): no code depends on one.
    OIDC_ISSUER: str = ""
    # Where to fetch the discovery document when the provider is not reached on its public address (Docker name,
    # internal URL...). Defaults to <issuer>/.well-known/openid-configuration.
    OIDC_DISCOVERY_URL: str = ""
    OIDC_CLIENT_ID: str = "app-backend"
    OIDC_CLIENT_SECRET: str = ""
    OIDC_SCOPES: str = "openid profile email"
    # Where the roles and groups are in the claims. Dotted path for nested claims: Keycloak puts the realm roles in
    # `realm_access.roles`, other providers use a flat `roles` or `groups`.
    OIDC_ROLES_CLAIM: str = "roles"
    OIDC_GROUPS_CLAIM: str = "groups"
    OIDC_ADMIN_ROLE: str = "admin"

    # Server-side session: the browser only holds an opaque id in an HttpOnly cookie.
    SESSION_COOKIE_NAME: str = "session"
    SESSION_COOKIE_SECURE: bool = True  # turned off for plain-HTTP local development
    SESSION_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    SESSION_TTL_SECONDS: int = 8 * 3600
    # Signs the short-lived cookie that carries state/PKCE during the login redirect.
    LOGIN_STATE_SECRET: str = "dev-only-secret-not-for-prod"

    # Public URL the browser uses to reach the backend: builds the redirect_uri to register in the provider
    # ({BACKEND_PUBLIC_URL}/api/auth/callback). Where the browser lands after login/logout.
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:5173"

    @property
    def discovery_url(self) -> str:
        return self.OIDC_DISCOVERY_URL or f"{self.OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration"

    @property
    def notification_emitters(self) -> dict[str, str]:
        """The key of each emitter, and its name: `{"the-key": "billing"}`."""
        pairs = (pair.partition("=") for pair in self.NOTIFICATION_API_KEYS.split(",") if pair.strip())
        return {key.strip(): name.strip() for name, _, key in pairs if name.strip() and len(key.strip()) >= 16}

    @property
    def callback_url(self) -> str:
        return f"{self.BACKEND_PUBLIC_URL.rstrip('/')}/api/auth/callback"


settings = Settings()

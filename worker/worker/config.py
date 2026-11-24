from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Where the jobs wait (the API puts them there, by the name of the task).
    REDIS_URL: str = "redis://localhost:6379/0"
    # The API of the platform, and the key that tells it who is calling (the same as its `WORKER_API_KEY`).
    BACKEND_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""
    # Where a file is kept while it is read (empty: the system's temporary folder): room for the largest one.
    WORKER_TEMP_DIR: str = ""
    # The Parquet copies: how many rows go in a row group (what a page of the preview reads), and the most memory a
    # batch of rows may take before it is written, whatever the number of rows (a cell can be a whole text).
    ROW_GROUP_ROWS: int = 50_000
    BATCH_BYTES: int = 64 * 1024**2
    # Pinning the code of a model: the hosts the worker may call (the same list as the API's `MODEL_CODE_HOSTS`: an
    # entry is `host`, or `host:port` for another port than 443), a token per host to raise the rate limit of public
    # lookups (JSON: {"github.com": "..."}), how long a host is waited for, and the most it may answer. A host that
    # resolves to a private address is refused, unless it is named in CODE_PRIVATE_HOSTS (a GitLab inside the company
    # network).
    CODE_HOSTS: list[str] = ["github.com", "gitlab.com"]
    CODE_TOKENS: dict[str, str] = {}
    CODE_PRIVATE_HOSTS: list[str] = []
    CODE_TIMEOUT_SECONDS: float = 15.0
    CODE_MAX_ANSWER_BYTES: int = 1024 * 1024
    # How many lookups a minute one worker makes (the public APIs limit the calls that have no token).
    CODE_RATE_LIMIT: str = "30/m"
    # How long the API, or the storage, is waited for.
    HTTP_TIMEOUT_SECONDS: float = 60.0
    # How often the safety nets run: queue the versions that nobody reads, give up the abandoned uploads.
    SWEEP_SECONDS: float = 60.0
    EXPIRE_UPLOADS_SECONDS: float = 15 * 60.0
    # How often the objects that nothing points to are collected (the backend decides what, and whether to delete),
    # and the most passes of one collection: each pass is bounded on the backend and goes on from where it stopped.
    COLLECT_STORAGE_SECONDS: float = 24 * 3600.0
    COLLECT_MAX_PASSES: int = 200


settings = Settings()

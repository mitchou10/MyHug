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

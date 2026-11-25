# myhug

The Python SDK of the platform: datasets and models from code, with transfers that resume. It is versioned and tagged
with the rest of the repository but not published anywhere (no PyPI): install it from the repository,
`uv pip install ./sdk`.

```python
from myhug import Client

with Client("https://myhug.example", token="mh_...") as client:  # or MYHUG_URL and MYHUG_TOKEN
    for dataset in client.datasets.list(q="sentiment"):
        print(dataset.owner, dataset.name, dataset.rows)
    for model in client.models.list(task="ner"):
        print(model.owner, model.name, model.version)
```

`AsyncClient` is the same for asyncio (`async with AsyncClient(...)`, `async for ... in client.datasets.list()`).

A token is made on the *Access tokens* page of the app. It acts as you, with your rights on the data, `read` or
`write`, never as an administrator. It is sent over HTTPS only (or to `localhost`): `allow_insecure=True` is for a
network you trust.

## What the core does

- **Errors are exceptions** (`myhug.errors`): `AuthenticationError`, `PermissionDenied`, `NotFound`, `Conflict`,
  `Invalid`, `RateLimited` (with `retry_after`), `ServerError`... all `ApiError` with the `status_code` and the sentence
  of the API. None holds the token, a header or a signed address.
- **Retries**: a read, a put or a delete is tried again (3 times, 0.5 s, 1 s, 2 s with jitter, or what `Retry-After`
  says, 30 s at most) when the server is busy (429, 502, 503, 504) or cannot be reached. A POST is never tried again by
  itself.
- **Lists** come in pages and are read as the loop goes.
- **Two HTTP clients**: one for the API (with the token), one for the storage (the signed addresses the API gives):
  the token never goes to the storage.
- **Uploads** (`myhug/_upload.py`): announce, send each part straight to the storage (3 at a time, each with its own
  signed address, 3 tries), complete. The id of an unfinished upload is kept in `~/.cache/myhug/uploads` (or
  `MYHUG_CACHE`): run the same call again and only the parts that are not in the storage are sent. A file the platform
  already holds (same SHA-256) is not sent.
- **Downloads** (`myhug/_download.py`): the API answers with a redirection to a signed address; the bytes are streamed
  to a `.part` file, resumed with `Range` if it was interrupted, checked against the size and the SHA-256 before they
  are kept, and a file with a fingerprint the machine already holds is not fetched again (`~/.cache/myhug/blobs`).

The models of what the API sends (`myhug/_models.py`) are generated from `openapi.json` at the root of the repository:

```bash
uv run python scripts/generate.py          # after the API changed (and `backend/scripts/export_openapi.py`)
uv run python scripts/generate.py --check  # what CI runs
```

## Development

```bash
uv sync
uv run pytest --cov     # no network: the platform is in memory (tests/fake.py)
uv run ruff check . && uv run ruff format --check . && uv run ty check myhug
```

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

`AsyncClient` is the same for asyncio: `async with AsyncClient(...) as client`, `await client.datasets.get(...)`,
`async for row in dataset.iter_rows()`, `async with dataset.new_version() as v`. Everything below exists in both.

A token is made on the *Access tokens* page of the app. It acts as you, with your rights on the data, `read` or
`write`, never as an administrator. It is sent over HTTPS only (or to `localhost`): `allow_insecure=True` is for a
network you trust.

## Datasets

```python
dataset = client.datasets.get("ada/sentiment")  # or client.datasets.create("reviews", modality="text")
dataset.splits  # ['test', 'train']
dataset.files(split="train")  # the files of a split, with their fingerprints

# The raw files, with the path they have in the dataset (by default in ~/.cache/myhug).
dataset.download("data/", split="train")  # a split; or path="data/train.csv"; or everything
for row in dataset.iter_rows("train"):  # one dict by row, file after file
    ...
for row in dataset.iter_rows("train", streaming=True):  # read from the storage as it arrives, kept nowhere
    ...
```

`iter_rows` reads csv, tsv and jsonl, and Parquet with `pip install "myhug[parquet]"`. Cells are typed as the platform's
preview types them (a csv cell is the integer, the float or the boolean it looks like, an empty one is `None`).

- By default each file is downloaded first (and kept, so the next read is from disk).
- With `streaming=True` nothing is kept on disk. A table the platform has made a **copy in Parquet** of (the files with
  `columnar=True` in `dataset.files()`) is read from that copy by ranges, one group of rows at a time: the memory is a
  group, a file of any size works, and stopping early costs only what was read. Without a copy, a csv, tsv or jsonl file
  is read as text while it arrives. The copy is typed from every row of the file, so a column that mixes types is text
  there (the same as the preview of the platform).
- A Parquet file is read by ranges too when streaming, and downloaded first otherwise.

Who has access: `dataset.members()`, `dataset.set_member("user-id", "annotator")` (`reader`, `annotator`, `maintainer`),
`dataset.remove_member("user-id")`: only for the people who can edit the dataset.

A dataset is **never changed in place**: changing it makes a new version, which keeps everything the one before had
except what you add, replace or remove.

```python
with dataset.new_version(message="fix labels") as version:  # nothing is sent if the block raises
    version.add("train.csv", "data/train.csv")  # a file, and the path it will have
    version.remove("data/old.csv")
dataset.upload_file("README.md")  # one file, one version
dataset.upload_folder("my-data/", delete=True, wait=True)  # what the folder holds: only the difference is sent
dataset.wait()  # until the platform has read the files (VersionFailed if not)
```

`upload_folder` sends what is new or changed (same SHA-256 means the same file), takes out what the folder no longer has
only with `delete=True`, and makes **no version** when nothing changes (it returns `None`). `prefix="images"` keeps it to
one folder of the dataset. A `.git`, `.DS_Store`, `__pycache__` and `*.part` are not sent (`ignore=` changes that).

## Models

```python
model = client.models.create("ner", tasks=["ner"], inputs=["text"])
model.upload_version(
    ["model.safetensors"], code={"url": "https://github.com/me/ner", "ref": "main"}, message="v1", wait=True
)
model.upload_version(folder="checkpoint/")  # or only code=..., or remove=[...]
model.versions()
model.files()
model.download("out/")  # the latest version by default; version=3, path="config.json"
model.predict("Le tribunal de Lyon...")  # only if the model is served
```

A version is files, a reference to code, or both. The reference is only a link: the platform pins it to its exact commit
(`version.code.sha`, `version.code.state`).

## Evaluations

A model trained in a notebook is evaluated there; its result can be sent to the page of the model.

```python
# The platform defines the metrics of each task: ['accuracy', 'precision', 'recall', 'f1', 'auc'].
client.metrics.ids("classification")

model = client.models.get("me/ner")
model.submit_evaluation(
    "classification",
    {"accuracy": 0.91, "f1": 0.8},  # the metrics of the task, finite numbers
    dataset="me/reviews",
    split="test",
    items=1200,
    target_column="label",
    shown=["accuracy"],  # what the others see; the result keeps all of them
    note="5-fold cross-validation",  # how you got it
)

# The newest first. Also: model.evaluation(id), model.set_shown(id, [...]), model.delete_evaluation(id).
model.evaluations(task="classification")
```

- Only the people who can edit the model send a result (`PermissionDenied` for the others), for any of its versions (the
  latest unless `version=`).
- It is kept and shown as **sent**, never as measured: nothing says how it was obtained but your `note`.
- A value that is not a finite number (a boolean, a text, `nan`) is refused here, before anything is sent; a metric the
  task does not have, or a dataset you cannot read, is refused by the platform (`Invalid`).
- A POST is never repeated by itself: if the answer is lost, look at `model.evaluations()` before sending it again.
- A reader of the model gets only the metrics that were chosen, and `hidden` says how many are left out.

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

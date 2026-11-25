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

The platform publishes **no number it did not compute**. You run your model where you like and send its **predictions**;
a worker of the platform computes the metrics against the ground truth of the dataset.

```python
# The platform defines the metrics of each task: ['accuracy', 'precision', 'recall', 'f1', 'auc'].
client.metrics.ids("classification")

model = client.models.get("me/ner")
predictions = [my_model(text) for text in test_texts]  # one for each item of the split, in its order

evaluation = model.evaluate(
    "classification",
    predictions,  # or the path of a .jsonl, .csv or .parquet file
    dataset="me/reviews",
    split="test",
    target_column="label",  # the column of the dataset with the right answer
    key_column="id",  # a column that says which item a prediction is about (empty: the position)
    note="my model, temperature 0",
    inference_seconds=watch.seconds,  # with myhug.Stopwatch() as watch: predictions = [...]
    hardware=True,  # read this machine
    wait=True,  # until the worker has computed the metrics
)
evaluation.results  # {'accuracy': 0.91, ...}: what you are allowed to see, see below

# The newest first. Also: model.evaluation(id), model.set_shown(id, [...]), model.delete_evaluation(id).
model.evaluations(task="classification")
```

- **How long it took, and on what.** Say how long your model took and where it ran, so that models can be compared on
  their cost too: `inference_seconds=` (`with myhug.Stopwatch() as watch: predictions = [...]`, then `watch.seconds`) and
  `hardware=True` to read this machine (processor, cores, memory, NVIDIA cards, system; `myhug.hardware.detect()` shows
  what would be sent), or a dict of your own. Nothing about the machine is sent unless you ask. The page shows it as
  **declared**: the platform cannot check it, unlike the time and the energy it measures when it runs a model itself.
- Only the people who can edit the model start an evaluation (`PermissionDenied` for the others), on any of its versions
  (the latest unless `version=`), against a dataset they can read.
- For now the platform computes the metrics of **classification** (and its variants: `row_label`, image, audio, video and
  time series classification), **regression** and **qa**, whose ground truth is a column of the dataset. For another
  task `evaluate` is refused with a sentence (`Invalid`), before anything is sent. The definitions of the metrics (macro
  averages, the clean-up of answers...) are in `docs/backend-models.md`.
- The predictions go **straight to the storage in parts**, like the files of a version. If it is interrupted, the error
  names the evaluation: `model.send_predictions(evaluation_id, predictions)` sends only the parts that are not there
  (the file must be the one that was announced, else `FileChanged`). `progress=` is called with the bytes sent.
- `wait=True` (or `model.wait_evaluation(id)`) waits for the worker: `EvaluationFailed` with its reason if the
  predictions do not match the split, `WaitTimeout` if it takes longer than `timeout`.
- Nothing you send is a metric, so a result cannot be made up; but nothing proves the predictions come from the model.
  The `source` of an evaluation says where they come from: `predictions` (you sent them), later `endpoint` and
  `inference` (the platform called or ran the model).
- A POST is never repeated by itself: if the answer is lost, look at `model.evaluations()` before starting again.
- A reader of the model gets only the metrics that were chosen (`shown`), and `hidden` says how many are left out.

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

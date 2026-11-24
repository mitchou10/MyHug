# MLflow

MLflow keeps the **versions** of the models (its Model Registry) and their **artifacts**. The platform keeps the rest:
who owns a model, who can see it, its card, its tags, the code it points to. The backend is the only caller of MLflow,
and nothing outside the backend imports it (the `models` issues describe the client).

## What runs

| Service | What it is |
|---|---|
| `mlflow-init` | one-shot, at every `docker compose up`: makes MLflow's database and the bucket if they are missing, leaves them alone if they are there |
| `mlflow` | `mlflow server --serve-artifacts`, healthy when `/health` answers |

The image (`docker/mlflow/Dockerfile`) is the official one, pinned (`MLFLOW_VERSION`), with what it lacks: the PostgreSQL
driver (`psycopg2-binary`) and `boto3`. It runs as a user without rights. Change the version in one place (the `ARG`), and
read the release notes of MLflow first: its database is migrated on start.

## Where the state is

- **Backend store**: the `mlflow` database of the PostgreSQL of the compose (not the tables of the app). The URI says
  `postgresql+psycopg2://`: without the driver in the name SQLAlchemy picks `psycopg` (version 3), which the image does not
  have.
- **Artifacts**: the bucket `app` of RustFS, under `mlflow/`. The collector of the storage walks `datasets/` and
  `derived/` only, so it never touches them.
- Nothing in a volume of its own. Restarting `mlflow` keeps the registered models (checked).

## Why it is not published to the network

MLflow has no login that fits (anyone who reaches it can read, change and delete every model and artifact). So its port
is bound to the loopback of the machine only (`127.0.0.1:5000`, to read its UI while developing): the other services
reach it as `http://mlflow:5000`, no other machine does. The backend adds the rights of the platform in front of it. `--allowed-hosts` lists the names it answers to (`mlflow:5000`,
`localhost:5000`): MLflow refuses a request whose `Host` is another, which is what makes an address rebinding attack hard.

In production, keep that: MLflow on a private network, or behind a proxy that authenticates (and then `MLFLOW_API_KEY` is
the token the backend sends).

## Artifacts go through the server

`--serve-artifacts` makes the server the one that talks to the storage: a client sends and reads artifacts with
`PUT`/`GET /api/2.0/mlflow-artifacts/artifacts/<path>` and needs no storage key. Large uploads straight to the storage,
as for datasets, are decided in the issue on the artifacts of the models.

## Check it

```bash
docker compose exec -T -e PYTHONPATH=/app backend python - < backend/scripts/check_mlflow.py
```

It makes an experiment and a run, sends an artifact through the server, reads it back, looks for it in the bucket under
`mlflow/`, makes a registered model with a version, and deletes everything. The backend does not install the `mlflow`
package (it is large): the script speaks to the REST API with `httpx2`, which is also what the backend will do.

## In production

- Give MLflow its own database and credentials (here `app`/`app`, dev only) and a bucket or prefix of its own.
- Do not use `--allowed-hosts` as a security boundary: it is a protection against browsers, not authentication.
- The image is only built in CI to check the Dockerfile; it is not published by a release.

## The link to MLflow

The model pages link to MLflow so that the detail can be read there: the runs, the metrics, the parameters, the
artifacts. The address is `MLFLOW_PUBLIC_URL` (empty: no link), and the link goes to the page of the exact version:

| What | Address |
|---|---|
| a model | `<MLFLOW_PUBLIC_URL>/#/models/<name>` |
| a version | `<MLFLOW_PUBLIC_URL>/#/models/<name>/versions/<version>` |
| the run it came from | `<MLFLOW_PUBLIC_URL>/#/experiments/<experiment id>/runs/<run id>` |

**Who sees it.** MLflow has no rights of its own: whoever opens its UI can change and delete everything. So the API gives
the link **only to the people who can edit the model** (owner, admins, maintainers, and the platform's admins), never to
readers of a public model, and never the internal address (`MLFLOW_TRACKING_URI`). A reader sees what the platform shows:
the card, the files, the versions, the metrics it chose to publish.

In production `MLFLOW_PUBLIC_URL` must point to MLflow **behind a proxy that signs people in** (the same identity
provider as the platform), otherwise the link is a way in for anyone who learns the address.

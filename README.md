# app-starter

Template for new applications: a FastAPI backend, a React frontend, and a CI/CD built on the reusable
workflows of [Mitchou10/github-workflow](https://github.com/Mitchou10/github-workflow).

```
backend/    FastAPI + uv        (own version, own CHANGELOG.md)
frontend/   React + Vite + pnpm + Tailwind + shadcn/ui + i18next   (own version, own CHANGELOG.md)
.github/
  workflows/ci.yml       pull requests: lint, types, tests, scans, image builds, one `gate` check
  workflows/release.yml  release-please, then image build + scan + dev sync
  releases/              release-please configs and manifests (stable on main, rc on dev)
```

## Using the template

1. Click **Use this template** (or copy the folder), then rename `app-backend` / `app-frontend`
   in `backend/pyproject.toml`, `frontend/package.json` and `.github/releases/*.json`.
2. Settings → Actions → General: **Read and write permissions** and **Allow GitHub Actions to create and approve pull requests**.
3. Create the `dev` branch from `main`.
4. Branch protection on `main` and `dev`: require the single `gate` check.
5. Optional: add `APP_CLIENT_ID` / `APP_PRIVATE_KEY` secrets and uncomment `secrets:` in `release.yml`
   so release PRs trigger the CI.

## Local development

```bash
docker compose up --build     # backend :8000, frontend :5173
cd backend && uv sync && uv run pytest   # needs the test database, see Backend > Tests
cd frontend && pnpm install && pnpm test
```

## Backend

FastAPI, fully async (SQLAlchemy 2 + asyncpg, aioboto3), with small layers that each only know the one below:

```
app/routers/        HTTP only: read the request, call a service, build the response (deps.py wires a service together)
app/schemas/        pydantic models of what goes out (and in): no logic, no database
app/services/       the rules: no HTTP, no SQL. Raise their own errors (services/errors.py), routers map them to HTTP
app/repositories/   the database, nothing else (one class per table)
app/models/         SQLAlchemy tables (Base, UserProfile)
app/storage/        object storage: an ObjectStore interface and its S3 implementation, nothing else knows about S3
app/auth/           login (OIDC BFF), sessions, the current user
app/config.py       every setting, from the environment (pydantic-settings)
migrations/         Alembic
```

**Add a feature**: a model (and a migration), a repository, a service, a schema, a router, one line in `main.py`.
Pydantic models are used at every border (settings, requests, responses, the current user, sessions).

### Configuration

Every setting is an environment variable, read by `app/config.py` (and from a `.env` or `.env.local` file in `backend/`).
The defaults suit local development; **change the ones marked \*** before any real deployment.

| Variable | Default | What it is |
| --- | --- | --- |
| `APP_NAME` | `app` | Title of the API (and of its `/api/docs`) |
| `DATABASE_URL` | `postgresql+asyncpg://app:app@localhost:5432/app` | PostgreSQL, through asyncpg \* |
| `AWS_ENDPOINT_URL` | `http://localhost:9000` | The S3-compatible storage (RustFS here) |
| `AWS_PUBLIC_ENDPOINT_URL` | empty | The storage as the browser reaches it, for the signed addresses of uploads and downloads (empty: same as `AWS_ENDPOINT_URL`) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | `rustfsadmin` | Its credentials \* |
| `AWS_REGION`, `AWS_BUCKET` | `us-east-1`, `app` | Region, and the bucket (created on first use) |
| `AVATAR_MAX_BYTES` | 2 MiB | Largest profile photo |
| `FEEDBACK_MAX_ATTACHMENTS` | `5` | Screenshots per feedback or answer |
| `FEEDBACK_ATTACHMENT_MAX_BYTES` | 5 MiB | Largest screenshot |
| `PAGE_SIZE_MAX` | `50` | Largest `limit` a list or a follow-up can ask for |
| `DATASET_UPLOAD_MAX_BYTES` | 50 GiB | Largest file sent to a dataset (it goes straight to the storage, in parts) |
| `UPLOAD_PART_BYTES` | 64 MiB | Size of a part of an upload (bigger for a file that would need more than 10 000 parts) |
| `UPLOAD_SESSION_HOURS` | `24` | How long an upload can take before it is given up |
| `SIGNED_ADDRESS_SECONDS` | `3600` | How long a signed address of the storage works |
| `REDIS_URL` | `redis://localhost:6379/0` | Where the API queues the jobs of the worker (it only sends the name of the task) |
| `WORKER_API_KEY` | empty | The key the worker calls `/api/internal` with, 16 characters at least (empty: the worker is refused) |
| `MLFLOW_TRACKING_URI` | empty | The MLflow server of the models' versions and artifacts, reached only from inside the compose (empty: models are not available) |
| `MLFLOW_PUBLIC_URL` | empty | Where people who can edit a model open it in MLflow (a link on the model page). MLflow has no login: behind a signing-in proxy in production. Empty: no link |
| `MLFLOW_API_KEY` | empty | Sent as a bearer token if a proxy in front of MLflow asks for one |
| `PROCESSING_STALE_MINUTES` | `30` | A version read for longer than this is taken to have lost its worker, and is read again |
| `PROCESSING_MAX_ATTEMPTS` | `3` | How many times a version is taken in hand before it is given up as `failed` |
| `DERIVATIVE_MIN_BYTES` | 8 MiB | A csv, tsv or jsonl file at least this big gets a Parquet copy, made by the worker (below it the copy gains nothing) |
| `DERIVATIVE_MAX_SOURCE_BYTES` | 20 GiB | A source over this is left as it is |
| `DERIVATIVE_PART_BYTES` | 16 MiB | The size of the parts the worker sends a copy in |
| `STORAGE_GC_ENABLED` | `true` | Kill switch of the collection of the objects that nothing points to |
| `STORAGE_GC_DRY_RUN` | `true` | The collection only says what it would delete, until this is turned off |
| `STORAGE_GC_GRACE_HOURS` | `0` | An object younger than this is never touched. 0: an upload session plus 12 h. Never less than that |
| `STORAGE_GC_MAX_SCANNED` | `20000` | Objects looked at in one pass |
| `STORAGE_GC_MAX_DELETIONS` | `5000` | Objects deleted in one pass |
| `STORAGE_GC_CHECK_ROWS` | `200` | Files of versions whose object is checked to be there, in the first pass |
| `DATASET_FILE_MAX_BYTES`, `DATASET_VERSION_MAX_FILES` | 100 MiB, `100` | Largest file, and most files, of a version sent through the API (small files) |
| `NOTIFICATION_API_KEYS` | empty | The applications allowed to emit notifications, as `name=key` pairs separated by commas (a key under 16 characters is ignored); the name becomes the `source` \* |
| `AUTH_MODE` | `oidc` | `oidc`, or `full-access`: no login, a fixed admin (development and tests only) |
| `OIDC_ISSUER` | empty | The provider's issuer URL; empty means no login is possible |
| `OIDC_DISCOVERY_URL` | `<issuer>/.well-known/openid-configuration` | Where to read the discovery document when the provider is not reached on its public address |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | `app-backend`, empty | The client registered in the provider \* |
| `OIDC_SCOPES` | `openid profile email` | Scopes asked at login |
| `OIDC_ROLES_CLAIM`, `OIDC_GROUPS_CLAIM` | `roles`, `groups` | Where the roles and the groups are in the claims (dotted path, e.g. `realm_access.roles`) |
| `OIDC_ADMIN_ROLE` | `admin` | The role that makes a user an admin |
| `SESSION_COOKIE_NAME` | `session` | Name of the session cookie |
| `SESSION_COOKIE_SECURE` | `true` | Send the cookie over HTTPS only: turn it off for plain-HTTP development only \* |
| `SESSION_COOKIE_SAMESITE` | `lax` | `lax`, `strict` or `none` |
| `SESSION_TTL_SECONDS` | 8 hours | Lifetime of a session |
| `LOGIN_STATE_SECRET` | `dev-only-secret-not-for-prod` | Signs the cookie of the login redirect \* |
| `BACKEND_PUBLIC_URL` | `http://localhost:8000` | The address the browser reaches the backend on: the callback to register in the provider is `<it>/api/auth/callback` |
| `FRONTEND_URL` | `http://localhost:5173` | Where the browser lands after login and logout |

The frontend keeps a copy of three limits to answer without sending the file: 2 MiB for a photo (`AVATAR_MAX_BYTES` in
`src/profile/useAvatar.ts`), and 5 screenshots of 5 MiB (`ScreenshotPicker.tsx`). The backend always checks them again.

### Database and migrations

PostgreSQL, `DATABASE_URL=postgresql+asyncpg://user:password@host:5432/db`. The schema only changes through Alembic:

```bash
cd backend
uv run alembic revision --autogenerate -m "add something"   # after changing a model, then read the file
uv run alembic upgrade head
uv run alembic check                                          # fails if the models and the migrations differ
```

With `docker compose up`, the `migrate` service brings the database to the latest migration before the backend starts.

### Object storage

RustFS in development, any S3-compatible service in production. The usual `AWS_*` variables:
`AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, plus `AWS_BUCKET` (the bucket is
created on first use). RustFS console: http://localhost:9001 (`rustfsadmin` / `rustfsadmin`).

### Feedback API

Users send feedback and follow it; admins answer and move it forward. The data model is drawn in
[docs/data-model.png](docs/data-model.png) (`uv run python scripts/draw_model.py`, needs Graphviz's `dot`, after a model
change).

| Who | Route |
| --- | --- |
| Everybody | `GET /api/feedback-types`, `GET /api/feedback-statuses` (archived ones included, flagged) |
| | `POST /api/feedback` (multipart: `title`, `description`, `type_id`, `page`, `files`) |
| | `GET /api/feedback` (mine), `GET /api/feedback/{id}`, `PATCH /api/feedback/{id}` (status, type) |
| | `GET`, `POST /api/feedback/{id}/messages`, `GET /api/feedback/{id}/attachments/{id}` |
| Admins | `GET /api/admin/feedback` (all of it) |
| | `POST`, `PATCH /api/admin/feedback-types` and `/api/admin/feedback-statuses` |

- **Visibility**: a feedback is seen by its author and by admins; for anybody else it does not exist (404).
- **Changes**: admins change the status and the type freely. An author can only close their feedback (status
  `closed`) or reopen it (`new`). Every change of status is written in the follow-up, between the answers.
- **Types and statuses are data**: the migration ships the defaults, admins add, rename, recolor, reorder and archive
  them (an archived value stays on its feedback but cannot be chosen again). The statuses with the keys `new` and
  `closed` are used by the app itself: they can be renamed, never archived.
- **Screenshots**: up to 5 per feedback or answer, PNG, JPEG or WebP of 5 MB at most, checked on their bytes, all
  of them before any is stored. They are in the object storage and served by the API, to whoever may see the feedback.
- **Pagination**: the list takes `limit` (1 to 50), `offset`, `status` (an id, or `open` for every status that is not
  final) and `type_id`, and answers `{items, total, limit, offset}`. The follow-up is read from the newest message:
  `limit` and `before` (the `next_before` of the previous page, an opaque cursor), and answers
  `{items, total, next_before}` with the items oldest first. The cursor holds `(created_at, id)`: a message added
  meanwhile moves nothing.
- **Errors** are raised by the services (`services/errors.py`) and turned into status codes in one place,
  `routers/errors.py`.

### Notifications API

Short messages that applications send to users, read in the app. Nothing leaves the app: no e-mail, no push. One page
for everybody, the same for a user and for an admin.

| Who | Route |
| --- | --- |
| A user | `GET /api/notifications` (`unread`, `limit`, `offset`), `GET /api/notifications/unread-count` (the badge) |
| | `PATCH /api/notifications/{id}` (`{"read": true}`, or `false`), `POST /api/notifications/read-all` |
| An application | `POST /api/emit/notifications`, authenticated by the `X-Api-Key` header |

A notification has a **title**, a **description**, an optional **link** (`url`), the application that **emitted** it
(`source`), its **recipient** (`user_id`, the `sub` of the user) and whether it was **read** (`read_at`). Each
recipient has their own copy, with their own read state.

- **Emitting** is for the other applications, not for users: each has a key in `NOTIFICATION_API_KEYS`
  (`billing=<key>,reports=<key>`). The `source` is the name the key belongs to, so an application cannot claim to be
  another. Nobody can emit while the setting is empty.

  ```bash
  curl -X POST http://localhost:8000/api/emit/notifications \
    -H "X-Api-Key: dev-only-key-not-for-prod" -H "Content-Type: application/json" \
    -d '{"user_ids": ["<sub of the user>"], "title": "Invoice ready",
         "description": "Your invoice for October is available.",
         "url": "https://billing.example.com/invoices/42"}'
  ```

- **The link** is a path of this app (`/feedback/…`, opened in the app) or an `http(s)` address of another application
  (opened in a new tab). Nothing else is accepted, not `javascript:` nor `//host`, in the API and in the database.
- Somebody else's notification does not exist (404). Reading twice keeps the first read date.

### Profile photo

`GET /api/me/profile`, then `GET` / `PUT` / `DELETE /api/me/avatar`. PNG, JPEG or WebP, 2 MB at most
(`AVATAR_MAX_BYTES`): the type is read from the bytes, not from what the client says, and SVG is refused. The image
is in the bucket under `avatars/<user>/<random>`, the database holds its key. In the frontend: the settings page, and
the profile at the bottom of the sidebar.

### Tests

They run against a real PostgreSQL (the schema is built by the migrations) and a simulated S3:

```bash
docker compose -f docker-compose.test.yaml up -d --wait     # PostgreSQL on :55433
cd backend && uv run pytest --cov
```

### The OpenAPI schema

`openapi.json` at the root is the contract of the API (the routes of the worker, `/api/internal`, are left out). The frontend
types and the future SDK are generated from it, so change a route, then regenerate **both**:

```bash
cd backend && uv run python scripts/export_openapi.py   # writes ../openapi.json
cd ../frontend && pnpm generate:api                     # writes src/lib/schema.ts
```

CI fails when `openapi.json` is not what the backend produces (a backend test) or when `src/lib/schema.ts` is not what
`openapi.json` gives (`pnpm check:api`).

## Frontend

React 19 + TypeScript on Vite, styled with [Tailwind CSS](https://tailwindcss.com) 4 and
[shadcn/ui](https://ui.shadcn.com) (components are copied into `src/components/ui`, so they are yours to edit).

- Add a component: `cd frontend && pnpm dlx shadcn@latest add dialog`.
- Translations: [react-i18next](https://react.i18next.com), files in `src/i18n/locales/` (`en`, `fr`). The language
  is the saved choice, else the browser's, else English. Add a language by adding its file and listing it in
  `src/i18n/index.ts`.
- `/api` is proxied to the backend (`BACKEND_URL`), so the session cookie stays on the page's own origin.
- The types of what the API sends are generated (`src/lib/schema.ts`, see [the OpenAPI schema](#the-openapi-schema)); the
  `wire.ts` files only name the ones a feature uses, and the mappers turn them into what the screens read.

### Structure, routing and layouts

```
src/routes.tsx         every route of the app, in one place
src/layouts/           RootLayout (public header + footer), AppLayout (sidebar), appNav.ts (sidebar entries)
src/pages/             one file per page (AppHomePage, SettingsPage, NotFoundPage)
src/auth/              AuthProvider (who is logged in, asked once), RequireAuth (protects routes)
src/components/        generic and reusable: Container, Section, SectionHeading, UserMenu, LanguageSwitcher...
src/components/ui/     shadcn/ui (generated, edit freely)
src/features/landing/  the home page: one small component per file, everything comes from props
  content.ts           the list of features (icon + key)
  LandingPage.tsx      only assembles the sections
```

Two worlds, like ChatGPT's site and app:

- **Public** (`RootLayout`): the landing page and the 404, with a header on top and a footer. The header holds
  the language dropdown and a "Sign in" button (or "Open the app" once logged in).
- **App** (`AppLayout`, behind `RequireAuth`): for logged-in users only. A sidebar on the left (a drawer on mobile)
  with the navigation, and the **profile at the bottom**: click it for a menu with the settings, the language and
  sign out. A visitor who is not logged in gets a sign-in button that brings them back to the page they asked for.
  There is no content yet: `/app` is empty on purpose, it is where your product starts.

[React Router](https://reactrouter.com). **Add a page of the app**: create it in `src/pages` (or `src/features/<name>`),
add a line under `AppLayout` in `routes.tsx` and an entry in `layouts/appNav.ts` for the sidebar. **Add a public
page**: a line under `RootLayout` (and a link in `layouts/nav.ts` if it belongs in the header, which has none for
now). Unknown addresses show the 404 page; nginx falls back to `index.html` so a refresh on any route works.

Components stay small, take their texts as props and know nothing about i18n; only the pages, the layouts,
`UserMenu` and `AuthButton` call `t()`. To adapt the landing page in a new project: edit the texts in
`src/i18n/locales/*.json`, the list in `content.ts`, and add or remove sections in `LandingPage.tsx`.

### Feedback module

Users send feedback (title, description, type, screenshots) from their profile menu and follow it; admins answer and
move it forward. The screens are in `src/features/feedback/` and talk to the backend's [feedback API](#feedback-api)
through [TanStack Query](https://tanstack.com/query):

```
api/            client.ts (fetch + the errors of the backend), wire.ts (what it sends), mappers.ts, types.ts (what the
                screens use), and one file per need: references, list, detail, thread, create
components/     the screens' pieces, one per file
pages/          the pages
```

- The screens never call `fetch`: they use the hooks of `api/` (`useFeedbackList`, `useThread`, `useReply`...), which
  keep the cache and refresh it after a change. The cache keys are in `api/keys.ts`.
- **The lists** are paginated by the server (`limit` and `offset`): *Show more* fetches the next page, and changing a
  filter starts again. The follow-up is paginated by cursor from the newest message. When messages are added, the newest
  page is **merged** into the cache (`refreshNewest`) rather than refetched: refetching an infinite query reloads every
  page from its saved cursor, which would leave a gap. The open feedback is refreshed every 15 seconds
  (`useLiveRefresh`), only while the page is visible.
- **Errors** of the backend become a sentence (`api/errors.ts`, the translations `feedback.errors.*`).
- **Tests** run against `src/test/fakeFeedbackApi.ts`, the API in memory with the rules of the real one (who sees what,
  who may change what, filters, pages, cursors). The real backend is tested on its own side.

One page per side, with the list on the left and the selected feedback on the right (they take turns on a phone).
The address says which one is open (`/feedback/<id>`), so it can be shared:

- **User** (`/feedback`): *My feedback*. The profile menu has a *Feedback* group: *Give feedback* (a dialog) and *Manage my feedback*.
- **Admin** (`/admin/feedback`): every feedback, with a second tab for the types and the statuses. It is in an
  *Administration* group of the profile menu, which only admins see. The sidebar stays light on purpose.

**Give feedback** is a modal, opened from the profile menu, the *New feedback* button or the keyboard shortcut
**Ctrl+Shift+F** (⌘⇧F on a Mac) from anywhere in the app. Plain Ctrl+F is the browser's "find in page", so it is not
taken; the key is one constant, `SHORTCUT_KEY` in `shortcut.ts`. The modal is mounted once in the app layout
(`FeedbackLauncher`) and its state is in `FeedbackDialogProvider`. The page the user is on when it opens (path and query)
is captured at that moment and offered as a checkbox, *Attach the page I am on*; the feedback then shows it as a link,
which tells the team where the problem was.

Nothing scrolls the page: the list, the follow-up and the description each scroll in their own box.

- **Follow-up**: opens on the latest message and goes back there when one is added. Only the latest 10 messages are
  shown; *Show older messages* loads the previous page at the top without moving what is being read. Changes of
  status are part of it.
- **List**: pages of 10 with *Show more* and a count (`10 of 34`); a new search starts again from the first page, and
  the feedback being read always stays in the list. The page size is `LIST_PAGE_SIZE` (`pagination.ts`), sent to the backend as
  `limit`.

Types and statuses are data, not code: an admin adds, edits or archives them. An author can close or reopen their own
feedback; only admins change the status or the type. To see it: `docker compose up` (the `dev` / `dev` user of the Keycloak realm is an admin, `user` / `user` is a plain user: a
plain author can only close or reopen their feedback), or run the backend with `AUTH_MODE=full-access` (a fixed admin)
and `pnpm dev` with `BACKEND_URL` pointing to it.

### Notifications (frontend)

What the applications tell the user, read in `/notifications`: the same page for a user and for an admin, reached from
*Notifications* in the profile menu (it is not in the sidebar). The code is in `src/features/notifications/`, on the
[notifications API](#notifications-api), through the same `src/lib/api.ts` client as the feedback module.

- **The badge**: a red dot on the avatar (shadcn's `AvatarBadge`), the count in the profile menu (`99+` above 99), and a
  dot on the sidebar button on a phone, where the avatar is hidden. The count is asked again every 30 seconds while a
  page is open (`UNREAD_POLL_MS`) and when the window gets the focus again, so a notification emitted meanwhile shows
  without a reload. Screen readers get *Open the user menu, 3 unread notifications* (the plural is translated).
- **The page**: newest first, by pages of 10 (*Show more*), with *All* and *Unread (n)* tabs, *Mark all as read*, and
  for each notification the application that emitted it, its date and its description. *Mark as read* and *as unread* are
  one click.
- **The link**: a path of the app is opened in the app, the address of another application in a new tab
  (`rel="noopener noreferrer"`, the host is shown on the button). Following a link reads the notification.
- **Tests** use `src/test/fakeNotificationsApi.ts`, the API in memory: `stubBackend(user, undefined, { notifications: [...] })`
  starts a user with some, and `emit()` adds one while a test runs.

## Authentication (BFF)

The backend is a BFF: the browser never sees a token. `/api/auth/login` sends it to the identity provider
(authorization code + PKCE), `/api/auth/callback` trades the code for tokens that stay in a server-side session,
and the browser only holds an opaque HttpOnly cookie. Non-browser clients can send `Authorization: Bearer <token>`.

| Route | Role |
| --- | --- |
| `GET /api/auth/login?redirect=/path` | start the login (only internal paths are accepted) |
| `GET /api/auth/callback` | end of the login, creates the session |
| `GET /api/auth/me` | the current user (`401` when logged out) |
| `POST /api/auth/logout` | ends the session, returns the provider's `logout_url` |

In a route: `async def route(user: CurrentUser)` (`from app.auth.deps import CurrentUser`).

Nothing in the code is tied to Keycloak. It speaks standard OIDC through [Authlib](https://authlib.org) and is
configured by `OIDC_*` variables (see `backend/app/config.py`); Keycloak only appears in `docker-compose.yaml`
and `docker/keycloak/realm-app.json` (user `dev` / `dev`). To use another provider, change `OIDC_ISSUER`, the client
credentials and, if the provider names them differently, `OIDC_ROLES_CLAIM` / `OIDC_GROUPS_CLAIM`
(dotted path for nested claims, e.g. `realm_access.roles`).

- `AUTH_MODE=full-access` disables authentication: every request is a fixed dev user (no provider needed, used by tests).
- Sessions live in memory (`app/auth/session.py`): implement the `SessionStore` protocol on Redis or a database
  before running several replicas.

### Access tokens (programs)

A program (a script, a notebook, the SDK) has no session, so a person makes it an **access token** on the
*Access tokens* page (sidebar), and the program sends `Authorization: Bearer mh_...`.

- **Shown once.** The token is only in the answer to its creation; the database keeps its SHA-256 (the token is long and
  random, so a slow hash is not needed) and its first characters, to recognise it in the list. Lose it: revoke it and
  make another. `TOKENS_MAX_ACTIVE` (20) tokens at most per person.
- **A scope, `read` or `write`** (`write` includes `read`), and an optional expiry (1 to 365 days). A `read` token is
  refused (`403`) on every route that changes something, except trying a model (`POST .../predict`, which changes nothing).
- **No scope per dataset or model.** A token has the rights its owner has on the data, looked up at every call: take
  the owner off a model and their tokens lose it at once.
- **Never an administrator**, even if the owner is. And **no token can make, list or revoke tokens, change the profile
  or call `/api/auth/*`**: those need a login, so a stolen token cannot make others or change who the person is.
- A revoked, expired or unknown token is a `401` that says nothing more. A wrong `mh_` token is not rescued by a session
  cookie or by the identity provider's tokens (which still work as before for anything that does not start with `mh_`).
- `TOKEN_RATE_PER_MINUTE` (600) calls a minute per token (counted in Redis, a `429` after that), `last_used_at` is written
  at most once a minute, and each call leaves one log line `token=<id> GET /api/... -> 200` on the `app.tokens` logger:
  never the token. Revoke from the page or `DELETE /api/tokens/{id}`.
- Not in `AUTH_MODE=full-access`: the dev user needs no token there.

### Login page theme

The Keycloak login page is restyled like the frontend: `docker/keycloak/themes/app/login/` extends Keycloak's
login theme with a small CSS. The colors, radius and font are the frontend's (`frontend/src/style.css`), copied by
`node docker/keycloak/sync-theme.mjs`: run it after changing the frontend's theme. The realm uses it
(`"loginTheme": "app"` in `realm-app.json`) and `docker-compose.yaml` mounts the folder, with Keycloak's theme cache
off so that a CSS edit shows up on reload.

The realm is only imported when it does not exist yet: on an already running Keycloak, recreate it
(`docker compose down && docker compose up -d`) or pick the theme in the admin console
(Realm settings → Themes → Login theme: `app`). Other providers have their own way to theme the login page: this
folder is specific to Keycloak and can be dropped with it.

## Releases

Commits follow [Conventional Commits](https://www.conventionalcommits.org/). release-please opens **one** release
pull request per branch (`dev`: release candidates `-rc.N`, `main`: stable) that bumps:

| Release | Tag | Changelog | Bumped when |
| --- | --- | --- | --- |
| Global | `vX.Y.Z` | `CHANGELOG.md` | any change in the repo |
| Backend | `backend-vX.Y.Z` | `backend/CHANGELOG.md` | a commit touches `backend/` |
| Frontend | `frontend-vX.Y.Z` | `frontend/CHANGELOG.md` | a commit touches `frontend/` |

Service versions are written to `backend/pyproject.toml` (and `uv.lock`) and `frontend/package.json`.
Container images (`ghcr.io/<owner>/<repo>-backend` and `-frontend`) are built and scanned on each global release,
tagged with the global version.

Attribution is by file path, not by commit scope: a commit appears in the changelog of every service whose folder it touches, and always in the global one.

## The worker

`worker/` is a service of its own (its own `pyproject.toml`, image, tests and releases, `worker-vX.Y.Z`). It has no
database and no storage key: it reads the jobs in Redis, asks the backend (`/api/internal`, with `X-Api-Key`) what to read,
downloads the files from the storage with the signed addresses the backend gives it, and tells the backend what it found
(fingerprint, rows, columns). The backend keeps every record and every decision. See
[docs/backend-datasets.md](docs/backend-datasets.md), section 6 bis.

| Variable | Default | |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Where the jobs wait |
| `BACKEND_URL` | `http://localhost:8000` | The backend |
| `WORKER_API_KEY` | empty | Its key (the same as the backend's) |
| `WORKER_TEMP_DIR` | empty (system) | Where a file is kept while it is read or converted: room for the source **and** its copy |
| `ROW_GROUP_ROWS` | `50000` | Rows in a row group of a Parquet copy (what a page of the preview reads) |
| `BATCH_BYTES` | 64 MiB | The most memory a batch of rows takes before it is written, whatever the rows |
| `COLLECT_STORAGE_SECONDS` | `86400` | How often the worker asks the backend to collect the objects that nothing points to |
| `COLLECT_MAX_PASSES` | `200` | The most passes of one collection (each is bounded on the backend) |
| `SWEEP_SECONDS` | `60` | How often the versions nobody reads are queued again |
| `EXPIRE_UPLOADS_SECONDS` | `900` | How often the abandoned uploads are given up |

```bash
cd worker
uv sync
uv run pytest                                   # no Redis, no backend: they are played by the tests
uv run celery -A worker.celery_app worker -Q datasets
uv run celery -A worker.celery_app beat         # one only
```

`docker compose up` starts `redis`, `worker` and `beat`. The image has no HTTP health check: the worker listens to nothing.

## MLflow

The versions and the artifacts of the models are kept by [MLflow](https://mlflow.org). `docker compose up` starts it
(`mlflow`, after a one-shot `mlflow-init`): its state is in its own PostgreSQL database (`mlflow`) and in the bucket of
RustFS under `mlflow/`, so there is no volume to keep and a restart keeps everything.

**It has no login of its own, so it is never published to the network**: only the services of the compose reach it
(`http://mlflow:5000`), and only the backend calls it. For you, its UI is on **http://localhost:5000** (the port is bound to
127.0.0.1, this machine only), and the model pages link to it for the people who can edit the model
(`MLFLOW_PUBLIC_URL`). Never bind that port to another address.

To check that it works as the backend will use it (a registered model and its version, an artifact sent and read back
through the server, and found in the bucket):

```bash
docker compose exec -T -e PYTHONPATH=/app backend python - < backend/scripts/check_mlflow.py
```

See [docs/mlflow.md](docs/mlflow.md).

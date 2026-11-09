# DatasetBuilder — TotalCare RAG Knowledge Studio

**Version 1.0.0 · Flask · Bootstrap 5 · Font Awesome · PostgreSQL / SQLite · UTF-8 · English / Greek**

DatasetBuilder is a multi-user application for authoring, previewing, and versioning Markdown troubleshooting knowledge. It stores current UTF-8 `.md` files in a configured directory **and** keeps authoritative article/revision metadata in a transactional database. It is intended to prepare structured datasets for a separate RAG pipeline; it is **not** itself a RAG indexer, retrieval engine, or AI question-answering API.

## Features

The dark, responsive, three-panel editor offers Markdown formatting with CodeMirror (bold, italic, headings, links, ordered/unordered lists, quotes, code, code blocks, tables, undo/redo and keyboard shortcuts), a structured article outline, editable metadata, customizable sections, plus buttons between sections, one-click subsection insertion, drag-free up/down ordering, unlimited independent solutions, a full raw Markdown mode, and a **live server-rendered, HTML-sanitized preview**. Use **Ctrl/Cmd+S** to save.

New records prepopulate *Problem Description, Possible Symptoms, Possible Causes, Diagnostic Procedure, Corrective Actions, Verification, Required Information for Further Diagnosis* and *Related Questions*, plus a solution template. Multiple solutions use a separate `## SOLUTIONS` heading and numbered `### Solution N: Name` subheadings, placed after Corrective Actions when it exists. Diagnostic `### Step ...` subheadings can be edited directly within a section.

Each article uses a unique stable ID based on the database sequence, with filenames such as `TC-KB-01-Kiosk_Communication_Lost.md` or `TC-KB-02-Απώλεια_Επικοινωνίας.md`. Spaces and punctuation become `_`, path separators are stripped, and Greek filenames/content are preserved as Unicode NFC UTF-8. Changing an article title updates the filename. Deleted articles go to a recoverable trash area (their `.md` mirror is removed).

Every record remembers **Created By**, **Last Edited By**, revision number, and timestamps, embedded into the Markdown as well as stored in the database. Every save, deletion, restoration, and import becomes an immutable revision. The history screen provides previews, text diffs, downloads, and restore-as-new-version. ZIP export includes current `articles/`, deleted `trash/`, all `history/` revisions, and a UTF-8 `MANIFEST.json`. For direct RAG ingestion, use files under `articles/` only, and optionally filter on knowledge status.

Users have **admin**, **editor** and **viewer** roles. Admins create/manage accounts. Editors can write, import, restore and delete. Viewers can browse/preview/download/export. The UI defaults to English, offers Greek (Ελληνικά) in the top bar and on the login page, and saves a user’s preference in **both their database settings and an HTTP-only language cookie**. The document language is independent of the interface language. Every meaningful save, delete, import, restore and settings change displays an upper-right toast. There are no background worker dependencies for normal editing.

## Quick start: Linux / Ubuntu

Requires Python 3.11+, pip/venv, and internet access for installing Python packages and for Font Awesome icons + Google Fonts (Bootstrap and CodeMirror JavaScript/CSS ship locally). Run from the extracted `DatasetBuilder/` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_hex(32))'
# Edit .env and put the generated value in SECRET_KEY.
# For non-Docker local development, use COOKIE_SECURE=0.
# Optional: omit DATABASE_URL to use the built-in absolute SQLite database path.
flask --app wsgi.py db upgrade
flask --app wsgi.py create-admin
flask --app wsgi.py run --host 127.0.0.1 --port 5000
```

Open `http://127.0.0.1:5000`. **Do not expose `flask run` on public networks.** For an internal network, use Gunicorn behind a trusted reverse proxy and HTTPS.

The default SQLite path is `data/datasetbuilder.sqlite` inside the project directory. The default Markdown output is `data/knowledge_base/` (configure it via `KB_DIRECTORY`). SQLite is suitable for evaluation/single-instance deployments but **PostgreSQL is strongly recommended for many concurrent editors**.

## Native Linux service and updates

On a systemd-based Linux host, run from a Git checkout as the user that should
own and run the application (not root). Python 3.11+, Git, sudo and systemd
are required. The installer offers to install missing nginx, rsync, curl and Python
venv packages on apt-based systems; install them manually elsewhere.

```bash
./scripts/setup.sh
```

Choose an installation directory when prompted (default `/opt/dataset-builder`);
for automation pass an absolute path: `./scripts/setup.sh install /opt/dataset-builder`.
The directory must not already exist. The installer copies the checkout,
including its `.env` and `data/`, creates a fresh virtual environment, installs
Python requirements, migrates the database, and enables a systemd service.
Stop any running source application before copying its SQLite database and
knowledge files. The source checkout is not modified. Absolute database and
knowledge paths in `.env` are preserved as-is and continue to point to their
original locations; ensure the service user can access them. If `.env` is absent,
setup creates one with a random secret and secure cookies. Existing settings are
never replaced: set `COOKIE_SECURE=1` for HTTPS if necessary. The service runs
as the invoking user and binds to `127.0.0.1:8000`. It uses one Gunicorn worker;
configure Redis in `.env` before using multiple workers or instances.
Setup and updates check the local HTTP/database health endpoint before reporting
success. The installer refuses an existing service or nginx site rather than
overwriting another installation.

Create the first administrator if the copied database does not already have one:

```bash
cd /opt/dataset-builder
APP_ENV=production .venv/bin/flask --app wsgi.py create-admin
```

Control the installation from its home directory:

```bash
./datase-ctl start
./datase-ctl stop
./datase-ctl status
./datase-ctl logs    # follow the systemd journal
./datase-ctl update
./datase-ctl debug   # service status, recent logs, database and HTTP health
```

Update fetches the source branch's configured upstream and fast-forwards only,
stops the service, preserves the
existing `.env` and entire `data/` directory (including tracked and untracked
files), installs dependencies, migrates the configured database and starts
the service. It refuses staged changes, tracked changes outside `data/`,
non-fast-forward updates, and updates touching a configured SQLite database
or knowledge directory outside `data/`. Local uncommitted code copied from the
source checkout remains uncommitted and must be committed or otherwise handled
before updating. Other Git conflicts also stop the
update. The service stays stopped if an update fails after it is stopped;
inspect the error and fix it before restarting. Migrations may modify the
database: **back up the database and knowledge directory before updating**.
For PostgreSQL, use a database-native backup such as `pg_dump`; `.env` and
external data paths are not database backups.

The installer installs and enables the [nginx site](scripts/datasetbuilder.nginx.conf)
for `dataset-builder.unixfor.gr` on Debian-style nginx installations. It
redirects HTTP to HTTPS and requires the existing certificate
`/opt/ssl/unixfor.crt` and key `/opt/ssl/unixfor.key`. Setup refuses to
overwrite an existing site, runs `nginx -t`, and reloads nginx only on success.
Check DNS, certificate hostname coverage, and nginx's other sites before
exposing the service. A failed installation may leave the new installation
directory or service in place; inspect it before retrying.

## Production: Docker Compose (PostgreSQL + Redis + Gunicorn)

1. Copy `.env.example` to `.env`. Set a random `SECRET_KEY` (64+ hex characters is fine) and a strong URL-safe `POSTGRES_PASSWORD` with no `@`, `:`, `/` or `?`. Set `COOKIE_SECURE=1` when accessed through HTTPS. Do not publish `.env`.
2. Start storage and application:

```bash
docker compose up -d --build
docker compose exec web flask --app wsgi.py db upgrade
docker compose exec web flask --app wsgi.py create-admin
docker compose ps
curl http://127.0.0.1:8000/healthz
```

3. Add an HTTPS reverse proxy. `scripts/nginx-example.conf` shows one starting configuration. Docker publishes only on `127.0.0.1:8000`; access externally via the TLS reverse proxy.
4. Back up **both** PostgreSQL and the persistent `knowledge_data` volume. ZIP export is a portable content/history backup, **not** a replacement for a complete user/database backup.
5. Run `docker compose exec web flask --app wsgi.py sync-files` if a disk failure or interrupted mirror write ever leaves Markdown files out of sync. SQL history is authoritative.

The compose setup uses PostgreSQL row-based version checks, an OS-level shared file lock, atomic rename for Markdown output, Redis-backed rate-limit storage, role-based permissions, CSRF validation, hashed passwords, encrypted/signed sessions, and defensive HTML sanitization. It is a substantial production-oriented baseline, but deployers should still add infrastructure monitoring, database backup/restore drills, HTTPS certificates, security reviews and load testing before high-assurance use.

**Note on restarts and migrations:** Run `flask db upgrade` during initial deployment and each release before sending traffic to the new version. This ZIP contains the initial Alembic revision `0001_initial`.

## Import the provided TotalCare example

Use the **Import .md** button on the dashboard. Uploaded source must be UTF-8 (with or without BOM), up to 1.75 MB, and begin with a top-level Markdown heading. The application assigns a new knowledge ID and records the importing user as creator. The original source from your request is included at `examples/TC-KB-001-Kiosk-Communication-Lost.md`.

Alternatively, import by CLI using a known existing username:

```bash
flask --app wsgi.py import-md examples/TC-KB-001-Kiosk-Communication-Lost.md --username admin
```

The KB number in an imported source is replaced by DatasetBuilder’s own monotonic ID to avoid collisions. Existing `### Step 1` procedure headings and `### Cause: ...` corrective-action subheadings remain Markdown inside their parent section. You may add an unlimited number of separately named solutions using **Add solution**.

## Concurrent editing / revision conflicts

Each editor loads a document revision number. Saving uses an atomic `UPDATE WHERE revision = expected`; if another user has already saved, the second request returns **HTTP 409** and **never silently overwrites the newer version**. The conflict dialog keeps the unsaved text in the browser and offers Copy Markdown / Download draft / Reload latest. Two people can work simultaneously on different articles, but this is **optimistic concurrency control, not Google Docs-style real-time co-editing**. File synchronization uses a lock and rechecks the committed SQL row before writing to avoid writing stale mirror content.

## Permissions and security

Password login is local, with >=12-character passwords hashed using Werkzeug `scrypt`. Registration is administrator-controlled only. Active admin/editor accounts can create and edit; admins additionally manage users; viewers cannot mutate data. Mutating browser requests are protected by CSRF tokens. UI previews are produced server-side with the Python Markdown renderer and Bleach sanitizer; user-submitted HTML is not run as JavaScript. CSP, HTTP-only cookies, and same-site policy are enabled. Use `COOKIE_SECURE=1` behind TLS. Rate-limits on `/login` are backed by Redis in Compose.

Deployment assumptions: trusted administrator provisions accounts and maintains volumes; the `KB_DIRECTORY` directory is writable only to the application service user. `.md` files are outputs, **not a safe location for arbitrary public uploads**. Under Docker, the app runs as an unprivileged user ID 10001. No external OAuth or MFA is included in v1.0.0; place the app behind enterprise SSO/proxy if required by your security policy.

## REST endpoints (authenticated)

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/` | Search/filter/paginate articles |
| `GET` | `/documents/new`, `/documents/<id>/edit` | Structured editor |
| `GET` | `/documents/<id>` | Formatted preview |
| `GET` | `/documents/<id>/history`, `/documents/<id>/history/<revision_id>` | Audit/version history and diff |
| `GET` | `/documents/<id>/download` | Download current UTF-8 Markdown |
| `GET` | `/export` | ZIP with all content and history |
| `POST` | `/import` | Import a UTF-8 `.md` via browser |
| `POST` | `/api/documents` | Create document from `{title,markdown,note}` |
| `PUT` | `/api/documents/<id>` | Update from `{title,markdown,revision,note}`, HTTP 409 if stale |
| `DELETE` | `/api/documents/<id>` | Move to trash from `{revision}` |
| `POST` | `/api/preview` | Sanitized `{html}` from `{markdown}` |
| `POST` | `/api/parse` | Parse raw Markdown into metadata/sections/solutions |
| `POST` | `/documents/<id>/restore` | Restore deleted article |
| `POST` | `/documents/<id>/history/<revision_id>/restore` | Restore old version as new revision |
| `GET/POST` | `/settings` | Account preferences/password; Greek/English language |
| `POST` | `/language` | Language and cookie quick-switch (also on login) |
| `GET/POST` | `/admin/users` | Admin-managed accounts |
| `GET` | `/healthz` | Database readiness check |

Browser JSON operations require session login and the `X-CSRFToken` header populated from the rendered page. The endpoints are intended for the web UI, not a public unauthenticated API. Document bodies are currently capped at 1.75 MB; request bodies are capped at 2.5 MB.

## Validation and next patch updates

```bash
# After installing dev requirements
pip install -r requirements-dev.txt
pytest -q
bash scripts/check-syntax.sh
```

For **future changes**, updates will be delivered as a new `DatasetBuilder-patch-vX.Y.Z.zip` containing changed files only, a `PATCH_NOTES.md` with changed paths, migration steps and rollback notes, and a version bump. Apply a patch to a backed-up installation **after checking your current `VERSION`**; run migrations when indicated. Preserve `.env`, database and `data/knowledge_base` volumes when updating. For major version jumps, a full release ZIP can also be produced.

## Directory map

```text
DatasetBuilder/
  datasetbuilder/           Flask routes, models, security, i18n, services
    templates/              Bootstrap HTML
    static/css/             Dark responsive styles
    static/js/              Toast notifications + CodeMirror editor
    static/vendor/          Bundled Bootstrap and CodeMirror
  data/knowledge_base/      UTF-8 Markdown output (generated)
  examples/                 Supplied sample troubleshooting article
  migrations/versions/      Alembic schema history
  tests/                    Pytest test suite
  scripts/                  Dev runner, syntax check, nginx example
  Dockerfile                Gunicorn production container
  docker-compose.yml        PostgreSQL + Redis + application
  .env.example              Configuration template
  wsgi.py                   WSGI entry point
  VERSION                   Release and patch compatibility
```

**License:** no license grant is included. Decide an appropriate license or proprietary terms before redistribution.

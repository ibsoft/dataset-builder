# DatasetBuilder v1.0.0 — Initial Release

This is the **complete source distribution** for the first Flask release. Later requested modifications can be supplied as **update-only ZIP patches** following the instructions in `README.md`.

The initial package includes the original user-supplied TotalCare communication-loss Markdown example, UTF-8 Greek content support, English/Greek interface selection persisted to the user database and an HTTP-only cookie, structured sections with **+ / reorder / delete**, unlimited solutions per article, CodeMirror raw editing, a sanitized live preview, user attribution inside both the database and Markdown header, incremental revision history and restore, concurrent-save conflict detection, soft deletion, a complete ZIP export with manifest and history, admin-controlled user accounts, CSRF protections, PostgreSQL migrations and Docker deployment.

**Verification in the packaging environment:** Python syntax compilation, Jinja template compilation, JavaScript syntax validation, parsing of the original example, and execution of the initial SQLite schema migration all succeeded. The bundled Flask/HTTP integration tests could not be executed here because network access to Python package repositories was unavailable. Deployers should install the declared dependencies, run `pytest -q`, check reverse-proxy/TLS behavior and database permissions, and perform application security review before putting the service on the public internet.

There are no built-in default credentials. Follow `README.md` to set the secret key, migrate the database, and create your first administrator.

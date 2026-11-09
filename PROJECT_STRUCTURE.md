# DatasetBuilder tree

```
DatasetBuilder/
├── datasetbuilder/
│   ├── __init__.py      # Flask factory, CSRF, CSP, session setup
│   ├── auth.py          # Login / logout
│   ├── admin.py         # Admin user management
│   ├── commands.py      # Admin import / Markdown resync CLI
│   ├── i18n.py          # English + Greek UI translations
│   ├── markdown_utils.py # Parsing, sanitization, slugging
│   ├── models.py        # ORM user/article/revisions/audit
│   ├── services.py      # Atomic compare-and-swap update, history
│   ├── storage.py       # Atomic Markdown mirror to disk
│   ├── views.py         # Page / editor / preview / export API
│   ├── static/          # Bootstrap, CodeMirror, CSS and JS
│   └── templates/       # Jinja HTML templates
├── migrations/          # Alembic migration and schema
├── examples/            # Original provided TotalCare example
├── tests/               # Integration and CLI tests
├── data/                # Runtime DB and .md mirrors (excluded from ZIP)
├── docker-compose.yml   # PostgreSQL + Redis + Gunicorn
├── Dockerfile
├── wsgi.py
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── CHANGELOG.md
└── VERSION
```

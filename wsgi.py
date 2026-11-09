"""Gunicorn/Flask entry point: gunicorn 'wsgi:app'."""
from datasetbuilder import create_app
app = create_app()

"""Shared pagination settings for application tables."""
from flask import request

PAGE_SIZE = 24


def current_page():
    return max(request.args.get('page', 1, type=int), 1)

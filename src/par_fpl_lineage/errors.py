"""Extractor errors."""


class BaselineNotFound(Exception):
    """The baseline checkout (or DB_codebase within it) does not exist."""

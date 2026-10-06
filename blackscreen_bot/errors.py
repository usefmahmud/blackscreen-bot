"""Exceptions shared across the package."""

from __future__ import annotations


class ProcessingError(Exception):
    """An error whose message is safe to show to the end user."""

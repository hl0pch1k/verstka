"""Verstka: read any PPTX template as a set of rules and generate decks in its style."""

__version__ = "3.0.0"

from verstka import pkgzip as _pkgzip
from verstka.env import load_env as _load_env

_load_env()
_pkgzip.install()  # decks are saved with their pictures stored, not deflated again

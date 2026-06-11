"""Mampok — Kubernetes deployment manager for bioinformatics pipelines."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("mampok")
except PackageNotFoundError:
    __version__ = "unknown"

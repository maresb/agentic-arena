"""Agentic Arena — Multi-model consensus via Cursor Cloud Agents."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agentic-arena")
except PackageNotFoundError:
    __version__ = "unknown"

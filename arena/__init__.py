"""Agentic Arena — Multi-model consensus via Cursor Cloud Agents."""

try:
    from arena._version import __version__
except ImportError:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("agentic-arena")
    except PackageNotFoundError:
        __version__ = "unknown"

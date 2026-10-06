"""docflow: local filing of personal documents. The version is written ONCE, in pyproject.toml, and read from there."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("docflow")
except PackageNotFoundError:  # run from a copy that was never installed (no metadata): say so rather than invent a number
    __version__ = "0+unknown"

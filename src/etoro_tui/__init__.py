"""etoro-tui — terminal UI for eToro portfolio."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("etoro-tui")
except PackageNotFoundError:  # editable/source checkout without install
    __version__ = "0.0.0+local"

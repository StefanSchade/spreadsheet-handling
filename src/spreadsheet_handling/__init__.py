# Keep top-level import light-weight: no CLI side-effects here.
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("spreadsheet-handling")
except PackageNotFoundError:  # in editable installs / tests
    __version__ = "0+local"

__all__ = ["__version__"]

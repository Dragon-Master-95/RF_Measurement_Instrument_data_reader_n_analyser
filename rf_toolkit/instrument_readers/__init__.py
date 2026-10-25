# Instrument file readers.
#
# Every module in this folder is imported automatically, so a new reader only needs a
# new file here containing a @register_reader class (see README.md).

import importlib
import pkgutil

from .base import (
    Measurement,
    MeasurementReader,
    STANDARD_INFO_KEYS,
    available_readers,
    file_dialog_filter,
    get_reader,
    read_measurement_file,
    register_reader,
    supported_extensions,
)

_SKIP = {"base", "utils"}

for _module in pkgutil.iter_modules(__path__):
    if _module.name not in _SKIP and not _module.name.startswith("_"):
        importlib.import_module(f"{__name__}.{_module.name}")

__all__ = [
    "Measurement",
    "MeasurementReader",
    "STANDARD_INFO_KEYS",
    "available_readers",
    "file_dialog_filter",
    "get_reader",
    "read_measurement_file",
    "register_reader",
    "supported_extensions",
]

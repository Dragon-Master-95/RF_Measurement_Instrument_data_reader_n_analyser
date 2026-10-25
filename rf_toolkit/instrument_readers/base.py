# Core of the reader plug-in system.
#
#   Measurement       - what every reader returns (dataframe + info dict)
#   MeasurementReader - base class every file-format reader inherits from
#   register_reader   - decorator that adds a reader to the registry
#   read_measurement_file(path) - finds the right reader and reads the file
#
# To support a new instrument / file type, see README.md ("Adding a new file format").

import os
from dataclasses import dataclass, field

import pandas as pd

# Keys every Measurement.info has. Readers may add more keys.
STANDARD_INFO_KEYS = {
    "file_path": None,
    "file_format": None,        # extension without dot, e.g. "s2p"
    "manufacturer": None,       # e.g. "Anritsu"
    "instrument_type": None,    # "VNA" or "SA"
    "model_number": None,
    "serial_number": None,
    "measurement_time": None,   # datetime or None
    "n_points": None,
    "settings": {},             # instrument / sweep settings
    "calibration": {},          # calibration settings (VNA)
    "warnings": [],             # anything the user should know about this file
}


@dataclass
class Measurement:
    """Result of reading one file.

    data : DataFrame, first column Frequency_Hz, then the standard columns
           (s11_log_mag, s11_phase, ... for VNA; trace1, trace2, ... for SA)
    info : dict with at least the STANDARD_INFO_KEYS

    Can be unpacked like the old API:  df, info = read_measurement_file(path)
    """
    data: pd.DataFrame
    info: dict = field(default_factory=dict)

    def __post_init__(self):
        for key, default in STANDARD_INFO_KEYS.items():
            self.info.setdefault(key, default.copy() if isinstance(default, (dict, list)) else default)
        self.info["n_points"] = self.info["n_points"] or len(self.data)

    def __iter__(self):
        yield self.data
        yield self.info

    @property
    def name(self):
        return os.path.basename(self.info.get("file_path") or "measurement")

    @property
    def instrument_type(self):
        return self.info.get("instrument_type")

    @property
    def variables(self):
        """Column names usable in analysis formulas."""
        return list(self.data.columns)


class MeasurementReader:
    """Base class for file readers. Subclass it, set the class attributes, implement read()."""

    manufacturer = "Generic"
    instrument_type = None      # "VNA" or "SA"
    extensions = ()             # lower-case, with dot, e.g. (".spa",)
    description = ""            # shown in the GUI file dialog
    priority = 0                # higher wins when several readers accept the same file

    @classmethod
    def can_read(cls, file_path, head):
        """Return True if this reader handles the file.

        head is the first 4 kB of the file (bytes) so a reader can check the content,
        e.g. a manufacturer name, when several readers share an extension.
        """
        return os.path.splitext(file_path)[1].lower() in cls.extensions

    def read(self, file_path):
        """Read the file and return a Measurement."""
        raise NotImplementedError


_READERS = []


def register_reader(cls):
    """Class decorator: add a MeasurementReader subclass to the registry."""
    if cls not in _READERS:
        _READERS.append(cls)
    return cls


def available_readers():
    """All registered reader classes, highest priority first."""
    return sorted(_READERS, key=lambda r: -r.priority)


def get_reader(file_path):
    """Return an instance of the best reader for this file, or raise ValueError."""
    with open(file_path, "rb") as f:
        head = f.read(4096)
    for reader_cls in available_readers():
        if reader_cls.can_read(file_path, head):
            return reader_cls()
    raise ValueError(f"No reader available for '{os.path.basename(file_path)}'. "
                     f"Supported extensions: {', '.join(supported_extensions())}")


def read_measurement_file(file_path):
    """Read any supported measurement file and return a Measurement."""
    measurement = get_reader(file_path).read(file_path)
    measurement.info["file_path"] = file_path
    return measurement


def supported_extensions():
    return sorted({ext for r in _READERS for ext in r.extensions})


def file_dialog_filter():
    """Qt file-dialog filter string built from the registered readers."""
    groups = {}
    for r in available_readers():
        label = r.description or f"{r.manufacturer} {r.instrument_type or ''}".strip()
        groups.setdefault(label, set()).update(r.extensions)
    all_ext = " ".join(f"*{e}" for e in supported_extensions())
    parts = [f"All supported ({all_ext})"]
    parts += [f"{label} ({' '.join(f'*{e}' for e in sorted(exts))})" for label, exts in groups.items()]
    parts.append("All files (*)")
    return ";;".join(parts)

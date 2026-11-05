# Measall readers (KC901 series handheld analysers, tested with KC901S+)
#
#   MeasallIniReader        : .ini  full sweep data ("[Curve]" with F:<Hz>,<value> lines)
#   MeasallKcdReader        : .kcd  instrument state file; uses the companion .ini (same name)
#                                   when present, otherwise the on-screen max envelope
#   MeasallTouchstoneReader : .s2p  Touchstone with the instrument settings as '!' comments
#
# The .bmp files next to them are screenshots and are not read.
# File layout notes are in README.md ("File format notes").

import os
import re
from datetime import datetime

import numpy as np
import pandas as pd

from .base import Measurement, MeasurementReader, register_reader
from .touchstone import TouchstoneReader
from .utils import FREQUENCY_COLUMN, read_text_lines, sparam_columns, to_number

# Mode name in the .ini [Mode] section -> (standard column, unit, how the value is stored)
#   "db"    : log magnitude in dB  -> <sparam>_log_mag
#   "delay" : group delay in s     -> <sparam>_group_delay
INI_MODES = {
    "s11_loss": ("s11_log_mag", "dB", "db"),
    "s21_loss": ("s21_log_mag", "dB", "db"),
    "group delay": ("s21_group_delay", "s", "delay"),
}

# "F:15000000,-2.752960"  or  "F: 536959380,delay:-1.598705e-08s"
_POINT = re.compile(r"^F:\s*([-+0-9.eE]+)\s*,\s*(?:[A-Za-z ]+:)?\s*([-+0-9.eE]+)\s*([A-Za-z]*)\s*$")
# File names such as "S11_Loss_00_01_10 23_30_07" = YY_MM_DD HH_MM_SS (instrument clock)
_NAME_TIME = re.compile(r"(\d{2})_(\d{2})_(\d{2}) (\d{2})_(\d{2})_(\d{2})")


def parse_ini_sections(lines):
    """INI-style text -> {section: {key: value}}; keys outside a section go to ''."""
    sections, current = {"": {}}, ""
    for line in lines:
        line = line.strip().lstrip("!").strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
        elif "=" in line:
            key, value = line.split("=", 1)
            sections[current][key.strip()] = to_number(re.sub(r"Hz$", "", value.strip()))
    return sections


def _find(sections, key):
    """First value of key in any section."""
    for values in sections.values():
        if key in values:
            return values[key]
    return None


def _time_from_name(file_path):
    m = _NAME_TIME.search(os.path.basename(file_path))
    if not m:
        return None
    yy, mo, dd, h, mi, s = (int(x) for x in m.groups())
    try:
        return datetime(2000 + yy, mo, dd, h, mi, s)
    except ValueError:
        return None


def _base_info(file_path, sections, file_format):
    cent, span = _find(sections, "CENT"), _find(sections, "SPAN")
    settings = {"center_freq_Hz": cent, "span_Hz": span}
    if isinstance(cent, (int, float)) and isinstance(span, (int, float)):
        settings.update(start_freq_Hz=cent - span / 2, stop_freq_Hz=cent + span / 2)
    for section, key, name in (("CAL", "CAL", "calibration"), ("SweepPoint", "Point", "sweep_points"),
                               ("AMP", "LEV", "ref_level"), ("AMP", "Step", "scale_per_div")):
        if key in sections.get(section, {}):
            settings[name] = sections[section][key]
    return {
        "file_format": file_format,
        "manufacturer": "Measall",
        "instrument_type": "VNA",
        "model_number": None,          # not stored in the files
        "instrument_name": "Measall KC901 series",
        "measurement_time": _time_from_name(file_path),
        "settings": settings,
        "calibration": {"CAL": _find(sections, "CAL")},
        "sections": sections,
        "warnings": [],
    }


def _frequency_axis(freq, info, warnings):
    """Use the stored frequencies unless they are all identical (group-delay files store one
    fixed value); then rebuild a linear axis from CENT / SPAN."""
    if len(freq) > 1 and np.all(np.diff(freq) > 0):
        return freq
    s = info["settings"]
    if s.get("start_freq_Hz") is None:
        raise ValueError("frequency column is not usable and CENT/SPAN are missing")
    warnings.append("stored frequencies are not increasing (all equal); axis rebuilt from CENT/SPAN")
    return np.linspace(s["start_freq_Hz"], s["stop_freq_Hz"], len(freq))


def _column_for_mode(mode, warnings):
    key = str(mode).strip().lower()
    if key in INI_MODES:
        return INI_MODES[key]
    col = re.sub(r"\W+", "_", key).strip("_") or "value"
    warnings.append(f"unknown measurement mode '{mode}'; data stored in column '{col}'")
    return col, "", "raw"


def _is_measall_text(head):
    return b"[Mode]" in head and (b"[Curve" in head or b"[Freq]" in head or b"[SweepPoint]" in head)


# ----------------------------------------------------------------------------------------
@register_reader
class MeasallIniReader(MeasurementReader):
    manufacturer = "Measall"
    instrument_type = "VNA"
    extensions = (".ini",)
    description = "Measall KC901 data"
    priority = 10

    @classmethod
    def can_read(cls, file_path, head):
        return super().can_read(file_path, head) and _is_measall_text(head)

    def read(self, file_path):
        lines = read_text_lines(file_path)
        sections = parse_ini_sections([ln for ln in lines if not ln.lstrip().startswith("F:")])
        info = _base_info(file_path, sections, "ini")
        warnings = info["warnings"]

        freq, value, units = [], [], set()
        for ln in lines:
            m = _POINT.match(ln.strip())
            if m:
                freq.append(float(m.group(1)))
                value.append(float(m.group(2)))
                units.add(m.group(3))
        if not freq:
            raise ValueError(f"No [Curve] data found in {file_path}")

        mode = sections.get("Mode", {}).get("Name", "")
        column, unit, _ = _column_for_mode(mode, warnings)
        freq = _frequency_axis(np.array(freq), info, warnings)
        df = pd.DataFrame({FREQUENCY_COLUMN: freq, column: np.array(value)})

        declared = sections.get("SweepPoint", {}).get("Point")
        if isinstance(declared, int) and declared not in (len(df), len(df) - 1):
            warnings.append(f"file declares {declared} sweep points but contains {len(df)}")
        info.update(measurement_mode=mode, value_unit=unit or "".join(sorted(units)))
        return Measurement(df, info)


# ----------------------------------------------------------------------------------------
@register_reader
class MeasallKcdReader(MeasurementReader):
    manufacturer = "Measall"
    instrument_type = "VNA"
    extensions = (".kcd",)
    description = "Measall KC901 state"
    priority = 10

    def read(self, file_path):
        sections = parse_ini_sections(read_text_lines(file_path))
        companion = os.path.splitext(file_path)[0] + ".ini"
        if os.path.exists(companion):
            m = MeasallIniReader().read(companion)
            m.info["file_format"] = "kcd"
            m.info["kcd_sections"] = sections
            m.info["warnings"].append(f"data taken from the companion file {os.path.basename(companion)}")
            return m

        # No .ini: only the on-screen envelope (one max value per display column) exists
        info = _base_info(file_path, sections, "kcd")
        curve = sections.get("Curve_Max", {})
        idx = sorted(int(k[1:-4]) for k in curve if re.fullmatch(r"P\d+_Max", k))
        if not idx:
            raise ValueError(f"{os.path.basename(file_path)} has no trace data and no companion .ini")
        freq = np.array([float(curve[f"P{i}_Freq"]) for i in idx])
        level = np.array([float(curve[f"P{i}_Max"]) for i in idx])
        # The .kcd mode is a number; only 0 (reflection, S11) is confirmed from the samples
        mode = sections.get("Mode", {}).get("Name")
        column = "s11_log_mag" if mode == 0 else "s21_log_mag"
        info["warnings"].append(f"no companion .ini: using the on-screen max envelope "
                                f"({len(idx)} points) instead of the full sweep")
        info["measurement_mode"] = mode
        return Measurement(pd.DataFrame({FREQUENCY_COLUMN: freq, column: level}), info)


# ----------------------------------------------------------------------------------------
@register_reader
class MeasallTouchstoneReader(TouchstoneReader):
    manufacturer = "Measall"
    description = "Touchstone"
    priority = 10

    @classmethod
    def can_read(cls, file_path, head):
        return (os.path.splitext(file_path)[1].lower() in cls.extensions
                and b"![Freq]" in head and b"!CENT=" in head)

    def read(self, file_path):
        m = super().read(file_path)
        m.info["measurement_time"] = _time_from_name(file_path)
        return m

    def parse_comments(self, comments):
        sections = parse_ini_sections(comments)
        info = _base_info("", sections, "s2p")
        info.pop("measurement_time")
        info.pop("warnings")
        return info

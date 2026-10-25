# Shared helpers for all readers: text parsing and the standard column naming.
#
# Standard dataframe columns (used by the analysis engine and the GUI):
#   Frequency_Hz                       - always the first column
#   s11_log_mag, s11_phase, s21_...    - VNA S-parameters, log magnitude (dB) and phase (deg)
#   trace1, trace2, ...                - spectrum analyser traces, power in dB units (e.g. dBm)

import numpy as np

# Frequency unit multipliers (to Hz)
FREQ_UNITS = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}

FREQUENCY_COLUMN = "Frequency_Hz"


def sparam_columns(df, name, values):
    """Add <name>_log_mag (dB) and <name>_phase (deg) columns from complex values."""
    values = np.asarray(values, dtype=complex)
    name = name.lower()
    with np.errstate(divide="ignore"):
        df[name + "_log_mag"] = 20 * np.log10(np.abs(values))
        df[name + "_phase"] = np.degrees(np.angle(values))


def trace_column(number):
    """Standard name of spectrum analyser trace <number> (1-based): trace1, trace2, ..."""
    return f"trace{number}"


def to_number(value):
    """Convert a text value to int/float when possible, otherwise return the stripped text."""
    value = value.strip()
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer() and "." not in value and "E" not in value.upper():
        return int(number)
    return number


def parse_key_values(lines):
    """Parse KEY=VALUE lines into a dict (later duplicates overwrite earlier ones)."""
    params = {}
    for line in lines:
        if "=" in line and not line.startswith(("#", "<")):
            key, value = line.split("=", 1)
            params[key.strip()] = to_number(value)
    return params


def section(lines, start_marker, end_marker):
    """Return the lines between the first start_marker line and the next end_marker line."""
    try:
        start = lines.index(start_marker) + 1
    except ValueError:
        return []
    for i in range(start, len(lines)):
        if lines[i] == end_marker:
            return lines[start:i]
    return lines[start:]


def read_text_lines(file_path):
    """Read a text file into a list of lines without line endings."""
    with open(file_path, "r", errors="replace") as f:
        return [ln.rstrip("\r\n") for ln in f]

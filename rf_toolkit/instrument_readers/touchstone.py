# Generic Touchstone v1 reader (.s1p ... .s4p), any manufacturer.
#
# Manufacturer-specific readers can subclass TouchstoneReader and only override
# parse_comments() to pull instrument / calibration info from the '!' header lines
# (see AnritsuTouchstoneReader in anritsu.py).

import os
import re

import numpy as np
import pandas as pd

from .base import Measurement, MeasurementReader, register_reader
from .utils import FREQ_UNITS, FREQUENCY_COLUMN, read_text_lines, sparam_columns


@register_reader
class TouchstoneReader(MeasurementReader):
    manufacturer = "Generic"
    instrument_type = "VNA"
    extensions = (".s1p", ".s2p", ".s3p", ".s4p")
    description = "Touchstone"
    priority = 0

    def parse_comments(self, comments):
        """Override in a subclass to extract instrument info from '!' lines.

        Must return a dict of info keys (e.g. model_number, settings, calibration).
        """
        return {}

    def read(self, file_path):
        lines = read_text_lines(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        m = re.fullmatch(r"\.s(\d+)p", ext)
        n_ports = int(m.group(1)) if m else 2

        # Option line: "# <freq unit> <parameter> <format> R <impedance>"
        freq_unit, data_format, ref_impedance, param_type = "GHZ", "MA", 50.0, "S"
        numbers, comments = [], []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("!"):
                comments.append(stripped[1:].rstrip())
                continue
            if stripped.startswith("#"):
                tokens = stripped[1:].upper().split()
                for i, tok in enumerate(tokens):
                    if tok in FREQ_UNITS:
                        freq_unit = tok
                    elif tok in ("MA", "DB", "RI"):
                        data_format = tok
                    elif tok in ("S", "Y", "Z", "H", "G"):
                        param_type = tok
                    elif tok == "R" and i + 1 < len(tokens):
                        ref_impedance = float(tokens[i + 1])
                continue
            numbers.extend(float(x) for x in stripped.split("!")[0].split())

        # Each row: freq + 2 numbers per parameter (also handles wrapped lines)
        data = np.array(numbers).reshape(-1, 1 + 2 * n_ports * n_ports)
        a, b = data[:, 1::2], data[:, 2::2]
        if data_format == "RI":
            values = a + 1j * b
        elif data_format == "MA":
            values = a * np.exp(1j * np.radians(b))
        else:  # DB
            values = 10 ** (a / 20) * np.exp(1j * np.radians(b))

        # Touchstone column order: 2-port is 11 21 12 22, otherwise row-major
        if n_ports == 2:
            names = ["11", "21", "12", "22"]
        else:
            names = [f"{i}{j}" for i in range(1, n_ports + 1) for j in range(1, n_ports + 1)]
        names = [param_type + n for n in names]

        df = pd.DataFrame({FREQUENCY_COLUMN: data[:, 0] * FREQ_UNITS[freq_unit]})
        placeholders = []
        for k, name in enumerate(names):
            sparam_columns(df, name, values[:, k])
            if np.all(values[:, k] == values[0, k]):
                placeholders.append(name.lower())  # constant = not measured

        info = {
            "file_format": ext.lstrip("."),
            "manufacturer": self.manufacturer if self.manufacturer != "Generic" else None,
            "instrument_type": "VNA",
            "n_ports": n_ports,
            "options": {"frequency_unit": freq_unit, "parameter": param_type,
                        "format": data_format, "reference_impedance_ohm": ref_impedance},
            "placeholder_parameters": placeholders,
            "comments": comments,
        }
        info.update(self.parse_comments(comments))
        if placeholders:
            info.setdefault("warnings", []).append(
                f"constant (not measured) parameters: {', '.join(placeholders)}")
        return Measurement(df, info)

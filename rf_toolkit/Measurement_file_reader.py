# Measurement File Reader
# Reads measurement files of different formats and instruments and returns a standardized data structure.
#
# This file is the public entry point. The actual readers live in instrument_readers/
# (one file per manufacturer). To add a new file type or instrument, add a reader there;
# nothing in this file needs to change. See README.md.
#
# Every read returns a Measurement:
#   measurement.data : DataFrame, first column Frequency_Hz, then
#                      VNA -> s11_log_mag | s11_phase | s21_log_mag | s21_phase | ...
#                      SA  -> trace1 | trace2 | ...   (power in dB units, e.g. dBm)
#   measurement.info : dict with instrument, settings, calibration, warnings, ...
# It can also be unpacked:  df, info = read_measurement_file(path)

#Import necessary libraries
import os

from .instrument_readers import (Measurement, available_readers, file_dialog_filter, get_reader,
                                read_measurement_file, supported_extensions)


# Class to read measurement files (works for every registered instrument / file type)
class MeasurementFileReader:
    def __init__(self, model_number=None, instrument_type=None, file_format=None):
        # Either the user provides these or they are taken from the measurement file
        self.model_number = model_number        # e.g. "MS2024B", "MS2720T"
        self.instrument_type = instrument_type  # "VNA" or "SA"
        self.file_format = file_format          # "s2p", "mna", "spa", ...

    def read_measurement_file(self, file_path):
        measurement = read_measurement_file(file_path)
        info = measurement.info
        # user-given values fill in anything the file did not provide
        info["model_number"] = info.get("model_number") or self.model_number
        info["instrument_type"] = info.get("instrument_type") or self.instrument_type
        self.model_number = info["model_number"]
        self.instrument_type = info["instrument_type"]
        self.file_format = info["file_format"]
        return measurement


# Old name kept so existing scripts keep working
Anritsu_MeasurementFileReader = MeasurementFileReader

__all__ = ["Measurement", "MeasurementFileReader", "Anritsu_MeasurementFileReader",
           "read_measurement_file", "get_reader", "available_readers",
           "supported_extensions", "file_dialog_filter"]


# Main function for testing the MeasurementFileReader class
if __name__ == "__main__":
    print("Registered readers:")
    for r in available_readers():
        print(f"  {r.__name__:26s} {r.manufacturer:8s} {r.instrument_type or '':4s} {', '.join(r.extensions)}")

    from .paths import DATA_DIR
    base = os.path.join(DATA_DIR, "Anritsu")
    examples = [
        os.path.join(base, "MS2024B_VNA", "hlf400cc_s21_2.s2p"),
        os.path.join(base, "MS2024B_VNA", "hlf400cc_s21_1.mna"),
        os.path.join(base, "MS2720T_SA", "east.spa"),
    ]
    for path in examples:
        if not os.path.exists(path):
            continue
        reader = MeasurementFileReader()
        data, info = reader.read_measurement_file(path)
        print("=" * 80)
        print(os.path.basename(path), "|", reader.model_number, reader.instrument_type, reader.file_format,
              "|", info.get("measurement_time"), "|", info["n_points"], "points")
        print("settings:", info["settings"])
        print(data.head())

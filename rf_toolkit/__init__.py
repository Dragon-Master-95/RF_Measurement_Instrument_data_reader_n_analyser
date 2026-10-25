# RF measurement toolkit: read instrument files, analyse with formulas, GUI.
#
#   rf_toolkit.Measurement_file_reader  - read_measurement_file(path) -> Measurement
#   rf_toolkit.Measurement_analysis     - MeasurementAnalyzer, save_results_csv
#   rf_toolkit.Measurement_analysis_GUI - run() starts the GUI (needs Qt)
#   rf_toolkit.instrument_readers       - one reader module per manufacturer
#   rf_toolkit.paths                    - project / Data_files folder locations
#
# Shortcuts such as rf_toolkit.read_measurement_file are loaded on first use, so
# 'python -m rf_toolkit.<module>' runs cleanly and the GUI (Qt) is never imported
# unless asked for.

import importlib

_SHORTCUTS = {
    "Measurement": "Measurement_file_reader",
    "MeasurementFileReader": "Measurement_file_reader",
    "read_measurement_file": "Measurement_file_reader",
    "MeasurementAnalyzer": "Measurement_analysis",
    "save_results_csv": "Measurement_analysis",
}

__all__ = list(_SHORTCUTS)


def __getattr__(name):
    if name in _SHORTCUTS:
        module = importlib.import_module(f"{__name__}.{_SHORTCUTS[name]}")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

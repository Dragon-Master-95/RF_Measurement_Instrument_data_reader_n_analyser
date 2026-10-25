# RF Measurement Instrument Data Reader & Analyser

A toolkit that reads measurement files from RF instruments (VNAs and spectrum analysers),
turns them into one standard table format, and lets you analyse and plot them with
formulas in a GUI or from Python.

**Supported today**

| Manufacturer | Instrument (tested) | File | Reader class |
|---|---|---|---|
| Any | any VNA | `.s1p` – `.s4p` Touchstone v1 | `TouchstoneReader` |
| Anritsu | VNA Master MS2024B | `.s1p` – `.s4p` with Anritsu header | `AnritsuTouchstoneReader` |
| Anritsu | VNA Master MS2024B | `.mna` (native) | `AnritsuMnaReader` |
| Anritsu | Spectrum Master MS2720T | `.spa` (native) | `AnritsuSpaReader` |

---

## 1. Quick start

```bash
pip install -r requirements.txt
python main.py                          # open the GUI
python main.py Data_files/Anritsu/MS2720T_SA/*.spa   # open with files loaded
python -m pytest tests                  # run the tests
python -m rf_toolkit.Measurement_file_reader   # reader demo on sample files
python -m rf_toolkit.Measurement_analysis      # formula demo
```

From Python:

```python
from rf_toolkit.Measurement_file_reader import read_measurement_file
from rf_toolkit.Measurement_analysis import MeasurementAnalyzer, save_results_csv
# or simply: import rf_toolkit; rf_toolkit.read_measurement_file(...)

m = read_measurement_file("Data_files/Anritsu/MS2024B_VNA/hlf400cc_s21_2.s2p")
m.data        # DataFrame: Frequency_Hz, s11_log_mag, s11_phase, s21_log_mag, ...
m.info        # dict: model_number, settings, calibration, warnings, ...
df, info = m  # unpacks like the old (df, info) API

r = MeasurementAnalyzer().analyse(m, "rl = -s11_log_mag\nworst = max(vswr(s11_log_mag))")
r.data        # Frequency_Hz, rl
r.scalars     # {'worst': 1.58}
save_results_csv([r], "results.csv")
```

---

## 2. Project layout

```
main.py                        Starts the GUI (python main.py [files...])
requirements.txt               Python dependencies
README.md                      This file
rf_toolkit/                    All code (Python package)
    __init__.py                Shortcuts: rf_toolkit.read_measurement_file, ...
    paths.py                   Project / Data_files folder locations
    Measurement_file_reader.py Public reading API. Thin wrapper, no format code here.
    Measurement_analysis.py    Formula engine + formula functions + CSV export
    Measurement_analysis_GUI.py Qt GUI main window
    plotting.py                PlotStyle + draw_results(): all plotting, no Qt (testable)
    plot_settings_dialog.py    "Plot settings" window that edits a PlotStyle
    qt_compat.py               Picks the Qt binding (PySide6 / PySide2 / PyQt5)
    instrument_readers/        One module per manufacturer / format (plug-ins)
        __init__.py            Auto-imports every module in this folder
        base.py                Measurement, MeasurementReader, registry, read_measurement_file
        utils.py               Shared parsing helpers + standard column naming
        touchstone.py          Generic Touchstone reader
        anritsu.py             Anritsu .s2p header, .mna, .spa
tests/test_toolkit.py          Reads every file in Data_files/ + analysis tests
Data_files/<Maker>/<Model>/    Sample measurement files (used by the tests)
```

How data flows:

```
file ──► instrument_readers.get_reader(path)          picks a reader (extension + content)
     ──► Reader.read(path) ──► Measurement(data, info) standard table + info dict
     ──► MeasurementAnalyzer.analyse(m, formulas) ──► AnalysisResult(data, scalars, errors)
     ──► GUI plot / table / CSV
```

---

## 3. The data standard (read this before changing anything)

Everything downstream (formulas, GUI, CSV) relies on these names. A new reader must
produce them; do not invent new column names for the same quantity.

### 3.1 `Measurement.data` columns

| Instrument | Columns | Units |
|---|---|---|
| all | `Frequency_Hz` (always first) | Hz |
| VNA | `s11_log_mag`, `s11_phase`, `s21_log_mag`, `s21_phase`, `s12_…`, `s22_…` | dB (20·log10), degrees |
| VNA, same S-parameter on two traces (.mna) | second one: `s11_tr3_log_mag`, `s11_tr3_phase` | |
| SA | `trace1`, `trace2`, … (trace A → `trace1`) | power, dB units in `info["amplitude_unit"]` (e.g. dBm) |

Use the helpers in `rf_toolkit/instrument_readers/utils.py`:
`sparam_columns(df, "S21", complex_values)` and `trace_column(1)`. They are the
single place where the naming is defined; change naming there, not in each reader.

### 3.2 `Measurement.info` keys

Always present (filled with defaults by `Measurement.__post_init__`, defined in
`STANDARD_INFO_KEYS` in `rf_toolkit/instrument_readers/base.py`):

| Key | Meaning |
|---|---|
| `file_path`, `file_format` | path, extension without dot |
| `manufacturer`, `instrument_type` | e.g. `"Anritsu"`, `"VNA"` / `"SA"` |
| `model_number`, `serial_number` | from the file when available |
| `measurement_time` | `datetime` or `None` |
| `n_points` | number of rows |
| `settings` | dict of instrument / sweep settings |
| `calibration` | dict of calibration settings (VNA) |
| `warnings` | list of strings shown to the user (GUI status log) |

Readers can add more keys (`markers`, `limits`, `amplitude_unit`, `raw_parameters`, …).
The GUI shows every key automatically; `header`, `raw_parameters` and `comments` are
only shown when "Show raw parameters" is ticked (`RAW_INFO_KEYS` in the GUI file).

Units convention in `settings`: frequencies in Hz with an `_Hz` suffix, levels with
`_dB`, times with `_s`. Raw instrument codes that are not decoded get a `_code`
suffix (e.g. `ifbw_code`) so nobody mistakes them for real values.

---

## 4. Where to edit for common upgrades

| I want to… | Edit |
|---|---|
| Support a new file type / instrument / manufacturer | add a module in `rf_toolkit/instrument_readers/` (section 5) |
| Add Anritsu header parsing for another model | `rf_toolkit/instrument_readers/anritsu.py` |
| Add info fields to an existing reader | the `info = {...}` dict in that reader's `read()` |
| Change standard column names | `rf_toolkit/instrument_readers/utils.py` (+ this README, tests, GUI help text) |
| Add a standard info key | `STANDARD_INFO_KEYS` in `rf_toolkit/instrument_readers/base.py` |
| Add a function usable in formulas | `FUNCTIONS` in `rf_toolkit/Measurement_analysis.py` (section 6) |
| Add a function that needs the frequency axis | `_make_frequency_functions()` in `rf_toolkit/Measurement_analysis.py` |
| Allow more Python syntax in formulas | `_ALLOWED_NODES` in `rf_toolkit/Measurement_analysis.py` (keep it safe) |
| Change default formulas per instrument | `DEFAULT_FORMULAS` in `rf_toolkit/Measurement_analysis_GUI.py` |
| Add a plot mode | `PLOT_MODES` + `_plan()` in `rf_toolkit/plotting.py` |
| Add a plot setting (e.g. y log scale) | field in `PlotStyle` + use it in `draw_results()` (`rf_toolkit/plotting.py`) + one `self._add_…()` line in `_build_general_tab()` (`rf_toolkit/plot_settings_dialog.py`) |
| Add a per-line option (e.g. alpha) | `LINE_KEYS` / `draw_results()` in `plotting.py` + a column in `_fill_lines()` in `plot_settings_dialog.py` |
| Add line styles, markers, palettes, legend positions | `LINE_STYLES`, `MARKERS`, `PALETTES`, `LEGEND_LOCATIONS` in `rf_toolkit/plotting.py` |
| Add a toolbar button | `_build_actions()` in `rf_toolkit/Measurement_analysis_GUI.py` |
| Change the info panel layout | `format_info()` / `GENERAL_INFO_KEYS` in `rf_toolkit/Measurement_analysis_GUI.py` |
| Change how files are labelled in formulas (f1, f2, …) | `file_label()` / `file_variable()` in `rf_toolkit/Measurement_analysis.py` |
| Change the cross-file frequency grid / interpolation | `_analyse_combined()` / `_interpolate()` in `rf_toolkit/Measurement_analysis.py` |
| Change the CSV format | `save_results_csv()` / `results_to_dataframe()` in `rf_toolkit/Measurement_analysis.py` |
| Change where sample data lives | `rf_toolkit/paths.py` |
| Add sample files for testing | `Data_files/<Maker>/<Model>/`; the tests pick them up automatically |

The GUI file dialog filter, the help page's "Supported files" list and the
start-up log line are built from the reader registry, so new readers appear in
the GUI without GUI changes.

---

## 5. Adding a new file format / instrument

### 5.1 Steps

1. Put a few sample files in `Data_files/<Maker>/<Model>/`.
2. Create `rf_toolkit/instrument_readers/<maker>.py` (any name not starting with `_`;
   `base` and `utils` are reserved). It is imported automatically.
3. Write a class that subclasses `MeasurementReader`, decorate it with
   `@register_reader`, set the class attributes and implement `read()`.
4. Return `Measurement(df, info)` using the standard columns (section 3).
5. Run `python -m pytest tests`. Every sample file is read and its columns are
   checked against the standard.
6. Add a row to the "Supported today" table at the top of this README and,
   if the format is binary or undocumented, a note in section 8.

### 5.2 Template

```python
# rf_toolkit/instrument_readers/keysight.py
import numpy as np
import pandas as pd

from .base import Measurement, MeasurementReader, register_reader
from .utils import FREQUENCY_COLUMN, read_text_lines, sparam_columns, trace_column


@register_reader
class KeysightCsvSpectrumReader(MeasurementReader):
    manufacturer = "Keysight"
    instrument_type = "SA"                 # "VNA" or "SA"
    extensions = (".csv",)                 # lower case, with dot
    description = "Keysight spectrum CSV"  # label in the GUI file dialog
    priority = 10                          # beats generic readers of the same extension

    @classmethod
    def can_read(cls, file_path, head):
        # head = first 4 kB of the file as bytes. Check the content when the
        # extension is shared with other readers (.csv, .txt, .s2p, ...).
        return super().can_read(file_path, head) and b"Keysight" in head

    def read(self, file_path):
        lines = read_text_lines(file_path)
        freq_hz, power_dbm = ..., ...                 # parse the file here

        df = pd.DataFrame({FREQUENCY_COLUMN: freq_hz})
        df[trace_column(1)] = power_dbm                # -> "trace1"
        # VNA instead:  sparam_columns(df, "S11", complex_values)

        info = {
            "file_format": "csv",
            "manufacturer": "Keysight",
            "instrument_type": "SA",
            "model_number": ...,
            "measurement_time": ...,                   # datetime or None
            "amplitude_unit": "dBm",
            "settings": {"rbw_Hz": ..., "span_Hz": ...},
            "warnings": [],
        }
        return Measurement(df, info)
```

### 5.3 How the reader is chosen

`get_reader(path)` reads the first 4 kB of the file, then asks every registered reader
`can_read(path, head)`, highest `priority` first, and uses the first that says yes.

* Generic readers use `priority = 0`, manufacturer-specific ones `10`.
* If two readers share an extension, the specific one must check the content in
  `can_read` (as `AnritsuTouchstoneReader` does with `b"Anritsu" in head`), otherwise it
  would also take files from other makers.

### 5.4 Extending Touchstone for another manufacturer

The numeric Touchstone parsing is shared. To read a maker's `!` comment header
(model, calibration, …), subclass `TouchstoneReader` and override only
`parse_comments(self, comments) -> dict`; see `AnritsuTouchstoneReader` in `anritsu.py`.

### 5.5 Reader options

Readers are created with no arguments by `get_reader`. Options need defaults in
`__init__` (e.g. `AnritsuMnaReader(all_traces=True)`); use them directly:
`AnritsuMnaReader(all_traces=True).read(path)`.

---

## 6. Analysis formulas

Written in the GUI formula box or passed to `MeasurementAnalyzer.analyse()`:

```
return_loss = -s11_log_mag          # named result
vswr(s11_log_mag)                   # unnamed: the expression is the name
delay_ns = group_delay(s21_phase) * 1e9
peak = max(trace1)                  # single value -> AnalysisResult.scalars
in_band = max(band(trace1, 400e6, 500e6))
```

* One formula per line, `#` starts a comment, later lines can use earlier names.
* Variables: the data columns plus `freq` (Hz), `freq_kHz`, `freq_MHz`, `freq_GHz`,
  and constants `pi`, `e`, `c0`.
* Formulas are parsed with `ast` and only whitelisted syntax runs (numbers, names,
  arithmetic, calls to listed functions). Attribute access, imports, indexing,
  lambdas etc. are rejected, so the formula box cannot run arbitrary Python.
* An error on one line is reported (`AnalysisResult.errors`) and the other lines still run.

### Formulas across several files

Each file gets a label from its position in the file list: `f1`, `f2`, `f3`, …
(`file_label()` in `rf_toolkit/Measurement_analysis.py`). Every variable is also available
with the label in front, and so are named per-file results:

```
rl = -s11_log_mag                            # per file: runs on f1, f2, ... separately
cable_loss = f2_s21_log_mag - f1_s21_log_mag # combined: runs once
worst = min(cable_loss)                      # uses a combined result -> combined too
rl_change = f2_rl - f1_rl                    # per-file result 'rl' of f1 and f2
east_minus_west = f1_trace1 - f2_trace1      # spectrum analyser files
```

* `split_formulas()` decides per line: a line is **combined** (cross-file) if it uses an
  `fN_…` name or the result of an earlier combined line; otherwise it is **per file**.
* Per-file lines run first for every file, then combined lines run once and produce one
  extra `AnalysisResult` with `label == "combined"`.
* Combined lines use the frequency points of the first analysed file. The other files
  are interpolated onto them (`_interpolate()`; phase is unwrapped first; NaN outside a
  file's range) and a warning is added to the combined result.
* `analyse_many(measurements, text, labels)`: the GUI passes the list positions of the
  ticked files as labels, so unticking a file does not renumber the others. Removing a
  file from the list does renumber them.
* Plain names (`s21_log_mag`) are not available in a combined line; the error message
  suggests the labelled name.

### Adding a formula function

```python
# rf_toolkit/Measurement_analysis.py
def noise_floor(x, percentile=10):
    """Noise floor estimate: the given percentile of x."""
    return float(np.nanpercentile(x, percentile))

FUNCTIONS["noise_floor"] = noise_floor          # or register_function("noise_floor", noise_floor)
```

The first line of the docstring is shown in the GUI help. If the function needs the
frequency axis, define it inside `_make_frequency_functions(freq)` instead.

Return either an array with one value per frequency point (plotted) or a single
number (listed as a scalar). Other shapes are reported as errors.

---

## 7. GUI overview (`rf_toolkit/Measurement_analysis_GUI.py`)

| Area | Widget / method |
|---|---|
| Toolbar | `_build_actions()`: open, remove, clear, run, save CSV, save plot, help |
| Left | loaded files (tick = include in analysis), variables (double-click inserts) |
| Centre | tabs Data / Plot / Results, formula box, plot mode, x-axis unit |
| Right | measurement info (`format_info()`), "Show raw parameters" |
| Bottom | status log (`log(msg, level)`; levels `info`, `ok`, `warn`, `error`) |

* Loading many files: `load_files()` warns when instrument types are mixed.
* Plot modes: all on one axis, one subplot per file, one subplot per formula.
* CSV: one file → plain table; several files → one long table with `file` and `label`
  columns (the combined result has label `combined`).
* File list shows `f1: name`; the Variables panel also lists the selected file's `fN_…` names.
* **Plot settings…** (Ctrl+P, toolbar or the button next to *Run analysis*) opens a window
  that redraws the plot on every change:
  * *General*: figure title, X / Y label, title / subplot title / axis label / tick / legend
    font sizes, legend on/off and position (incl. outside right, below plot), grid,
    logarithmic X, X/Y limits (X in the selected x-axis unit), default line width,
    colour palette, export DPI.
  * *Subplots*: title and Y label per subplot.
  * *Lines*: show/hide, legend label, colour, line style, width, marker per line.
  * *Reset all*, *Save style… / Load style…* (JSON) to reuse a look across sessions.
  Blank / `auto` means automatic. Line settings are keyed by `"<f1: file> | <formula>"`, so
  they survive re-running the analysis as long as the file label and formula name stay.
* The settings live in one `PlotStyle` object (`rf_toolkit/plotting.py`); `draw_results()`
  is the only plotting code, so the GUI, saved images and scripts all look the same.
* Qt binding: tries PySide6, then PySide2, then PyQt5 (`rf_toolkit/qt_compat.py`). Matplotlib's
  `QtAgg` backend works with all three.

---

## 8. File format notes

### Touchstone (`.sNp`)
Option line `# <unit> <param> <MA|DB|RI> R <Z0>`. 2-port data order is
S11 S21 S12 S22; wrapped lines are handled by reading all numbers and reshaping.
Parameters that are constant over frequency are listed in
`info["placeholder_parameters"]` (VNA Master is 1-path 2-port, so S12/S22 are dummy).

Anritsu header: two columns, *Current Settings* → `info["settings"]`,
*Active Cal Settings* → `info["calibration"]`.

### Anritsu `.mna` (VNA Master native)
Not documented by Anritsu; the layout was worked out from sample files and checked
against `.s2p` files saved from the same sweep (S21 within 0.01 dB).

* Text part: `<ANRITSU>` header (MODEL, SN, DATE = `YYYY-MM-DD-weekday-HH-MM-SS`),
  `<MWVNA PARAMETERS>` (`KEY=value`, frequencies in MHz), `<MWVNA MARKERS>` (frequency in mHz),
  `<MWVNA LIMITS>`, `<MWVNA CAL KITS>`.
* `<BINARY DATA>`: blocks. Block 0 header = `uint32 0, uint32 records+1, uint32 ?, uint32 type(0),
  uint32 1, uint8 0, uint32 points`, then `records` × 16 bytes
  `(uint32 index, uint32 flag, float32 re, float32 im)` = 4 traces × points.
  Later blocks: type 2 = calibration coefficients (not decoded), type 6 = small trailer.
* `TRACE_S_TYPES`: one hex digit per trace, TR1 lowest; 0=S11, 1=S21 (2=S12, 3=S22 assumed).
* `TOTAL_TRACES` = traces on screen (only these are returned by default).
* Frequency axis: linear `TRACE_1_START_FREQ` … `TRACE_1_STOP_FREQ` (MHz), `points` long.
* `CURRENT_TEMPERATURE / 4` = °C (matched one `.s2p` header; treat as likely, not certain).

### Anritsu `.spa` (Spectrum Master native)
Plain text. `# Begin TRACE A Setup` … `# Setup Done` holds the settings (MHz),
`# Begin TRACE A Data` … `# Data Done` holds `P_i=<level> , <freq> MHz`.
Markers: `MKR_SPA_FREQM` in mHz. Limits: `LIMIT_POINTn=<freq mHz> <level×1000> <flag>`.
`UNITS=0` is dBm; other unit codes are not mapped yet (`SPA_UNIT_CODES` in `anritsu.py`).

---

## 9. Known limitations / open items

* `.mna` binary calibration coefficients are not decoded; cal settings are numeric codes.
* `.mna` codes such as `IFBW`, `RF_SOURCE_POWER`, `CAL_TYPE` are not translated to text.
* `.spa` RBW/VBW are stored as 1 kHz / 10 kHz in every sample file regardless of span; they
  may be the manual setting rather than the RBW in use when auto-RBW is on (hence the
  `rbw_setting_Hz` name). Check against the instrument before relying on them.
* `lwafinal.mna` declares 1895 points but only the first 201 contain data; the reader
  adds a warning for files like this.
* Touchstone v2 keywords (`[Version] 2.0`, …) are not supported yet; add them in
  `touchstone.py`.
* Several `info` fields are commented out in `anritsu.py` (firmware, raw parameters, …).
  Un-comment them to bring them back.

---

## 10. Checklist before committing a change

- [ ] `python -m pytest tests` passes
- [ ] New readers produce only standard column names (tests check this)
- [ ] New sample files added under `Data_files/` (if a new format)
- [ ] README tables updated (supported formats, where-to-edit, format notes)
- [ ] GUI still starts: `python main.py`

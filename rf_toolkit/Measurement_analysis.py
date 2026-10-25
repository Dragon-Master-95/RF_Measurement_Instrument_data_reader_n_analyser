# This file takes care of the measurement analysis.
# The class/functions in this file used the structured data and formulae from the text bar in the GUI to perform the analysis.
# The analysis is performed on the structured data and the results are returned in a structured format.
# The standard name of the variables are as follows:
# for sparameters - s11_log_mag | s11_phase | s21_log_mag | s21_phase | s12_... | s22_...
# for spectrum_analyser or spa - trace1, trace2, trace3, trace4
#
# Formula syntax (one per line, '#' starts a comment):
#     return_loss = -s11_log_mag
#     vswr(s11_log_mag)                 <- unnamed lines get the expression as name
#     gain_lin = db_to_lin(s21_log_mag)
#     peak = max(trace1)                <- scalar results are reported separately
# Later lines can use results of earlier lines. Extra variables: freq (Hz), freq_kHz,
# freq_MHz, freq_GHz. Formulas are evaluated with a whitelist (no imports / attributes),
# so typing in the GUI cannot run arbitrary Python.
#
# Several files: each file gets a label f1, f2, ... and its variables are also
# available as f1_s21_log_mag, f2_s21_log_mag, f2_trace1, ... A line using these runs
# once across the files (on the f1 frequency points) and gives a "combined" result:
#     cable_loss = f2_s21_log_mag - f1_s21_log_mag
#
# To add a function usable in formulas, add it to FUNCTIONS (or call register_function).

import ast
import os
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FREQ = "Frequency_Hz"


# ----------------------------------------------------------------------------------------
# Functions available inside formulas
# ----------------------------------------------------------------------------------------
def db_to_lin(db):
    """Log magnitude (dB, 20log10) -> linear magnitude."""
    return 10 ** (np.asarray(db) / 20)


def lin_to_db(mag):
    """Linear magnitude -> log magnitude (dB, 20log10)."""
    with np.errstate(divide="ignore"):
        return 20 * np.log10(np.abs(mag))


def db_to_power(db):
    """Power ratio in dB (10log10) -> linear ratio."""
    return 10 ** (np.asarray(db) / 10)


def power_to_db(ratio):
    """Linear power ratio -> dB (10log10)."""
    with np.errstate(divide="ignore"):
        return 10 * np.log10(np.abs(ratio))


def dbm_to_mw(dbm):
    return 10 ** (np.asarray(dbm) / 10)


def dbm_to_w(dbm):
    return 10 ** (np.asarray(dbm) / 10) / 1000


def mw_to_dbm(mw):
    with np.errstate(divide="ignore"):
        return 10 * np.log10(np.abs(mw))


def vswr(log_mag):
    """VSWR from a reflection log magnitude (e.g. s11_log_mag)."""
    g = np.clip(db_to_lin(log_mag), 0, 0.999999)
    return (1 + g) / (1 - g)


def return_loss(log_mag):
    """Return loss (positive dB) from a reflection log magnitude."""
    return -np.asarray(log_mag)


def mismatch_loss(log_mag):
    """Mismatch loss (dB) from a reflection log magnitude."""
    g = np.clip(db_to_lin(log_mag), 0, 0.999999)
    return -10 * np.log10(1 - g ** 2)


def real_part(log_mag, phase):
    """Real part of the complex value given log magnitude (dB) and phase (deg)."""
    return db_to_lin(log_mag) * np.cos(np.radians(phase))


def imag_part(log_mag, phase):
    """Imaginary part of the complex value given log magnitude (dB) and phase (deg)."""
    return db_to_lin(log_mag) * np.sin(np.radians(phase))


def unwrap_phase(phase):
    """Unwrap a phase in degrees."""
    return np.degrees(np.unwrap(np.radians(phase)))


def smooth(x, n=5):
    """Moving average over n points (centred)."""
    x = np.asarray(x, dtype=float)
    n = max(1, int(n))
    return pd.Series(x).rolling(n, center=True, min_periods=1).mean().to_numpy()


def _make_frequency_functions(freq):
    """Functions that need the frequency axis of the current measurement."""

    def group_delay(phase):
        """Group delay (s) from a phase in degrees."""
        return -np.gradient(np.unwrap(np.radians(phase)), freq) / (2 * np.pi)

    def z_real(log_mag, phase, z0=50.0):
        """Input resistance (ohm) from a reflection S-parameter."""
        g = db_to_lin(log_mag) * np.exp(1j * np.radians(phase))
        return np.real(z0 * (1 + g) / (1 - g))

    def z_imag(log_mag, phase, z0=50.0):
        """Input reactance (ohm) from a reflection S-parameter."""
        g = db_to_lin(log_mag) * np.exp(1j * np.radians(phase))
        return np.imag(z0 * (1 + g) / (1 - g))

    def value_at(x, f_hz):
        """Value of x at frequency f_hz (linear interpolation)."""
        return float(np.interp(f_hz, freq, x))

    def freq_at_max(x):
        """Frequency (Hz) where x is largest."""
        return float(freq[int(np.nanargmax(x))])

    def freq_at_min(x):
        """Frequency (Hz) where x is smallest."""
        return float(freq[int(np.nanargmin(x))])

    def band(x, f_start, f_stop):
        """x outside [f_start, f_stop] Hz is set to NaN (useful with max/mean)."""
        x = np.asarray(x, dtype=float).copy()
        x[(freq < f_start) | (freq > f_stop)] = np.nan
        return x

    return {f.__name__: f for f in (group_delay, z_real, z_imag, value_at,
                                     freq_at_max, freq_at_min, band)}


FUNCTIONS = {
    # numpy
    "abs": np.abs, "sqrt": np.sqrt, "log10": np.log10, "log": np.log, "exp": np.exp,
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "arctan": np.arctan, "arctan2": np.arctan2,
    "radians": np.radians, "degrees": np.degrees, "clip": np.clip, "diff": np.gradient,
    "min": np.nanmin, "max": np.nanmax, "mean": np.nanmean, "median": np.nanmedian,
    "std": np.nanstd, "sum": np.nansum,
    # RF helpers
    "db_to_lin": db_to_lin, "lin_to_db": lin_to_db, "db_to_power": db_to_power,
    "power_to_db": power_to_db, "dbm_to_mw": dbm_to_mw, "dbm_to_w": dbm_to_w,
    "mw_to_dbm": mw_to_dbm, "vswr": vswr, "return_loss": return_loss,
    "mismatch_loss": mismatch_loss, "real_part": real_part, "imag_part": imag_part,
    "unwrap_phase": unwrap_phase, "smooth": smooth,
}

# Functions that need the frequency axis: names listed here for help text / docs
FREQUENCY_FUNCTIONS = sorted(_make_frequency_functions(np.array([0.0, 1.0])).keys())

CONSTANTS = {"pi": np.pi, "e": np.e, "c0": 299792458.0}


def register_function(name, func):
    """Make func usable in formulas under name."""
    FUNCTIONS[name] = func


def function_help():
    """{name: first docstring line} for every formula function (used by the GUI help)."""
    funcs = dict(FUNCTIONS)
    funcs.update(_make_frequency_functions(np.array([0.0, 1.0])))
    out = {}
    for name, f in sorted(funcs.items()):
        if getattr(f, "__module__", None) == __name__:
            doc = (f.__doc__ or "").strip().splitlines()
            out[name] = doc[0] if doc else ""
        else:
            out[name] = f"numpy.{getattr(f, '__name__', name)}"
    return out


# ----------------------------------------------------------------------------------------
# Safe formula evaluation
# ----------------------------------------------------------------------------------------
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant,
    ast.keyword, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
    ast.USub, ast.UAdd, ast.Tuple,
)


class FormulaError(ValueError):
    pass


def parse_formulas(text):
    """Split the formula text into [(name, expression), ...]."""
    formulas = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, expr = None, line
        if "=" in line:
            left, right = line.split("=", 1)
            if left.strip().isidentifier() and not right.startswith("="):
                name, expr = left.strip(), right.strip()
        formulas.append((name or expr, expr, line_no))
    return formulas


def _check(expr, names, hint=None):
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"syntax error in '{expr}': {e.msg}") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise FormulaError(f"'{type(node).__name__}' is not allowed in '{expr}'")
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise FormulaError(f"only plain function calls are allowed in '{expr}'")
        if isinstance(node, ast.Name) and node.id not in names:
            extra = hint(node.id) if hint else ""
            raise FormulaError(f"unknown name '{node.id}' in '{expr}'" + (f" ({extra})" if extra else ""))
    return compile(tree, "<formula>", "eval")


def measurement_variables(data):
    """Variables a formula can use for one measurement's dataframe."""
    variables = {col: data[col].to_numpy() for col in data.columns}
    if FREQ in data:
        f = data[FREQ].to_numpy()
        variables.update(freq=f, freq_kHz=f / 1e3, freq_MHz=f / 1e6, freq_GHz=f / 1e9)
    return variables


# ----------------------------------------------------------------------------------------
# Several files: file labels f1, f2, ... and cross-file formulas
# ----------------------------------------------------------------------------------------
# With several files, every variable also exists with the file label in front:
#     f1_s21_log_mag, f2_s21_log_mag, f3_trace1, ...   (+ named per-file results: f2_rl)
# A formula line that uses such a name is a cross-file formula. It runs once, on the
# frequency points of the first file, and gives one "combined" result. Lines without
# file labels still run on each file separately.
_FILE_VAR = re.compile(r"^(f\d+)_(\w+)$")
COMBINED_NAME = "combined"


def file_label(index):
    """Label of the file at 0-based position index: f1, f2, ..."""
    return f"f{index + 1}"


def file_variable(label, name):
    """Name of variable 'name' of file 'label' in cross-file formulas, e.g. f2_s21_log_mag."""
    return f"{label}_{name}"


def _names_in(expr):
    try:
        return {n.id for n in ast.walk(ast.parse(expr, mode="eval")) if isinstance(n, ast.Name)}
    except SyntaxError:
        return set()


def split_formulas(text):
    """Split formulas into (per_file, cross_file) lists of (name, expr, line_no).

    A line is cross-file if it uses a file-labelled name (f2_s21_log_mag) or the result
    of an earlier cross-file line.
    """
    per_file, cross, cross_names = [], [], set()
    for formula in parse_formulas(text):
        name, expr, _ = formula
        names = _names_in(expr)
        if any(_FILE_VAR.match(n) for n in names) or names & cross_names:
            cross.append(formula)
            cross_names.add(name)
        else:
            per_file.append(formula)
    return per_file, cross


def _interpolate(x_new, x, y, is_phase=False):
    """Interpolate y(x) onto x_new; NaN outside the measured range. Phase (deg) is unwrapped first."""
    y = np.asarray(y, dtype=float)
    if np.array_equal(x_new, x):
        return y
    if is_phase:
        y = np.degrees(np.unwrap(np.radians(y)))
    out = np.interp(x_new, x, y, left=np.nan, right=np.nan)
    if is_phase:
        out = (out + 180.0) % 360.0 - 180.0
    return out


@dataclass
class AnalysisResult:
    """Results of the formulas for one measurement (or the combined cross-file result).

    data     : DataFrame with Frequency_Hz and one column per array formula
    scalars  : {name: value} for formulas that give a single number
    errors   : ["line 2: ...", ...]
    warnings : notes such as "f2 interpolated onto the f1 frequency points"
    label    : file label (f1, f2, ...) or "combined"
    """
    name: str
    data: pd.DataFrame
    scalars: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    label: str = ""

    @property
    def array_names(self):
        return [c for c in self.data.columns if c != FREQ]

    @property
    def display_name(self):
        """'f2: file.s2p' for a file, the name alone for the combined result."""
        return f"{self.label}: {self.name}" if self.label and self.label != COMBINED_NAME else self.name


def _base_env(freq):
    env = dict(CONSTANTS)
    env.update(FUNCTIONS)
    env.update(_make_frequency_functions(freq))
    env.update(freq=freq, freq_kHz=freq / 1e3, freq_MHz=freq / 1e6, freq_GHz=freq / 1e9)
    return env


def _run_formulas(formulas, env, freq, hint=None):
    """Evaluate (label, expr, line_no) formulas in env; returns (result_df, scalars, errors)."""
    n = len(freq)
    result = pd.DataFrame({FREQ: freq})
    scalars, errors = {}, []
    for label, expr, line_no in formulas:
        try:
            code = _check(expr, env, hint)
            with np.errstate(all="ignore"):
                value = eval(code, {"__builtins__": {}}, env)  # names are whitelisted above
            value = np.asarray(value)
            if value.ndim == 0:
                scalars[label] = float(value)
                if label.isidentifier():
                    env[label] = float(value)
            elif value.shape == (n,):
                result[label] = value.astype(float)
                if label.isidentifier():
                    env[label] = value
            else:
                raise FormulaError(f"result has shape {value.shape}, expected {n} points")
        except Exception as e:  # report and continue with the next formula
            errors.append(f"line {line_no}: {e}")
    return result, scalars, errors


class MeasurementAnalyzer:
    """Apply formula text to one or many Measurement objects."""

    def analyse(self, measurement, formula_text, name=None, label=""):
        """Run the per-file formulas on one measurement.

        Cross-file lines (using f1_..., f2_... names) are skipped here; analyse_many runs them.
        """
        data = measurement.data
        freq = data[FREQ].to_numpy() if FREQ in data else np.arange(len(data), dtype=float)
        env = _base_env(freq)
        env.update(measurement_variables(data))
        result, scalars, errors = _run_formulas(split_formulas(formula_text)[0], env, freq)
        return AnalysisResult(name or getattr(measurement, "name", "measurement"), result,
                              scalars, errors, label=label)

    def analyse_many(self, measurements, formula_text, labels=None):
        """Per-file results for every measurement, plus one 'combined' result when the
        text contains cross-file formulas.

        labels: file labels in the same order as measurements (default f1, f2, ...).
                The GUI passes the position in its file list so labels stay stable.
        """
        labels = list(labels) if labels else [file_label(i) for i in range(len(measurements))]
        results = [self.analyse(m, formula_text, label=lab) for m, lab in zip(measurements, labels)]
        cross = split_formulas(formula_text)[1]
        if cross and measurements:
            results.append(self._analyse_combined(measurements, labels, results, cross))
        return results

    def _analyse_combined(self, measurements, labels, per_file, formulas):
        ref = measurements[0]
        ref_freq = ref.data[FREQ].to_numpy()
        env = _base_env(ref_freq)
        warnings = []
        for m, lab, res in zip(measurements, labels, per_file):
            freq = m.data[FREQ].to_numpy()
            if not np.array_equal(freq, ref_freq):
                warnings.append(f"{lab} ({m.name}) interpolated onto the {labels[0]} frequency points")
            for col in m.data.columns:
                if col != FREQ:
                    env[file_variable(lab, col)] = _interpolate(ref_freq, freq, m.data[col],
                                                                col.endswith("_phase"))
            for col in res.array_names:  # named per-file results, e.g. f2_rl
                if col.isidentifier():
                    env.setdefault(file_variable(lab, col), _interpolate(ref_freq, freq, res.data[col]))
            for k, v in res.scalars.items():
                if k.isidentifier():
                    env.setdefault(file_variable(lab, k), v)

        def hint(name):
            m = _FILE_VAR.match(name)
            if m and m.group(1) not in labels:
                return f"{m.group(1)} is not among the analysed (ticked) files: {', '.join(labels)}"
            if m:
                return f"{m.group(1)} has no variable '{m.group(2)}'"
            if name in measurements[0].data.columns:
                return f"in a formula using several files write it with a file label, e.g. {labels[0]}_{name}"
            return ""

        result, scalars, errors = _run_formulas(formulas, env, ref_freq, hint)
        name = f"{COMBINED_NAME} ({', '.join(labels)})"
        return AnalysisResult(name, result, scalars, errors, warnings, label=COMBINED_NAME)


def results_to_dataframe(results):
    """Combine results of several files into one long table with 'file' and 'label' columns."""
    frames = []
    for r in results:
        df = r.data.copy()
        df.insert(0, "file", r.name)
        df.insert(1, "label", r.label)
        for k, v in r.scalars.items():
            df[k] = v
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def save_results_csv(results, file_path):
    """Save results. One file -> one CSV; several -> one CSV with 'file' and 'label' columns."""
    table = results_to_dataframe(results)
    if len(results) == 1:
        table = table.drop(columns=["file", "label"])
    table.to_csv(file_path, index=False)
    return file_path


if __name__ == "__main__":
    from .Measurement_file_reader import read_measurement_file
    from .paths import DATA_DIR

    base = os.path.join(DATA_DIR, "Anritsu")
    m = read_measurement_file(os.path.join(base, "MS2024B_VNA", "hlf400cc_s21_2.s2p"))
    text = """
    rl = return_loss(s11_log_mag)
    vswr(s11_log_mag)
    loss_per_GHz = -s21_log_mag / freq_GHz
    gd_ns = group_delay(s21_phase) * 1e9
    worst_vswr = max(vswr(s11_log_mag))
    f_best_match = freq_at_min(s11_log_mag) / 1e6
    """
    r = MeasurementAnalyzer().analyse(m, text)
    print(r.data.head())
    print(r.scalars, r.errors)

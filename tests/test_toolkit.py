# Run from the project folder:  python -m pytest tests
import glob
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rf_toolkit.instrument_readers import (STANDARD_INFO_KEYS, Measurement, MeasurementReader, get_reader,
                                           register_reader)
from rf_toolkit.instrument_readers import base as reader_base
from rf_toolkit.Measurement_analysis import MeasurementAnalyzer, parse_formulas
from rf_toolkit.Measurement_file_reader import read_measurement_file

DATA_FILES = sorted(glob.glob(os.path.join(ROOT, "Data_files", "*", "*", "*")))
VNA_COLUMN = r"^(Frequency_Hz|s\d\d(_tr\d+)?_(log_mag|phase))$"
SA_COLUMN = r"^(Frequency_Hz|trace\d+)$"


@pytest.mark.parametrize("path", DATA_FILES, ids=os.path.basename)
def test_every_sample_file_reads_with_standard_columns(path):
    m = read_measurement_file(path)
    assert m.data.columns[0] == "Frequency_Hz"
    assert len(m.data) == m.info["n_points"] > 0
    assert set(STANDARD_INFO_KEYS) <= set(m.info)
    pattern = VNA_COLUMN if m.instrument_type == "VNA" else SA_COLUMN
    assert m.data.columns.str.match(pattern).all(), list(m.data.columns)
    assert np.all(np.diff(m.data["Frequency_Hz"]) > 0)


def test_mna_matches_touchstone_saved_from_same_sweep():
    base = os.path.join(ROOT, "Data_files", "Anritsu", "MS2024B_VNA")
    if not os.path.isdir(base):
        pytest.skip("sample data not present")
    s2p = read_measurement_file(os.path.join(base, "hlf400cc_s21_2.s2p")).data
    mna = read_measurement_file(os.path.join(base, "hlf400cc_s21_1.mna")).data
    assert np.allclose(s2p["Frequency_Hz"], mna["Frequency_Hz"], atol=1)
    assert np.sqrt(np.mean((s2p["s21_log_mag"] - mna["s21_log_mag"]) ** 2)) < 0.05


def test_measurement_unpacks_like_old_api():
    m = Measurement(pd.DataFrame({"Frequency_Hz": [1.0, 2.0]}), {})
    df, info = m
    assert df is m.data and info["n_points"] == 2


def test_new_reader_can_be_registered(tmp_path):
    @register_reader
    class DummyReader(MeasurementReader):
        manufacturer = "Dummy"
        instrument_type = "SA"
        extensions = (".dummy",)

        def read(self, file_path):
            return Measurement(pd.DataFrame({"Frequency_Hz": [1.0, 2.0], "trace1": [-50.0, -60.0]}),
                               {"instrument_type": "SA"})

    try:
        f = tmp_path / "x.dummy"
        f.write_text("anything")
        assert isinstance(get_reader(str(f)), DummyReader)
        assert read_measurement_file(str(f)).data["trace1"].tolist() == [-50.0, -60.0]
    finally:
        reader_base._READERS.remove(DummyReader)


def _sa_measurement():
    return Measurement(pd.DataFrame({"Frequency_Hz": [1e6, 2e6, 3e6], "trace1": [-50.0, -40.0, -60.0]}),
                       {"instrument_type": "SA"})


def test_formulas_arrays_scalars_and_chaining():
    r = MeasurementAnalyzer().analyse(_sa_measurement(),
                                      "p = dbm_to_mw(trace1)\np2 = p * 2\npeak = max(trace1)\n"
                                      "f = freq_at_max(trace1)  # comment")
    assert not r.errors
    assert np.allclose(r.data["p2"], 2 * 10 ** (np.array([-50, -40, -60]) / 10))
    assert r.scalars == {"peak": -40.0, "f": 2e6}


@pytest.mark.parametrize("bad", ["__import__('os')", "trace1.real", "open('x')", "[1, 2]",
                                 "(lambda: 1)()", "unknown_var"])
def test_formulas_reject_unsafe_or_unknown_input(bad):
    r = MeasurementAnalyzer().analyse(_sa_measurement(), bad)
    assert r.errors and not r.array_names and not r.scalars


def test_parse_formulas_names():
    assert [(n, e) for n, e, _ in parse_formulas("a = b + 1\nvswr(x)\n# c\nx == 1")] == \
        [("a", "b + 1"), ("vswr(x)", "vswr(x)"), ("x == 1", "x == 1")]


# ---- several files: f1_, f2_ ... variables -------------------------------------------
def _sa(freq, level):
    return Measurement(pd.DataFrame({"Frequency_Hz": freq, "trace1": level}), {"instrument_type": "SA"})


def test_cross_file_formulas_give_combined_result():
    a = _sa([1.0, 2.0, 3.0], [-50.0, -40.0, -60.0])
    b = _sa([1.0, 2.0, 3.0], [-52.0, -45.0, -61.0])
    text = "p = trace1 + 1\nd = f1_trace1 - f2_trace1\nworst = max(d)\npd = f2_p - f1_p"
    results = MeasurementAnalyzer().analyse_many([a, b], text)
    assert [r.label for r in results] == ["f1", "f2", "combined"]
    assert all(r.array_names == ["p"] and not r.errors for r in results[:2])
    combined = results[-1]
    assert not combined.errors
    assert combined.data["d"].tolist() == [2.0, 5.0, 1.0]
    assert combined.data["pd"].tolist() == [-2.0, -5.0, -1.0]
    assert combined.scalars == {"worst": 5.0}


def test_cross_file_interpolates_onto_first_file_and_uses_given_labels():
    a = _sa([1.0, 2.0, 3.0], [0.0, 0.0, 0.0])
    b = _sa([0.0, 2.0, 2.5], [0.0, 20.0, 25.0])
    r = MeasurementAnalyzer().analyse_many([a, b], "x = f4_trace1 - f2_trace1", labels=["f2", "f4"])[-1]
    assert r.data["x"].iloc[:2].tolist() == [10.0, 20.0] and np.isnan(r.data["x"].iloc[2])
    assert r.warnings and "f4" in r.warnings[0]


def test_cross_file_errors_explain_the_fix():
    a, b = _sa([1.0, 2.0], [0.0, 1.0]), _sa([1.0, 2.0], [0.0, 1.0])
    r = MeasurementAnalyzer().analyse_many([a, b], "trace1 - f1_trace1\nf3_trace1\nf1_nothing")[-1]
    assert "f1_trace1" in r.errors[0] and "f3" in r.errors[1] and "nothing" in r.errors[2]


# ---- plot styling (no Qt needed) ------------------------------------------------------
def test_plot_style_overrides_and_json_roundtrip(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from rf_toolkit.plotting import PlotStyle, draw_results

    a = _sa([1e6, 2e6, 3e6], [-50.0, -40.0, -60.0])
    b = _sa([1e6, 2e6, 3e6], [-52.0, -45.0, -61.0])
    results = MeasurementAnalyzer().analyse_many([a, b], "trace1")
    style = PlotStyle(title="RFI", ylabel="Power (dBm)", tick_size=12, ymin=-70, legend_loc="outside right")
    key = "f1: measurement | trace1"
    style.lines[key] = {"label": "East", "color": "#ff0000", "linestyle": "dashed", "linewidth": 3.0}
    style.lines["f2: measurement | trace1"] = {"visible": False}
    style.subplots["plot"] = {"title": "Survey"}

    fig = Figure()
    lines, subplots = draw_results(fig, results, mode=0, x_unit="MHz", style=style)
    ax = fig.axes[0]
    assert [l.key for l in lines] == [key, "f2: measurement | trace1"]
    assert len(ax.lines) == 1                       # second line hidden
    line = ax.lines[0]
    assert (line.get_label(), line.get_color(), line.get_linestyle(), line.get_linewidth()) == \
        ("East", "#ff0000", "--", 3.0)
    assert ax.get_title() == "Survey" and ax.get_ylabel() == "Power (dBm)"
    assert fig._suptitle.get_text() == "RFI" and ax.get_ylim()[0] == -70
    assert ax.xaxis.get_ticklabels()[0].get_fontsize() == 12

    path = tmp_path / "style.json"
    style.save(path)
    assert PlotStyle.load(path) == style

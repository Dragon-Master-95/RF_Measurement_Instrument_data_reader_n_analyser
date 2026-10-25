# this file will contain GUI interface codes for the measurement
# analysis.
# Features:
# 1. Load the measurement data file (Touchstone or Anritsu Spectrum
#    Master .spa) and display the structured data in a table.
# 2. Display the measurement settings and calibration settings in a
#    text box.
# 3. Provide a text box for the user to enter the formulae for the
#    analysis. The formulae can be in terms of the standard variable
#    names (s11_log_mag, s11_phase, s21_log_mag, s21_phase, s12_...,
#    s22_..., trace1, trace2, trace3, trace4).
# 4. Provide a button to perform the analysis and display the results
#    as a plot using seaborn or matplotlib.
# 5. Also will have feature to read multiple same filetype measurement
#    files and perform the analysis on all of them and display the
#    results in a single or multiple plot as per user preference.
# 6. Provide a button to save the analysis results in a CSV file.
# 7. There will be a help button to display the help information for
#    the user.
# 8. The GUI will be built using PyQt5 or PySide2.
#    (PySide6 is used when installed, then PySide2, then PyQt5.)
# 9. The GUI will be designed to be user-friendly and intuitive.
# 10. There will be text display bar either in bottom of in write side
#     of the GUI to display the status of the analysis and any error
#     messages.
# 11. There will be text display the measurement information like
#     instrument settings and calibration information.
# 12. The GUI will support future upgrades like inclusion of new measurement
#     file types and instrument from other manufacturers.
#     (The file dialog and variable list come from the reader registry, so a new
#      reader in instrument_readers/ shows up here without GUI changes.)

import html
import os
import sys
from datetime import datetime

from .qt_compat import QAction, QT_BINDING, Qt, QtCore, QtGui, QtWidgets, exec_dialog

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import seaborn as sns

from .Measurement_analysis import (CONSTANTS, MeasurementAnalyzer, file_label, file_variable, function_help,
                                  results_to_dataframe, save_results_csv)
from .Measurement_file_reader import available_readers, file_dialog_filter, read_measurement_file
from .paths import DATA_DIR
from .plot_settings_dialog import PlotSettingsDialog
from .plotting import PLOT_MODES, X_UNITS, PlotStyle, draw_results

# Default formulas offered when the first file of a type is loaded
DEFAULT_FORMULAS = {
    "VNA": "# one formula per line, e.g.  name = expression\ns11_log_mag\ns21_log_mag",
    "SA": "# one formula per line, e.g.  name = expression\ntrace1",
}

# Keys shown in the 'General' block of the info panel (in this order)
GENERAL_INFO_KEYS = ["file_path", "manufacturer", "model_number", "serial_number", "instrument_type",
                     "file_format", "measurement_time", "n_points", "n_valid_points", "amplitude_unit"]
# Large keys hidden unless 'Show raw parameters' is ticked
RAW_INFO_KEYS = {"header", "raw_parameters", "comments"}



# ----------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------
class DataFrameModel(QtCore.QAbstractTableModel):
    """Read-only table model for a pandas DataFrame."""

    def __init__(self, df=None):
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()

    def set_dataframe(self, df):
        self.beginResetModel()
        self._df = df if df is not None else pd.DataFrame()
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return self._df.shape[1]

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            value = self._df.iat[index.row(), index.column()]
            if isinstance(value, (float, np.floating)):
                return f"{value:.10g}"
            return str(value)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section)


def format_info(info, show_raw=False):
    """Turn a Measurement.info dict into readable text for the info panel."""
    lines = ["== General =="]
    for key in GENERAL_INFO_KEYS:
        if info.get(key) not in (None, "", [], {}):
            lines.append(f"{key:18s}: {info[key]}")
    for key, value in info.items():
        if key in GENERAL_INFO_KEYS or (key in RAW_INFO_KEYS and not show_raw):
            continue
        if value in (None, "", [], {}):
            continue
        lines.append("")
        lines.append(f"== {key.replace('_', ' ').title()} ==")
        lines.extend(_format_value(value, indent=0))
    return "\n".join(lines)


def _format_value(value, indent):
    pad = "  " * indent
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out.extend(_format_value(v, indent + 1))
            else:
                out.append(f"{pad}{k}: {v}")
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(pad + ", ".join(f"{k}={v}" for k, v in item.items()))
            else:
                out.append(f"{pad}- {item}")
        return out
    return [f"{pad}{value}"]


# ----------------------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------------------
class MeasurementAnalysisGUI(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RF Measurement Analyser")
        self.resize(1400, 860)
        self.measurements = []   # loaded Measurement objects, same order as the file list
        self.results = []        # AnalysisResult objects from the last run
        self.analyzer = MeasurementAnalyzer()
        self.plot_style = PlotStyle()     # edited in the Plot settings window
        self.plot_dialog = None
        self._plot_info = ([], [])        # (lines, subplots) of the last drawn plot
        sns.set_theme(style="whitegrid", context="notebook")

        self._build_actions()
        self._build_layout()
        self.log(f"Ready ({QT_BINDING}). Readers: "
                 + ", ".join(f"{r.manufacturer} {'/'.join(r.extensions)}" for r in available_readers()))

    # ---------------------------------------------------------------- layout
    def _build_actions(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        style = self.style()

        def action(text, icon, slot, shortcut=None, tip=None):
            a = QAction(style.standardIcon(icon), text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QtGui.QKeySequence(shortcut))
            a.setToolTip(tip or text)
            tb.addAction(a)
            return a

        SP = QtWidgets.QStyle
        action("Open files…", SP.SP_DialogOpenButton, self.open_files, "Ctrl+O",
               "Load one or more measurement files")
        action("Remove", SP.SP_TrashIcon, self.remove_selected, "Delete", "Remove the selected file")
        action("Clear all", SP.SP_DialogResetButton, self.clear_all)
        tb.addSeparator()
        action("Run analysis", SP.SP_MediaPlay, self.run_analysis, "Ctrl+Return",
               "Evaluate the formulas on all ticked files and plot")
        action("Save results CSV…", SP.SP_DialogSaveButton, self.save_results, "Ctrl+S")
        action("Plot settings…", SP.SP_FileDialogDetailedView, self.open_plot_settings, "Ctrl+P",
               "Titles, labels, legend, fonts, line colour / style / width, limits")
        action("Save plot…", SP.SP_FileIcon, self.save_plot)
        tb.addSeparator()
        action("Help", SP.SP_DialogHelpButton, self.show_help, "F1")

    def _build_layout(self):
        # Left: files + variables
        self.file_list = QtWidgets.QListWidget()
        self.file_list.setToolTip("Ticked files are used by 'Run analysis'. Click a file to view it.")
        self.file_list.currentRowChanged.connect(self.show_measurement)
        self.var_list = QtWidgets.QListWidget()
        self.var_list.setToolTip("Double-click to insert into the formula box")
        self.var_list.itemDoubleClicked.connect(lambda it: self.formula_edit.insertPlainText(it.text()))

        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.addWidget(QtWidgets.QLabel("<b>Loaded files</b> (tick = include in analysis)"))
        lv.addWidget(self.file_list, 3)
        lv.addWidget(QtWidgets.QLabel("<b>Variables</b> (double-click to insert)"))
        lv.addWidget(self.var_list, 2)

        # Centre: tabs (data / plot / results) + formula box
        self.data_model = DataFrameModel()
        self.data_view = QtWidgets.QTableView()
        self.data_view.setModel(self.data_model)
        self.data_view.verticalHeader().setDefaultSectionSize(22)

        self.figure = Figure(figsize=(8, 5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        plot_tab = QtWidgets.QWidget()
        pv = QtWidgets.QVBoxLayout(plot_tab)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(NavigationToolbar2QT(self.canvas, plot_tab))
        pv.addWidget(self.canvas)

        self.results_model = DataFrameModel()
        self.results_view = QtWidgets.QTableView()
        self.results_view.setModel(self.results_model)
        self.results_view.verticalHeader().setDefaultSectionSize(22)
        self.scalar_model = DataFrameModel()
        self.scalar_view = QtWidgets.QTableView()
        self.scalar_view.setModel(self.scalar_model)
        results_tab = QtWidgets.QSplitter(Qt.Vertical)
        for title, view in (("Array results", self.results_view), ("Single-value results", self.scalar_view)):
            box = QtWidgets.QGroupBox(title)
            QtWidgets.QVBoxLayout(box).addWidget(view)
            results_tab.addWidget(box)
        results_tab.setSizes([500, 150])

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.data_view, "Data")
        self.tabs.addTab(plot_tab, "Plot")
        self.tabs.addTab(results_tab, "Results")

        self.formula_edit = QtWidgets.QPlainTextEdit()
        self.formula_edit.setPlaceholderText(
            "One formula per line, e.g.\n  return_loss = -s11_log_mag\n  vswr(s11_log_mag)\n"
            "  peak = max(trace1)\nPress Help (F1) for all variables and functions.")
        self.formula_edit.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.plot_mode = QtWidgets.QComboBox()
        self.plot_mode.addItems(PLOT_MODES)
        self.plot_mode.currentIndexChanged.connect(lambda _: self.plot_results())
        self.x_unit = QtWidgets.QComboBox()
        self.x_unit.addItems(list(X_UNITS))
        self.x_unit.setCurrentText("MHz")
        self.x_unit.currentIndexChanged.connect(lambda _: self.plot_results())
        run_btn = QtWidgets.QPushButton("Run analysis")
        run_btn.setDefault(True)
        run_btn.clicked.connect(self.run_analysis)

        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel("Plot:"))
        controls.addWidget(self.plot_mode)
        controls.addWidget(QtWidgets.QLabel("X axis:"))
        controls.addWidget(self.x_unit)
        settings_btn = QtWidgets.QPushButton("Plot settings…")
        settings_btn.clicked.connect(self.open_plot_settings)
        controls.addWidget(settings_btn)
        controls.addStretch(1)
        controls.addWidget(run_btn)

        formula_box = QtWidgets.QGroupBox("Formulas")
        fv = QtWidgets.QVBoxLayout(formula_box)
        fv.addWidget(self.formula_edit)
        fv.addLayout(controls)

        centre = QtWidgets.QSplitter(Qt.Vertical)
        centre.addWidget(self.tabs)
        centre.addWidget(formula_box)
        centre.setSizes([600, 220])

        # Right: measurement info
        self.info_text = QtWidgets.QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.show_raw = QtWidgets.QCheckBox("Show raw parameters")
        self.show_raw.toggled.connect(lambda _: self.show_measurement(self.file_list.currentRow()))
        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(4, 4, 4, 4)
        rv.addWidget(QtWidgets.QLabel("<b>Measurement information</b> (settings & calibration)"))
        rv.addWidget(self.info_text)
        rv.addWidget(self.show_raw)

        main = QtWidgets.QSplitter(Qt.Horizontal)
        main.addWidget(left)
        main.addWidget(centre)
        main.addWidget(right)
        main.setSizes([260, 800, 340])

        # Bottom: status / log
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(2000)
        outer = QtWidgets.QSplitter(Qt.Vertical)
        outer.addWidget(main)
        log_box = QtWidgets.QGroupBox("Status")
        QtWidgets.QVBoxLayout(log_box).addWidget(self.log_text)
        outer.addWidget(log_box)
        outer.setSizes([720, 130])
        self.setCentralWidget(outer)
        self.statusBar()

    # ---------------------------------------------------------------- status
    def log(self, message, level="info"):
        colour = {"info": "#444", "ok": "#2a7a2a", "warn": "#b36b00", "error": "#c0392b"}[level]
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.appendHtml(f'<span style="color:{colour}">[{stamp}] {html.escape(message)}</span>')
        self.statusBar().showMessage(message, 8000)

    # ---------------------------------------------------------------- files
    def open_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Open measurement files", self._last_dir(), file_dialog_filter())
        self.load_files(paths)

    def _last_dir(self):
        if self.measurements:
            return os.path.dirname(self.measurements[-1].info["file_path"])
        return DATA_DIR if os.path.isdir(DATA_DIR) else os.getcwd()

    def load_files(self, paths):
        loaded = 0
        for path in paths:
            try:
                m = read_measurement_file(path)
            except Exception as e:
                self.log(f"Could not read {os.path.basename(path)}: {e}", "error")
                continue
            types = {x.instrument_type for x in self.measurements}
            if types and m.instrument_type not in types:
                self.log(f"{m.name} is a {m.instrument_type} file but {', '.join(types)} files are "
                         f"loaded; formulas may not fit both", "warn")
            self.measurements.append(m)
            item = QtWidgets.QListWidgetItem()
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setToolTip(m.info["file_path"])
            self.file_list.addItem(item)
            self._refresh_file_labels()
            for w in m.info.get("warnings") or []:
                self.log(f"{m.name}: {w}", "warn")
            loaded += 1
            if not self.formula_edit.toPlainText().strip():
                self.formula_edit.setPlainText(DEFAULT_FORMULAS.get(m.instrument_type, ""))
        if loaded:
            self.file_list.setCurrentRow(self.file_list.count() - 1)
            self.log(f"Loaded {loaded} file(s); {len(self.measurements)} in total", "ok")

    def remove_selected(self):
        row = self.file_list.currentRow()
        if row < 0:
            return
        m = self.measurements.pop(row)
        self.file_list.takeItem(row)
        self._refresh_file_labels()
        self.log(f"Removed {m.name}; files are renumbered f1..f{len(self.measurements)}")
        if not self.measurements:
            self.show_measurement(-1)

    def clear_all(self):
        self.measurements.clear()
        self.results.clear()
        self.file_list.clear()
        self.results_model.set_dataframe(None)
        self.scalar_model.set_dataframe(None)
        self.figure.clear()
        self.canvas.draw_idle()
        self.show_measurement(-1)
        self.log("Cleared all files")

    def show_measurement(self, row):
        if row < 0 or row >= len(self.measurements):
            self.data_model.set_dataframe(None)
            self.info_text.clear()
            self.var_list.clear()
            return
        m = self.measurements[row]
        self.data_model.set_dataframe(m.data)
        self.data_view.resizeColumnsToContents()
        self.info_text.setPlainText(format_info(m.info, self.show_raw.isChecked()))
        self.var_list.clear()
        self.var_list.addItems(m.variables + ["freq", "freq_kHz", "freq_MHz", "freq_GHz"])
        if len(self.measurements) > 1:
            # names for formulas that combine files, e.g. f2_s21_log_mag - f1_s21_log_mag
            header = QtWidgets.QListWidgetItem(f"── using several files ({file_label(row)} = this file) ──")
            header.setFlags(Qt.NoItemFlags)
            self.var_list.addItem(header)
            self.var_list.addItems([file_variable(file_label(row), v) for v in m.variables
                                    if v != "Frequency_Hz"])

    def _refresh_file_labels(self):
        """List text 'f1: name [VNA]'; the label is the position in the list."""
        for i, m in enumerate(self.measurements):
            self.file_list.item(i).setText(f"{file_label(i)}: {m.name}  [{m.instrument_type}]")

    def checked_measurements(self, with_labels=False):
        rows = [i for i in range(len(self.measurements))
                if self.file_list.item(i).checkState() == Qt.Checked]
        if with_labels:
            return [self.measurements[i] for i in rows], [file_label(i) for i in rows]
        return [self.measurements[i] for i in rows]

    # ---------------------------------------------------------------- analysis
    def run_analysis(self):
        targets, labels = self.checked_measurements(with_labels=True)
        text = self.formula_edit.toPlainText()
        if not targets:
            self.log("No files ticked: load files and tick the ones to analyse", "warn")
            return
        if not text.strip():
            self.log("The formula box is empty", "warn")
            return
        if len({m.instrument_type for m in targets}) > 1:
            self.log("Ticked files mix instrument types; formulas that use missing variables "
                     "will fail for some files", "warn")

        self.results = self.analyzer.analyse_many(targets, text, labels)
        n_err = 0
        for r in self.results:
            for w in r.warnings:
                self.log(f"{r.display_name}: {w}", "warn")
            for err in r.errors:
                self.log(f"{r.display_name}: {err}", "error")
                n_err += 1
            for k, v in r.scalars.items():
                self.log(f"{r.display_name}: {k} = {v:.6g}")

        table = results_to_dataframe(self.results)
        self.results_model.set_dataframe(table.loc[:, [c for c in table.columns
                                                         if not any(c in r.scalars for r in self.results)]])
        scalars = pd.DataFrame([{"file": r.name, "label": r.label, **r.scalars}
                                for r in self.results if r.scalars])
        self.scalar_model.set_dataframe(scalars)
        self.plot_results()
        if any(r.array_names for r in self.results):
            self.tabs.setCurrentIndex(1)
        else:
            self.tabs.setCurrentIndex(2)
        level = "warn" if n_err else "ok"
        self.log(f"Analysis done on {len(targets)} file(s), {n_err} error(s)", level)

    def plot_results(self):
        """Redraw the plot from self.results using the current plot mode, x unit and style."""
        try:
            self._plot_info = draw_results(self.figure, self.results, self.plot_mode.currentIndex(),
                                           self.x_unit.currentText(), self.plot_style)
        except Exception as e:  # e.g. invalid axis limits; keep the GUI alive
            self.log(f"Plot error: {e}", "error")
        self.canvas.draw_idle()
        if self.plot_dialog is not None and self.plot_dialog.isVisible():
            self.plot_dialog.refresh(*self._plot_info)

    def open_plot_settings(self):
        if self.plot_dialog is None:
            self.plot_dialog = PlotSettingsDialog(self, self.plot_style, self.plot_results)
        self.plot_dialog.refresh(*self._plot_info, force=True)
        self.plot_dialog.show()
        self.plot_dialog.raise_()
        self.plot_dialog.activateWindow()

    # ---------------------------------------------------------------- saving
    def save_results(self):
        if not self.results:
            self.log("Nothing to save: run an analysis first", "warn")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save analysis results", os.path.join(self._last_dir(), "analysis_results.csv"),
            "CSV files (*.csv)")
        if path:
            save_results_csv(self.results, path)
            self.log(f"Results saved to {path}", "ok")

    def save_plot(self):
        if not self.results:
            self.log("Nothing to save: run an analysis first", "warn")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save plot", os.path.join(self._last_dir(), "analysis_plot.png"),
            "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if path:
            self.figure.savefig(path, dpi=self.plot_style.dpi, bbox_inches="tight")
            self.log(f"Plot saved to {path}", "ok")

    # ---------------------------------------------------------------- help
    def show_help(self):
        funcs = "".join(f"<tr><td><code>{html.escape(n)}</code></td><td>{html.escape(d)}</td></tr>"
                        for n, d in function_help().items())
        consts = ", ".join(f"<code>{k}</code>" for k in CONSTANTS)
        readers = "".join(f"<li>{r.manufacturer} {r.instrument_type or ''}: {', '.join(r.extensions)}</li>"
                          for r in available_readers())
        text = f"""
        <h2>RF Measurement Analyser</h2>
        <ol>
          <li><b>Open files…</b> (Ctrl+O) and pick one or more files of the same type.</li>
          <li>Click a file to see its data table and its settings / calibration on the right.</li>
          <li>Type formulas in the <b>Formulas</b> box (one per line) and press <b>Run analysis</b>
              (Ctrl+Enter). Ticked files are analysed.</li>
          <li>Choose how to plot: all together, one plot per file, or one plot per formula.</li>
          <li><b>Plot settings…</b> (Ctrl+P): titles, axis labels, font and tick sizes, legend,
              grid, limits, palette, and colour / style / width / marker of each line.
              Blank or <i>auto</i> = automatic. Styles can be saved and loaded as JSON.</li>
          <li><b>Save results CSV…</b> (Ctrl+S) or <b>Save plot…</b> (uses the export DPI).</li>
        </ol>
        <h3>Variables</h3>
        <p>VNA: <code>s11_log_mag, s11_phase, s21_log_mag, s21_phase, s12_…, s22_…</code>
        (dB and degrees)<br>
        Spectrum analyser: <code>trace1, trace2, …</code> (power, dB units such as dBm)<br>
        Frequency: <code>freq</code> (Hz), <code>freq_kHz</code>, <code>freq_MHz</code>, <code>freq_GHz</code><br>
        Constants: {consts}</p>
        <h3>Formula examples</h3>
        <pre>return_loss = -s11_log_mag
vswr(s11_log_mag)
gain_lin = db_to_lin(s21_log_mag)
delay_ns = group_delay(s21_phase) * 1e9
p_mw = dbm_to_mw(trace1)
peak_dBm = max(trace1)                # single value
f_peak_MHz = freq_at_max(trace1) / 1e6
in_band_max = max(band(trace1, 400e6, 500e6))</pre>
        <p>A line <code>name = expression</code> names the result; later lines can use it.
        Single-value results appear in the Results tab and the status log.</p>
        <h3>Formulas across several files</h3>
        <p>Every loaded file has a label shown in the file list: <code>f1</code>, <code>f2</code>, …
        Its variables are also available with that label in front:
        <code>f1_s21_log_mag</code>, <code>f2_s21_log_mag</code>, <code>f3_trace1</code>, and so are
        named per-file results (<code>rl = -s11_log_mag</code> gives <code>f1_rl</code>, <code>f2_rl</code>, …).</p>
        <ul>
          <li>Lines with plain names (<code>s21_log_mag</code>) run on <b>each</b> ticked file.</li>
          <li>Lines with labelled names run <b>once</b> and give a <b>combined</b> result.
              Later lines that use a combined result are combined too.</li>
          <li>Combined formulas use the frequency points of the first ticked file; other files
              are interpolated onto them (NaN outside their range).</li>
          <li>Labels follow the order of the file list and are renumbered when a file is removed.</li>
        </ul>
        <pre>cable_loss = f2_s21_log_mag - f1_s21_log_mag
worst_loss = min(cable_loss)
rl = -s11_log_mag                   # per file
rl_change = f2_rl - f1_rl           # combined
east_minus_west = f1_trace1 - f2_trace1</pre>
        <h3>Functions</h3><table cellspacing="4">{funcs}</table>
        <h3>Supported files</h3><ul>{readers}</ul>
        """
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Help")
        dlg.resize(720, 640)
        browser = QtWidgets.QTextBrowser()
        browser.setHtml(text)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(browser)
        lay.addWidget(buttons)
        exec_dialog(dlg)


def run(files=None):
    """Start the GUI; optionally pre-load files."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = MeasurementAnalysisGUI()
    window.show()
    if files:
        window.load_files(files)
    return exec_dialog(app)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))

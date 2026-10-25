# "Plot settings" window: edits a PlotStyle and redraws the plot on every change.
#
#   General  - figure title, axis labels, font sizes, legend, grid, limits, palette, DPI
#   Subplots - title and y label of each subplot
#   Lines    - legend text, colour, line style, width, marker, visibility of each line
#
# Blank fields / "auto" mean the automatic value. To add a new general setting:
# add a field to PlotStyle (plotting.py), use it in draw_results(), and add one
# self._add_*() line in _build_general_tab() below.

from .plotting import LEGEND_LOCATIONS, LINE_STYLES, MARKERS, PALETTES, PlotStyle
from .qt_compat import Qt, QtGui, QtWidgets

AUTO = "auto"


class PlotSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent, style, on_change):
        super().__init__(parent)
        self.setWindowTitle("Plot settings")
        self.resize(760, 560)
        self.style = style
        self.on_change = on_change          # called after every edit -> redraw
        self._general = {}                  # attribute name -> (widget, kind)
        self._line_keys = []
        self._subplot_keys = []
        self._updating = False

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_general_tab(), "General")
        self.subplot_table = QtWidgets.QTableWidget(0, 3)
        self.subplot_table.setHorizontalHeaderLabels(["Subplot", "Title", "Y label"])
        tabs.addTab(self._wrap(self.subplot_table, "Leave a field blank to use the automatic text."),
                    "Subplots")
        self.line_table = QtWidgets.QTableWidget(0, 7)
        self.line_table.setHorizontalHeaderLabels(
            ["Show", "Line", "Legend label", "Colour", "Style", "Width", "Marker"])
        tabs.addTab(self._wrap(self.line_table, "Blank label / 'auto' = automatic. "
                                                "Settings are kept per file and formula."), "Lines")
        for table in (self.subplot_table, self.line_table):
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setStretchLastSection(True)

        buttons = QtWidgets.QHBoxLayout()
        for text, slot in (("Reset all", self.reset), ("Save style…", self.save_style),
                           ("Load style…", self.load_style)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(buttons)

    @staticmethod
    def _wrap(widget, note):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.addWidget(QtWidgets.QLabel(note))
        v.addWidget(widget)
        return w

    # ------------------------------------------------------------ general tab
    def _build_general_tab(self):
        w = QtWidgets.QWidget()
        grid = QtWidgets.QHBoxLayout(w)
        left, right = QtWidgets.QFormLayout(), QtWidgets.QFormLayout()
        grid.addLayout(left)
        grid.addSpacing(20)
        grid.addLayout(right)

        self._form = left
        self._add_text("title", "Figure title", "none")
        self._add_text("xlabel", "X label", "Frequency (<unit>)")
        self._add_text("ylabel", "Y label (all subplots)", "automatic")
        self._add_float("title_size", "Title size", 4, 40)
        self._add_float("subplot_title_size", "Subplot title size", 4, 40)
        self._add_float("label_size", "Axis label size", 4, 40)
        self._add_float("tick_size", "Tick label size", 4, 40)
        self._add_float("linewidth", "Default line width", 0.1, 10, step=0.1)
        self._add_choice("palette", "Colour palette", PALETTES)

        self._form = right
        self._add_bool("legend", "Show legend")
        self._add_choice("legend_loc", "Legend position", LEGEND_LOCATIONS)
        self._add_float("legend_size", "Legend font size", 4, 40)
        self._add_bool("grid", "Grid")
        self._add_bool("log_x", "Logarithmic X axis")
        self._add_optional("xmin", "X min (x-axis unit)")
        self._add_optional("xmax", "X max (x-axis unit)")
        self._add_optional("ymin", "Y min")
        self._add_optional("ymax", "Y max")
        self._add_int("dpi", "Export DPI (Save plot)", 50, 1200)
        return w

    def _add_text(self, attr, label, placeholder):
        e = QtWidgets.QLineEdit(getattr(self.style, attr))
        e.setPlaceholderText(placeholder)
        e.textChanged.connect(lambda t: self._set(attr, t))
        self._form.addRow(label, e)
        self._general[attr] = (e, "text")

    def _add_float(self, attr, label, lo, hi, step=0.5):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setValue(getattr(self.style, attr))
        s.valueChanged.connect(lambda v: self._set(attr, float(v)))
        self._form.addRow(label, s)
        self._general[attr] = (s, "float")

    def _add_int(self, attr, label, lo, hi):
        s = QtWidgets.QSpinBox()
        s.setRange(lo, hi)
        s.setValue(getattr(self.style, attr))
        s.valueChanged.connect(lambda v: self._set(attr, int(v)))
        self._form.addRow(label, s)
        self._general[attr] = (s, "int")

    def _add_bool(self, attr, label):
        c = QtWidgets.QCheckBox()
        c.setChecked(getattr(self.style, attr))
        c.toggled.connect(lambda v: self._set(attr, bool(v)))
        self._form.addRow(label, c)
        self._general[attr] = (c, "bool")

    def _add_choice(self, attr, label, options):
        c = QtWidgets.QComboBox()
        c.addItems(options)
        c.setCurrentText(getattr(self.style, attr))
        c.currentTextChanged.connect(lambda t: self._set(attr, t))
        self._form.addRow(label, c)
        self._general[attr] = (c, "choice")

    def _add_optional(self, attr, label):
        e = QtWidgets.QLineEdit("" if getattr(self.style, attr) is None else str(getattr(self.style, attr)))
        e.setPlaceholderText("auto")
        e.setValidator(QtGui.QDoubleValidator())

        def changed(text):
            try:
                self._set(attr, float(text) if text.strip() else None)
            except ValueError:
                pass  # half-typed number such as "-" or "1e"

        e.textChanged.connect(changed)
        self._form.addRow(label, e)
        self._general[attr] = (e, "optional")

    def _set(self, attr, value):
        if self._updating:
            return
        setattr(self.style, attr, value)
        self.on_change()

    def _load_general_widgets(self):
        self._updating = True
        for attr, (w, kind) in self._general.items():
            value = getattr(self.style, attr)
            if kind == "text":
                w.setText(value)
            elif kind in ("float", "int"):
                w.setValue(value)
            elif kind == "bool":
                w.setChecked(value)
            elif kind == "choice":
                w.setCurrentText(value)
            else:
                w.setText("" if value is None else str(value))
        self._updating = False

    # ------------------------------------------------------------ tables
    def refresh(self, lines, subplots, force=False):
        """Rebuild the subplot / line tables when the drawn lines or their automatic
        values (colour, label, ...) change."""
        line_keys = [tuple(vars(l).values()) for l in lines]
        sp_keys = [tuple(vars(s).values()) for s in subplots]
        if not force and line_keys == self._line_keys and sp_keys == self._subplot_keys:
            return
        self._line_keys, self._subplot_keys = line_keys, sp_keys
        self._updating = True
        self._fill_subplots(subplots)
        self._fill_lines(lines)
        self._updating = False

    def _override(self, store, key, field, value, auto_values=("", None, AUTO, 0, 0.0)):
        """Set/remove one override; automatic values remove the entry."""
        if self._updating:
            return
        entry = store.setdefault(key, {})
        if value in auto_values and not (field == "visible" and value is False):
            entry.pop(field, None)
        else:
            entry[field] = value
        if not entry:
            store.pop(key, None)
        self.on_change()

    def _fill_subplots(self, subplots):
        t = self.subplot_table
        t.setRowCount(len(subplots))
        for row, sp in enumerate(subplots):
            over = self.style.subplot(sp.key)
            item = QtWidgets.QTableWidgetItem(sp.key)
            item.setFlags(Qt.ItemIsEnabled)
            t.setItem(row, 0, item)
            for col, field, auto in ((1, "title", sp.title), (2, "ylabel", sp.ylabel)):
                e = QtWidgets.QLineEdit(over.get(field, ""))
                e.setPlaceholderText(auto or "(none)")
                e.textChanged.connect(lambda txt, k=sp.key, f=field:
                                      self._override(self.style.subplots, k, f, txt))
                t.setCellWidget(row, col, e)
        t.resizeColumnsToContents()

    def _fill_lines(self, lines):
        t = self.line_table
        t.setRowCount(len(lines))
        store = self.style.lines
        for row, li in enumerate(lines):
            over = self.style.line(li.key)

            show = QtWidgets.QCheckBox()
            show.setChecked(over.get("visible", True))
            show.toggled.connect(lambda v, k=li.key: self._override(store, k, "visible", None if v else False))
            t.setCellWidget(row, 0, self._centred(show))

            name = QtWidgets.QTableWidgetItem(li.key)
            name.setFlags(Qt.ItemIsEnabled)
            name.setToolTip(f"subplot: {li.subplot}")
            t.setItem(row, 1, name)

            label = QtWidgets.QLineEdit(over.get("label", ""))
            label.setPlaceholderText(li.label)
            label.textChanged.connect(lambda txt, k=li.key: self._override(store, k, "label", txt))
            t.setCellWidget(row, 2, label)

            t.setCellWidget(row, 3, self._colour_button(li, over.get("color")))

            ls = QtWidgets.QComboBox()
            ls.addItems([AUTO] + list(LINE_STYLES))
            ls.setCurrentText(over.get("linestyle", AUTO))
            ls.setToolTip(f"automatic: {li.linestyle}")
            ls.currentTextChanged.connect(lambda v, k=li.key: self._override(store, k, "linestyle", v))
            t.setCellWidget(row, 4, ls)

            width = QtWidgets.QDoubleSpinBox()
            width.setRange(0, 10)
            width.setSingleStep(0.25)
            width.setSpecialValueText(AUTO)
            width.setValue(over.get("linewidth") or 0)
            width.valueChanged.connect(lambda v, k=li.key: self._override(store, k, "linewidth", float(v)))
            t.setCellWidget(row, 5, width)

            marker = QtWidgets.QComboBox()
            marker.addItems(list(MARKERS))
            marker.setCurrentText(over.get("marker", "none"))
            marker.currentTextChanged.connect(
                lambda v, k=li.key: self._override(store, k, "marker", v, auto_values=("none",)))
            t.setCellWidget(row, 6, marker)
        t.resizeColumnsToContents()
        t.setColumnWidth(1, min(t.columnWidth(1), 280))

    @staticmethod
    def _centred(widget):
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setAlignment(Qt.AlignCenter)
        h.addWidget(widget)
        return w

    def _colour_button(self, li, colour):
        b = QtWidgets.QToolButton()
        b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        menu = QtWidgets.QMenu(b)

        def show(c):
            pix = QtGui.QPixmap(14, 14)
            pix.fill(QtGui.QColor(c or li.color))
            b.setIcon(QtGui.QIcon(pix))
            b.setText(c if c else AUTO)

        def choose():
            c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.style.line(li.key).get("color") or li.color),
                                                self, "Line colour")
            if c.isValid():
                show(c.name())
                self._override(self.style.lines, li.key, "color", c.name())

        def automatic():
            show(None)
            self._override(self.style.lines, li.key, "color", None)

        menu.addAction("Choose colour…", choose)
        menu.addAction("Automatic", automatic)
        b.setMenu(menu)
        show(colour)
        return b

    # ------------------------------------------------------------ buttons
    def set_style(self, style):
        """Copy another style's values into the shared PlotStyle object and redraw."""
        for k, v in style.to_dict().items():
            setattr(self.style, k, v)
        self._load_general_widgets()
        self._line_keys, self._subplot_keys = [], []   # force table rebuild on next refresh
        self.on_change()

    def reset(self):
        self.set_style(PlotStyle())

    def save_style(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save plot style", "plot_style.json",
                                                        "Plot style (*.json)")
        if path:
            self.style.save(path)

    def load_style(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load plot style", "", "Plot style (*.json)")
        if path:
            try:
                self.set_style(PlotStyle.load(path))
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Load plot style", f"Could not load {path}:\n{e}")

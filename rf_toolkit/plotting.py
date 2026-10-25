# Plotting of analysis results with user-editable styling (no Qt here).
#
#   PlotStyle     - every user setting: titles, labels, font sizes, legend, grid, limits,
#                   palette, plus per-subplot and per-line overrides. Saved/loaded as JSON.
#   draw_results  - draws AnalysisResult objects on a matplotlib Figure using a PlotStyle
#                   and returns which lines / subplots were drawn (for the settings dialog).
#
# Empty text / None in an override means "automatic".

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Optional

import seaborn as sns
from matplotlib.colors import to_hex

FREQ = "Frequency_Hz"

PLOT_MODES = ["Single plot (all together)", "One plot per file", "One plot per formula"]
X_UNITS = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}

LINE_STYLES = {"solid": "-", "dashed": "--", "dotted": ":", "dash-dot": "-."}
MARKERS = {"none": "", "point": ".", "circle": "o", "square": "s", "triangle": "^",
           "diamond": "D", "x": "x", "plus": "+", "star": "*"}
LEGEND_LOCATIONS = ["best", "upper right", "upper left", "lower left", "lower right",
                    "center right", "center left", "upper center", "lower center", "center",
                    "outside right", "below plot"]
PALETTES = ["tab10", "deep", "muted", "bright", "dark", "colorblind", "Set1", "Set2",
            "Dark2", "Paired", "viridis", "rocket", "mako", "husl"]

# Line override keys and their meaning (empty / None = automatic)
LINE_KEYS = ("label", "color", "linestyle", "linewidth", "marker", "markersize", "visible")


@dataclass
class PlotStyle:
    # figure
    title: str = ""                 # figure title (suptitle); empty = none
    title_size: float = 13.0
    subplot_title_size: float = 10.0
    # axes
    xlabel: str = ""                # empty = "Frequency (<unit>)"
    ylabel: str = ""                # empty = none (or the formula name for a single formula)
    label_size: float = 10.0
    tick_size: float = 9.0
    grid: bool = True
    xmin: Optional[float] = None    # in the selected x-axis unit
    xmax: Optional[float] = None
    ymin: Optional[float] = None
    ymax: Optional[float] = None
    log_x: bool = False
    # legend
    legend: bool = True
    legend_loc: str = "best"
    legend_size: float = 8.0
    # lines
    linewidth: float = 1.2
    palette: str = "tab10"
    # export
    dpi: int = 200
    # overrides: subplot key -> {"title": str, "ylabel": str}
    subplots: dict = field(default_factory=dict)
    # overrides: line key -> {label, color, linestyle, linewidth, marker, markersize, visible}
    lines: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def line(self, key):
        return self.lines.get(key, {})

    def subplot(self, key):
        return self.subplots.get(key, {})


@dataclass
class LineInfo:
    """A drawn line: key used for overrides, and its automatic label / colour / style."""
    key: str
    label: str
    color: str
    linestyle: str
    subplot: str


@dataclass
class SubplotInfo:
    key: str
    title: str      # automatic title
    ylabel: str     # automatic y label


def line_key(result, column):
    return f"{result.display_name} | {column}"


def _plan(results, mode):
    """[(subplot key, auto title, [(result, column, auto label, colour index, style index)])]"""
    names = list(dict.fromkeys(n for r in results for n in r.array_names))
    single_file = len(results) == 1
    if mode == 0:
        series = []
        for i, r in enumerate(results):
            for j, n in enumerate(r.array_names):
                label = n if single_file else (r.display_name if len(names) == 1 else f"{r.display_name}: {n}")
                series.append((r, n, label, j if single_file else i, 0 if single_file else j))
        title = names[0] if len(names) == 1 else "Analysis results"
        return [("plot", title, series)]
    if mode == 1:
        return [(r.display_name, r.display_name,
                 [(r, n, n, j, 0) for j, n in enumerate(r.array_names)]) for r in results]
    return [(n, n, [(r, n, r.display_name, i, 0) for i, r in enumerate(results) if n in r.data])
            for n in names]


def draw_results(figure, results, mode=0, x_unit="MHz", style=None):
    """Draw results on figure. Returns (list[LineInfo], list[SubplotInfo])."""
    style = style or PlotStyle()
    figure.clear()
    results = [r for r in results if r.array_names]
    if not results:
        return [], []

    plan = _plan(results, mode)
    n_colours = max(len(results), max(len(s) for _, _, s in plan), 1)
    palette = [to_hex(c) for c in sns.color_palette(style.palette, n_colours)]
    style_cycle = list(LINE_STYLES)
    scale = X_UNITS[x_unit]
    single_formula = len({n for r in results for n in r.array_names}) == 1

    axes = figure.subplots(len(plan), 1, sharex=True, squeeze=False)[:, 0]
    line_infos, subplot_infos = [], []
    for ax, (sp_key, auto_title, series) in zip(axes, plan):
        over = style.subplot(sp_key)
        auto_ylabel = auto_title if (mode == 0 and single_formula) else ""
        subplot_infos.append(SubplotInfo(sp_key, auto_title, auto_ylabel))

        for r, col, auto_label, colour_i, style_i in series:
            key = line_key(r, col)
            auto_colour = palette[colour_i % len(palette)]
            auto_ls = style_cycle[style_i % len(style_cycle)]
            line_infos.append(LineInfo(key, auto_label, auto_colour, auto_ls, sp_key))
            lo = style.line(key)
            if lo.get("visible") is False:
                continue
            ax.plot(r.data[FREQ] / scale, r.data[col],
                    label=lo.get("label") or auto_label,
                    color=lo.get("color") or auto_colour,
                    linestyle=LINE_STYLES.get(lo.get("linestyle") or auto_ls, "-"),
                    linewidth=lo.get("linewidth") or style.linewidth,
                    marker=MARKERS.get(lo.get("marker") or "none", ""),
                    markersize=lo.get("markersize") or 4)

        ax.set_title(over.get("title") or (auto_title if len(plan) > 1 or not style.title else ""),
                     fontsize=style.subplot_title_size)
        # global Y label: on the axis for one subplot, once for the whole figure otherwise
        global_ylabel = style.ylabel if len(plan) == 1 else ""
        ax.set_ylabel(over.get("ylabel") or global_ylabel or auto_ylabel, fontsize=style.label_size)
        ax.tick_params(labelsize=style.tick_size)
        ax.grid(style.grid)
        if style.log_x:
            ax.set_xscale("log")
        if style.xmin is not None or style.xmax is not None:
            ax.set_xlim(style.xmin, style.xmax)
        if style.ymin is not None or style.ymax is not None:
            ax.set_ylim(style.ymin, style.ymax)
        if style.legend and ax.lines:
            if style.legend_loc == "outside right":
                ax.legend(fontsize=style.legend_size, loc="upper left", bbox_to_anchor=(1.01, 1.0))
            elif style.legend_loc == "below plot":
                ax.legend(fontsize=style.legend_size, loc="upper center",
                          bbox_to_anchor=(0.5, -0.18), ncol=3)
            else:
                ax.legend(fontsize=style.legend_size, loc=style.legend_loc)

    axes[-1].set_xlabel(style.xlabel or f"Frequency ({x_unit})", fontsize=style.label_size)
    if style.ylabel and len(plan) > 1:
        figure.supylabel(style.ylabel, fontsize=style.label_size)
    if style.title:
        figure.suptitle(style.title, fontsize=style.title_size)
    return line_infos, subplot_infos

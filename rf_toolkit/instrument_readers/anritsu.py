# Anritsu readers
#
#   AnritsuTouchstoneReader : .s1p/.s2p saved by VNA Master (adds Anritsu header parsing)
#   AnritsuMnaReader        : .mna  native VNA Master file (e.g. MS2024B)
#   AnritsuSpaReader        : .spa  native Spectrum Master file (e.g. MS2720T)
#
# File layout notes are in README.md ("File format notes").

import re
import struct
from datetime import datetime

import numpy as np
import pandas as pd

from .base import Measurement, MeasurementReader, register_reader
from .touchstone import TouchstoneReader
from .utils import (FREQ_UNITS, FREQUENCY_COLUMN, parse_key_values, read_text_lines, section,
                    sparam_columns, to_number, trace_column)

# S-parameter code used in the .mna TRACE_S_TYPES field (one hex digit per trace)
MNA_S_PARAM_CODES = {0: "S11", 1: "S21", 2: "S12", 3: "S22"}

# Amplitude unit code used in the .spa UNITS field (only 0 = dBm is confirmed from data)
SPA_UNIT_CODES = {0: "dBm"}


def anritsu_date(text):
    """Anritsu native files store DATE as YYYY-MM-DD-weekday-HH-MM-SS."""
    try:
        y, mo, d, _weekday, h, mi, s = (int(x) for x in str(text).split("-"))
        return datetime(y, mo, d, h, mi, s)
    except (ValueError, TypeError):
        return None


# ----------------------------------------------------------------------------------------
# Touchstone with Anritsu header
# ----------------------------------------------------------------------------------------
@register_reader
class AnritsuTouchstoneReader(TouchstoneReader):
    manufacturer = "Anritsu"
    description = "Touchstone"
    priority = 10

    @classmethod
    def can_read(cls, file_path, head):
        return super().can_read(file_path, head) and b"Anritsu" in head

    def parse_comments(self, comments):
        """Instrument info plus the two columns 'Current Settings' / 'Active Cal Settings'."""
        info = {"manufacturer": "Anritsu", "settings": {}, "calibration": {}}
        for line in comments:
            text = line.strip()
            m = re.search(r"Model:\s*(\S+)", text)
            if m:
                info["model_number"] = m.group(1)
                info["instrument_name"] = text.split("Model:")[0].strip(" :")
                continue
            m = re.match(r"SN:\s*(\S+)", text)
            if m:
                info["serial_number"] = m.group(1)
                continue
            if text.startswith("/"):
                info["instrument_file_path"] = text
                continue
            # "KEY:   current value,   active cal value"
            m = re.match(r"([A-Z0-9 #.]+?):\s+(.*)$", text)
            if m and "," in m.group(2) and not text.startswith("FREQ"):
                key = m.group(1).strip()
                if key == "TYPE":
                    continue
                if key == "CAL TYPE":
                    current, active = _split_cal_type(m.group(2))
                else:
                    current, active = (p.strip() for p in m.group(2).rsplit(",", 1))
                info["settings"][key] = current
                info["calibration"][key] = active
        try:
            info["measurement_time"] = datetime.strptime(info["settings"].get("TIME"),
                                                         "%m/%d/%Y %I:%M:%S %p")
        except (TypeError, ValueError):
            pass
        return info


def _split_cal_type(text):
    """CAL TYPE values can contain commas ('1P2P S11,S21, 1P2P S11,S21'): split in the middle."""
    parts = [p.strip() for p in text.split(",")]
    half = len(parts) // 2
    return ",".join(parts[:half]), ",".join(parts[half:])


# ----------------------------------------------------------------------------------------
# VNA Master native file (.mna)
# ----------------------------------------------------------------------------------------
@register_reader
class AnritsuMnaReader(MeasurementReader):
    manufacturer = "Anritsu"
    instrument_type = "VNA"
    extensions = (".mna",)
    description = "Anritsu VNA Master"
    priority = 10

    def __init__(self, all_traces=False):
        # By default only the traces that were on screen (TOTAL_TRACES) are returned
        self.all_traces = all_traces

    def read(self, file_path):
        with open(file_path, "rb") as f:
            raw = f.read()

        bin_start = raw.find(b"<BINARY DATA>")
        if bin_start < 0:
            raise ValueError(f"No <BINARY DATA> section in {file_path}")
        lines = raw[:bin_start].decode("latin-1").replace("\r", "").split("\n")

        header = parse_key_values(section(lines, "<ANRITSU>", "# Begin MWVNA Setup"))
        params = parse_key_values(section(lines, "<MWVNA PARAMETERS>", "</MWVNA PARAMETERS>"))
        marker_params = parse_key_values(section(lines, "<MWVNA MARKERS>", "</MWVNA MARKERS>"))

        # --- binary trace data (block 0) ---
        # header: uint32 0, uint32 records+1, uint32 ?, uint32 block type (0), uint32 1,
        #         uint8 0, uint32 points; then records of (uint32 index, uint32 flag, f32 re, f32 im)
        data_start = raw.index(b"\n", bin_start) + 1
        blob = raw[data_start:raw.rfind(b"</BINARY DATA>")]
        _, n_records_plus1, _, block_type, _ = struct.unpack_from("<5I", blob, 0)
        n_points = struct.unpack_from("<I", blob, 21)[0]
        if block_type != 0:
            raise ValueError(f"Unexpected first binary block type {block_type} in {file_path}")
        n_records = n_records_plus1 - 1
        n_traces = n_records // n_points
        rec = np.frombuffer(blob, dtype=[("idx", "<u4"), ("flag", "<u4"), ("re", "<f4"), ("im", "<f4")],
                            count=n_records, offset=25)
        if not np.array_equal(rec["idx"], np.tile(np.arange(n_points), n_traces)):
            raise ValueError(f"Trace data in {file_path} does not have the expected layout")
        traces = (rec["re"].astype(float) + 1j * rec["im"].astype(float)).reshape(n_traces, n_points)

        # --- frequency axis (MHz in file) ---
        start_hz = float(params.get("TRACE_1_START_FREQ", 0)) * 1e6
        stop_hz = float(params.get("TRACE_1_STOP_FREQ", 0)) * 1e6
        freq_hz = np.linspace(start_hz, stop_hz, n_points)

        # --- which S-parameter each trace shows (one hex digit per trace, TR1 = lowest) ---
        s_types = int(float(params.get("TRACE_S_TYPES", 0)))
        trace_params = {}
        for t in range(n_traces):
            code = (s_types >> (4 * t)) & 0xF
            trace_params[f"TR{t + 1}"] = MNA_S_PARAM_CODES.get(code, f"code{code}")
        n_active = int(float(params.get("TOTAL_TRACES", n_traces)))
        keep = n_traces if self.all_traces else max(1, min(n_active, n_traces))

        # Same S-parameter on two traces: the later one is named e.g. s11_tr3_log_mag
        df = pd.DataFrame({FREQUENCY_COLUMN: freq_hz})
        used = set()
        for t in range(keep):
            s_param = trace_params[f"TR{t + 1}"]
            sparam_columns(df, s_param if s_param not in used else f"{s_param}_tr{t + 1}", traces[t])
            used.add(s_param)

        # --- markers (XVALUE is stored in mHz) ---
        markers = []
        for key, value in marker_params.items():
            m = re.fullmatch(r"MKR_MWVNA_XVALUE(\d+)", key)
            if not m:
                continue
            i = m.group(1)
            point = marker_params.get(f"MKR_MWVNA_POINT{i}", -1)
            if point is None or point < 0:
                continue  # marker not placed
            markers.append({"marker": int(i), "frequency_Hz": float(value) / 1e3,
                            "trace": marker_params.get(f"MKR_MWVNA_TRACE{i}"), "point": point,
                            "flags": marker_params.get(f"MKR_MWVNA_FLAGS{i}")})

        # --- limit lines per trace ---
        limits = {}
        for kind in ("LOWER", "UPPER"):
            for t in range(1, 5):
                sec = parse_key_values(section(lines, f"<{kind} LIMITS TR {t}>", f"</{kind} LIMITS TR {t}>"))
                if sec.get("LIMIT_MWVNA_TOTAL_POINTS", 0):
                    limits[f"{kind.lower()}_TR{t}"] = sec

        # --- calibration settings (text part; the binary cal coefficients are not decoded) ---
        calibration = {
            "settings": {k: v for k, v in params.items() if re.search(r"(^|_)CAL(_|$)", k)},
            "port1_ref_plane_length": params.get("PORT_1_REF_PLANE_LENGTH"),
            "port2_ref_plane_length": params.get("PORT_2_REF_PLANE_LENGTH"),
            "user_cal_kits": _parse_cal_kits(section(lines, "<MWVNA CAL KITS>", "</MWVNA CAL KITS>")),
            "binary_cal_data_bytes": len(blob) - (25 + 16 * n_records),
        }

        # --- warnings ---
        warnings = []
        if params.get("DOMAIN", 0):
            warnings.append("DOMAIN is not 0: data may be time/distance domain, x-axis is still given as frequency")
        filled = np.nonzero(np.any(traces[:keep] != 0, axis=0))[0]
        n_valid = int(filled[-1]) + 1 if len(filled) else 0
        if n_valid < n_points:
            warnings.append(f"only the first {n_valid} of {n_points} points contain data; the rest are zero")

        temp = params.get("CURRENT_TEMPERATURE")
        info = {
            "file_format": "mna",
            "manufacturer": "Anritsu",
            "instrument_type": "VNA",
            "model_number": str(header.get("MODEL", "")) or None,
            "serial_number": header.get("SN"),
            # "instrument_file_path": header.get("DESCR"),
            # "measurement_time": anritsu_date(header.get("DATE")),
            # "app_name": header.get("APP_NAME"),
            # "firmware": {"package": header.get("PACKAGE_VER"), "base": header.get("BASE_VER"),
            #              "app": header.get("APP_VER")},
            "n_points": n_points,
            "n_valid_points": n_valid,
            "settings": {
                "start_freq_Hz": start_hz,
                "stop_freq_Hz": stop_hz,
                "n_points": n_points,
                "averaging_factor": params.get("AVERAGING_FACTOR"),
                # "ifbw_code": params.get("IFBW"),
                # "source_power_code": params.get("RF_SOURCE_POWER"),
                # "sweep_type_code": params.get("SWEEP_TYPE"),
                # "domain_code": params.get("DOMAIN"),  # 0 = frequency domain
                # "bias_tee_state": params.get("BIAS_TEE_STATE"),
                "internal_temp_C": temp / 4 if isinstance(temp, (int, float)) else None,
            },
            # "total_traces_on_screen": n_active,
            # "trace_parameters": trace_params,
            # "markers": markers,
            # "limits": limits,
            "calibration": calibration,
            # "header": header,
            # "raw_parameters": params,
            "warnings": warnings,
        }
        return Measurement(df, info)


def _parse_cal_kits(lines):
    """Parse the user cal kit tree into {'COAXIAL/SOLT/USER=1': {...}, ...}, skipping empty kits."""
    kits, path, current = {}, [], None
    for line in lines:
        line = line.strip()
        if line.startswith("</"):
            if current is not None and any(v not in ("", 0, 0.0) for v in current.values()):
                kits["/".join(path)] = current
            current = None
            if path:
                path.pop()
        elif line.startswith("<") and line.endswith(">"):
            path.append(line[1:-1])
            if line.startswith("<USER="):
                current = {}
        elif "=" in line and current is not None:
            key, value = line.split("=", 1)
            current[key.strip()] = to_number(value)
    return kits


# ----------------------------------------------------------------------------------------
# Spectrum Master native file (.spa)
# ----------------------------------------------------------------------------------------
@register_reader
class AnritsuSpaReader(MeasurementReader):
    manufacturer = "Anritsu"
    instrument_type = "SA"
    extensions = (".spa",)
    description = "Anritsu Spectrum Master"
    priority = 10

    def read(self, file_path):
        lines = read_text_lines(file_path)
        header = parse_key_values(section(lines, "<ANRITSU>", "# Begin SPA Setup"))
        setup = parse_key_values(section(lines, "# Begin TRACE A Setup", "# Setup Done"))
        unit_code = int(float(setup.get("UNITS", 0)))
        amp_unit = SPA_UNIT_CODES.get(unit_code, f"unit_code{unit_code}")

        # --- trace data: "P_<i>=<amplitude> , <freq> <unit>"; trace A -> trace1, B -> trace2 ...
        point_re = re.compile(r"P_(\d+)=\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*([A-Za-z]+)")
        trace_data = {}
        for number, letter in enumerate("ABCDEF", start=1):
            pts = [point_re.match(ln) for ln in section(lines, f"# Begin TRACE {letter} Data", "# Data Done")]
            pts = [p for p in pts if p]
            if pts:
                freq = np.array([float(p.group(3)) * FREQ_UNITS[p.group(4).upper()] for p in pts])
                amp = np.array([float(p.group(2)) for p in pts])
                trace_data[trace_column(number)] = (freq, amp)
        if not trace_data:
            raise ValueError(f"No trace data found in {file_path}")

        first_freq = next(iter(trace_data.values()))[0]
        df = pd.DataFrame({FREQUENCY_COLUMN: first_freq})
        for col, (freq, amp) in trace_data.items():
            if len(freq) == len(first_freq) and np.allclose(freq, first_freq):
                df[col] = amp
            else:  # trace on a different frequency grid: keep its own frequency column
                df = df.join(pd.DataFrame({f"{FREQUENCY_COLUMN}_{col}": freq, col: amp}), how="outer")

        # --- markers (FREQM in mHz) ---
        marker_params = parse_key_values(section(lines, "# Begin SPA Marker", "# SPA Marker Done"))
        markers = []
        for key, value in marker_params.items():
            m = re.fullmatch(r"MKR_SPA_FREQM(\d+)", key)
            if m and float(value) > 0:
                i = m.group(1)
                markers.append({"marker": int(i), "frequency_Hz": float(value) / 1e3,
                                "amplitude": marker_params.get(f"MKR_SPA_MAGNT{i}"),
                                "point": marker_params.get(f"MKR_SPA_POINT{i}"),
                                "trace": marker_params.get(f"MKR_SPA_TRACE{i}"),
                                "flags": marker_params.get(f"MKR_SPA_FLAGS{i}")})

        # --- limit lines: "LIMIT_POINTn=<freq mHz> <level x1000> <flag>" ---
        limits = {}
        for kind, start in (("upper", "# Upper Limit"), ("lower", "# Lower Limit")):
            sec = section(lines, start, "# Limit Done")
            pts = []
            for ln in sec:
                m = re.match(r"LIMIT_POINT\d+=\s*(\S+)\s+(\S+)", ln)
                if m:
                    pts.append((float(m.group(1)) / 1e3, float(m.group(2)) / 1e3))
            limits[kind] = {"enabled": bool(parse_key_values(sec).get("LIMIT_FLAG", 0)),
                            "points_Hz_level": pts}

        def mhz(key):
            return float(setup[key]) * 1e6 if key in setup else None

        info = {
            "file_format": "spa",
            "manufacturer": "Anritsu",
            "instrument_type": "SA",
            "model_number": str(header.get("MODEL", "")) or None,
            "serial_number": header.get("SN"),
            # "instrument_file_path": header.get("DESCR"),
            "measurement_time": anritsu_date(header.get("DATE")),
            # "app_name": header.get("APP_NAME"),
            # "firmware": {"package": header.get("PACKAGE_VER"), "base": header.get("BASE_VER"),
            #              "app": header.get("APP_VER")},
            # "traces": list(trace_data.keys()),
            "amplitude_unit": amp_unit,
            "settings": {
                "center_freq_Hz": mhz("CENTER_FREQ"),
                "span_Hz": mhz("SPAN"),
                "start_freq_Hz": mhz("START_FREQ"),
                "stop_freq_Hz": mhz("STOP_FREQ"),
                # stored RBW/VBW setting; may not be the RBW in use when auto RBW/VBW is on
                "rbw_setting_Hz": mhz("RBW"),
                "vbw_setting_Hz": mhz("VBW"),
                "rbw_type_code": setup.get("RBW_TYPE"),
                "vbw_type_code": setup.get("VBW_TYPE"),
                # "attenuation_type_code": setup.get("ATTEN_TYPE"),
                "rbw_vbw_ratio": setup.get("RBW_VBW_RATIO"),
                "span_rbw_ratio": setup.get("SPAN_RBW_RATIO"),
                "measured_sweep_time_s": setup.get("MEAS_SWEEP_TIME"),
                # "reference_level": setup.get("REFERENCE_LEVEL"),
                # "ref_level_offset_dB": setup.get("REF_LEVEL_OFFSET"),
                # "scale_dB_per_div": setup.get("SCALE"),
                "input_attenuation_dB": setup.get("INPUT_ATTEN"),
                "preamp_on": bool(setup.get("PREAMP_SET", 0)),
                # "detection_code": setup.get("DETECTION"),
                # "trace_average_count": setup.get("TRACE_AVERAGE"),
                # "trace_mode_code": setup.get("TRACE_MODE"),
            },
            "markers": markers,
            "limits": limits,
            "header": header,
            "raw_parameters": setup,
        }
        return Measurement(df, info)

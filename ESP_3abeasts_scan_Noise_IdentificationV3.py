import math
import argparse
import subprocess
import sys
import threading
import time
import csv
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from matplotlib.ticker import MaxNLocator
import serial
from serial.tools import list_ports

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.backend_bases import MouseButton

# ============================================================
#  AlphaBeast - Serial Noise Scan GUI
#  Version revue:
#   - scan complet automatique
#   - estimation auto de gaussienne pendant/après scan
#   - validation manuelle APRES tous les scans
#   - sélection manuelle de:
#         * mu bruit
#         * mu - 3 sigma
#   - sauvegarde CSV finale
# ============================================================

NUM_CHIPS = 3
NUM_THRESHOLDS = 3
VTHBL_REG = 3
THRESHOLD_REGS = [4, 5, 6]     # TH0, TH1, TH2
COUNTER_INDEXES = [0, 1, 2]    # c0, c1, c2
COUNTER_MOD = 1 << 24
ANALYSIS_GAUSSIAN = "gaussian"
ANALYSIS_SIGMOID = "sigmoid"


@dataclass
class ScanPoint:
    chip: int
    threshold: int
    dac: int
    vth_bl: int | None
    hits_per_s: float
    count0: int
    count1: int
    dt_s: float
    mu_est: float | None = None
    sigma_est: float | None = None
    r2_est: float | None = None


class FirmwareSerialText:
    def __init__(self):
        self.ser: serial.Serial | None = None
        self.lock = threading.RLock()

    def open(self, port: str, baudrate: int = 115200, timeout: float = 0.2):
        self.close()
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=1.0,
        )
        time.sleep(0.4)
        self.clear_input()

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def read_reg(self, chip: int, addr: int, timeout: float = 2.0) -> int:

        with self.lock:

            self._require_open()
            self.clear_input()  # vider tout ce qui reste du boot

            self._write_line(f"REG.R {chip} {addr}")

            t0 = time.time()

            while time.time() - t0 < timeout:

                line = self._readline_decoded()

                if not line:
                    continue

                # on ignore tout sauf la vraie réponse
                if not line.startswith("REG.R"):
                    continue

                # exemple:
                # REG.R chip0 addr3 => 96

                parts = line.replace("=>", " ").split()

                for p in reversed(parts):
                    if p.isdigit():
                        return int(p)

            raise RuntimeError("Timeout waiting for REG.R reply")

    def is_open(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def _require_open(self):
        if not self.is_open():
            raise RuntimeError("Serial port not open")

    def clear_input(self):
        if not self.is_open():
            return
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

    def _write_line(self, line: str):
        self._require_open()
        if not line.endswith("\n"):
            line += "\n"
        self.ser.write(line.encode("utf-8", errors="replace"))
        self.ser.flush()

    def _readline_decoded(self) -> str | None:
        self._require_open()
        raw = self.ser.readline()
        if not raw:
            return None
        try:
            return raw.decode("utf-8", errors="replace").strip()
        except Exception:
            return None

    def _collect_until(self, predicate, timeout: float = 2.0) -> list[str]:
        lines: list[str] = []
        t0 = time.time()
        while time.time() - t0 < timeout:
            line = self._readline_decoded()
            if line is None or line == "":
                continue
            lines.append(line)
            if predicate(lines, line):
                return lines
        return lines

    def send_and_expect_one_of(self, cmd: str, accepted_prefixes: list[str], timeout: float = 2.0) -> str:
        with self.lock:
            self._require_open()
            self.clear_input()
            self._write_line(cmd)

            lines = self._collect_until(
                lambda _lines, last: any(last.startswith(p) for p in accepted_prefixes),
                timeout=timeout,
            )

            for line in reversed(lines):
                if any(line.startswith(p) for p in accepted_prefixes):
                    return line

            raise RuntimeError(f"No valid reply for '{cmd}'. Received: {lines}")

    def write_reg(self, chip: int, addr: int, value: int, timeout: float = 2.0) -> bool:
        reply = self.send_and_expect_one_of(
            f"REG.W {chip} {addr} {value}",
            accepted_prefixes=["OK REG.W", "ERR"],
            timeout=timeout,
        )
        return reply.startswith("OK REG.W")

    def zero_counters(self, timeout: float = 2.0) -> bool:
        reply = self.send_and_expect_one_of(
            "ZERO",
            accepted_prefixes=["OK ZERO", "ERR"],
            timeout=timeout,
        )
        return reply.startswith("OK ZERO")

    def set_mux(self, value: str, timeout: float = 2.0) -> str:
        return self.send_and_expect_one_of(
            f"MUX {value}",
            accepted_prefixes=["OK MUX", "ERR"],
            timeout=timeout,
        )

    def read_esp_id(self, timeout: float = 2.0) -> int | None:
        reply = self.send_and_expect_one_of(
            "ID?",
            accepted_prefixes=["ESP_abeast_ID=", "ERR"],
            timeout=timeout,
        )
        if reply.startswith("ERR") or "=" not in reply:
            return None
        try:
            return int(reply.split("=", 1)[1].strip())
        except Exception:
            return None

    def read_cntcsv(self, timeout: float = 2.0) -> dict[int, tuple[int, int, int]]:
        with self.lock:
            self._require_open()
            self.clear_input()
            self._write_line("CNTCSV")

            lines: list[str] = []
            t0 = time.time()

            while time.time() - t0 < timeout:
                line = self._readline_decoded()
                if not line:
                    continue

                parts = line.split(",")
                if len(parts) != 4:
                    continue

                try:
                    chip = int(parts[0].strip())
                    c0 = int(parts[1].strip())
                    c1 = int(parts[2].strip())
                    c2 = int(parts[3].strip())
                except ValueError:
                    continue

                if 0 <= chip < NUM_CHIPS:
                    lines.append((chip, c0, c1, c2))

                    # 🔥 dès qu'on a les 3 chips → stop
                    if len(lines) == NUM_CHIPS:
                        break

            if len(lines) != NUM_CHIPS:
                raise RuntimeError(f"CNTCSV timeout or incomplete data: {lines}")

            # 🔥 reconstruction propre (évite mélange ordre)
            parsed: dict[int, tuple[int, int, int]] = {}
            for chip, c0, c1, c2 in lines:
                parsed[chip] = (c0, c1, c2)

            # 🔥 sécurité : vérifier qu'on a bien 0,1,2
            if set(parsed.keys()) != set(range(NUM_CHIPS)):
                raise RuntimeError(f"CNTCSV corrupted frame: {parsed}")

            return parsed


class NoiseScanEngine:
    def __init__(self, fw: FirmwareSerialText, log_fn, point_cb, status_cb, done_cb):
        self.fw = fw
        self.log = log_fn
        self.on_point = point_cb
        self.on_status = status_cb
        self.on_done = done_cb
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_results: list[ScanPoint] = []
        self.summary_rows: list[dict] = []
        self.pause_event = threading.Event()
        self.skip_threshold_event = threading.Event()
        self.scan_vthbl_by_chip: dict[int, int] = {}
    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def stop(self):
        self.stop_event.set()

    def start(
            self,
            dwell_s,
            settle_s,
            do_zero_each_point,
            use_mux,
            mux_value,
            analysis_mode,
            thresholds,
            output_dir=None,
            chips=None,
            stop_on_zero=False,
            max_zero=2,
            dac_ranges=None,
            vthbl_values=None,
    ):
        if self.is_running():
            raise RuntimeError("A scan is already running")

        self.stop_event.clear()
        self.last_results = []
        self.summary_rows = []
        self.scan_vthbl_by_chip = dict(vthbl_values or {})

        self.thread = threading.Thread(
            target=self._run,
            args=(dwell_s, settle_s, do_zero_each_point, use_mux, mux_value, analysis_mode, thresholds, output_dir, chips, stop_on_zero, max_zero, dac_ranges),
            daemon=True,
        )
        self.thread.start()

    def pause(self):
        self.pause_event.set()

    def resume(self):
        self.pause_event.clear()

    def skip_threshold(self):
        self.skip_threshold_event.set()

    def _save_plot(self, output_dir, chip, th, xs, ys):
        try:
            import matplotlib.pyplot as plt
            from pathlib import Path

            Path(output_dir).mkdir(parents=True, exist_ok=True)

            plt.figure(figsize=(6, 4))
            plt.plot(xs, ys, marker='o')

            plt.title(f"IC{chip + 1} TH{th}")
            plt.xlabel("DAC")
            plt.ylabel("Hits/s")
            plt.grid(True)

            # 🔥 IMPORTANT : axes propres
            plt.gca().xaxis.set_major_locator(plt.MaxNLocator(integer=True))

            filename = Path(output_dir) / f"IC{chip + 1}_TH{th}.png"
            plt.savefig(filename, dpi=150)
            plt.close()

            self.log(f"Saved plot: {filename}")

        except Exception as e:
            self.log(f"Plot save error: {e}")
    def _run(
            self,
            dwell_s,
            settle_s,
            do_zero_each_point,
            use_mux,
            mux_value,
            analysis_mode,
            thresholds,
            output_dir,
            chips,
            stop_on_zero,
            max_zero,
            dac_ranges,
    ):
        try:
            if use_mux:
                self.on_status(f"Setting MUX {mux_value}...")
                reply = self.fw.set_mux(mux_value)
                self.log(f"MUX reply: {reply}")

            total_scans = len(chips) * len(thresholds)
            scan_index = 0
            if dac_ranges is None:
                dac_ranges = {
                    (chip, th): (255, 0)
                    for chip in chips
                    for th in thresholds
                }
            for chip in chips:
                for th in thresholds:
                    if self.stop_event.is_set():
                        self.on_status("Scan stopped by user")
                        return

                    scan_index += 1
                    reg = THRESHOLD_REGS[th]
                    counter_idx = COUNTER_INDEXES[th]

                    self.on_status(f"Scanning IC{chip + 1} TH{th} ({scan_index}/{total_scans})")
                    self.log(f"--- IC{chip + 1} TH{th} | reg={reg} | counter={counter_idx} ---")

                    xs: list[int] = []
                    ys: list[float] = []
                    zero_hits_streak = 0
                    dac_min, dac_max = dac_ranges[(chip, th)]

                    step = -1 if dac_min > dac_max else 1

                    for dac in range(dac_min, dac_max + step, step):

                        if self.stop_event.is_set():
                            self.on_status("Scan stopped by user")
                            return

                        # pause utilisateur
                        while self.pause_event.is_set():
                            time.sleep(0.1)

                        # skip threshold demandé
                        if self.skip_threshold_event.is_set():
                            self.skip_threshold_event.clear()
                            self.log("Threshold skipped by user")
                            break
                        if self.stop_event.is_set():
                            self.on_status("Scan stopped by user")
                            return

                        ok = self.fw.write_reg(chip, reg, dac, timeout=2.0)
                        if not ok:
                            raise RuntimeError(f"Failed writing DAC={dac} on IC{chip + 1} TH{th}")

                        if settle_s > 0:
                            time.sleep(settle_s)

                        if do_zero_each_point:
                            ok_zero = self.fw.zero_counters(timeout=2.0)
                            if not ok_zero:
                                raise RuntimeError(f"ZERO failed before DAC={dac} on IC{chip + 1} TH{th}")

                            t0 = time.time()
                            time.sleep(dwell_s)
                            cnt = self.fw.read_cntcsv(timeout=2.0)
                            t1 = time.time()

                            dt = max(t1 - t0, 1e-9)
                            c0 = 0
                            c1 = cnt[chip][counter_idx]
                            delta = c1
                        else:
                            cnt0 = self.fw.read_cntcsv(timeout=2.0)
                            c0 = cnt0[chip][counter_idx]

                            t0 = time.time()
                            time.sleep(dwell_s)

                            cnt1 = self.fw.read_cntcsv(timeout=2.0)
                            t1 = time.time()

                            dt = max(t1 - t0, 1e-9)
                            c1 = cnt1[chip][counter_idx]
                            delta = (c1 - c0) % COUNTER_MOD

                        rate = delta / dt

                        xs.append(dac)
                        ys.append(rate)


                        # arrêt si plus de bruit
                        if rate == 0:
                            zero_hits_streak += 1
                        else:
                            zero_hits_streak = 0

                        if stop_on_zero and zero_hits_streak >= max_zero:
                            self.log(f"{max_zero} DAC consécutifs à 0 hits → stop TH")
                            break
                        if analysis_mode == ANALYSIS_SIGMOID:
                            inflect_est, sigmoid_r2 = self._fit_sigmoid_inflection(xs, ys)
                            mu_est = inflect_est
                            sigma_est = None
                            r2_est = sigmoid_r2
                        else:
                            mu_est, sigma_est, r2_est = self._fit_gaussian_estimate(xs, ys)


                        # if r2_est is not None and r2_est > 0.92:
                        #     self.log(f"Gaussian detected (R²={r2_est:.3f}) -> next threshold")
                        #     break
                        point = ScanPoint(
                            chip=chip,
                            threshold=th,
                            dac=dac,
                            vth_bl=self.scan_vthbl_by_chip.get(chip),
                            hits_per_s=rate,
                            count0=c0,
                            count1=c1,
                            dt_s=dt,
                            mu_est=mu_est,
                            sigma_est=sigma_est,
                            r2_est=r2_est,
                        )
                        self.last_results.append(point)
                        self.on_point(point)

                    if analysis_mode == ANALYSIS_SIGMOID:
                        final_inflect, final_r2 = self._fit_sigmoid_inflection(xs, ys)
                        final_mu, final_sigma = final_inflect, None
                    else:
                        final_mu, final_sigma, final_r2 = self._fit_gaussian_estimate(xs, ys)
                    if output_dir:
                        self._save_plot(output_dir, chip, th, xs, ys)
                    mu_minus_3sigma = None
                    if final_mu is not None and final_sigma is not None:
                        mu_minus_3sigma = final_mu - 3.0 * final_sigma

                    self.summary_rows.append({
                        "chip": chip + 1,
                        "threshold": th,
                        "vth_bl": self.scan_vthbl_by_chip.get(chip),
                        "analysis_mode": analysis_mode,
                        "points": len(xs),
                        "mu_auto": final_mu if analysis_mode == ANALYSIS_GAUSSIAN else None,
                        "sigma_auto": final_sigma,
                        "r2_auto": final_r2,
                        "mu_minus_3sigma_auto": mu_minus_3sigma,
                        "inflection_auto": final_mu if analysis_mode == ANALYSIS_SIGMOID else None,
                        "best_dac": self._best_dac(xs, ys),
                        "max_hits_per_s": max(ys) if ys else None,
                    })

            self.on_status("Scan completed - manual validation required")
            self.log("Scan completed - enter manual validation mode")
            self.on_done()

        except Exception as e:
            self.on_status(f"Error: {e}")
            self.log(f"ERROR: {e}")

    @staticmethod
    def _best_dac(xs: list[int], ys: list[float]) -> int | None:
        if not xs or not ys:
            return None
        idx = max(range(len(ys)), key=lambda i: ys[i])
        return xs[idx]

    @staticmethod
    def _fit_gaussian_estimate(xs: list[int], ys: list[float]) -> tuple[float | None, float | None, float | None]:
        if len(xs) < 5:
            return None, None, None

        pairs = [(float(x), float(y)) for x, y in zip(xs, ys) if y > 0]
        if len(pairs) < 5:
            return None, None, None

        x = [p[0] for p in pairs]
        y = [p[1] for p in pairs]

        y_sum = sum(y)
        if y_sum <= 0:
            return None, None, None

        mu = sum(xx * yy for xx, yy in zip(x, y)) / y_sum
        var = sum(yy * (xx - mu) ** 2 for xx, yy in zip(x, y)) / y_sum
        sigma = math.sqrt(max(var, 1e-12))
        amp = max(y)

        if sigma <= 0:
            return None, None, None

        y_hat = [amp * math.exp(-0.5 * ((xx - mu) / sigma) ** 2) for xx in x]
        y_mean = sum(y) / len(y)
        ss_res = sum((yy - yhh) ** 2 for yy, yhh in zip(y, y_hat))
        ss_tot = sum((yy - y_mean) ** 2 for yy in y)
        r2 = 0.0 if ss_tot <= 1e-12 else 1.0 - (ss_res / ss_tot)

        mu_dac = int(round(mu))
        sigma_dac = int(round(sigma))
        return mu_dac, sigma_dac, r2

    @staticmethod
    def _fit_sigmoid_inflection(xs: list[int], ys: list[float]) -> tuple[int | None, float | None]:
        if len(xs) < 5 or len(ys) < 5:
            return None, None

        pairs = [(float(x), float(y)) for x, y in zip(xs, ys)]
        pairs.sort(key=lambda p: p[0])
        x = [p[0] for p in pairs]
        y = [p[1] for p in pairs]

        y_min = min(y)
        y_max = max(y)
        amp = y_max - y_min
        if amp <= 1e-9:
            return None, None

        mid = y_min + 0.5 * amp
        idx = min(range(len(y)), key=lambda i: abs(y[i] - mid))
        x0 = x[idx]

        x_left = x[0]
        x_right = x[-1]
        scale = max((x_right - x_left) / 8.0, 1.0)

        y_hat = [y_min + amp / (1.0 + math.exp(-(xx - x0) / scale)) for xx in x]
        y_mean = sum(y) / len(y)
        ss_res = sum((yy - yhh) ** 2 for yy, yhh in zip(y, y_hat))
        ss_tot = sum((yy - y_mean) ** 2 for yy in y)
        r2 = 0.0 if ss_tot <= 1e-12 else 1.0 - (ss_res / ss_tot)

        return int(round(x0)), r2

    def save_results(
        self,
        outdir: Path,
        manual_selections: dict[tuple[int, int], dict[str, int | None]],
        selected_chips: set[int] | None = None,
    ):
        outdir.mkdir(parents=True, exist_ok=True)
        if selected_chips is None:
            selected_chips = set(range(NUM_CHIPS))

        raw_path = outdir / "noise_scan_raw.csv"
        with raw_path.open("w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow([
                "chip", "threshold", "vth_bl", "dac", "hits_per_s",
                "count0", "count1", "dt_s",
                "mu_est", "sigma_est", "r2_est"
            ])
            for p in self.last_results:
                if p.chip not in selected_chips:
                    continue
                wr.writerow([
                    p.chip + 1,
                    p.threshold,
                    p.vth_bl,
                    p.dac,
                    p.hits_per_s,
                    p.count0,
                    p.count1,
                    p.dt_s,
                    p.mu_est,
                    p.sigma_est,
                    p.r2_est,
                ])

        summary_path = outdir / "noise_scan_summary_validated.csv"
        with summary_path.open("w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow([
                "chip",
                "threshold",
                "vth_bl",
                "analysis_mode",
                "points",
                "mu_auto",
                "sigma_auto",
                "r2_auto",
                "mu_minus_3sigma_auto",
                "inflection_auto",
                "best_dac",
                "max_hits_per_s",
                "mu_manual",
                "mu_minus_3sigma_manual",
                "inflection_manual",
            ])

            for row in self.summary_rows:
                key = (row["chip"] - 1, row["threshold"])
                if key[0] not in selected_chips:
                    continue
                sel = manual_selections.get(key, {})
                wr.writerow([
                    row["chip"],
                    row["threshold"],
                    row.get("vth_bl"),
                    row.get("analysis_mode"),
                    row["points"],
                    row["mu_auto"],
                    row["sigma_auto"],
                    row["r2_auto"],
                    row["mu_minus_3sigma_auto"],
                    row.get("inflection_auto"),
                    row["best_dac"],
                    row["max_hits_per_s"],
                    sel.get("mu"),
                    sel.get("mu_minus_3sigma"),
                    sel.get("inflection"),
                ])


class App(tk.Tk):
    def __init__(self, auto_port: str | None = None):
        super().__init__()
        self.title("AlphaBeast Serial Noise Scan GUI")
        self.geometry("1400x900")

        self.fw = FirmwareSerialText()
        self.engine = NoiseScanEngine(
            self.fw,
            log_fn=self._threadsafe_log,
            point_cb=self._threadsafe_point,
            status_cb=self._threadsafe_status,
            done_cb=self._threadsafe_done,
        )
        self.curves_by_key = {}
        self.manual_selections = {}
        self.output_dir_after_scan = None
        self.review_mode = False

        self.notebook = None
        self.axes = {}
        self.canvases = {}
        self.lines_by_chip_th = {}
        self.last_analysis_mode = ANALYSIS_GAUSSIAN
        self.connected_esp_id: int | None = None
        self.connected_port: str | None = None
        self.scan_status = ""
        self._build_ui()
        self.refresh_ports()
        if auto_port:
            self.port_var.set(auto_port)
            self.after(250, self._auto_connect_port)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _auto_connect_port(self):
        if self.fw.is_open():
            return
        if not self.port_var.get().strip():
            return
        self.toggle_connect()
    def pause_scan(self):
        self.engine.pause()
        self._log("Scan paused")

    def load_vthbl_defaults(self):

        if not self.fw.is_open():
            return

        try:

            for chip in range(NUM_CHIPS):
                val = self.fw.read_reg(chip, VTHBL_REG)

                print("VTHBL READ", chip, val)



                self.vthbl_vars[chip].set(str(val))

                self._log(f"IC{chip + 1} VTH_BL = {val}")

        except Exception as e:

            self._log(f"Error reading VTH_BL: {e}")
    def bind_canvas_click(self, canvas, chip):
        canvas.mpl_connect(
            "button_press_event",
            lambda event: self.on_plot_click_chip(event, chip)
        )
    def resume_scan(self):
        self.engine.resume()
        self._log("Scan resumed")

    def skip_threshold(self):
        self.engine.skip_threshold()
        self._log("Skip threshold requested")

    def set_vthbl(self, chip):

        try:
            if not self.fw.is_open():
                raise RuntimeError("Serial not connected")

            val = int(self.vthbl_vars[chip].get())

            ok = self.fw.write_reg(chip, VTHBL_REG, val)

            if not ok:
                raise RuntimeError("REG.W failed")

            self._log(f"IC{chip + 1} VTH_BL set to {val}")

        except Exception as e:
            messagebox.showerror("VTH_BL error", str(e))
    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        conn = ttk.LabelFrame(top, text="Serial connection", padding=8)
        conn.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        ttk.Label(conn, text="Port").grid(row=0, column=0, sticky="w")
        self.port_var = tk.StringVar()
        self.port_cb = ttk.Combobox(conn, textvariable=self.port_var, width=18, state="readonly")
        self.port_cb.grid(row=0, column=1, padx=4)
        ttk.Button(conn, text="Refresh", command=self.refresh_ports).grid(row=0, column=2, padx=4)
        ttk.Label(conn, text="Multi-ESP").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.multi_ports_listbox = tk.Listbox(conn, selectmode=tk.MULTIPLE, height=4, exportselection=False)
        self.multi_ports_listbox.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            conn,
            text="Open selected in new windows",
            command=self.open_selected_ports_in_new_windows,
        ).grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        ttk.Label(conn, text="Baud").grid(row=1, column=0, sticky="w")
        self.baud_var = tk.StringVar(value="115200")
        ttk.Entry(conn, textvariable=self.baud_var, width=10).grid(row=1, column=1, sticky="w", padx=4)

        self.connect_btn = ttk.Button(conn, text="Connect", command=self.toggle_connect)
        self.connect_btn.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        scan = ttk.LabelFrame(top, text="Scan settings", padding=8)
        scan.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        ttk.Label(scan, text="Dwell time (s)").grid(row=0, column=0, sticky="w")
        self.dwell_var = tk.StringVar(value="3")
        ttk.Entry(scan, textvariable=self.dwell_var, width=10).grid(row=0, column=1, sticky="w", padx=4)

        ttk.Label(scan, text="Settling time (s)").grid(row=1, column=0, sticky="w")
        self.settle_var = tk.StringVar(value="0.03")
        ttk.Entry(scan, textvariable=self.settle_var, width=10).grid(row=1, column=1, sticky="w", padx=4)

        self.zero_each_point_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(scan, text="ZERO before each DAC point", variable=self.zero_each_point_var).grid(
            row=2, column=0, columnspan=2, sticky="w"
        )

        self.use_mux_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(scan, text="Set MUX before scan", variable=self.use_mux_var).grid(
            row=3, column=0, columnspan=2, sticky="w"
        )

        ttk.Label(scan, text="MUX value").grid(row=4, column=0, sticky="w")
        self.mux_var = tk.StringVar(value="1")
        ttk.Combobox(
            scan,
            textvariable=self.mux_var,
            values=["0", "1", "2", "3", "Abeast0", "Abeast1", "Abeast2"],
            width=10,
            state="readonly",
        ).grid(row=4, column=1, sticky="w", padx=4)
        # --- Sélection des IC ---
        ttk.Label(scan, text="IC à scanner").grid(row=5, column=0, sticky="w")

        self.ic_vars = []
        ic_frame = ttk.Frame(scan)
        ic_frame.grid(row=5, column=1, sticky="w")

        for i in range(NUM_CHIPS):
            var = tk.BooleanVar(value=True)
            self.ic_vars.append(var)
            ttk.Checkbutton(ic_frame, text=f"IC{i + 1}", variable=var).pack(side=tk.LEFT)

        # --- Arrêt sur 0 hits ---
        ttk.Label(scan, text="Stop si 0 hits").grid(row=6, column=0, sticky="w")

        self.stop_on_zero_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(scan, variable=self.stop_on_zero_var).grid(row=6, column=1, sticky="w")

        ttk.Label(scan, text="Nb 0 consécutifs").grid(row=7, column=0, sticky="w")

        # --- Plage DAC par threshold ---
        # --- Plages DAC par IC et TH ---
        ttk.Label(scan, text="DAC ranges (min → max)").grid(row=8, column=0, sticky="w")

        self.dac_ranges = {}  # clé = (chip, th)

        range_frame = ttk.Frame(scan)
        range_frame.grid(row=9, column=0, columnspan=2, sticky="w")

        # header TH
        for th in range(NUM_THRESHOLDS):
            ttk.Label(range_frame, text=f"TH{th}").grid(row=0, column=th + 1, padx=5)

        # lignes IC
        for chip in range(NUM_CHIPS):
            ttk.Label(range_frame, text=f"IC{chip + 1}").grid(row=chip + 1, column=0, padx=5)

            for th in range(NUM_THRESHOLDS):
                min_var = tk.StringVar(value="255")
                max_var = tk.StringVar(value="0")

                self.dac_ranges[(chip, th)] = (min_var, max_var)

                cell = ttk.Frame(range_frame)
                cell.grid(row=chip + 1, column=th + 1, padx=5, pady=2)

                ttk.Entry(cell, textvariable=min_var, width=4).pack(side=tk.LEFT)
                ttk.Label(cell, text="→").pack(side=tk.LEFT)
                ttk.Entry(cell, textvariable=max_var, width=4).pack(side=tk.LEFT)

        self.zero_streak_var = tk.StringVar(value="2")
        ttk.Entry(scan, textvariable=self.zero_streak_var, width=10).grid(row=7, column=1, sticky="w")

        analysis_tabs_box = ttk.LabelFrame(scan, text="Analyses", padding=6)
        analysis_tabs_box.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.analysis_notebook = ttk.Notebook(analysis_tabs_box)
        self.analysis_notebook.pack(fill=tk.BOTH, expand=True)

        noise_tab = ttk.Frame(self.analysis_notebook, padding=6)
        signal_tab = ttk.Frame(self.analysis_notebook, padding=6)
        self.analysis_notebook.add(noise_tab, text="Analyse bruit")
        self.analysis_notebook.add(signal_tab, text="Analyse signal")

        ttk.Label(
            noise_tab,
            text="Scan gaussien automatique sur TH0..TH2\nEstimation µ/σ pour chaque IC et chaque TH.",
            justify=tk.LEFT,
        ).pack(anchor="w")

        ttk.Label(signal_tab, text="TH à scanner pour la sigmoïde").pack(anchor="w")
        th_sel_frame = ttk.Frame(signal_tab)
        th_sel_frame.pack(anchor="w", pady=(4, 0))
        self.signal_th_vars = []
        for th in range(NUM_THRESHOLDS):
            var = tk.BooleanVar(value=True)
            self.signal_th_vars.append(var)
            ttk.Checkbutton(th_sel_frame, text=f"TH{th}", variable=var).pack(side=tk.LEFT, padx=(0, 6))


        actions = ttk.LabelFrame(top, text="Actions", padding=8)
        actions.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Button(actions, text="Manual MUX", command=self.manual_mux).pack(fill=tk.X, pady=2)
        ttk.Button(actions, text="Start scan", command=self.start_scan).pack(fill=tk.X, pady=2)
        ttk.Button(actions, text="Stop scan", command=self.stop_scan).pack(fill=tk.X, pady=2)

        ttk.Separator(actions, orient="horizontal").pack(fill=tk.X, pady=6)
        ttk.Button(actions, text="Pause scan", command=self.pause_scan).pack(fill=tk.X, pady=2)
        ttk.Button(actions, text="Resume scan", command=self.resume_scan).pack(fill=tk.X, pady=2)
        ttk.Button(actions, text="Skip threshold", command=self.skip_threshold).pack(fill=tk.X, pady=2)

        ttk.Separator(actions, orient="horizontal").pack(fill=tk.X, pady=6)
        ttk.Button(actions, text="Previous IC", command=self.prev_curve).pack(fill=tk.X, pady=2)
        ttk.Button(actions, text="Next IC", command=self.next_curve).pack(fill=tk.X, pady=2)
        ttk.Button(actions, text="Valider et suivant", command=self.validate_and_next).pack(fill=tk.X, pady=2)
        ttk.Button(actions, text="Suivant sans sélectionner", command=self.skip_and_next).pack(fill=tk.X, pady=2)

        ttk.Separator(actions, orient="horizontal").pack(fill=tk.X, pady=6)

        export_box = ttk.LabelFrame(actions, text="Export CSV (IC)", padding=4)
        export_box.pack(fill=tk.X, pady=(0, 4))
        self.export_ic_vars = []
        for i in range(NUM_CHIPS):
            var = tk.BooleanVar(value=True)
            self.export_ic_vars.append(var)
            ttk.Checkbutton(export_box, text=f"IC{i + 1}", variable=var).pack(side=tk.LEFT, padx=2)

        ttk.Button(actions, text="Save validated CSV...", command=self.save_csv_dialog).pack(fill=tk.X, pady=2)

        help_box = ttk.LabelFrame(top, text="Manual validation", padding=8)
        help_box.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0))
        ttk.Label(help_box, text="Left click  = select µ").pack(anchor="w")
        ttk.Label(help_box, text="Right click = select µ - 3σ").pack(anchor="w")

        self.status_var = tk.StringVar(value="Disconnected")
        ttk.Label(self, textvariable=self.status_var, padding=(8, 4)).pack(side=tk.TOP, fill=tk.X)

        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, padding=8)
        right = ttk.Frame(main, padding=8)
        main.add(left, weight=3)
        main.add(right, weight=2)

        # NOTEBOOK PAR IC
        self.notebook = ttk.Notebook(left)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.axes = {}
        self.canvases = {}
        self.lines_by_chip_th = {}
        baseline = ttk.LabelFrame(top, text="Baseline VTH_BL", padding=8)
        baseline.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        self.vthbl_vars = []

        for chip in range(NUM_CHIPS):
            ttk.Label(baseline, text=f"IC{chip + 1}").grid(row=chip, column=0, sticky="w")

            var = tk.StringVar(value="120")
            self.vthbl_vars.append(var)

            ttk.Entry(baseline, textvariable=var, width=6).grid(row=chip, column=1)

            ttk.Button(
                baseline,
                text="Set",
                command=lambda c=chip: self.set_vthbl(c)
            ).grid(row=chip, column=2, padx=4)
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text=f"IC{chip + 1}")

            fig = Figure(figsize=(8, 5), dpi=100)
            ax = fig.add_subplot(111)
            ax.set_title(f"IC{chip + 1}")
            ax.set_xlabel("DAC")
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.set_ylabel("HIT/s")
            ax.grid(True)

            canvas = FigureCanvasTkAgg(fig, master=tab)
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

            self.bind_canvas_click(canvas, chip)

            self.axes[chip] = ax
            self.canvases[chip] = canvas

        table_frame = ttk.LabelFrame(right, text="Acquired points", padding=4)
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("chip", "th", "dac", "hits", "mu", "sigma", "r2")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=20)
        for c, w in [("chip", 60), ("th", 50), ("dac", 60), ("hits", 110), ("mu", 80), ("sigma", 80), ("r2", 70)]:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ysb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=ysb.set)

        log_frame = ttk.LabelFrame(self, text="Log", padding=4)
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH)

        self.log_text = tk.Text(log_frame, height=11, wrap="word")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.port_cb["values"] = ports
        self.multi_ports_listbox.delete(0, tk.END)
        for p in ports:
            self.multi_ports_listbox.insert(tk.END, p)
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def open_selected_ports_in_new_windows(self):
        sel = self.multi_ports_listbox.curselection()
        if not sel:
            messagebox.showinfo("Multi-ESP", "Sélectionne au moins un port.")
            return

        ports = [self.multi_ports_listbox.get(i) for i in sel]
        script = str(Path(__file__).resolve())
        for port in ports:
            try:
                subprocess.Popen([sys.executable, script, "--port", port])
                self._log(f"Opened new window for {port}")
            except Exception as e:
                self._log(f"Failed opening {port}: {e}")

    def toggle_connect(self):

        try:

            if self.fw.is_open():
                self.fw.close()
                self.connect_btn.configure(text="Connect")
                self.connected_esp_id = None
                self.connected_port = None
                self.scan_status = ""
                self._update_status_bar()
                self._log("Serial port closed")
                return

            port = self.port_var.get().strip()
            baud = int(self.baud_var.get().strip())

            self.fw.open(port, baudrate=baud, timeout=0.2)
            esp_id = self.fw.read_esp_id(timeout=2.0)
            self.connected_esp_id = esp_id
            self.connected_port = port
            self.scan_status = ""

            self.connect_btn.configure(text="Disconnect")
            self._update_status_bar()
            if esp_id is None:
                self._log(f"Connected to {port} @ {baud} | ESP_abeast_ID unknown")
            else:
                self._log(f"Connected to {port} @ {baud} | ESP_abeast_ID={esp_id}")

            # 👇 AJOUTER ICI
            self.after(600, self.load_vthbl_defaults)

        except Exception as e:
            messagebox.showerror("Connection error", str(e))

    def manual_mux(self):
        try:
            if not self.fw.is_open():
                raise RuntimeError("Serial not connected")
            val = self.mux_var.get().strip()
            reply = self.fw.set_mux(val)
            self._log(f"MUX {val} -> {reply}")
            self._set_scan_status(f"MUX {val} selected")
        except Exception as e:
            messagebox.showerror("MUX error", str(e))

    def start_scan(self):
        try:
            if not self.fw.is_open():
                raise RuntimeError("Serial not connected")

            dwell_s = float(self.dwell_var.get())
            settle_s = float(self.settle_var.get())
            do_zero_each_point = bool(self.zero_each_point_var.get())
            use_mux = bool(self.use_mux_var.get())
            mux_value = self.mux_var.get().strip()
            chips = [i for i, v in enumerate(self.ic_vars) if v.get()]
            selected_analysis_tab = self.analysis_notebook.tab(self.analysis_notebook.select(), "text")
            if selected_analysis_tab == "Analyse signal":
                analysis_mode = ANALYSIS_SIGMOID
                thresholds = [i for i, v in enumerate(self.signal_th_vars) if v.get()]
            else:
                analysis_mode = ANALYSIS_GAUSSIAN
                thresholds = list(range(NUM_THRESHOLDS))
            self.last_analysis_mode = analysis_mode

            if not chips:
                raise RuntimeError("Aucun IC sélectionné")
            if analysis_mode == ANALYSIS_SIGMOID and not thresholds:
                raise RuntimeError("Aucun TH sélectionné")

            stop_on_zero = self.stop_on_zero_var.get()

            max_zero = int(self.zero_streak_var.get())
            vthbl_values = {
                chip: int(self.vthbl_vars[chip].get())
                for chip in range(NUM_CHIPS)
            }
            # --- Récupération des plages DAC ---
            dac_ranges = {}

            for chip in range(NUM_CHIPS):
                for th in range(NUM_THRESHOLDS):
                    min_val = int(self.dac_ranges[(chip, th)][0].get())
                    max_val = int(self.dac_ranges[(chip, th)][1].get())

                    dac_ranges[(chip, th)] = (min_val, max_val)

            self.curves_by_key.clear()
            self.manual_selections.clear()
            self.review_mode = False

            for item in self.tree.get_children():
                self.tree.delete(item)

            for chip in range(NUM_CHIPS):
                self.refresh_chip_plot(chip)

            mode_label = "gaussienne" if analysis_mode == ANALYSIS_GAUSSIAN else "sigmoïde"
            self._log(f"Starting scan ({mode_label})...")

            outdir = filedialog.askdirectory(title="Optional output folder (Cancel = no autosave)")
            if not outdir:
                outdir = None
            self.output_dir_after_scan = outdir

            self.engine.start(
                dwell_s=dwell_s,
                settle_s=settle_s,
                do_zero_each_point=do_zero_each_point,
                use_mux=use_mux,
                mux_value=mux_value,
                analysis_mode=analysis_mode,
                thresholds=thresholds,
                output_dir=outdir,
                chips=chips,
                stop_on_zero=stop_on_zero,
                max_zero=max_zero,
                dac_ranges=dac_ranges,
                vthbl_values=vthbl_values,
            )
        except Exception as e:
            messagebox.showerror("Start error", str(e))

    def stop_scan(self):
        self.engine.stop()
        self._log("Stop requested")

    def save_csv_dialog(self):
        if not self.engine.last_results:
            messagebox.showinfo("No data", "No acquired points to save")
            return
        selected_chips = {i for i, v in enumerate(self.export_ic_vars) if v.get()}
        if not selected_chips:
            messagebox.showerror("Export error", "Sélectionne au moins un IC à exporter")
            return

        outdir = filedialog.askdirectory(title="Choose output folder")
        if not outdir:
            return

        self.engine.save_results(Path(outdir), self.manual_selections, selected_chips=selected_chips)
        chips_txt = ", ".join(f"IC{i + 1}" for i in sorted(selected_chips))
        self._log(f"Saved validated CSV files to {outdir} ({chips_txt})")

    def _threadsafe_log(self, msg: str):
        self.after(0, lambda: self._log(msg))

    def _threadsafe_status(self, msg: str):
        self.scan_status = msg
        self.after(0, self._update_status_bar)

    def _set_scan_status(self, msg: str):
        self.scan_status = msg
        self._update_status_bar()

    def _update_status_bar(self):
        if self.connected_port:
            if self.connected_esp_id is None:
                conn = f"{self.connected_port} | ESP_ID=?"
            else:
                conn = f"{self.connected_port} | ESP_ID={self.connected_esp_id}"
        else:
            conn = "Disconnected"

        if self.scan_status:
            self.status_var.set(f"{conn}  ||  {self.scan_status}")
        else:
            self.status_var.set(conn)

    def _threadsafe_point(self, point: ScanPoint):
        self.after(0, lambda p=point: self._consume_point(p))

    def _threadsafe_done(self):
        self.after(0, self.on_scan_done)

    def _log(self, msg: str):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)

    def _consume_point(self, p: ScanPoint):
        key = (p.chip, p.threshold)
        if key not in self.curves_by_key:
            self.curves_by_key[key] = []
        self.curves_by_key[key].append(p)

        self.tree.insert("", tk.END, values=(
            p.chip + 1,
            p.threshold,
            p.dac,
            f"{p.hits_per_s:.2f}",
            "" if p.mu_est is None else f"{p.mu_est:.2f}",
            "" if p.sigma_est is None else f"{p.sigma_est:.2f}",
            "" if p.r2_est is None else f"{p.r2_est:.3f}",
        ))

        self.refresh_chip_plot(p.chip)

    def on_scan_done(self):
        self.review_mode = True
        if self.last_analysis_mode == ANALYSIS_SIGMOID:
            self._set_scan_status("Scan completed - validate point d'inflexion manuellement (clic gauche)")
        else:
            self._set_scan_status("Scan completed - validate µ and µ-3σ manually")
        self._log("Review mode enabled")

        for chip in range(NUM_CHIPS):
            self.refresh_chip_plot(chip)

        if self.output_dir_after_scan:
            self._log("Auto-save folder selected earlier. Use 'Save validated CSV...' after manual validation.")



    def prev_curve(self):
        if self.notebook is None:
            return
        current = self.notebook.index(self.notebook.select())
        if current > 0:
            self.notebook.select(current - 1)

    def next_curve(self):
        if self.notebook is None:
            return
        current = self.notebook.index(self.notebook.select())
        if current < NUM_CHIPS - 1:
            self.notebook.select(current + 1)

    def validate_and_next(self):
        if self.notebook is None:
            return

        current = self.notebook.index(self.notebook.select())
        self._log(f"Validation OK for IC{current + 1}")

        if current < NUM_CHIPS - 1:
            self.notebook.select(current + 1)
        else:
            self._set_scan_status("Validation finished for all ICs")
            self._log("Validation finished for all ICs")

    def skip_and_next(self):
        if self.notebook is None:
            return

        current = self.notebook.index(self.notebook.select())
        self._log(f"Skipped validation advance for IC{current + 1}")

        if current < NUM_CHIPS - 1:
            self.notebook.select(current + 1)
        else:
            self._set_scan_status("Validation finished for all ICs")
            self._log("Validation finished for all ICs")

    def on_plot_click_chip(self, event, chip):
        print("CLICK DETECTED", chip, event.button, event.xdata, event.ydata)
        print("review_mode =", self.review_mode)



        if chip not in self.axes:
            return

        if event.inaxes != self.axes[chip] or event.xdata is None or event.ydata is None:
            return

        clicked_th = None
        best_line_dist = None

        # déterminer quelle courbe TH est la plus proche
        for th in range(NUM_THRESHOLDS):
            pts = self.curves_by_key.get((chip, th), [])
            if not pts:
                continue

            local_best = None
            for p in pts:
                dx = float(p.dac) - float(event.xdata)
                dy = float(p.hits_per_s) - float(event.ydata)
                d2 = dx * dx + dy * dy
                if local_best is None or d2 < local_best:
                    local_best = d2

            if local_best is not None and (best_line_dist is None or local_best < best_line_dist):
                best_line_dist = local_best
                clicked_th = th

        if clicked_th is None:
            return

        pts = self.curves_by_key.get((chip, clicked_th), [])
        if not pts:
            return

        # point avec DAC entier le plus proche
        target_dac = int(round(event.xdata))
        best_pt = min(pts, key=lambda p: abs(int(p.dac) - target_dac))
        selected_dac = int(best_pt.dac)

        key = (chip, clicked_th)
        if key not in self.manual_selections:
            self.manual_selections[key] = {"mu": None, "mu_minus_3sigma": None, "inflection": None}

        # bouton gauche / droit
        is_left = (event.button == 1) or (event.button == MouseButton.LEFT)
        is_right = (event.button == 3) or (event.button == MouseButton.RIGHT)

        if is_left:
            if self.last_analysis_mode == ANALYSIS_SIGMOID:
                self.manual_selections[key]["inflection"] = selected_dac
                self._log(f"Manual inflection selected -> IC{chip + 1} TH{clicked_th}: DAC={selected_dac}")
                self._set_scan_status(f"Inflection selected: IC{chip + 1} TH{clicked_th} DAC={selected_dac}")
            else:
                self.manual_selections[key]["mu"] = selected_dac
                self._log(f"Manual µ selected -> IC{chip + 1} TH{clicked_th}: DAC={selected_dac}")
                self._set_scan_status(f"µ selected: IC{chip + 1} TH{clicked_th} DAC={selected_dac}")
        elif is_right:
            self.manual_selections[key]["mu_minus_3sigma"] = selected_dac
            self._log(f"Manual µ-3σ selected -> IC{chip + 1} TH{clicked_th}: DAC={selected_dac}")
            self._set_scan_status(f"µ-3σ selected: IC{chip + 1} TH{clicked_th} DAC={selected_dac}")
        else:
            return

        self.refresh_chip_plot(chip)

    def refresh_chip_plot(self, chip: int):
        if chip not in self.axes:
            return

        ax = self.axes[chip]
        ax.clear()
        ax.grid(True)
        ax.set_xlabel("DAC")
        ax.set_ylabel("HIT/s")
        ax.set_title(f"IC{chip + 1}")

        labels = ["TH0", "TH1", "TH2"]
        markers = ["o", "s", "^"]

        all_x = []
        all_y = []

        for th in range(NUM_THRESHOLDS):
            pts = self.curves_by_key.get((chip, th), [])
            xs = [int(p.dac) for p in pts]
            ys = [p.hits_per_s for p in pts]

            if xs and ys:
                line, = ax.plot(xs, ys, marker=markers[th], linestyle="-", label=labels[th], picker=5)
                self.lines_by_chip_th[(chip, th)] = line
                all_x.extend(xs)
                all_y.extend(ys)
            else:
                self.lines_by_chip_th[(chip, th)] = None

            key = (chip, th)
            sel = self.manual_selections.get(key, {})
            mu_sel = sel.get("mu")
            mu3_sel = sel.get("mu_minus_3sigma")
            inflection_sel = sel.get("inflection")

            for p in pts:
                if mu_sel is not None and p.dac == mu_sel:
                    ax.plot([p.dac], [p.hits_per_s], marker="o", markersize=12, linestyle="None")
                    ax.annotate(f"µ TH{th}", (p.dac, p.hits_per_s), textcoords="offset points", xytext=(8, 8))

                if mu3_sel is not None and p.dac == mu3_sel:
                    ax.plot([p.dac], [p.hits_per_s], marker="s", markersize=11, linestyle="None")
                    ax.annotate(f"µ-3σ TH{th}", (p.dac, p.hits_per_s), textcoords="offset points", xytext=(8, -14))

                if inflection_sel is not None and p.dac == inflection_sel:
                    ax.plot([p.dac], [p.hits_per_s], marker="D", markersize=10, linestyle="None")
                    ax.annotate(f"Infl. TH{th}", (p.dac, p.hits_per_s), textcoords="offset points", xytext=(8, 16))

        if all_x and all_y:
            xmin = min(all_x)
            xmax = max(all_x)
            ymin = min(all_y)
            ymax = max(all_y)

            if xmin == xmax:
                xmin -= 1
                xmax += 1
            if ymin == ymax:
                ymin -= 1
                ymax += 1

            pad_y = max((ymax - ymin) * 0.1, 1.0)
            ax.set_xlim(xmax + 2, xmin - 2)
            ax.set_ylim(max(0.0, ymin - pad_y), ymax + pad_y)

        ax.legend()
        self.canvases[chip].draw_idle()

    def on_close(self):
        try:
            self.engine.stop()
            self.fw.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None, help="Auto-connect serial port at startup (for multi-ESP windows)")
    args = parser.parse_args()
    app = App(auto_port=args.port)
    app.mainloop()

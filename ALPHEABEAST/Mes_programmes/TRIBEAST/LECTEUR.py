import csv
import math
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


@dataclass
class CsvPoint:
    source: str
    chip: int
    threshold: int
    dac: int
    hits_per_s: float
    mode: str  # gaussian | sigmoid | unknown


class CsvOverlayViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CSV Overlay Viewer - Gaussiennes & Sigmoïdes")
        self.geometry("1400x900")

        self.points: list[CsvPoint] = []
        self.sources: list[str] = []
        self.hover_annotation = None
        self.plotted_artists = []

        self.chip_var = tk.IntVar(value=1)
        self.show_th_vars = [tk.BooleanVar(value=True) for _ in range(3)]
        self.save_ic_vars = [tk.BooleanVar(value=True) for _ in range(3)]
        self.show_sigmoid_fit_var = tk.BooleanVar(value=False)
        self.fit_ranges_by_th: dict[int, tuple[tk.StringVar, tk.StringVar]] = {
            th: (tk.StringVar(value="255"), tk.StringVar(value="0"))
            for th in range(3)
        }

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)

        ttk.Button(top, text="Charger CSV...", command=self.load_csv_files).pack(side=tk.LEFT, padx=4)
        ttk.Label(top, text="IC").pack(side=tk.LEFT, padx=(16, 4))
        chip_cb = ttk.Combobox(top, state="readonly", width=8, textvariable=self.chip_var, values=[1, 2, 3])
        chip_cb.pack(side=tk.LEFT)
        chip_cb.bind("<<ComboboxSelected>>", lambda _e: self.refresh_plot())

        th_frame = ttk.Frame(top)
        th_frame.pack(side=tk.LEFT, padx=(16, 0))
        for th in range(3):
            cb = ttk.Checkbutton(
                th_frame,
                text=f"TH{th}",
                variable=self.show_th_vars[th],
                command=self.refresh_plot,
            )
            cb.pack(side=tk.LEFT, padx=4)

        ttk.Button(top, text="Rafraîchir", command=self.refresh_plot).pack(side=tk.LEFT, padx=8)
        ttk.Button(top, text="Effacer", command=self.clear_data).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(
            top,
            text="Fitter sigmoïde + inflexion",
            variable=self.show_sigmoid_fit_var,
            command=self.refresh_plot,
        ).pack(side=tk.LEFT, padx=(12, 0))

        fit_range_box = ttk.LabelFrame(top, text="Plage fit (par TH)", padding=4)
        fit_range_box.pack(side=tk.LEFT, padx=(12, 0))
        for th in range(3):
            min_var, max_var = self.fit_ranges_by_th[th]
            row = ttk.Frame(fit_range_box)
            row.pack(side=tk.TOP, anchor="w")
            ttk.Label(row, text=f"TH{th}").pack(side=tk.LEFT, padx=(0, 3))
            ttk.Entry(row, textvariable=min_var, width=4).pack(side=tk.LEFT)
            ttk.Label(row, text="→").pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=max_var, width=4).pack(side=tk.LEFT)

        save_box = ttk.LabelFrame(top, text="Enregistrer données (IC)", padding=4)
        save_box.pack(side=tk.LEFT, padx=(16, 0))
        for chip in range(3):
            ttk.Checkbutton(
                save_box,
                text=f"IC{chip + 1}",
                variable=self.save_ic_vars[chip],
            ).pack(side=tk.LEFT, padx=2)
        ttk.Button(save_box, text="Exporter CSV filtré...", command=self.export_filtered_csv).pack(side=tk.LEFT, padx=8)

        self.status_var = tk.StringVar(value="Charge un ou plusieurs CSV noise_scan_raw.csv")
        ttk.Label(self, textvariable=self.status_var, padding=(8, 0)).pack(fill=tk.X)

        fig = Figure(figsize=(10, 7), dpi=100)
        self.ax = fig.add_subplot(111)
        self.ax.set_title("Superposition des courbes")
        self.ax.set_xlabel("DAC")
        self.ax.set_ylabel("Hits/s")
        self.ax.grid(True)

        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = FigureCanvasTkAgg(fig, master=canvas_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        toolbar = NavigationToolbar2Tk(self.canvas, canvas_frame)
        toolbar.update()

        self.info_var = tk.StringVar(value="Survole un point pour voir les valeurs (source, IC, TH, DAC, hits/s)")
        ttk.Label(self, textvariable=self.info_var, padding=8).pack(fill=tk.X)

        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_move)

    def clear_data(self):
        self.points.clear()
        self.sources.clear()
        self.refresh_plot()
        self.status_var.set("Données effacées")

    def load_csv_files(self):
        files = filedialog.askopenfilenames(
            title="Choisir un ou plusieurs CSV",
            filetypes=[("CSV", "*.csv"), ("Tous les fichiers", "*.*")],
        )
        if not files:
            return

        loaded = 0
        for f in files:
            try:
                new_points = self._read_csv(Path(f))
                if not new_points:
                    continue
                self.points.extend(new_points)
                self.sources.append(Path(f).name)
                loaded += 1
            except Exception as e:
                messagebox.showwarning("Lecture CSV", f"Impossible de lire {f}: {e}")

        self.refresh_plot()
        self.status_var.set(f"{loaded} fichier(s) chargé(s) | {len(self.points)} points")

    def export_filtered_csv(self):
        if not self.points:
            messagebox.showinfo("Export CSV", "Aucune donnée chargée.")
            return

        selected_ics = {i for i, v in enumerate(self.save_ic_vars) if v.get()}
        if not selected_ics:
            messagebox.showerror("Export CSV", "Sélectionne au moins un IC à exporter.")
            return

        selected_th = {i for i, v in enumerate(self.show_th_vars) if v.get()}
        if not selected_th:
            messagebox.showerror("Export CSV", "Sélectionne au moins un TH à exporter.")
            return

        out_path = filedialog.asksaveasfilename(
            title="Exporter un CSV filtré",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Tous les fichiers", "*.*")],
            initialfile="overlay_filtered.csv",
        )
        if not out_path:
            return

        filtered = [
            p for p in self.points
            if p.chip in selected_ics and p.threshold in selected_th
        ]

        if not filtered:
            messagebox.showinfo("Export CSV", "Aucune ligne à exporter avec ce filtre.")
            return

        with Path(out_path).open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["source", "analysis_mode", "chip", "threshold", "dac", "hits_per_s"])
            for p in filtered:
                writer.writerow([p.source, p.mode, p.chip + 1, p.threshold, p.dac, p.hits_per_s])

        self.status_var.set(f"CSV exporté: {out_path} ({len(filtered)} points)")

    @staticmethod
    def _to_int(row: dict, key: str, default: int = 0) -> int:
        v = row.get(key, "")
        try:
            return int(float(v))
        except Exception:
            return default

    @staticmethod
    def _to_float(row: dict, key: str, default: float = 0.0) -> float:
        v = row.get(key, "")
        try:
            return float(v)
        except Exception:
            return default

    def _infer_mode(self, csv_path: Path, row: dict) -> str:
        if "analysis_mode" in row and row.get("analysis_mode"):
            return str(row.get("analysis_mode")).strip().lower()

        name = csv_path.name.lower()
        if "sig" in name or "signal" in name:
            return "sigmoid"
        if "noise" in name or "gauss" in name:
            return "gaussian"
        return "unknown"

    def _read_csv(self, csv_path: Path) -> list[CsvPoint]:
        points: list[CsvPoint] = []
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            needed = {"chip", "threshold", "dac", "hits_per_s"}
            if not needed.issubset(set(reader.fieldnames or [])):
                raise ValueError(
                    "Colonnes attendues: chip, threshold, dac, hits_per_s (fichier noise_scan_raw.csv recommandé)"
                )

            for row in reader:
                chip_raw = self._to_int(row, "chip", 0)
                chip = chip_raw - 1 if chip_raw > 0 else chip_raw
                if chip not in (0, 1, 2):
                    continue

                th = self._to_int(row, "threshold", 0)
                if th not in (0, 1, 2):
                    continue

                points.append(
                    CsvPoint(
                        source=csv_path.stem,
                        chip=chip,
                        threshold=th,
                        dac=self._to_int(row, "dac", 0),
                        hits_per_s=self._to_float(row, "hits_per_s", 0.0),
                        mode=self._infer_mode(csv_path, row),
                    )
                )
        return points

    def refresh_plot(self):
        self.ax.clear()
        self.ax.grid(True)
        self.ax.set_xlabel("DAC")
        self.ax.set_ylabel("Hits/s")
        self.ax.set_title("Superposition des courbes")
        self.ax.set_xlim(255, 0)
        self.plotted_artists.clear()

        chip = self.chip_var.get() - 1
        selected_th = {i for i, v in enumerate(self.show_th_vars) if v.get()}

        filtered = [p for p in self.points if p.chip == chip and p.threshold in selected_th]
        if not filtered:
            self.canvas.draw_idle()
            return

        grouped: dict[tuple[str, int, str], list[CsvPoint]] = {}
        for p in filtered:
            key = (p.source, p.threshold, p.mode)
            grouped.setdefault(key, []).append(p)

        markers = {0: "o", 1: "s", 2: "^"}
        inflection_labels: list[str] = []
        for (source, th, mode), pts in sorted(grouped.items()):
            pts_sorted = sorted(pts, key=lambda x: x.dac)
            xs = [p.dac for p in pts_sorted]
            ys = [p.hits_per_s for p in pts_sorted]

            mode_tag = "G" if mode == "gaussian" else "S" if mode == "sigmoid" else "?"
            label = f"{source} | TH{th} | {mode_tag}"
            line = self.ax.plot(xs, ys, marker=markers.get(th, "o"), linewidth=1.3, label=label)[0]
            self.plotted_artists.append((line, pts_sorted))

            if self.show_sigmoid_fit_var.get() and mode == "sigmoid":
                fit_min, fit_max = self._fit_range_for_threshold(th)
                fit_pts = [p for p in pts_sorted if fit_min <= p.dac <= fit_max]
                fit_xs = [p.dac for p in fit_pts]
                fit_ys = [p.hits_per_s for p in fit_pts]
                fit = self._fit_sigmoid_curve(fit_xs, fit_ys)
                if fit is None:
                    continue
                fit_x, fit_y, x0, y0, r2 = fit
                fit_label = f"{source} | TH{th} | fit S (x0={x0:.1f})"
                self.ax.plot(fit_x, fit_y, linestyle="--", linewidth=1.2, color=line.get_color(), alpha=0.9, label=fit_label)
                self.ax.axvline(x=x0, color=line.get_color(), linestyle=":", linewidth=1.2, alpha=0.9)
                self.ax.plot([x0], [y0], marker="D", markersize=6, color=line.get_color())
                inflection_labels.append(f"{source} TH{th}: x0={x0:.1f} (R²={r2:.3f})")

        self.ax.legend(fontsize=8)
        if self.show_sigmoid_fit_var.get():
            if inflection_labels:
                self.status_var.set("Points d'inflexion: " + " | ".join(inflection_labels))
            else:
                self.status_var.set("Aucune courbe sigmoïde fittable avec la sélection courante.")
        self.canvas.draw_idle()

    @staticmethod
    def _fit_sigmoid_curve(xs: list[int], ys: list[float]) -> tuple[list[float], list[float], float, float, float] | None:
        if len(xs) < 5 or len(ys) < 5:
            return None

        pairs = sorted((float(x), float(y)) for x, y in zip(xs, ys))
        x = [p[0] for p in pairs]
        y = [p[1] for p in pairs]
        y_min = min(y)
        y_max = max(y)
        amp = y_max - y_min
        if amp <= 1e-9:
            return None

        x_left = x[0]
        x_right = x[-1]
        if abs(x_right - x_left) < 1e-9:
            return None

        # inflexion estimée par pente maximale sur la plage sélectionnée
        best_i = None
        best_slope = None
        for i in range(len(x) - 1):
            dx = x[i + 1] - x[i]
            if abs(dx) < 1e-12:
                continue
            slope = (y[i + 1] - y[i]) / dx
            if best_slope is None or abs(slope) > abs(best_slope):
                best_slope = slope
                best_i = i

        if best_i is None or best_slope is None:
            return None

        x0 = 0.5 * (x[best_i] + x[best_i + 1])
        slope0 = best_slope
        if abs(slope0) < 1e-12:
            return None

        # pour une logistique: pente max = amp / (4*scale)
        scale = max(abs(amp / (4.0 * slope0)), 0.5)

        x_fit = [x_left + i * (x_right - x_left) / 200.0 for i in range(201)]
        y_fit = [y_min + amp / (1.0 + math.exp(-(xx - x0) / scale)) for xx in x_fit]
        y_hat = [y_min + amp / (1.0 + math.exp(-(xx - x0) / scale)) for xx in x]

        y_mean = sum(y) / len(y)
        ss_res = sum((yy - yh) ** 2 for yy, yh in zip(y, y_hat))
        ss_tot = sum((yy - y_mean) ** 2 for yy in y)
        r2 = 0.0 if ss_tot <= 1e-12 else 1.0 - (ss_res / ss_tot)
        y0 = y_min + amp / 2.0
        return x_fit, y_fit, x0, y0, r2

    def _fit_range_for_threshold(self, threshold: int) -> tuple[int, int]:
        min_var, max_var = self.fit_ranges_by_th[threshold]
        try:
            a = int(min_var.get())
            b = int(max_var.get())
        except Exception:
            return 0, 255
        return (a, b) if a <= b else (b, a)

    def on_mouse_move(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return

        best = None
        best_d2 = None

        for _line, pts in self.plotted_artists:
            for p in pts:
                dx = p.dac - event.xdata
                dy = p.hits_per_s - event.ydata
                d2 = dx * dx + dy * dy
                if best_d2 is None or d2 < best_d2:
                    best_d2 = d2
                    best = p

        if best is None:
            return

        self.info_var.set(
            f"source={best.source} | mode={best.mode} | IC{best.chip + 1} | TH{best.threshold} | DAC={best.dac} | hits/s={best.hits_per_s:.3f}"
        )


if __name__ == "__main__":
    app = CsvOverlayViewer()
    app.mainloop()
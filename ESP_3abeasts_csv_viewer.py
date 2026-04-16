import csv
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import statistics

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
    sigma_est: float | None = None


@dataclass
class SigmaTargetResult:
    chip: int
    threshold: int
    mu_dac: int
    target_hits: float
    target_dac: int
    target_hits_found: float
    n_sigma: float | None
    sigma_ref: float | None


class CsvOverlayViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CSV Overlay Viewer - Gaussiennes & Sigmoïdes")
        self.geometry("1400x900")

        self.points: list[CsvPoint] = []
        self.sources: list[str] = []
        self.hover_annotation = None
        self.plotted_artists = []
        self.manual_mu_by_chip_th: dict[tuple[int, int], int] = {}
        self.sigma_targets_by_chip_th: dict[tuple[int, int], SigmaTargetResult] = {}

        self.chip_var = tk.IntVar(value=1)
        self.show_th_vars = [tk.BooleanVar(value=True) for _ in range(3)]
        self.save_ic_vars = [tk.BooleanVar(value=True) for _ in range(3)]
        self.pick_mu_mode = tk.BooleanVar(value=False)
        self.target_hits_var = tk.DoubleVar(value=1000.0)

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

        pick_box = ttk.LabelFrame(top, text="Sélection µ / sigma", padding=4)
        pick_box.pack(side=tk.LEFT, padx=(16, 0))
        ttk.Checkbutton(
            pick_box,
            text="Cliquer pour définir µ",
            variable=self.pick_mu_mode,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(pick_box, text="Hits/s cible").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(pick_box, textvariable=self.target_hits_var, width=10).pack(side=tk.LEFT)
        ttk.Button(pick_box, text="Calculer µ-xσ", command=self.compute_sigma_targets).pack(side=tk.LEFT, padx=6)
        ttk.Button(pick_box, text="Reset µ", command=self.clear_manual_mu).pack(side=tk.LEFT, padx=4)

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

        self.info_var = tk.StringVar(
            value="Survole un point pour voir les valeurs (source, IC, TH, DAC, hits/s). "
                  "Active 'Cliquer pour définir µ' puis clique un point pour fixer µ."
        )
        ttk.Label(self, textvariable=self.info_var, padding=8).pack(fill=tk.X)

        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_move)
        self.canvas.mpl_connect("button_press_event", self.on_mouse_click)

    def clear_data(self):
        self.points.clear()
        self.sources.clear()
        self.manual_mu_by_chip_th.clear()
        self.sigma_targets_by_chip_th.clear()
        self.refresh_plot()
        self.status_var.set("Données effacées")

    def clear_manual_mu(self):
        self.manual_mu_by_chip_th.clear()
        self.sigma_targets_by_chip_th.clear()
        self.refresh_plot()
        self.status_var.set("Sélections µ supprimées")

    def load_csv_files(self):
        files = filedialog.askopenfilenames(
            title="Choisir un ou plusieurs fichiers de données",
            filetypes=[
                ("Données", "*.csv *.xlsx"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx"),
                ("Tous les fichiers", "*.*"),
            ],
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
            writer.writerow([
                "source",
                "analysis_mode",
                "chip",
                "threshold",
                "dac",
                "hits_per_s",
                "mu_user_dac",
                "target_hits_requested",
                "target_dac_for_hits",
                "target_hits_found",
                "n_sigma_from_mu",
                "sigma_ref",
            ])
            for p in filtered:
                key = (p.chip, p.threshold)
                mu_user = self.manual_mu_by_chip_th.get(key)
                tgt = self.sigma_targets_by_chip_th.get(key)
                writer.writerow([
                    p.source,
                    p.mode,
                    p.chip + 1,
                    p.threshold,
                    p.dac,
                    p.hits_per_s,
                    mu_user,
                    tgt.target_hits if tgt else None,
                    tgt.target_dac if tgt else None,
                    tgt.target_hits_found if tgt else None,
                    tgt.n_sigma if tgt else None,
                    tgt.sigma_ref if tgt else None,
                ])

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

    @staticmethod
    def _normalize_key(value: str) -> str:
        return "".join(ch for ch in str(value).strip().lower() if ch.isalnum())

    def _pick_key(self, row: dict, *aliases: str) -> str | None:
        if not row:
            return None
        normalized = {self._normalize_key(k): k for k in row.keys()}
        for alias in aliases:
            if alias in normalized:
                return normalized[alias]
        return None

    def _rows_from_xlsx(self, xlsx_path: Path) -> list[dict]:
        rows: list[dict] = []
        with ZipFile(xlsx_path) as zf:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in ss_root.findall(".//{*}si"):
                    txt = "".join(node.text or "" for node in si.findall(".//{*}t"))
                    shared_strings.append(txt)

            wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
            sheet_nodes = wb_root.findall(".//{*}sheet")
            if not sheet_nodes:
                return rows
            first_sheet_rid = sheet_nodes[0].attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            if not first_sheet_rid:
                return rows

            rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            target = None
            for rel in rels_root.findall(".//{*}Relationship"):
                if rel.attrib.get("Id") == first_sheet_rid:
                    target = rel.attrib.get("Target")
                    break
            if not target:
                return rows

            if target.startswith("/"):
                sheet_path = target.lstrip("/")
            else:
                sheet_path = f"xl/{target}" if not target.startswith("xl/") else target

            sheet_root = ET.fromstring(zf.read(sheet_path))

            header: list[str] = []
            for row in sheet_root.findall(".//{*}sheetData/{*}row"):
                values: list[str] = []
                for c in row.findall("{*}c"):
                    v = c.find("{*}v")
                    if v is None:
                        values.append("")
                        continue
                    raw = v.text or ""
                    if c.attrib.get("t") == "s":
                        try:
                            values.append(shared_strings[int(raw)])
                        except Exception:
                            values.append(raw)
                    else:
                        values.append(raw)

                if not header:
                    header = [str(h).strip() for h in values]
                    continue
                if not any(str(x).strip() for x in values):
                    continue
                padded = values + [""] * max(0, len(header) - len(values))
                rows.append(dict(zip(header, padded)))
        return rows

    def _read_csv(self, csv_path: Path) -> list[CsvPoint]:
        points: list[CsvPoint] = []
        suffix = csv_path.suffix.lower()
        if suffix == ".xlsx":
            rows = self._rows_from_xlsx(csv_path)
        else:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                sample = f.read(4096)
                f.seek(0)
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter if sample else ","
                reader = csv.DictReader(f, delimiter=delimiter)
                rows = list(reader)

        if not rows:
            return points

        key_chip = self._pick_key(rows[0], "chip", "ic")
        key_th = self._pick_key(rows[0], "threshold", "th")
        key_dac = self._pick_key(rows[0], "dac", "bestdac")
        key_hits = self._pick_key(rows[0], "hitspers", "hitss", "hits_per_s", "maxhitspers")
        key_sigma = self._pick_key(rows[0], "sigmaest", "sigma_auto", "sigmaauto")

        if not all([key_chip, key_th, key_dac, key_hits]):
            raise ValueError("Colonnes attendues (ou alias): chip/ic, threshold/th, dac/best_dac, hits_per_s/max_hits_per_s")

        for row in rows:
            chip_raw = self._to_int(row, key_chip, 0)
            chip = chip_raw - 1 if chip_raw > 0 else chip_raw
            if chip not in (0, 1, 2):
                continue

            th = self._to_int(row, key_th, 0)
            if th not in (0, 1, 2):
                continue

            points.append(
                CsvPoint(
                    source=csv_path.stem,
                    chip=chip,
                    threshold=th,
                    dac=self._to_int(row, key_dac, 0),
                    hits_per_s=self._to_float(row, key_hits, 0.0),
                    mode=self._infer_mode(csv_path, row),
                    sigma_est=self._to_float(row, key_sigma, 0.0) if key_sigma else None,
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
        for (source, th, mode), pts in sorted(grouped.items()):
            pts_sorted = sorted(pts, key=lambda x: x.dac)
            xs = [p.dac for p in pts_sorted]
            ys = [p.hits_per_s for p in pts_sorted]

            mode_tag = "G" if mode == "gaussian" else "S" if mode == "sigmoid" else "?"
            label = f"{source} | TH{th} | {mode_tag}"
            line = self.ax.plot(xs, ys, marker=markers.get(th, "o"), linewidth=1.3, label=label)[0]
            self.plotted_artists.append((line, pts_sorted))

            mu_key = (chip, th)
            if mu_key in self.manual_mu_by_chip_th:
                mu_dac = self.manual_mu_by_chip_th[mu_key]
                self.ax.axvline(mu_dac, linestyle="--", linewidth=1.0, color=line.get_color(), alpha=0.8)

            target = self.sigma_targets_by_chip_th.get((chip, th))
            if target is not None:
                self.ax.scatter(
                    [target.target_dac],
                    [target.target_hits_found],
                    marker="X",
                    s=80,
                    color=line.get_color(),
                    edgecolors="black",
                    linewidths=0.5,
                    zorder=4,
                )
                txt = f"TH{th} → DAC {target.target_dac}"
                self.ax.annotate(
                    txt,
                    (target.target_dac, target.target_hits_found),
                    textcoords="offset points",
                    xytext=(6, 6),
                    fontsize=8,
                    color=line.get_color(),
                )

        self.ax.legend(fontsize=8)
        self.canvas.draw_idle()

    def _nearest_point(self, x: float, y: float) -> CsvPoint | None:
        best = None
        best_d2 = None
        for _line, pts in self.plotted_artists:
            for p in pts:
                dx = p.dac - x
                dy = p.hits_per_s - y
                d2 = dx * dx + dy * dy
                if best_d2 is None or d2 < best_d2:
                    best_d2 = d2
                    best = p
        return best

    def on_mouse_click(self, event):
        if not self.pick_mu_mode.get():
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        best = self._nearest_point(event.xdata, event.ydata)
        if best is None:
            return

        self.manual_mu_by_chip_th[(best.chip, best.threshold)] = best.dac
        self.sigma_targets_by_chip_th.pop((best.chip, best.threshold), None)
        self.status_var.set(f"µ manuel défini: IC{best.chip + 1} TH{best.threshold} -> DAC={best.dac}")
        self.refresh_plot()

    def compute_sigma_targets(self):
        if not self.points:
            messagebox.showinfo("µ-xσ", "Aucune donnée chargée.")
            return
        try:
            target_hits = float(self.target_hits_var.get())
        except Exception:
            messagebox.showerror("µ-xσ", "Valeur hits/s cible invalide.")
            return

        if not self.manual_mu_by_chip_th:
            messagebox.showinfo("µ-xσ", "Définis au moins un µ manuel (clic sur un point).")
            return

        lines: list[str] = []
        self.sigma_targets_by_chip_th.clear()
        for (chip, th), mu_dac in sorted(self.manual_mu_by_chip_th.items()):
            pts = [p for p in self.points if p.chip == chip and p.threshold == th]
            if not pts:
                continue
            pts_sorted = sorted(pts, key=lambda p: abs(p.dac - mu_dac))
            under = [p for p in pts_sorted if p.hits_per_s <= target_hits]
            target_point = under[0] if under else min(pts, key=lambda p: p.hits_per_s)

            sigma_vals = [p.sigma_est for p in pts if p.sigma_est is not None and p.sigma_est > 0]
            sigma_ref = statistics.median(sigma_vals) if sigma_vals else None

            if sigma_ref and sigma_ref > 0:
                n_sigma = (mu_dac - target_point.dac) / sigma_ref
                self.sigma_targets_by_chip_th[(chip, th)] = SigmaTargetResult(
                    chip=chip,
                    threshold=th,
                    mu_dac=mu_dac,
                    target_hits=target_hits,
                    target_dac=target_point.dac,
                    target_hits_found=target_point.hits_per_s,
                    n_sigma=n_sigma,
                    sigma_ref=sigma_ref,
                )
                lines.append(
                    f"IC{chip + 1} TH{th}: µ={mu_dac}, cible≤{target_hits:.3f} hits/s à DAC={target_point.dac} "
                    f"(~µ-{n_sigma:.2f}σ, σ≈{sigma_ref:.2f})"
                )
            else:
                delta = mu_dac - target_point.dac
                self.sigma_targets_by_chip_th[(chip, th)] = SigmaTargetResult(
                    chip=chip,
                    threshold=th,
                    mu_dac=mu_dac,
                    target_hits=target_hits,
                    target_dac=target_point.dac,
                    target_hits_found=target_point.hits_per_s,
                    n_sigma=None,
                    sigma_ref=None,
                )
                lines.append(
                    f"IC{chip + 1} TH{th}: µ={mu_dac}, cible≤{target_hits:.3f} hits/s à DAC={target_point.dac} "
                    f"(écart µ-DAC={delta}, sigma non disponible)"
                )

        if not lines:
            messagebox.showinfo("µ-xσ", "Aucun résultat exploitable.")
            return

        msg = "\n".join(lines)
        self.info_var.set(lines[0])
        self.refresh_plot()
        messagebox.showinfo("Estimation µ-xσ", msg)

    def on_mouse_move(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return

        best = self._nearest_point(event.xdata, event.ydata)

        if best is None:
            return

        self.info_var.set(
            f"source={best.source} | mode={best.mode} | IC{best.chip + 1} | TH{best.threshold} | DAC={best.dac} | hits/s={best.hits_per_s:.3f}"
        )


if __name__ == "__main__":
    app = CsvOverlayViewer()
    app.mainloop()

# -*- coding: utf-8 -*-
"""
Analyse automatique des fichiers binaires de scan gaussien.

Workflow:
1) Lit tous les fichiers .bin d'un dossier.
2) Extrait l'airgap depuis le nom de fichier (par défaut: airgap = 130 - position_mm).
3) Extrait les minima par événement du channel 0.
4) Affiche un histogramme interactif pour fitter une gaussienne (sélection à la souris + bouton).
5) Récupère mu pour chaque airgap.
6) Trace mu(ADC) en fonction de l'airgap.
7) Trace la calibration énergie=f(ADC) si des points énergie sont disponibles.
"""

from __future__ import annotations
import csv
import argparse
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, RectangleSelector
from scipy.optimize import curve_fit

from wavecatcher_binary_file_read import load_and_process_single_file_with_minimums


# Table énergie issue de newreadscanv3.py (airgap_mm -> (energie, sigma_energie))
DEFAULT_ENERGY_DATA: Dict[float, tuple[float, float]] = {
    30.00: (2127167.82, 56023.28),
    30.50: (2049825.53, 53582.21),
    31.00: (1966669.19, 55633.82),
    31.50: (1881606.38, 56316.23),
    32.00: (1800364.82, 60969.95),
    32.50: (1711380.90, 65444.31),
    33.00: (1619899.16, 65845.74),
    33.50: (1528505.82, 64028.56),
    34.00: (1431287.73, 64278.85),
    34.50: (1335583.72, 75839.93),
    35.00: (1229292.28, 69149.41),
    35.50: (1128426.74, 79124.49),
    36.00: (1016027.68, 77020.53),
    36.50: (904778.31, 79221.41),
    37.00: (791146.97, 79910.69),
    37.50: (676008.60, 80042.46),
    38.00: (557209.27, 80381.41),
    38.50: (441598.08, 74268.22),
    39.00: (336842.21, 66520.31),
    39.50: (240852.68, 61303.87),
    40.00: (165470.33, 51834.72),
}


@dataclass
class FitResult:
    filename: str
    airgap_mm: float
    mu_adc: float
    sigma_adc: float
    amplitude: float


class InteractiveSingleGaussFit:
    def __init__(self, x: np.ndarray, y: np.ndarray, title: str):
        self.x = x
        self.y = y
        self.title = title
        self.xmin = float(np.min(x)) if len(x) else 0.0
        self.xmax = float(np.max(x)) if len(x) else 1.0
        self.fit_params: Optional[np.ndarray] = None

        self.fig, self.ax = plt.subplots(figsize=(10, 5))
        self.ax.plot(self.x, self.y, drawstyle="steps-mid", label="Histogramme")
        self.ax.set_title(title)
        self.ax.set_xlabel("ADC min (channel 0)")
        self.ax.set_ylabel("Comptes")
        self.ax.grid(True, alpha=0.3)

        self.selector = RectangleSelector(
            self.ax,
            self.on_select,
            useblit=True,
            button=[1],
            minspanx=5,
            minspany=5,
            spancoords="pixels",
            interactive=True,
            props=dict(facecolor="tab:red", edgecolor="black", alpha=0.2, fill=True),
        )

        fit_ax = self.fig.add_axes([0.75, 0.01, 0.1, 0.06])
        skip_ax = self.fig.add_axes([0.63, 0.01, 0.1, 0.06])
        self.fit_button = Button(fit_ax, "Fit")
        self.skip_button = Button(skip_ax, "Skip")
        self.fit_button.on_clicked(self.on_fit)
        self.skip_button.on_clicked(self.on_skip)
        self.ax.legend()

    @staticmethod
    def gaussian(x, amp, mu, sigma):
        return amp * np.exp(-((x - mu) ** 2) / (2 * sigma**2))

    def on_select(self, eclick, erelease):
        if eclick.xdata is None or erelease.xdata is None:
            return
        self.xmin = min(eclick.xdata, erelease.xdata)
        self.xmax = max(eclick.xdata, erelease.xdata)
        mask = (self.x >= self.xmin) & (self.x <= self.xmax)
        print(f"Sélection: {np.count_nonzero(mask)} points")

    def on_fit(self, _event):
        mask = (self.x >= self.xmin) & (self.x <= self.xmax)
        if np.count_nonzero(mask) < 3:
            print("Sélection insuffisante, fit sur toutes les données.")
            mask = np.ones_like(self.x, dtype=bool)

        x_fit = self.x[mask]
        y_fit = self.y[mask]
        if len(x_fit) < 3:
            print("Pas assez de points pour fitter.")
            return

        amp0 = float(np.max(y_fit))
        mu0 = float(x_fit[np.argmax(y_fit)])
        sigma0 = max(float(np.std(x_fit)), 1.0)

        try:
            popt, _ = curve_fit(self.gaussian, x_fit, y_fit, p0=[amp0, mu0, sigma0], maxfev=20000)
            self.fit_params = popt
            y_model = self.gaussian(self.x, *popt)
            self.ax.plot(self.x, y_model, "--", lw=2,
                         label=f"Fit μ={popt[1]:.2f}, σ={popt[2]:.2f}, A={popt[0]:.1f}")
            self.ax.legend()
            self.fig.canvas.draw_idle()
            print(f"Fit OK: mu={popt[1]:.3f}, sigma={popt[2]:.3f}")
        except Exception as exc:
            print(f"Fit impossible: {exc}")

    def on_skip(self, _event):
        plt.close(self.fig)

    def show_and_get(self) -> Optional[np.ndarray]:
        plt.show(block=True)
        return self.fit_params


def extract_position_mm(filename: str) -> Optional[float]:
    match = re.search(r"at(\d+(?:\.\d+)?)mm", filename, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    fallback = re.search(r"(\d+(?:\.\d+)?)mm", filename, flags=re.IGNORECASE)
    if fallback:
        return float(fallback.group(1))
    return None


def collect_bin_files(data_dir: str) -> List[str]:
    return sorted([f for f in os.listdir(data_dir) if f.lower().endswith(".bin")])


def fit_min_distribution_for_file(data_dir: str, filename: str, bins: int, ref_mm: float) -> Optional[FitResult]:
    pos_mm = extract_position_mm(filename)
    if pos_mm is None:
        print(f"[SKIP] Position introuvable dans: {filename}")
        return None

    airgap_mm = ref_mm - pos_mm
    print(f"\n=== {filename} | position={pos_mm:.2f} mm | airgap={airgap_mm:.2f} mm ===")

    _, num_channels, event_mins, used_offset, _ = load_and_process_single_file_with_minimums(filename, data_dir)
    print(f"Offset retenu: {used_offset}, canaux: {num_channels}")

    if num_channels < 1 or not event_mins or not event_mins[0]:
        print("[SKIP] Pas de minima channel 0 exploitables.")
        return None

    values = np.asarray(event_mins[0], dtype=float)
    counts, edges = np.histogram(values, bins=bins)
    x = 0.5 * (edges[:-1] + edges[1:])

    fit_ui = InteractiveSingleGaussFit(
        x=x,
        y=counts,
        title=f"{filename} | airgap={airgap_mm:.2f} mm | Channel 0 minima",
    )
    fit_params = fit_ui.show_and_get()
    if fit_params is None:
        print("[SKIP] Fit non validé (fenêtre fermée ou skip).")
        return None

    return FitResult(
        filename=filename,
        airgap_mm=airgap_mm,
        mu_adc=abs(float(fit_params[1])),
        sigma_adc=abs(float(fit_params[2])),
        amplitude=float(fit_params[0]),
    )


def _format_energy_tick_label(airgap_value: float, energy_data: Dict[float, tuple[float, float]]) -> str:
    if airgap_value in energy_data:
        energy_ev, sigma_ev = energy_data[airgap_value]
        energy_mev = energy_ev / 1_000_000.0
        sigma_mev = sigma_ev / 1_000_000.0
        return f"{energy_mev:.3f}±{sigma_mev:.3f}"
    return ""


def plot_mu_vs_airgap(results: List[FitResult], energy_data: Dict[float, tuple[float, float]]):
    if not results:
        print("Aucun résultat de fit à tracer.")
        return

    # Tri décroissant pour afficher l'axe airgap de 40 vers 30 mm
    results_sorted = sorted(results, key=lambda r: r.airgap_mm, reverse=True)
    airgaps = np.array([r.airgap_mm for r in results_sorted])
    mus = np.array([abs(r.mu_adc) for r in results_sorted])
    sigma_adcs = np.array([abs(r.sigma_adc) for r in results_sorted])

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.errorbar(
        airgaps,
        mus,
        yerr=sigma_adcs,
        fmt="o-",
        lw=1.8,
        capsize=3,
        label="μ ± σ_ADC",
    )
    ax.set_xlabel("Airgap (mm)")
    ax.set_ylabel("μ du fit gaussien (ADC)")
    ax.set_title("μ(ADC) en fonction de l'airgap")
    ax.grid(True, alpha=0.35)
    ax.set_xlim(40, 30)

    # Axe secondaire au-dessus: énergie correspondante en MeV pour chaque airgap
    top_ax = ax.twiny()
    top_ax.set_xlim(ax.get_xlim())
    top_ax.set_xlabel("Énergie correspondante (MeV) [valeur±σ_E]")
    top_ax.set_xticks(airgaps)
    top_ax.set_xticklabels([_format_energy_tick_label(a, energy_data) for a in airgaps], rotation=45, ha="left")

    # Message utile si aucun mapping airgap->énergie n'est trouvé
    has_energy_labels = any(a in energy_data for a in airgaps)
    if not has_energy_labels:
        print("Aucune énergie de référence trouvée pour les airgaps affichés (axe du haut vide).")

    ax.legend(loc="best")
    fig.tight_layout()
    plt.show(block=True)


def plot_energy_vs_adc(results: List[FitResult], energy_data: Dict[float, tuple[float, float]]):
    if not results:
        print("Aucun résultat de fit pour la calibration énergie.")
        return

    adc_vals = []
    adc_sigma_vals = []
    ene_vals = []
    ene_err = []

    for res in results:
        if res.airgap_mm in energy_data:
            energy, sigma_e = energy_data[res.airgap_mm]
            adc_vals.append(abs(res.mu_adc))
            adc_sigma_vals.append(abs(res.sigma_adc))
            ene_vals.append(energy)
            ene_err.append(sigma_e)

    if len(adc_vals) < 2:
        print("Pas assez de points airgap<->énergie communs pour tracer la calibration.")
        return

    adc_vals = np.asarray(adc_vals)
    adc_sigma_vals = np.asarray(adc_sigma_vals)
    ene_vals = np.asarray(ene_vals)
    ene_err = np.asarray(ene_err)

    # Ajustement linéaire énergie = a*ADC + b
    coeff = np.polyfit(adc_vals, ene_vals, deg=1)
    poly = np.poly1d(coeff)
    adc_line = np.linspace(np.min(adc_vals), np.max(adc_vals), 200)

    plt.figure(figsize=(8, 5))
    plt.errorbar(
        adc_vals,
        ene_vals,
        xerr=adc_sigma_vals,
        yerr=ene_err,
        fmt="o",
        capsize=3,
        label="Points (barres d'erreur: σ_ADC et σ_E)",
    )
    plt.plot(adc_line, poly(adc_line), "--", label=f"Fit linéaire: E={coeff[0]:.3f}*ADC+{coeff[1]:.3f}")
    plt.xlabel("ADC (μ du fit gaussien)")
    plt.ylabel("Énergie")
    plt.title("Calibration énergie en fonction de l'ADC")
    plt.text(
        0.02,
        0.02,
        f"⟨σ_ADC⟩ = {np.mean(adc_sigma_vals):.2f}\\n⟨σ_E⟩ = {np.mean(ene_err):.1f} eV",
        transform=plt.gca().transAxes,
        fontsize=9,
        bbox=dict(facecolor="white", alpha=0.75, edgecolor="gray"),
    )
    plt.grid(True, alpha=0.35)
    plt.legend()
    plt.tight_layout()
    plt.show(block=True)
def save_energy_vs_adc_csv(
    results: List[FitResult],
    energy_data: Dict[float, tuple[float, float]],
    output_dir: str,
    n_curve_points: int = 500,
):
    """
    Sauvegarde :
    1) Les points expérimentaux énergie vs ADC
    2) La courbe de calibration linéaire E = a*ADC + b
    """

    adc_vals = []
    adc_sigma_vals = []
    ene_vals = []
    ene_err = []
    airgaps = []
    filenames = []

    for res in results:
        if res.airgap_mm in energy_data:
            energy_ev, sigma_e_ev = energy_data[res.airgap_mm]

            airgaps.append(res.airgap_mm)
            adc_vals.append(abs(res.mu_adc))
            adc_sigma_vals.append(abs(res.sigma_adc))
            ene_vals.append(energy_ev)
            ene_err.append(sigma_e_ev)
            filenames.append(res.filename)

    if len(adc_vals) < 2:
        print("Pas assez de points pour sauvegarder une calibration énergie vs ADC.")
        return

    adc_vals = np.asarray(adc_vals)
    adc_sigma_vals = np.asarray(adc_sigma_vals)
    ene_vals = np.asarray(ene_vals)
    ene_err = np.asarray(ene_err)

    # Fit linéaire : E = a*ADC + b
    coeff = np.polyfit(adc_vals, ene_vals, deg=1)
    a, b = coeff

    points_csv = os.path.join(output_dir, "calibration_points_energy_vs_adc.csv")
    curve_csv = os.path.join(output_dir, "calibration_curve_energy_vs_adc.csv")

    # CSV des points réels
    with open(points_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "filename",
            "airgap_mm",
            "adc_mu",
            "adc_sigma",
            "energy_eV",
            "sigma_energy_eV",
            "energy_MeV",
            "sigma_energy_MeV",
        ])

        for fname, airgap, adc, adc_sigma, ene, ene_sigma in zip(
            filenames, airgaps, adc_vals, adc_sigma_vals, ene_vals, ene_err
        ):
            writer.writerow([
                fname,
                f"{airgap:.3f}",
                f"{adc:.6f}",
                f"{adc_sigma:.6f}",
                f"{ene:.6f}",
                f"{ene_sigma:.6f}",
                f"{ene / 1_000_000:.9f}",
                f"{ene_sigma / 1_000_000:.9f}",
            ])

    # CSV de la courbe de calibration interpolée
    adc_curve = np.linspace(np.min(adc_vals), np.max(adc_vals), n_curve_points)
    energy_curve = a * adc_curve + b

    with open(curve_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "adc",
            "energy_eV",
            "energy_MeV",
            "fit_a_eV_per_ADC",
            "fit_b_eV",
        ])

        for adc, ene in zip(adc_curve, energy_curve):
            writer.writerow([
                f"{adc:.6f}",
                f"{ene:.6f}",
                f"{ene / 1_000_000:.9f}",
                f"{a:.12f}",
                f"{b:.6f}",
            ])

    print("\n=== CSV calibration sauvegardés ===")
    print(f"Points expérimentaux : {points_csv}")
    print(f"Courbe de calibration : {curve_csv}")
    print(f"Fit linéaire : E = {a:.6f} * ADC + {b:.6f} eV")

def main():
    parser = argparse.ArgumentParser(description="Analyse multi-fichiers .bin et calibration airgap/ADC/énergie")
    parser.add_argument(
        "--data-dir",
        default=r"C:\Users\higueret_adm\PycharmProjects\MANIP\monoabeast1_gauss",
        help="Dossier contenant les fichiers .bin",
    )
    parser.add_argument("--bins", type=int, default=200, help="Nombre de bins histogramme")
    parser.add_argument("--reference-mm", type=float, default=127.3,
                        help="Référence pour l'airgap: airgap = reference_mm - position_mm")
    # parser.add_argument("--reference-mm", type=float, default=127.5,
    #                     help="Référence pour l'airgap: airgap = reference_mm - position_mm")
    args = parser.parse_args()

    if not os.path.isdir(args.data_dir):
        raise FileNotFoundError(f"Dossier introuvable: {args.data_dir}")

    files = collect_bin_files(args.data_dir)
    if not files:
        raise FileNotFoundError(f"Aucun fichier .bin dans {args.data_dir}")

    print(f"{len(files)} fichier(s) détecté(s).")

    results: List[FitResult] = []
    for fname in files:
        fit_result = fit_min_distribution_for_file(
            data_dir=args.data_dir,
            filename=fname,
            bins=args.bins,
            ref_mm=args.reference_mm,
        )
        if fit_result is not None:
            results.append(fit_result)

    if not results:
        print("Aucun fit validé. Fin du programme.")
        return

    print("\n=== Résultats validés ===")
    for r in sorted(results, key=lambda it: it.airgap_mm):
        print(f"airgap={r.airgap_mm:.2f} mm | mu={r.mu_adc:.3f} ADC | sigma={r.sigma_adc:.3f} | {r.filename}")

    plot_mu_vs_airgap(results, DEFAULT_ENERGY_DATA)
    plot_energy_vs_adc(results, DEFAULT_ENERGY_DATA)

    save_energy_vs_adc_csv(
        results=results,
        energy_data=DEFAULT_ENERGY_DATA,
        output_dir=args.data_dir,
    )


if __name__ == "__main__":
    main()
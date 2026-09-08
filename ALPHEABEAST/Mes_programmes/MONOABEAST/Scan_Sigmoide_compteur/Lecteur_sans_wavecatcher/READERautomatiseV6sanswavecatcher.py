# -*- coding: utf-8 -*-
"""
Analyse des scans AlphaBeast sans WaveCatcher

Objectif :
1) Lire le CSV produit par le programme de scan compteur.
2) Regrouper les données par position moteur.
3) Pour chaque position :
   - tracer C0_Rate en fonction du Threshold_DAC ;
   - choisir une plage DAC à afficher ;
   - faire ou non un fit sigmoïde sur cette plage ;
   - sauvegarder les figures et les résultats de fit.

CSV attendu :
Position_mm, Delta_mm, Threshold_DAC, Temps_integration_demande_s,
Temps_mesure_reel_s, C0_initial, C0_final, C0_Hits, C0_Rate, Status
"""

from __future__ import annotations

import os
import csv
import math
from dataclasses import dataclass
from typing import Optional, Tuple, List

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit


# ============================================================
# PARAMÈTRES
# ============================================================

DEFAULT_DAC_MIN_DISPLAY = 0
DEFAULT_DAC_MAX_DISPLAY = 255

SAVE_FIGURES = True
FIGURE_DPI = 200

OUTPUT_FIT_CSV = "sigmoid_fit_results.csv"


# ============================================================
# MODÈLE SIGMOÏDE
# ============================================================

def sigmoid(x, y_low, y_high, x0, k):
    """
    Sigmoïde 4 paramètres.

    y_low  : plateau bas
    y_high : plateau haut
    x0     : point d'inflexion en DAC
    k      : pente. Le signe de k gère le sens de la courbe.
    """
    x = np.asarray(x, dtype=float)
    return y_low + (y_high - y_low) / (1.0 + np.exp(-(x - x0) / k))


@dataclass
class FitResult:
    position_mm: float
    delta_mm: float
    dac_min_fit: float
    dac_max_fit: float
    y_low: float
    y_high: float
    x0: float
    k: float
    success: bool
    message: str


# ============================================================
# OUTILS
# ============================================================

def ask_csv_path() -> str:
    path = input("Chemin du fichier CSV à analyser : ").strip().strip('"')
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    return path


def ask_float_or_default(prompt: str, default: float) -> float:
    txt = input(f"{prompt} [{default}] : ").strip().replace(",", ".")
    if not txt:
        return default
    return float(txt)


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    default_txt = "o" if default else "n"
    txt = input(f"{prompt} [o/n, défaut={default_txt}] : ").strip().lower()
    if not txt:
        return default
    return txt in ["o", "oui", "y", "yes"]


def clean_numeric_column(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def load_scan_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    required_cols = ["Position_mm", "Delta_mm", "Threshold_DAC", "C0_Rate", "Status"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans le CSV : {missing}")

    df["Position_mm"] = clean_numeric_column(df, "Position_mm")
    df["Delta_mm"] = clean_numeric_column(df, "Delta_mm")
    df["Threshold_DAC"] = clean_numeric_column(df, "Threshold_DAC")
    df["C0_Rate"] = clean_numeric_column(df, "C0_Rate")

    df = df.dropna(subset=["Position_mm", "Delta_mm", "Threshold_DAC", "C0_Rate"])

    if "Status" in df.columns:
        df = df[df["Status"].astype(str).str.upper() == "SUCCESS"].copy()

    df = df.sort_values(["Position_mm", "Threshold_DAC"], ascending=[True, False])
    return df


def filter_dac_range(df: pd.DataFrame, dac_min: float, dac_max: float) -> pd.DataFrame:
    low = min(dac_min, dac_max)
    high = max(dac_min, dac_max)
    return df[(df["Threshold_DAC"] >= low) & (df["Threshold_DAC"] <= high)].copy()


def initial_guess_for_sigmoid(x: np.ndarray, y: np.ndarray) -> Tuple[float, float, float, float]:
    y_low = float(np.nanmin(y))
    y_high = float(np.nanmax(y))

    if y_high == y_low:
        y_high = y_low + 1.0

    # x0 initial : DAC proche de la moitié entre min et max
    half = y_low + 0.5 * (y_high - y_low)
    idx = int(np.argmin(np.abs(y - half)))
    x0 = float(x[idx])

    # k initial : largeur grossière de la plage / 10
    x_span = float(np.nanmax(x) - np.nanmin(x))
    k = x_span / 10.0 if x_span > 0 else 1.0

    # Si la courbe diminue avec x, k négatif peut aider.
    if len(x) >= 2:
        slope_est = np.polyfit(x, y, 1)[0]
        if slope_est < 0:
            k = -abs(k)
        else:
            k = abs(k)

    if abs(k) < 1e-6:
        k = 1.0

    return y_low, y_high, x0, k


def fit_sigmoid_on_data(x: np.ndarray, y: np.ndarray) -> Tuple[Optional[np.ndarray], str]:
    if len(x) < 5:
        return None, "Pas assez de points pour un fit sigmoïde fiable. Minimum conseillé : 5 points."

    if np.nanmax(y) == np.nanmin(y):
        return None, "Tous les points ont le même taux, fit impossible."

    p0 = initial_guess_for_sigmoid(x, y)

    try:
        # maxfev augmenté car les sigmoïdes peuvent être difficiles à fitter.
        popt, pcov = curve_fit(
            sigmoid,
            x,
            y,
            p0=p0,
            maxfev=50000,
        )
        return popt, "OK"

    except Exception as e:
        return None, f"Fit impossible : {e}"


def save_fit_results(results: List[FitResult], output_dir: str) -> None:
    if not results:
        return

    out_path = os.path.join(output_dir, OUTPUT_FIT_CSV)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Position_mm",
            "Delta_mm",
            "DAC_min_fit",
            "DAC_max_fit",
            "y_low",
            "y_high",
            "x0_inflexion_DAC",
            "k",
            "success",
            "message",
        ])

        for r in results:
            writer.writerow([
                f"{r.position_mm:.1f}",
                f"{r.delta_mm:.1f}",
                f"{r.dac_min_fit:.1f}",
                f"{r.dac_max_fit:.1f}",
                f"{r.y_low:.6g}" if r.success else "NA",
                f"{r.y_high:.6g}" if r.success else "NA",
                f"{r.x0:.6g}" if r.success else "NA",
                f"{r.k:.6g}" if r.success else "NA",
                r.success,
                r.message,
            ])

    print(f"Résultats des fits sauvegardés dans : {out_path}")


# ============================================================
# PLOT D'UNE POSITION
# ============================================================

def plot_one_position(
    df_pos: pd.DataFrame,
    position: float,
    output_dir: str,
    dac_min_display: float,
    dac_max_display: float,
    do_fit: bool,
) -> FitResult:
    df_display = filter_dac_range(df_pos, dac_min_display, dac_max_display)

    if df_display.empty:
        print(f"Aucune donnée pour position {position:.1f} mm dans la plage DAC demandée.")
        return FitResult(position, np.nan, dac_min_display, dac_max_display,
                         np.nan, np.nan, np.nan, np.nan, False, "Aucune donnée dans la plage")

    # Pour affichage : DAC décroissant de 255 vers 0 si l'axe est inversé.
    df_display = df_display.sort_values("Threshold_DAC", ascending=False)

    x = df_display["Threshold_DAC"].to_numpy(dtype=float)
    y = df_display["C0_Rate"].to_numpy(dtype=float)

    delta = float(df_display["Delta_mm"].iloc[0])

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.scatter(x, y, label="Mesures", zorder=3)

    fit_result = FitResult(
        position_mm=position,
        delta_mm=delta,
        dac_min_fit=min(dac_min_display, dac_max_display),
        dac_max_fit=max(dac_min_display, dac_max_display),
        y_low=np.nan,
        y_high=np.nan,
        x0=np.nan,
        k=np.nan,
        success=False,
        message="Fit non demandé",
    )

    if do_fit:
        popt, msg = fit_sigmoid_on_data(x, y)

        if popt is not None:
            y_low, y_high, x0, k = popt

            x_fit = np.linspace(np.nanmin(x), np.nanmax(x), 500)
            y_fit = sigmoid(x_fit, *popt)
            ax.plot(x_fit, y_fit, label=f"Fit sigmoïde | x0 = {x0:.2f} DAC")
            ax.axvline(x0, linestyle="--", label=f"Inflexion x0 = {x0:.2f}")

            fit_result = FitResult(
                position_mm=position,
                delta_mm=delta,
                dac_min_fit=min(dac_min_display, dac_max_display),
                dac_max_fit=max(dac_min_display, dac_max_display),
                y_low=float(y_low),
                y_high=float(y_high),
                x0=float(x0),
                k=float(k),
                success=True,
                message="OK",
            )

            print(f"Position {position:.1f} mm | Fit OK : x0 = {x0:.3f} DAC, k = {k:.3f}")
        else:
            print(f"Position {position:.1f} mm | {msg}")
            fit_result.message = msg

    ax.set_title(f"Position {position:.1f} mm | Delta {delta:.1f} mm")
    ax.set_xlabel("Threshold DAC")
    ax.set_ylabel("C0 Rate (coups/s)")
    ax.grid(True, alpha=0.3)
    ax.legend()

    # On affiche de 255 vers 0 comme un balayage DAC descendant.
    ax.set_xlim(max(dac_min_display, dac_max_display), min(dac_min_display, dac_max_display))

    plt.tight_layout()

    if SAVE_FIGURES:
        safe_pos = f"{position:.1f}".replace(".", "p")
        fig_path = os.path.join(output_dir, f"scan_position_{safe_pos}mm_sigmoid.png")
        fig.savefig(fig_path, dpi=FIGURE_DPI)
        print(f"Figure sauvegardée : {fig_path}")

    plt.show()
    return fit_result


# ============================================================
# MAIN
# ============================================================

def main():
    csv_path = ask_csv_path()
    df = load_scan_csv(csv_path)

    if df.empty:
        print("Aucune donnée valide trouvée dans le CSV.")
        return

    output_dir = os.path.join(os.path.dirname(csv_path), "plots_sigmoid")
    os.makedirs(output_dir, exist_ok=True)

    print("\nRésumé du fichier :")
    print(f"Nombre de lignes valides : {len(df)}")
    print(f"Positions disponibles : {sorted(df['Position_mm'].unique())}")
    print(f"DAC min/max dans le fichier : {df['Threshold_DAC'].min()} / {df['Threshold_DAC'].max()}")

    dac_min_display = ask_float_or_default("DAC minimum à afficher/fitter", DEFAULT_DAC_MIN_DISPLAY)
    dac_max_display = ask_float_or_default("DAC maximum à afficher/fitter", DEFAULT_DAC_MAX_DISPLAY)
    do_fit = ask_yes_no("Faire un fit sigmoïde sur cette plage ?", default=True)

    fit_results: List[FitResult] = []

    for position, df_pos in df.groupby("Position_mm"):
        result = plot_one_position(
            df_pos=df_pos,
            position=float(position),
            output_dir=output_dir,
            dac_min_display=dac_min_display,
            dac_max_display=dac_max_display,
            do_fit=do_fit,
        )
        fit_results.append(result)

    if do_fit:
        save_fit_results(fit_results, output_dir)

    print("\nAnalyse terminée.")
    print(f"Dossier des figures : {output_dir}")


if __name__ == "__main__":
    main()

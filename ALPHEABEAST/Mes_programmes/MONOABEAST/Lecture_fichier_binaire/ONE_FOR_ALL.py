# -*- coding: utf-8 -*-
"""
Author  : Djokhar BETELGUERIEV (Simplified)
Date    : 2025-03-18
Description : Simplified WaveCatcher data analysis program.
"""

import matplotlib.pyplot as plt
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog
import os
import copy
import csv
from datetime import datetime
from pathlib import Path
from bisect import bisect_left
from scipy.optimize import curve_fit
from matplotlib.widgets import Button, RectangleSelector, Slider, CheckButtons

# Constantes globales
drct = "C:/Program Files (x86)/WaveCatcher_64ch/Run_Data/"
samples = 1024          # nombre de samples réellement lus dans le fichier
display_samples = 1000  # samples utilisés pour les minima et pour l'affichage (<= samples)
ANALOG_BASELINE_SAMPLES = 100  # samples pré-trigger utilisés pour estimer la baseline

fixed_header = 0x186
# fixed_header = 0x17f
max_events_per_file = 100000
possible_offsets = [40,52, 56, 60, 64, 48, 68, 44, 72, 76, 80, 84, 88, 92]


# ---------------------------------------------------------------------------
# Configurations physiques supportées
# ---------------------------------------------------------------------------
# Câblage des voies WaveCatcher utilisé pour l'analyse :
#
#   CH0 : voie analogique Boron          -> validée par le discriminateur CH1
#   CH1 : discriminateur Boron
#   CH2 : voie analogique Polyethylene   -> validée par le discriminateur CH3
#   CH3 : discriminateur Polyethylene
#   CH4 : voie analogique sans convert.  -> validée par le discriminateur CH5
#   CH5 : discriminateur sans convertisseur
#
# En configuration 4 voies, seuls les deux premiers couples sont présents :
# CH0/CH1 et CH2/CH3. En configuration 6 voies, CH4/CH5 est également présent.
CHANNEL_LAYOUTS = {
    4: [0, 1, 2, 3],
    6: [0, 1, 2, 3, 4, 5],
}
ALLOWED_NUMBER_OF_CHANNELS = tuple(sorted(CHANNEL_LAYOUTS))

# Mapping maximal position dans l'événement -> numéro de channel physique.
PHYSICAL_CHANNELS = CHANNEL_LAYOUTS[6]

# Association voie analogique / discriminateur pour le tri des événements.
DETECTORS = {
    "Boron": {
        "analog_channel": 0,
        "discriminator_channel": 1,
    },
    "Polyethylene": {
        "analog_channel": 2,
        "discriminator_channel": 3,
    },
    "No converter": {
        "analog_channel": 4,
        "discriminator_channel": 5,
    },
}

# Réglages de détection des discriminateurs.
DISCRIMINATOR_BASELINE_SAMPLES = 100
DISCRIMINATOR_PLATEAU_SAMPLES = 10
DISCRIMINATOR_SIGMA_FACTOR = 10.0
DISCRIMINATOR_MIN_STEP = 0.5


def channel_count_is_allowed(value, expected_channels=None):
    """Vrai si NumberOfChannel correspond à une configuration autorisée."""
    if value is None:
        return False

    try:
        value = int(value)
    except (TypeError, ValueError):
        return False

    if expected_channels is None:
        return 0 < value <= 10

    if isinstance(expected_channels, (tuple, list, set, frozenset)):
        return value in {int(v) for v in expected_channels}

    return value == int(expected_channels)


def physical_channels_for_count(number_of_channels):
    """Mapping position -> numéro physique pour 4 ou 6 voies."""
    try:
        n = int(number_of_channels)
    except (TypeError, ValueError):
        return PHYSICAL_CHANNELS
    return CHANNEL_LAYOUTS.get(n, PHYSICAL_CHANNELS[:max(0, n)])


def available_detectors_for_amplitudes(amplitudes):
    """Détecteurs réellement présents dans cet événement."""
    available = []
    n = len(amplitudes) if amplitudes is not None else 0

    for detector_name, cfg in DETECTORS.items():
        apos = channel_position(cfg["analog_channel"])
        dpos = channel_position(cfg["discriminator_channel"])
        if (
            apos is not None and dpos is not None
            and apos < n and dpos < n
        ):
            available.append(detector_name)

    return available


def active_detectors_from_events(detection_events):
    """Union ordonnée des détecteurs réellement présents dans le fichier."""
    present = set()
    for evt in detection_events or []:
        present.update(evt.get("available_detectors", []))

    active = [name for name in DETECTORS if name in present]
    return active if active else list(DETECTORS)


def physical_channel_from_position(position):
    """Convertit la position 0..5 dans l'événement en numéro de channel physique."""
    if 0 <= position < len(PHYSICAL_CHANNELS):
        return PHYSICAL_CHANNELS[position]
    return position


def channel_position(physical_channel):
    """Retourne la position dans amplitudes/hit_counts pour un channel physique."""
    try:
        return PHYSICAL_CHANNELS.index(physical_channel)
    except ValueError:
        return None


def discriminator_step_is_active(waveform):
    """Détecte l'échelon logique d'un discriminateur."""
    if waveform is None or len(waveform) < DISCRIMINATOR_PLATEAU_SAMPLES:
        return False

    arr = np.asarray(waveform, dtype=float)
    if arr.size == 0 or not np.all(np.isfinite(arr)):
        return False

    nbase = min(DISCRIMINATOR_BASELINE_SAMPLES, len(arr))
    baseline = arr[:nbase]
    baseline_mean = float(np.mean(baseline))
    baseline_std = float(np.std(baseline))

    # Un pic isolé n'est pas considéré comme un trigger : le niveau haut
    # doit rester présent plusieurs samples de suite.
    step = max(DISCRIMINATOR_MIN_STEP,
               DISCRIMINATOR_SIGMA_FACTOR * baseline_std)
    threshold = baseline_mean + step

    consecutive = 0
    for value in arr:
        if value > threshold:
            consecutive += 1
            if consecutive >= DISCRIMINATOR_PLATEAU_SAMPLES:
                return True
        else:
            consecutive = 0

    return False


def event_discriminator_hits(amplitudes):
    """
    Pour un événement WaveCatcher, indique quels discriminateurs ont commuté.

    Returns:
        dict {"Boron": bool, "Polyethylene": bool, "No converter": bool}
    """
    result = {}

    for detector_name, cfg in DETECTORS.items():
        pos = channel_position(cfg["discriminator_channel"])

        if pos is None or pos >= len(amplitudes):
            result[detector_name] = False
            continue

        result[detector_name] = discriminator_step_is_active(amplitudes[pos])

    return result


# ---------------------------------------------------------------------------
# Calibration ADC <-> énergie
# ---------------------------------------------------------------------------
def _float_or_none(value):
    if value is None:
        return None
    txt = str(value).strip().replace(",", ".")
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _normalise_header(name):
    return str(name or "").strip().lower().replace("\\", "").replace(" ", "")


class EnergyCalibration:
    """
    Lit une calibration contenant au minimum :
        adc
        energy_eV ou energy_MeV

    Colonnes supplémentaires reconnues :
        fit_a_eV_per_ADC
        fit_b_eV

    Conversion utilisée :
      - interpolation linéaire entre les points de la table dans la plage ;
      - si les coefficients a,b sont présents, E[eV] = a*ADC+b est utilisé
        pour l'extrapolation hors de la plage.

    Pour discriminer les énergies, les lignes de la calibration servent de
    centres de classes. Les frontières sont placées à mi-distance entre deux
    valeurs ADC successives.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.adc = np.asarray([], dtype=float)
        self.energy_ev = np.asarray([], dtype=float)
        self.energy_mev = np.asarray([], dtype=float)
        self.fit_a = None
        self.fit_b = None

        self._read()

    def _read(self):
        raw_text = self.path.read_text(encoding="utf-8-sig", errors="replace")
        lines = [line for line in raw_text.splitlines() if line.strip()]
        if not lines:
            raise ValueError("Le fichier de calibration est vide.")

        # Support CSV/TSV/point-virgule et également une table Markdown avec |.
        first = lines[0]
        if "|" in first and first.count("|") >= 2:
            cleaned = []
            for line in lines:
                s = line.strip()
                if s.startswith("|"):
                    s = s[1:]
                if s.endswith("|"):
                    s = s[:-1]
                parts = [p.strip() for p in s.split("|")]
                # Ignore la ligne Markdown du type | --- | --- |
                if parts and all(
                    p.replace("-", "").replace(":", "").strip() == ""
                    for p in parts
                ):
                    continue
                cleaned.append(",".join(parts))
            raw_text = "\n".join(cleaned)
            delimiter = ","
        else:
            sample = raw_text[:8192]
            try:
                delimiter = csv.Sniffer().sniff(
                    sample, delimiters=",;\t"
                ).delimiter
            except csv.Error:
                delimiter = ";" if first.count(";") > first.count(",") else ","

        reader = csv.DictReader(raw_text.splitlines(), delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("En-tête de calibration introuvable.")

        header_map = {
            _normalise_header(name): name
            for name in reader.fieldnames
        }

        adc_key = header_map.get("adc")
        ev_key = header_map.get("energy_ev")
        mev_key = header_map.get("energy_mev")
        a_key = header_map.get("fit_a_ev_per_adc")
        b_key = header_map.get("fit_b_ev")

        if adc_key is None:
            raise ValueError("La colonne 'adc' est absente.")
        if ev_key is None and mev_key is None:
            raise ValueError(
                "Il faut une colonne 'energy_eV' ou 'energy_MeV'."
            )

        rows = []
        fit_as = []
        fit_bs = []

        for raw in reader:
            adc = _float_or_none(raw.get(adc_key))
            ev = _float_or_none(raw.get(ev_key)) if ev_key else None
            mev = _float_or_none(raw.get(mev_key)) if mev_key else None

            if ev is None and mev is not None:
                ev = mev * 1e6
            if mev is None and ev is not None:
                mev = ev / 1e6

            if adc is None or ev is None or mev is None:
                continue

            rows.append((adc, ev, mev))

            if a_key:
                a = _float_or_none(raw.get(a_key))
                if a is not None:
                    fit_as.append(a)
            if b_key:
                b = _float_or_none(raw.get(b_key))
                if b is not None:
                    fit_bs.append(b)

        if len(rows) < 2:
            raise ValueError(
                "La calibration doit contenir au moins deux lignes exploitables."
            )

        rows.sort(key=lambda r: r[0])

        # En cas d'ADC dupliqués, garder une seule ligne par valeur.
        unique = {}
        for row in rows:
            unique[row[0]] = row
        rows = [unique[k] for k in sorted(unique)]

        self.adc = np.asarray([r[0] for r in rows], dtype=float)
        self.energy_ev = np.asarray([r[1] for r in rows], dtype=float)
        self.energy_mev = np.asarray([r[2] for r in rows], dtype=float)

        if fit_as:
            self.fit_a = float(np.median(fit_as))
        if fit_bs:
            self.fit_b = float(np.median(fit_bs))

        # Frontières ADC pour l'affectation à une classe d'énergie.
        self.adc_edges = (self.adc[:-1] + self.adc[1:]) / 2.0

    @property
    def adc_min(self):
        return float(self.adc[0])

    @property
    def adc_max(self):
        return float(self.adc[-1])

    def energy_for_adc(self, adc_value):
        """Retourne (energy_eV, energy_MeV, mode)."""
        adc_value = float(adc_value)

        if self.adc_min <= adc_value <= self.adc_max:
            ev = float(np.interp(adc_value, self.adc, self.energy_ev))
            return ev, ev / 1e6, "interp"

        if self.fit_a is not None and self.fit_b is not None:
            ev = self.fit_a * adc_value + self.fit_b
            return float(ev), float(ev / 1e6), "fit-extrap"

        return None, None, "out-of-range"

    def adc_for_energy(self, energy_mev):
        """
        Conversion inverse énergie -> ADC, utile pour afficher le seuil de la jauge.

        Priorité au fit E[eV] = a*ADC + b lorsqu'il est présent.
        Sinon interpolation inverse sur les points de calibration.
        """
        energy_mev = float(energy_mev)
        energy_ev = energy_mev * 1e6

        if (
            self.fit_a is not None
            and self.fit_b is not None
            and abs(self.fit_a) > 1e-15
        ):
            return float((energy_ev - self.fit_b) / self.fit_a)

        order = np.argsort(self.energy_mev)
        e = self.energy_mev[order]
        a = self.adc[order]

        if energy_mev < float(e[0]) or energy_mev > float(e[-1]):
            return None

        return float(np.interp(energy_mev, e, a))

    def class_for_adc(self, adc_value):
        """
        Classe l'ADC sur la ligne de calibration la plus proche.

        Retourne un dictionnaire avec le centre ADC / énergie de la classe,
        ou None si l'ADC est hors de la plage couverte par la table.
        """
        adc_value = float(adc_value)
        if adc_value < self.adc_min or adc_value > self.adc_max:
            return None

        idx = int(np.searchsorted(self.adc_edges, adc_value, side="right"))
        idx = max(0, min(idx, len(self.adc) - 1))

        return {
            "index": idx,
            "adc_center": float(self.adc[idx]),
            "energy_eV": float(self.energy_ev[idx]),
            "energy_MeV": float(self.energy_mev[idx]),
            "label": f"{self.energy_mev[idx]:.6f} MeV",
        }


def analog_min_adc(waveform):
    """
    ADC utilisé pour la conversion en énergie.

    Les voies analogiques CH0 / CH2 / CH4 ont des pulses NEGATIFS.
    La calibration, elle, utilise une amplitude ADC positive.

    On calcule donc :
        amplitude_ADC = baseline - minimum_du_pulse

    La baseline est la médiane des premiers ANALOG_BASELINE_SAMPLES points.
    Cette méthode est plus robuste que abs(minimum), notamment si la baseline
    n'est pas exactement à zéro.
    """
    if waveform is None or len(waveform) == 0:
        return None

    arr = np.asarray(waveform, dtype=float)
    if arr.size == 0 or not np.all(np.isfinite(arr)):
        return None

    n = (
        len(arr)
        if display_samples is None
        else min(display_samples, len(arr))
    )
    if n <= 0:
        return None

    used = arr[:n]

    n_baseline = min(
        ANALOG_BASELINE_SAMPLES,
        max(1, len(used))
    )
    baseline = float(np.median(used[:n_baseline]))
    minimum = float(np.min(used))

    amplitude_adc = baseline - minimum

    # Un pulse négatif doit donner une amplitude positive.
    return max(0.0, float(amplitude_adc))


def event_analog_adc_values(amplitudes):
    """
    ADC analogique associé à chaque chaîne :
      Boron        -> CH0
      Polyethylene -> CH2
      No converter -> CH4
    """
    result = {}

    for detector_name, cfg in DETECTORS.items():
        pos = channel_position(cfg["analog_channel"])
        if pos is None or pos >= len(amplitudes):
            result[detector_name] = None
            continue
        result[detector_name] = analog_min_adc(amplitudes[pos])

    return result


def apply_energy_calibration(detection_events, calibration):
    """
    Ajoute à chaque événement :
      evt["energies"][detector] = {
          adc, energy_eV, energy_MeV, mode,
          class_index, class_energy_MeV, class_label
      }

    L'énergie n'est considérée comme un "coup énergétique" que si le
    discriminateur correspondant a effectivement détecté le coup.
    """
    if calibration is None:
        return

    for evt in detection_events:
        energies = {}
        adc_values = evt.get("adc_values", {})

        for detector_name in DETECTORS:
            adc = adc_values.get(detector_name)

            if adc is None:
                energies[detector_name] = None
                continue

            ev, mev, mode = calibration.energy_for_adc(adc)
            energy_class = calibration.class_for_adc(adc)

            info = {
                "adc": float(adc),
                "energy_eV": ev,
                "energy_MeV": mev,
                "mode": mode,
                "class_index": None,
                "class_energy_eV": None,
                "class_energy_MeV": None,
                "class_label": "hors gamme",
            }

            if energy_class is not None:
                info.update({
                    "class_index": energy_class["index"],
                    "class_energy_eV": energy_class["energy_eV"],
                    "class_energy_MeV": energy_class["energy_MeV"],
                    "class_label": energy_class["label"],
                })

            energies[detector_name] = info

        evt["energies"] = energies


class InteractiveGaussFit:
    """
    Outil interactif pour fitter une gaussienne sur une zone choisie à la souris.

    Utilisation :
    1) sélectionner une zone de l'histogramme avec la souris,
    2) cliquer sur "Add Fit",
    3) utiliser "Clear Fits" pour supprimer les fits du canal.

    Important : les instances de cette classe doivent rester stockées dans une variable
    tant que la figure est ouverte, sinon Matplotlib peut perdre les callbacks.
    """

    def __init__(self, x, y, ax):
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.ax = ax
        self.fig = ax.figure
        self.fits = []

        if len(self.x) > 0:
            self.xmin = float(np.min(self.x))
            self.xmax = float(np.max(self.x))
        else:
            self.xmin = 0.0
            self.xmax = 1.0

        # Sélecteur de zone à la souris sur l'axe du canal.
        self.rect_selector = RectangleSelector(
            self.ax,
            self.on_select,
            useblit=True,
            button=[1],
            minspanx=5,
            minspany=5,
            spancoords='pixels',
            interactive=True,
            props=dict(facecolor='red', edgecolor='black', alpha=0.2, fill=True)
        )

        # Boutons placés dans la même figure, en bas à droite de chaque axe.
        pos = self.ax.get_position()
        button_width = 0.08
        button_height = 0.03
        button_y = max(0.01, pos.y0 + 0.01)

        self.button_ax = self.fig.add_axes([
            pos.x1 - button_width - 0.01,
            button_y,
            button_width,
            button_height
        ])
        self.clear_button_ax = self.fig.add_axes([
            pos.x1 - 2 * button_width - 0.02,
            button_y,
            button_width,
            button_height
        ])

        self.button = Button(self.button_ax, 'Add Fit')
        self.button.on_clicked(self.add_fit)

        self.clear_button = Button(self.clear_button_ax, 'Clear Fits')
        self.clear_button.on_clicked(self.clear_fits)

    @staticmethod
    def gaussian(x, amp, mu, sigma):
        return amp * np.exp(-(x - mu) ** 2 / (2 * sigma ** 2))

    def on_select(self, eclick, erelease):
        """Mémorise la zone sélectionnée avec la souris."""
        x1, x2 = eclick.xdata, erelease.xdata

        if x1 is None or x2 is None:
            return

        self.xmin, self.xmax = min(x1, x2), max(x1, x2)
        mask = (self.x >= self.xmin) & (self.x <= self.xmax)
        num_points = int(np.sum(mask))

        if num_points < 3:
            print(f"Attention: seulement {num_points} points dans la sélection. Élargir la zone.")
        else:
            print(f"Sélection valide: {num_points} points.")

    def add_fit(self, event):
        """Ajoute un fit gaussien sur la zone sélectionnée."""
        if len(self.x) == 0 or len(self.y) == 0:
            print("Pas de données disponibles pour l'ajustement.")
            return

        try:
            mask = (self.x >= self.xmin) & (self.x <= self.xmax)
            num_points = int(np.sum(mask))

            if num_points < 3:
                print(f"Pas assez de points dans la sélection ({num_points}). Utilisation de toutes les données.")
                x_fit = self.x
                y_fit = self.y
            else:
                x_fit = self.x[mask]
                y_fit = self.y[mask]
                print(f"Ajustement avec {num_points} points.")

            if len(x_fit) < 3 or np.max(y_fit) <= 0:
                print("Données insuffisantes pour fitter une gaussienne.")
                return

            max_y_index = int(np.argmax(y_fit))
            max_y = float(y_fit[max_y_index])
            mean_x = float(x_fit[max_y_index])

            half_height = max_y / 2.0
            above_half = y_fit >= half_height
            if np.sum(above_half) > 1:
                x_above = x_fit[above_half]
                fwhm = float(np.max(x_above) - np.min(x_above))
                sigma = fwhm / 2.355 if fwhm > 0 else max(1.0, (np.max(x_fit) - np.min(x_fit)) / 10.0)
            else:
                sigma = max(1.0, (np.max(x_fit) - np.min(x_fit)) / 10.0)

            p0 = [max_y, mean_x, sigma]

            # Bounds : amplitude positive et sigma positif.
            popt, pcov = curve_fit(
                self.gaussian,
                x_fit,
                y_fit,
                p0=p0,
                bounds=([0.0, -np.inf, 1e-9], [np.inf, np.inf, np.inf]),
                maxfev=10000
            )

            fit_y = self.gaussian(self.x, *popt)
            label = f'Fit μ={popt[1]:.2f}, σ={popt[2]:.2f}, A={popt[0]:.2f}'
            line, = self.ax.plot(self.x, fit_y, '--', label=label)
            self.fits.append(line)

            self.ax.legend()
            self.fig.canvas.draw_idle()

            print(f"Fit ajouté: mu={popt[1]:.3f}, sigma={popt[2]:.3f}, A={popt[0]:.3f}")

        except Exception as e:
            print(f"Erreur lors de l'ajustement: {e}")
            print("Le fitting n'a pas convergé. Essayer une autre région.")

    def clear_fits(self, event):
        """Supprime tous les fits du canal."""
        for line in self.fits:
            try:
                line.remove()
            except ValueError:
                pass

        self.fits = []
        self.ax.legend()
        self.fig.canvas.draw_idle()


def ret_4bytes(rawdata, k):
    """Extrait 4 octets des données brutes à partir de l'index k"""
    if k >= 0 and k + 3 < len(rawdata):
        return rawdata[k] + (rawdata[k + 1] << 8) + (rawdata[k + 2] << 12) + (rawdata[k + 3] << 16)
    else:
        return None


def read_single_wave(rawdata, idx):
    """Lit une forme d'onde unique à partir de l'index idx"""
    wtmp = []
    for i in range(samples):
        val = rawdata[idx] | (rawdata[idx + 1] << 8)
        # Vérifier si le bit de poids fort est à 1 (nombre négatif)
        if val & 0x8000:
            # Conversion en complément à 2 pour obtenir la valeur négative
            val = -((val ^ 0xFFFF) + 1)
        wtmp.append(val)
        idx += 2
    return idx, wtmp


def read_event_fullwave(rawdata, idx, amp, prev_timestamp=None, header_offset=None, expected_channels=None):
    """
    Lit un événement dans les données binaires.
    Returns None si erreur,
    Returns (idx, trigger, amplitudes, NumberOfChannel, hit_counts, rates, current_timestamp, EventNumber, timestamp_info, False) si succès,
    Returns (None, None, None, None, None, None, None, None, None, True) si fin de fichier naturelle
    """
    # Si l'index est au-delà de la fin du fichier ou très proche,
    # c'est probablement une fin de fichier naturelle
    if idx is None or idx >= len(rawdata) - 100:
        return (None, None, None, None, None, None, None, None, None, True)

    if rawdata is None:
        return None

    try:
        # Lecture des métadonnées de l'événement
        EventNumber = ret_4bytes(rawdata, idx + 0)
        Year = ret_4bytes(rawdata, idx + 12)
        Month = ret_4bytes(rawdata, idx + 16)
        Day = ret_4bytes(rawdata, idx + 20)
        Hour = ret_4bytes(rawdata, idx + 24)
        Minute = ret_4bytes(rawdata, idx + 28)
        Second = ret_4bytes(rawdata, idx + 32)
        Millisecond = ret_4bytes(rawdata, idx + 36)
        NumberOfChannel = ret_4bytes(rawdata, idx + 48)
        channel = ret_4bytes(rawdata, idx + 52)

        # Vérification précoce des valeurs de date/heure pour détecter des valeurs aberrantes
        if Year is not None and Month is not None and Day is not None and Hour is not None and Minute is not None and Second is not None:
            if Month <= 0 or Month > 12 or Day <= 0 or Day > 31 or Hour < 0 or Hour > 23 or Minute < 0 or Minute > 59 or Second < 0 or Second > 59:
                print(
                    f"ALERTE: Valeurs de date/heure invalides: {Day}/{Month}/{Year} - {Hour}:{Minute}:{Second}.{Millisecond}")
                return None

        # Vérification et correction du nombre de canaux
        if NumberOfChannel is None or NumberOfChannel <= 0 or NumberOfChannel > 10:
            found_valid = False
            # Liste des décalages à essayer pour l'en-tête
            for test_offset in [0, 4, -4, 8, -8, 12, -12]:
                test_idx = idx + test_offset
                test_number_of_channels = ret_4bytes(rawdata, test_idx + 48)

                # Vérifier si ce décalage donne un nombre de canaux valide
                if test_number_of_channels is not None and 0 < test_number_of_channels <= 10:
                    # Vérifier si c'est cohérent avec le nombre de canaux attendu
                    if expected_channels is None or channel_count_is_allowed(test_number_of_channels, expected_channels):
                        # Mettre à jour les valeurs avec le nouveau décalage
                        idx = test_idx
                        EventNumber = ret_4bytes(rawdata, idx + 0)
                        Year = ret_4bytes(rawdata, idx + 12)
                        Month = ret_4bytes(rawdata, idx + 16)
                        Day = ret_4bytes(rawdata, idx + 20)
                        Hour = ret_4bytes(rawdata, idx + 24)
                        Minute = ret_4bytes(rawdata, idx + 28)
                        Second = ret_4bytes(rawdata, idx + 32)
                        Millisecond = ret_4bytes(rawdata, idx + 36)
                        NumberOfChannel = test_number_of_channels
                        channel = ret_4bytes(rawdata, idx + 52)
                        found_valid = True
                        break

            # Si aucun décalage valide n'est trouvé
            if not found_valid:
                print("Aucun décalage valide trouvé pour le nombre de canaux")
                return None

        # Vérifier la cohérence avec le nombre de canaux attendu (si spécifié)
        if expected_channels is not None and not channel_count_is_allowed(NumberOfChannel, expected_channels):
            print(f"ALERTE: Nombre de canaux incohérent: attendu l'une des configurations {expected_channels}, trouvé {NumberOfChannel}")

            # Essayons de trouver un meilleur index qui donne le bon nombre de canaux
            for test_idx_offset in range(-100, 100, 4):  # Essayer des décalages dans une plage de ±100 octets
                test_idx = idx + test_idx_offset
                if test_idx < 0 or test_idx >= len(rawdata) - 60:
                    continue

                test_number_of_channels = ret_4bytes(rawdata, test_idx + 48)

                if channel_count_is_allowed(test_number_of_channels, expected_channels):
                    print(f"Index corrigé trouvé à {test_idx_offset:+d} octets du point initial")
                    # Mettre à jour toutes les valeurs avec le nouveau décalage
                    idx = test_idx
                    EventNumber = ret_4bytes(rawdata, idx + 0)
                    Year = ret_4bytes(rawdata, idx + 12)
                    Month = ret_4bytes(rawdata, idx + 16)
                    Day = ret_4bytes(rawdata, idx + 20)
                    Hour = ret_4bytes(rawdata, idx + 24)
                    Minute = ret_4bytes(rawdata, idx + 28)
                    Second = ret_4bytes(rawdata, idx + 32)
                    Millisecond = ret_4bytes(rawdata, idx + 36)
                    NumberOfChannel = test_number_of_channels
                    channel = ret_4bytes(rawdata, idx + 52)
                    break

            # Vérifier si nous avons réussi à corriger
            if not channel_count_is_allowed(NumberOfChannel, expected_channels):
                print(f"ERREUR: Impossible de trouver un index cohérent pour une configuration {expected_channels}")
                return None

        # Validation des données essentielles
        if EventNumber is None or NumberOfChannel is None or NumberOfChannel <= 0:
            print(f"Erreur: Données d'en-tête incomplètes ou invalides à l'index 0x{idx:x}")
            return None

        if Day is None or Hour is None or Minute is None or Second is None or Millisecond is None:
            print(f"Erreur: Données de timestamp incomplètes à l'index 0x{idx:x}")
            return None

        # Timestamp WaveCatcher ORIGINAL, exactement selon la convention du programme
        # fourni par l'utilisateur. Exemple : 1850842085 pour 21/07/2026 10:07:22.085.
        current_timestamp = ((Day * 24 + Hour) * 3600 + Minute * 60 + Second) * 1000 + Millisecond

        # On conserve EN PLUS une base temporelle absolue pour calculer correctement
        # les temps relatifs même si l'acquisition traverse minuit ou change de mois.
        absolute_timestamp_ms = None
        try:
            event_datetime = datetime(
                int(Year), int(Month), int(Day),
                int(Hour), int(Minute), int(Second),
                int(Millisecond) * 1000
            )
            absolute_timestamp_ms = event_datetime.timestamp() * 1000.0
        except (ValueError, TypeError, OverflowError, OSError):
            pass

        timestamp_info = {
            "year": int(Year),
            "month": int(Month),
            "day": int(Day),
            "hour": int(Hour),
            "minute": int(Minute),
            "second": int(Second),
            "millisecond": int(Millisecond),
            "raw_timestamp_ms": int(current_timestamp),
            "absolute_timestamp_ms": absolute_timestamp_ms,
            "label": (
                f"{int(Day):02d}/{int(Month):02d}/{int(Year):04d} "
                f"{int(Hour):02d}:{int(Minute):02d}:{int(Second):02d}."
                f"{int(Millisecond):03d}"
            ),
        }

        print(
            f'EventNumber : {EventNumber}, {NumberOfChannel} channels, {current_timestamp} - '
            f'{Day}/{Month}/{Year} - {Hour}:{Minute}:{Second}.{Millisecond} - {channel}')

        # Si c'est le premier appel, déterminer le décalage approprié entre l'en-tête et les données
        if header_offset is None:
            # Essayer différents décalages pour trouver le bon format
            # possible_offsets = [52, 56, 60, 64, 48, 68]

            found_offset = False

            for offset in possible_offsets:
                test_idx = idx + offset
                if test_idx + 28 < len(rawdata):  # Vérifier qu'on peut lire le hit_count
                    hit_count = ret_4bytes(rawdata, test_idx + 28)
                    if hit_count is not None and hit_count >= 0:
                        print(f"Décalage trouvé: {offset} octets")
                        header_offset = offset
                        found_offset = True
                        break

            if not found_offset:
                print("Impossible de déterminer le décalage approprié, utilisation de la valeur par défaut (56)")
                header_offset = 56

        # Appliquer le décalage pour accéder aux données des canaux
        idx += header_offset

        # Initialiser les structures pour les données des canaux
        trigger = [False] * NumberOfChannel
        amplitudes = [[] for _ in range(NumberOfChannel)]
        hit_counts = [0] * NumberOfChannel
        rates = [0] * NumberOfChannel

        # Lire les données pour chaque canal
        for i in range(NumberOfChannel):
            # Lire le hit_count
            hit_count = ret_4bytes(rawdata, idx + 28)
            if hit_count is None:
                print(f"Erreur: Impossible de lire le hit_count pour le canal {i}")
                return None

            # Mettre à jour hit_counts et rates
            hit_counts[i] = hit_count
            rates[i] = hit_count / (2.56 * 10 ** (-6)) if hit_count is not None else 0

            # Avancer l'index pour la forme d'onde
            idx += 36

            # Vérifier qu'on a assez de données pour la forme d'onde
            if idx + 2 * samples > len(rawdata):
                print(f"Erreur: Pas assez de données pour la forme d'onde (idx={idx}, canal {i})")
                return None

            # Lire la forme d'onde
            idx, wtmp = read_single_wave(rawdata, idx)

            # Déterminer si le canal a été déclenché
            trigger[i] = (hit_count > 0)
            amplitudes[i] = wtmp

        # Retourner - avec un flag False pour indiquer que ce n'est pas une fin de fichier
        return idx, trigger, amplitudes, NumberOfChannel, hit_counts, rates, current_timestamp, EventNumber, timestamp_info, False

    except Exception as e:
        print(f"Exception lors de la lecture de l'événement à l'index 0x{idx:x}: {str(e)}")
        return None


def find_first_0a01_header(data):
    """Trouve le premier 0a 01 dans le fichier binaire et retourne l'index de 01."""
    print("Recherche de l'index dans le fichier...")

    for i in range(len(data) - 1):
        if data[i] == 0x0a and data[i + 1] == 0x01:
            print(f"Le fixed header est à 0x{i + 1:x}")
            return i + 1  # Retourne l'index de 01

    print("Aucune séquence 0a 01 trouvée dans le fichier.")
    return None


def load_and_process_single_file(filename, base_dir):
    """
    Loads and processes a binary file, extracting waveforms and minimum values.
    Simplified version without standard amplitude histogram.
    """
    print(f"Processing file: {filename}")

    # Reference to global fixed_header variable
    global fixed_header
    successful_offset = None

    # Open and read the selected file
    with open(os.path.join(base_dir, filename), mode='rb') as file:
        data = file.read()

    # Find the first 0a 01 in the file
    idx = find_first_0a01_header(data)
    if idx is None:
        print(f"Using default value for fixed header: 0x{fixed_header:x}")
        idx = fixed_header
    else:
        # Update global fixed_header variable
        fixed_header = idx

    # List of possible offsets to try
    # possible_offsets = [52, 56, 60, 64, 48, 68]
    print(f"List of offsets to try: {possible_offsets}")

    # Variable to store the best attempt
    best_attempt = {
        "offset": None,
        "num_channels": 0,
        "event_minimums": [],
        "events_read": 0,
        "raw_waveforms": [],
        "detection_events": []
    }

    # Try each offset until one works correctly
    for current_offset in possible_offsets:
        print(f"\n===== Trying with header_offset = {current_offset} bytes =====")

        num_channels = None
        event_minimums = []  # List to store minimums per event
        raw_waveforms = []  # To store raw waveforms
        detection_events = []  # timestamp + état des 3 discriminateurs pour chaque événement
        current_idx = idx  # Reset start index
        previous_event_number = None  # To check event continuity
        sequence_error = False  # To detect sequence errors
        events_read = 0  # Event counter

        # Read all events from the file with this offset
        for i in range(max_events_per_file):
            # Use current offset without automatic detection
            readed_event = read_event_fullwave(data, current_idx, [], None, current_offset, ALLOWED_NUMBER_OF_CHANNELS)

            if readed_event is None:
                # This is a read error (not a natural end of file)
                if i == 0:
                    print(f"Failed to read first event with header_offset = {current_offset}")
                else:
                    print(f"Read error after {events_read} events")
                sequence_error = True  # Mark as error to try next offset
                break

            # Check if it's a natural end of file
            if len(readed_event) == 10 and readed_event[9] is True:
                print(f"Natural end of file reached after {events_read} events")
                # If at least one event was read, it's a success
                if events_read > 0:
                    # Store successful offset
                    successful_offset = current_offset
                    print(f"\n*** Successful read with header_offset = {current_offset} ***")
                    print(f"Number of events read: {events_read}")
                    print("End of file reached naturally without errors. Stop testing offsets.")
                    return num_channels, event_minimums, successful_offset, raw_waveforms, detection_events
                break

            # An event was successfully read
            events_read += 1

            # Use return structure with event number included (ignore last element which is end-of-file flag)
            current_idx, trigger, amplitudes, NumberOfChannel, hit_counts, rates, current_timestamp, EventNumber, timestamp_info, _ = readed_event

            # Store raw waveforms for this event (make a copy)
            raw_waveforms.append(copy.deepcopy(amplitudes))

            # Détection des fronts montants sur les discriminateurs 1, 4 et 6.
            discriminator_hits = event_discriminator_hits(amplitudes)

            # ADC analogique du même événement, utilisé ensuite pour reconstruire
            # l'énergie si un fichier de calibration ADC <-> énergie est chargé.
            analog_adc_values = event_analog_adc_values(amplitudes)

            detection_events.append({
                "event_number": EventNumber,
                # Timestamp brut WaveCatcher, exactement celui imprimé par ton programme.
                "timestamp_ms": float(current_timestamp),
                # Base absolue uniquement utilisée pour calculer t-t0 de façon robuste.
                "absolute_timestamp_ms": timestamp_info.get("absolute_timestamp_ms"),
                "timestamp_label": timestamp_info.get("label", str(current_timestamp)),
                "timestamp_info": timestamp_info,
                "hits": discriminator_hits,
                "adc_values": analog_adc_values,
                "available_detectors": available_detectors_for_amplitudes(amplitudes),
                "number_of_channels": NumberOfChannel,
            })

            # Check continuity of event numbers
            if previous_event_number is not None:
                expected_event_number = previous_event_number + 1
                if EventNumber != expected_event_number:
                    print(f"ALERT: Event sequence break at event #{EventNumber}")
                    print(f"  Expected: Event #{expected_event_number}")
                    print(f"  Found: Event #{EventNumber}")
                    print(f"  Trying with next offset...")
                    sequence_error = True
                    break

            # Update previous_event_number for next iteration
            previous_event_number = EventNumber

            # Initialize data arrays for first event
            if num_channels is None:
                num_channels = NumberOfChannel
                event_minimums = [[] for _ in range(num_channels)]
                layout = physical_channels_for_count(num_channels)
                print(
                    f"Configuration détectée : {num_channels} voies "
                    f"(channels physiques {layout})"
                )

            # Remplissage des voies analogiques après validation du discri associé.
            # CH0<-CH1, CH2<-CH3, CH4<-CH5.
            for detector_name, cfg in DETECTORS.items():
                analog_ch = cfg["analog_channel"]
                discri_ch = cfg["discriminator_channel"]

                analog_pos = channel_position(analog_ch)
                discri_pos = channel_position(discri_ch)

                # Couple absent en acquisition 4 voies.
                if (
                    analog_pos is None or discri_pos is None
                    or analog_pos >= num_channels
                    or discri_pos >= num_channels
                    or analog_pos >= len(amplitudes)
                    or discri_pos >= len(amplitudes)
                ):
                    continue

                # Pas d'échelon : pas d'entrée dans l'histogramme analogique.
                if not discriminator_hits.get(detector_name, False):
                    continue

                wf = amplitudes[analog_pos]
                if not wf:
                    continue

                # Une seule valeur par événement : le minimum de la waveform complète.
                # Même fenêtre que pour l'affichage : on ignore les 24 derniers samples.
                n = min(display_samples, len(wf)) if display_samples is not None else len(wf)
                if n <= 0:
                    continue
                waveform_min = min(wf[:n])
                event_minimums[analog_pos].append(waveform_min)


        # Update best attempt if this one read more events
        if num_channels is not None and events_read > best_attempt["events_read"]:
            best_attempt["offset"] = current_offset
            best_attempt["num_channels"] = num_channels
            best_attempt["event_minimums"] = event_minimums
            best_attempt["events_read"] = events_read
            best_attempt["raw_waveforms"] = raw_waveforms
            best_attempt["detection_events"] = detection_events

    # If we get here, none of the offsets allowed to reach the end of file naturally without error
    print("\n===== No offset allowed a perfect read =====")

    # Use best attempt if available
    if best_attempt["num_channels"] > 0:
        print(
            f"Using best result: offset={best_attempt['offset']}, {best_attempt['events_read']} events read")
        return (
            best_attempt["num_channels"],
            best_attempt["event_minimums"],
            best_attempt["offset"],
            best_attempt["raw_waveforms"],
            best_attempt["detection_events"],
        )

    print("ERROR: Failed to read with all possible offsets")
    return 0, [], None, [], []


class FileSelector:
    """
    Sélection du fichier WaveCatcher + calibration ADC <-> énergie optionnelle.
    """

    def __init__(self, directory):
        self.directory = directory
        self.selected_file = None
        self.calibration_file = None

    def create_window(self):
        self.window = tk.Tk()
        self.window.title("WaveCatcher File Selector")
        self.window.geometry("650x430")

        label = ttk.Label(
            self.window,
            text="Select a WaveCatcher binary file to analyze:"
        )
        label.pack(pady=(12, 6))

        self.listbox = tk.Listbox(self.window, width=78, height=12)
        self.listbox.pack(pady=6, padx=12, fill="x")

        files = self.get_files_list()
        for file in files:
            self.listbox.insert(tk.END, file)

        calib_frame = ttk.LabelFrame(
            self.window,
            text="Calibration ADC ↔ Energy (optional)",
            padding=10
        )
        calib_frame.pack(fill="x", padx=12, pady=10)

        self.calib_var = tk.StringVar(value="No calibration selected")
        ttk.Label(
            calib_frame,
            textvariable=self.calib_var
        ).pack(side="left", fill="x", expand=True)

        ttk.Button(
            calib_frame,
            text="Choose calibration...",
            command=self.choose_calibration
        ).pack(side="right", padx=4)

        ttk.Button(
            calib_frame,
            text="Clear",
            command=self.clear_calibration
        ).pack(side="right", padx=4)

        info = ttk.Label(
            self.window,
            text=(
                "Energy ADC = baseline - minimum du pulse analogique "
                "(amplitude positive pour les pulses négatifs)."
            )
        )
        info.pack(pady=(0, 8))

        buttons = ttk.Frame(self.window)
        buttons.pack(pady=8)

        ttk.Button(
            buttons,
            text="Analyze",
            command=self.on_analyze
        ).pack(side="left", padx=8)

        ttk.Button(
            buttons,
            text="Quit",
            command=self.on_quit
        ).pack(side="left", padx=8)

        self.window.mainloop()

    def get_files_list(self):
        return [
            f for f in os.listdir(self.directory)
            if os.path.isfile(os.path.join(self.directory, f))
        ]

    def choose_calibration(self):
        filename = filedialog.askopenfilename(
            parent=self.window,
            title="Choose ADC / Energy calibration",
            filetypes=[
                ("Calibration files", "*.csv *.txt"),
                ("CSV", "*.csv"),
                ("Text", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if filename:
            self.calibration_file = filename
            self.calib_var.set(filename)

    def clear_calibration(self):
        self.calibration_file = None
        self.calib_var.set("No calibration selected")

    def on_analyze(self):
        if self.listbox.curselection():
            self.selected_file = self.listbox.get(self.listbox.curselection())
            self.window.quit()
            self.window.destroy()

    def on_quit(self):
        self.selected_file = None
        self.window.quit()
        self.window.destroy()

def _triggered_analog_entries(event_minimums):
    """Liste des couples analogique/discriminateur présents dans le fichier."""
    entries = []
    for detector_name, cfg in DETECTORS.items():
        analog_ch = cfg["analog_channel"]
        discri_ch = cfg["discriminator_channel"]
        analog_pos = channel_position(analog_ch)
        discri_pos = channel_position(discri_ch)

        if (
            analog_pos is not None and discri_pos is not None
            and analog_pos < len(event_minimums)
            and discri_pos < len(event_minimums)
        ):
            entries.append((detector_name, analog_ch, discri_ch, analog_pos))

    return entries


def _format_hist_axis(ax):
    """Mise en forme commune aux histogrammes ADC."""
    ax.grid(axis='y', linestyle='--', linewidth=0.7, alpha=0.30)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.tick_params(axis='both', labelsize=9)


def create_min_amplitude_histogram(event_minimums, filename, n_bins=100):
    """Histogrammes CH0/CH2/CH4 après validation par leur discriminateur."""
    analog_entries = _triggered_analog_entries(event_minimums)

    if not analog_entries:
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.canvas.manager.set_window_title(f'ADC - {filename}')
        ax.text(0.5, 0.5, 'Aucun couple analogique / discriminateur disponible',
                ha='center', va='center', transform=ax.transAxes)
        ax.set_xlabel('|minimum ADC de l’événement|')
        _format_hist_axis(ax)
        return fig, [], []

    num_plots = len(analog_entries)
    fig, axs = plt.subplots(num_plots, 1, figsize=(11, 3.8 * num_plots))
    fig.canvas.manager.set_window_title(f'ADC triggered - {filename}')
    fig.suptitle(f'Minimum ADC par événement déclenché - {filename}',
                 fontsize=14, fontweight='bold')

    if num_plots == 1:
        axs = [axs]

    # On fixe la géométrie avant de créer les boutons des fits interactifs.
    fig.subplots_adjust(top=0.90, bottom=0.08, left=0.09, right=0.97, hspace=0.48)

    interactive_fits = []
    histogram_counts = []

    plot_colors = ['tab:blue', 'tab:orange', 'tab:green']

    for idx, (ax, entry) in enumerate(zip(axs, analog_entries)):
        detector_name, analog_ch, discri_ch, analog_pos = entry
        raw_values = event_minimums[analog_pos]
        _format_hist_axis(ax)

        if not raw_values:
            ax.text(0.5, 0.5, f'Aucun événement détecté par CH{discri_ch}',
                    ha='center', va='center', transform=ax.transAxes)
            ax.set_title(f'CH{analog_ch}  —  trigger CH{discri_ch}')
            ax.set_ylabel('Occurrences')
            continue

        # Les valeurs restent signées dans l'analyse. On passe en valeur absolue
        # uniquement pour l'affichage des histogrammes.
        values = np.abs(np.asarray(raw_values, dtype=float))
        color = plot_colors[idx % len(plot_colors)]

        counts, bins, _ = ax.hist(
            values,
            bins=n_bins,
            histtype='stepfilled',
            alpha=0.30,
            color=color,
            edgecolor=color,
            linewidth=1.0,
        )
        ax.hist(
            values,
            bins=bins,
            histtype='step',
            color=color,
            linewidth=1.6,
        )
        histogram_counts.append(counts)

        centers = (bins[:-1] + bins[1:]) / 2.0
        min_val = float(np.min(values))
        max_val = float(np.max(values))
        mean_val = float(np.mean(values))
        median_val = float(np.median(values))

        data_range = max_val - min_val
        margin = max(10.0, data_range * 0.06)
        ax.set_xlim(max(0.0, min_val - margin), max_val + margin)

        ymax = float(np.max(counts)) if len(counts) else 0.0
        ax.set_ylim(0, max(1.0, ymax * 1.15))

        ax.axvline(mean_val, linestyle='--', linewidth=1.1, alpha=0.75,
                   label=f'Moyenne : {mean_val:.1f}')
        ax.axvline(median_val, linestyle=':', linewidth=1.1, alpha=0.75,
                   label=f'Médiane : {median_val:.1f}')

        ax.set_title(
            f'CH{analog_ch}  —  trigger CH{discri_ch}  |  {len(values)} événements',
            fontsize=11,
        )
        ax.set_ylabel('Occurrences')
        ax.legend(loc='upper right', fontsize=9, frameon=False)

        interactive_fits.append(InteractiveGaussFit(centers, counts, ax))

    axs[-1].set_xlabel('|minimum ADC de l’événement|')

    return fig, interactive_fits, histogram_counts


def create_combined_triggered_histogram(event_minimums, filename, n_bins=100):
    """Superpose CH0, CH2 et CH4 avec les mêmes bins."""
    entries = _triggered_analog_entries(event_minimums)
    datasets = []

    for detector_name, analog_ch, discri_ch, analog_pos in entries:
        values = event_minimums[analog_pos]
        if values:
            datasets.append((
                detector_name,
                analog_ch,
                discri_ch,
                np.abs(np.asarray(values, dtype=float)),
            ))

    fig, ax = plt.subplots(figsize=(11, 6))
    fig.canvas.manager.set_window_title(f'ADC overlay - {filename}')
    _format_hist_axis(ax)

    if not datasets:
        ax.text(0.5, 0.5, 'Aucun événement déclenché',
                ha='center', va='center', transform=ax.transAxes)
        ax.set_xlabel('|minimum ADC de l’événement|')
        ax.set_ylabel('Occurrences')
        return fig

    global_min = min(float(np.min(values)) for _, _, _, values in datasets)
    global_max = max(float(np.max(values)) for _, _, _, values in datasets)

    if np.isclose(global_min, global_max):
        bins = np.linspace(max(0.0, global_min - 0.5), global_max + 0.5, n_bins + 1)
    else:
        bins = np.linspace(global_min, global_max, n_bins + 1)

    plot_colors = ['tab:blue', 'tab:orange', 'tab:green']

    for idx, (detector_name, analog_ch, discri_ch, values) in enumerate(datasets):
        color = plot_colors[idx % len(plot_colors)]
        label = f'CH{analog_ch} (trigger CH{discri_ch}) — {len(values)} evt'

        ax.hist(
            values,
            bins=bins,
            histtype='step',
            linewidth=1.8,
            color=color,
            label=label,
        )

    data_range = global_max - global_min
    margin = max(10.0, data_range * 0.06)
    ax.set_xlim(max(0.0, global_min - margin), global_max + margin)

    ax.set_title('Minimum ADC des voies analogiques déclenchées',
                 fontsize=13, fontweight='bold')
    ax.set_xlabel('|minimum ADC de l’événement|')
    ax.set_ylabel('Occurrences')
    ax.legend(frameon=False)
    fig.tight_layout()

    return fig


def create_waveform_display(amplitudes, filename, max_samples_to_plot=None):
    """
    Crée une nouvelle fenêtre pour afficher les formes d'onde de chaque canal
    avec mise en évidence des coordonnées x,y.
    max_samples_to_plot : nombre maximum de points par événement (ex : 1000).
                          Si None -> on affiche toute la longueur disponible.
    """
    num_channels = len(amplitudes)

    fig, axs = plt.subplots(num_channels, 1, figsize=(10, 5 * num_channels))
    fig.canvas.manager.set_window_title(f'Formes d\'onde - {filename}')
    fig.suptitle(f'Formes d\'onde - {filename} - {num_channels} canaux')

    if num_channels == 1:
        axs = [axs]

    # Déterminer la longueur max utilisable (en fonction des événements réels)
    all_lengths = [
        len(event)
        for ch in amplitudes
        for event in ch
        if event
    ]

    if not all_lengths:
        print("Aucune forme d'onde disponible pour l'affichage.")
        return fig

    max_length_in_data = min(all_lengths)  # plus sûr : tout le monde a au moins cette longueur

    if max_samples_to_plot is None:
        n_samples = max_length_in_data
    else:
        n_samples = min(max_samples_to_plot, max_length_in_data)

    # Axe X commun à tous les événements
    x = np.arange(n_samples)

    all_events = []
    for channel_idx in range(num_channels):
        channel_events = []
        for event_idx in range(len(amplitudes[channel_idx])):
            if amplitudes[channel_idx][event_idx]:
                # On tronque / ajuste à n_samples
                waveform = amplitudes[channel_idx][event_idx][:n_samples]
                channel_events.append(waveform)
        all_events.append(channel_events)

    for idx in range(num_channels):
        if all_events[idx]:
            print(f'Canal {physical_channel_from_position(idx)}, événements : {len(all_events[idx])}')

            try:
                all_min_values = [min(event) for event in all_events[idx] if event]
                all_max_values = [max(event) for event in all_events[idx] if event]

                channel_min = min(all_min_values)
                channel_max = max(all_max_values)

                # Moyenne des formes d'onde (si tu veux l'utiliser plus tard)
                avg_waveform = np.zeros(n_samples)
                valid_events = 0

                for event in all_events[idx]:
                    if len(event) == n_samples:
                        avg_waveform += np.array(event)
                        valid_events += 1

                if valid_events > 0:
                    avg_waveform /= valid_events

                y_margin = (channel_max - channel_min) * 0.05
                y_min = channel_min - y_margin - 1000
                y_max = channel_max + y_margin + 1000

                # Tracé de tous les événements du canal
                for j, event in enumerate(all_events[idx]):
                    if len(event) == len(x):
                        axs[idx].plot(x, event, alpha=0.2, linewidth=0.8)

                info_text = (f"Événements: {len(all_events[idx])}\n"
                             f"Min global: {channel_min:.1f}\n"
                             f"Max global: {channel_max:.1f}\n"
                             f"Points affichés: {n_samples}")

                axs[idx].text(0.02, 0.97, info_text, transform=axs[idx].transAxes,
                              verticalalignment='top', horizontalalignment='left',
                              bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

                axs[idx].set_title(f'Canal {physical_channel_from_position(idx)}')
                axs[idx].set_xlabel('Point d\'échantillonnage (x)')
                axs[idx].set_ylabel('Valeur ADC (y)')
                axs[idx].set_ylim(y_min, y_max)
                axs[idx].grid(True, linestyle='--', alpha=0.4)

            except (ValueError, TypeError) as e:
                print(f"Erreur lors du tracé du canal {idx}: {e}")
                axs[idx].set_title(f'Canal {physical_channel_from_position(idx)} (données manquantes)')
                axs[idx].set_xlabel('Point d\'échantillonnage')
                axs[idx].set_ylabel('Valeur ADC')
                axs[idx].set_ylim(-10000, 10000)
                axs[idx].grid(True, linestyle='--', alpha=0.4)

    plt.tight_layout()
    return fig



def event_time_base_ms(evt):
    absolute = evt.get("absolute_timestamp_ms")
    if absolute is not None:
        return float(absolute)
    return float(evt["timestamp_ms"])


def _prepare_detection_events_for_plot(detection_events):
    valid_events = [
        evt for evt in detection_events
        if evt.get("timestamp_ms") is not None
    ]
    valid_events.sort(key=event_time_base_ms)

    if not valid_events:
        return [], []

    t0_base_ms = event_time_base_ms(valid_events[0])
    cumulative = {name: 0 for name in DETECTORS}
    event_times_s = []

    for evt in valid_events:
        t_s = (event_time_base_ms(evt) - t0_base_ms) / 1000.0
        evt["_plot_time_s"] = t_s

        for detector_name in DETECTORS:
            if evt.get("hits", {}).get(detector_name, False):
                cumulative[detector_name] += 1

        evt["_cumulative_counts"] = dict(cumulative)
        event_times_s.append(t_s)

    return valid_events, event_times_s


def create_detection_count_plot(detection_events, filename, calibration=None):
    """
    Nombre total cumulé de coups en fonction du temps.

    Avec calibration, le hover affiche également l'ADC analogique et l'énergie
    reconstruite du/des détecteur(s) ayant déclenché sur l'événement.
    """
    fig, ax = plt.subplots(1, 1, figsize=(13, 7))
    fig.canvas.manager.set_window_title(f'Detection counts - {filename}')

    valid_events, event_times_s = _prepare_detection_events_for_plot(
        detection_events
    )

    active_detectors = active_detectors_from_events(valid_events)

    if not valid_events:
        ax.text(
            0.5, 0.5,
            "Aucun événement/timestamp valide pour le comptage.",
            ha="center", va="center",
            transform=ax.transAxes
        )
        ax.set_xlabel("Temps (s)")
        ax.set_ylabel("Nombre cumulé de coups")
        return fig

    t_end_s = max(0.0, event_times_s[-1])
    summary_lines = []

    for detector_name in active_detectors:
        hit_times_s = [
            evt["_plot_time_s"]
            for evt in valid_events
            if evt.get("hits", {}).get(detector_name, False)
        ]

        final_count = len(hit_times_s)
        summary_lines.append(f"{detector_name}: {final_count} coups")

        if hit_times_s:
            x = [0.0] + hit_times_s
            y = [0] + list(range(1, final_count + 1))
            ax.step(
                x, y,
                where="post",
                linewidth=1.6,
                label=f"{detector_name} ({final_count})"
            )
        else:
            ax.plot(
                [0.0, t_end_s if t_end_s > 0 else 1.0],
                [0, 0],
                linewidth=1.2,
                label=f"{detector_name} (0)"
            )

    calib_text = ""
    if calibration is not None:
        calib_text = f"\nCalibration: {calibration.path.name}"

    ax.set_title(
        f"Nombre cumulé de coups en fonction du temps - {filename}\n"
        f"1 échelon montant du discriminateur = 1 coup{calib_text}"
    )
    ax.set_xlabel(
        "Temps depuis le premier événement (s) — déplacer la souris pour voir le timestamp"
    )
    ax.set_ylabel("Nombre cumulé de coups")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend()

    ax.text(
        0.02,
        0.98,
        "\n".join(summary_lines),
        transform=ax.transAxes,
        ha="left",
        va="top",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85)
    )

    hover_line = ax.axvline(
        0.0,
        linestyle=":",
        linewidth=1.0,
        alpha=0.7,
        visible=False
    )

    hover_annotation = ax.annotate(
        "",
        xy=(0, 0),
        xytext=(14, 14),
        textcoords="offset points",
        ha="left",
        va="bottom",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.95),
        arrowprops=dict(arrowstyle="->", alpha=0.6),
        visible=False,
        zorder=20,
    )

    def nearest_event_index(x_s):
        if not event_times_s:
            return None

        pos = bisect_left(event_times_s, x_s)
        if pos <= 0:
            return 0
        if pos >= len(event_times_s):
            return len(event_times_s) - 1

        before = pos - 1
        after = pos
        if abs(event_times_s[after] - x_s) < abs(x_s - event_times_s[before]):
            return after
        return before

    def detector_hover_line(evt, detector_name):
        count = evt.get("_cumulative_counts", {}).get(detector_name, 0)
        hit = evt.get("hits", {}).get(detector_name, False)

        if not hit:
            return f"{detector_name} = {count}"

        energy_info = evt.get("energies", {}).get(detector_name)
        adc = evt.get("adc_values", {}).get(detector_name)

        if energy_info is None or energy_info.get("energy_MeV") is None:
            if adc is None:
                return f"{detector_name} = {count}  [HIT]"
            return f"{detector_name} = {count}  [HIT, ADC={adc:.3f}]"

        return (
            f"{detector_name} = {count}  "
            f"[HIT, ADC={energy_info['adc']:.3f}, "
            f"E={energy_info['energy_MeV']:.6f} MeV, "
            f"classe={energy_info['class_label']}]"
        )

    def on_mouse_move(mouse_event):
        if mouse_event.inaxes != ax or mouse_event.xdata is None:
            if hover_annotation.get_visible() or hover_line.get_visible():
                hover_annotation.set_visible(False)
                hover_line.set_visible(False)
                fig.canvas.draw_idle()
            return

        idx_evt = nearest_event_index(float(mouse_event.xdata))
        if idx_evt is None:
            return

        evt = valid_events[idx_evt]
        x_evt = evt["_plot_time_s"]

        y0, y1 = ax.get_ylim()
        y_evt = y0 + 0.82 * (y1 - y0)

        raw_timestamp = evt.get("timestamp_ms")
        raw_timestamp_text = (
            "--" if raw_timestamp is None
            else str(int(round(float(raw_timestamp))))
        )

        info_lines = [
            f"Event #{evt.get('event_number', '--')}",
            f"t - t0 = {x_evt:.3f} s",
            f"Timestamp = {raw_timestamp_text} ms",
            f"{evt.get('timestamp_label', '--')}",
        ]

        for detector_name in active_detectors:
            info_lines.append(detector_hover_line(evt, detector_name))

        hover_line.set_xdata([x_evt, x_evt])
        hover_line.set_visible(True)

        hover_annotation.xy = (x_evt, y_evt)
        hover_annotation.set_text("\n".join(info_lines))

        xmin, xmax = ax.get_xlim()
        if xmax > xmin and x_evt > xmin + 0.65 * (xmax - xmin):
            hover_annotation.set_position((-14, 14))
            hover_annotation.set_ha("right")
        else:
            hover_annotation.set_position((14, 14))
            hover_annotation.set_ha("left")

        hover_annotation.set_visible(True)
        fig.canvas.draw_idle()

    callback_id = fig.canvas.mpl_connect(
        "motion_notify_event",
        on_mouse_move
    )

    fig._timestamp_hover_callback = on_mouse_move
    fig._timestamp_hover_callback_id = callback_id
    fig._timestamp_hover_annotation = hover_annotation
    fig._timestamp_hover_line = hover_line

    plt.tight_layout()
    return fig





def create_energy_threshold_count_plot(
    detection_events,
    calibration,
    filename
):
    """
    Courbe de comptage cumulée avec filtre énergie optionnel.

    HUD volontairement minimal :
      - un seul bloc compact en haut à gauche ;
      - légende en haut à droite ;
      - aucun panneau d'aide dans le graphe ;
      - checkbox + slider séparés proprement sous le graphe.
    """
    if calibration is None:
        return None

    valid_events, event_times_s = _prepare_detection_events_for_plot(
        detection_events
    )

    active_detectors = active_detectors_from_events(valid_events)

    if not valid_events:
        return None

    apply_energy_calibration(valid_events, calibration)

    fig, ax = plt.subplots(1, 1, figsize=(14, 8))
    fig.canvas.manager.set_window_title(
        f'Energy discriminator - {filename}'
    )

    # Laisse une vraie zone dédiée aux contrôles, sans empiéter sur le graphe.
    plt.subplots_adjust(
        left=0.075,
        right=0.975,
        top=0.88,
        bottom=0.18
    )

    t_end_s = max(event_times_s) if event_times_s else 0.0

    e_min = float(np.min(calibration.energy_mev))
    e_max = float(np.max(calibration.energy_mev))

    if e_max <= e_min:
        e_max = e_min + 1e-6

    initial_threshold = e_min

    lines = {}

    for detector_name in active_detectors:
        line, = ax.step(
            [0.0, t_end_s if t_end_s > 0 else 1.0],
            [0, 0],
            where="post",
            linewidth=1.8,
            label=detector_name
        )
        lines[detector_name] = line

    ax.set_xlabel(
        "Temps depuis le premier événement (s)"
    )
    ax.set_ylabel(
        "Nombre cumulé de coups"
    )
    ax.grid(True, linestyle="--", alpha=0.35)

    # Légende simple, seule à droite.
    ax.legend(
        loc="upper right",
        framealpha=0.90
    )

    # ------------------------------------------------------------------
    # HUD UNIQUE ET COMPACT
    # ------------------------------------------------------------------
    hud_text = ax.text(
        0.015,
        0.975,
        "",
        transform=ax.transAxes,
        ha="left",
        va="top",
        family="monospace",
        fontsize=9.5,
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor="white",
            alpha=0.88
        ),
        zorder=15
    )

    # État du déplacement manuel du HUD.
    # Le HUD reste en coordonnées de l'axe (0..1), donc sa position suit
    # correctement les redimensionnements/zooms de la fenêtre.
    hud_drag = {
        "active": False,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }

    overlay_visibility = {
        "hud": False,
        "legend": True,
        "hover": True,
    }

    hud_text.set_visible(
        overlay_visibility["hud"]
    )

    accepted_cumulative = {
        detector_name: np.zeros(
            len(valid_events),
            dtype=int
        )
        for detector_name in active_detectors
    }

    raw_hit_totals = {
        detector_name: sum(
            1
            for evt in valid_events
            if evt.get("hits", {}).get(
                detector_name,
                False
            )
        )
        for detector_name in active_detectors
    }

    current_threshold = {
        "value": initial_threshold
    }

    energy_filter_enabled = {
        "value": False
    }

    trend_enabled = {
        "value": False
    }

    # Une ligne de tendance par détecteur actif.
    # Même couleur que le compteur, mais en pointillés.
    trend_lines = {}
    trend_stats = {}

    for detector_name in active_detectors:
        trend_line, = ax.plot(
            [],
            [],
            linestyle="--",
            linewidth=1.6,
            alpha=0.85,
            color=lines[detector_name].get_color(),
            visible=False,
            label=f"Tendance {detector_name}"
        )
        trend_lines[detector_name] = trend_line
        trend_stats[detector_name] = None

    def linear_trend(times, cumulative):
        """
        Régression linéaire N(t) = a*t + b.

        Retourne (a, b, R²) ou None si le fit est impossible.
        a est en coups/s.
        """
        x = np.asarray(times, dtype=float)
        y = np.asarray(cumulative, dtype=float)

        mask = np.isfinite(x) & np.isfinite(y)
        x = x[mask]
        y = y[mask]

        if len(x) < 2 or np.ptp(x) <= 0:
            return None

        a, b = np.polyfit(x, y, 1)
        y_fit = a * x + b

        ss_res = float(np.sum((y - y_fit) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))

        if ss_tot > 0:
            r2 = 1.0 - ss_res / ss_tot
        else:
            r2 = float("nan")

        return float(a), float(b), float(r2)

    def refresh_legend():
        """
        Légende indépendante du HUD.
        """
        legend = ax.get_legend()

        if not overlay_visibility["legend"]:
            if legend is not None:
                legend.set_visible(False)
            return

        handles = [lines[name] for name in active_detectors]

        if trend_enabled["value"]:
            handles += [
                trend_lines[name]
                for name in active_detectors
                if trend_lines[name].get_visible()
            ]

        legend = ax.legend(
            handles=handles,
            loc="upper right",
            framealpha=0.90,
            fontsize=9
        )
        legend.set_visible(True)

    def event_passes(
        evt,
        detector_name,
        threshold_mev
    ):
        if not evt.get("hits", {}).get(
            detector_name,
            False
        ):
            return False

        # Mode de base :
        # tout front discriminateur est compté.
        if not energy_filter_enabled["value"]:
            return True

        info = evt.get(
            "energies",
            {}
        ).get(detector_name)

        if not info:
            return False

        energy = info.get(
            "energy_MeV"
        )

        if (
            energy is None
            or not np.isfinite(energy)
        ):
            return False

        return (
            float(energy)
            >= float(threshold_mev)
        )

    def update_curves(
        threshold_mev
    ):
        current_threshold["value"] = float(
            threshold_mev
        )

        final_counts = {}
        max_count = 0

        for detector_name in active_detectors:

            accepted_flags = np.asarray([
                event_passes(
                    evt,
                    detector_name,
                    threshold_mev
                )
                for evt in valid_events
            ], dtype=int)

            cumulative = np.cumsum(
                accepted_flags
            )

            accepted_cumulative[
                detector_name
            ] = cumulative

            hit_times = [
                evt["_plot_time_s"]
                for evt, accepted in zip(
                    valid_events,
                    accepted_flags
                )
                if accepted
            ]

            final_count = (
                int(cumulative[-1])
                if len(cumulative)
                else 0
            )

            final_counts[
                detector_name
            ] = final_count

            max_count = max(
                max_count,
                final_count
            )

            if hit_times:
                x = [0.0] + hit_times
                y = [0] + list(
                    range(
                        1,
                        final_count + 1
                    )
                )

                if t_end_s > x[-1]:
                    x.append(t_end_s)
                    y.append(final_count)

            else:
                x = [
                    0.0,
                    t_end_s
                    if t_end_s > 0
                    else 1.0
                ]
                y = [0, 0]

            lines[
                detector_name
            ].set_data(
                x,
                y
            )

            # ----------------------------------------------------------
            # Tendance linéaire du compteur réellement affiché.
            # On fitte N cumulatif aux timestamps de TOUS les événements,
            # ce qui conserve aussi les plateaux sans coup.
            # ----------------------------------------------------------
            trend = linear_trend(
                event_times_s,
                cumulative
            )
            trend_stats[detector_name] = trend

            trend_line = trend_lines[detector_name]

            if trend_enabled["value"] and trend is not None:
                a, b, r2 = trend

                x_fit = np.asarray(
                    [0.0, t_end_s if t_end_s > 0 else 1.0],
                    dtype=float
                )
                y_fit = a * x_fit + b

                trend_line.set_data(
                    x_fit,
                    y_fit
                )
                trend_line.set_visible(True)

                if np.isfinite(r2):
                    r2_text = f"{r2:.4f}"
                else:
                    r2_text = "—"

                trend_line.set_label(
                    f"{detector_name} fit: "
                    f"N={a:.6g}·t{b:+.3f}  "
                    f"R²={r2_text}"
                )
            else:
                trend_line.set_visible(False)

        if energy_filter_enabled["value"]:

            adc_threshold = calibration.adc_for_energy(
                threshold_mev
            )

            if adc_threshold is None:
                adc_short = "--"
            else:
                adc_short = (
                    f"{adc_threshold:.1f}"
                )

            mode_line = (
                f"MODE : ÉNERGIE ON   "
                f"E ≥ {threshold_mev:.6f} MeV   "
                f"ADC ≈ {adc_short}"
            )

            ax.set_title(
                f"Comptage cumulé avec discrimination en énergie — {filename}",
                fontsize=15
            )

        else:

            mode_line = (
                "MODE : BASE   "
                "Tous les coups discriminateur sont comptés"
            )

            ax.set_title(
                f"Comptage cumulé — {filename}",
                fontsize=15
            )

        # Une seule ligne par détecteur : très compact.
        stats = []

        for detector_name in active_detectors:

            accepted = final_counts.get(
                detector_name,
                0
            )

            total = raw_hit_totals[
                detector_name
            ]

            stats.append(
                f"{detector_name}: {accepted}/{total}"
            )

        hud_lines = [
            mode_line,
            "   |   ".join(stats)
        ]

        if trend_enabled["value"]:
            fit_parts = []

            for detector_name in active_detectors:
                trend = trend_stats.get(detector_name)

                if trend is None:
                    fit_parts.append(
                        f"{detector_name}: fit —"
                    )
                    continue

                a, b, r2 = trend
                if np.isfinite(r2):
                    r2_text = f"{r2:.3f}"
                else:
                    r2_text = "—"

                fit_parts.append(
                    f"{detector_name}: "
                    f"a={a:.6g} cps, "
                    f"b={b:.2f}, "
                    f"R²={r2_text}"
                )

            hud_lines.append(
                "TENDANCES : " + "   |   ".join(fit_parts)
            )

        hud_text.set_text(
            "\n".join(hud_lines)
        )
        hud_text.set_visible(
            overlay_visibility["hud"]
        )

        refresh_legend()

        ax.relim()
        ax.autoscale_view(
            scalex=False,
            scaley=True
        )

        ax.set_ylim(
            -0.5,
            max(
                1.0,
                max_count * 1.08 + 0.5
            )
        )

        fig.canvas.draw_idle()

    # ------------------------------------------------------------------
    # CONTRÔLES : 1 ligne PROPRE sous le graphe
    # ------------------------------------------------------------------

    # Contrôles d'affichage / calcul.
    # Le HUD est volontairement OFF par défaut.
    checkbox_ax = fig.add_axes(
        [0.045, 0.018, 0.235, 0.13]
    )

    options_checkbox = CheckButtons(
        checkbox_ax,
        [
            "Filtre énergie",
            "Tendances ax+b",
            "Afficher HUD",
            "Afficher légende",
            "Afficher survol",
        ],
        [
            False,
            False,
            False,
            True,
            True,
        ]
    )

    checkbox_ax.set_xticks([])
    checkbox_ax.set_yticks([])

    # Alias conservé.
    energy_checkbox = options_checkbox

    # Libellé du slider séparé pour éviter tout chevauchement.
    fig.text(
        0.33,
        0.083,
        "Seuil énergie",
        ha="right",
        va="center",
        fontsize=10
    )

    slider_ax = fig.add_axes(
        [0.35, 0.070, 0.49, 0.028]
    )

    energy_slider = Slider(
        ax=slider_ax,
        label="",
        valmin=e_min,
        valmax=e_max,
        valinit=initial_threshold,
        valfmt="%.6f MeV",
    )

    # Valeur numérique à droite du slider.
    slider_value_text = fig.text(
        0.87,
        0.083,
        f"{initial_threshold:.6f} MeV",
        ha="left",
        va="center",
        fontsize=10
    )

    # On masque le valtext intégré du slider
    # pour éviter un second texte qui se superpose.
    try:
        energy_slider.valtext.set_visible(False)
    except Exception:
        pass

    energy_slider.set_active(False)

    def update_slider_visual_state():

        enabled = energy_filter_enabled[
            "value"
        ]

        energy_slider.set_active(
            enabled
        )

        alpha = (
            1.0
            if enabled
            else 0.30
        )

        for artist_name in (
            "track",
            "poly",
            "vline"
        ):
            try:
                getattr(
                    energy_slider,
                    artist_name
                ).set_alpha(alpha)
            except Exception:
                pass

        slider_value_text.set_alpha(
            alpha
        )

    def on_slider_change(
        value
    ):
        slider_value_text.set_text(
            f"{value:.6f} MeV"
        )

        update_curves(
            value
        )

    def on_option_checkbox(
        label
    ):
        if label == "Filtre énergie":
            energy_filter_enabled["value"] = (
                not energy_filter_enabled["value"]
            )
            update_slider_visual_state()

        elif label == "Tendances ax+b":
            trend_enabled["value"] = (
                not trend_enabled["value"]
            )

        elif label == "Afficher HUD":
            overlay_visibility["hud"] = (
                not overlay_visibility["hud"]
            )
            hud_text.set_visible(
                overlay_visibility["hud"]
            )

        elif label == "Afficher légende":
            overlay_visibility["legend"] = (
                not overlay_visibility["legend"]
            )

        elif label == "Afficher survol":
            overlay_visibility["hover"] = (
                not overlay_visibility["hover"]
            )

            if not overlay_visibility["hover"]:
                hover_annotation.set_visible(False)
                hover_line.set_visible(False)

        update_curves(
            energy_slider.val
        )

    options_checkbox.on_clicked(
        on_option_checkbox
    )

    energy_slider.on_changed(
        on_slider_change
    )

    update_slider_visual_state()

    # ------------------------------------------------------------------
    # HOVER : PLUS PETIT
    # ------------------------------------------------------------------
    hover_line = ax.axvline(
        0.0,
        linestyle=":",
        linewidth=1.0,
        alpha=0.65,
        visible=False
    )

    hover_annotation = ax.annotate(
        "",
        xy=(0, 0),
        xytext=(12, 12),
        textcoords="offset points",
        ha="left",
        va="bottom",
        family="monospace",
        fontsize=8.5,
        bbox=dict(
            boxstyle="round,pad=0.30",
            facecolor="white",
            alpha=0.94
        ),
        visible=False,
        zorder=20,
    )

    def nearest_event_index(
        x_s
    ):
        if not event_times_s:
            return None

        pos = bisect_left(
            event_times_s,
            x_s
        )

        if pos <= 0:
            return 0

        if pos >= len(
            event_times_s
        ):
            return (
                len(event_times_s)
                - 1
            )

        before = pos - 1
        after = pos

        if (
            abs(
                event_times_s[after]
                - x_s
            )
            <
            abs(
                x_s
                - event_times_s[
                    before
                ]
            )
        ):
            return after

        return before

    def short_detector_line(
        evt,
        idx_evt,
        detector_name
    ):
        hit = evt.get(
            "hits",
            {}
        ).get(
            detector_name,
            False
        )

        count = int(
            accepted_cumulative[
                detector_name
            ][idx_evt]
        )

        if not hit:
            return (
                f"{detector_name}: — "
                f"| N={count}"
            )

        info = evt.get(
            "energies",
            {}
        ).get(
            detector_name
        )

        if not info:
            return (
                f"{detector_name}: HIT "
                f"| N={count}"
            )

        adc = info.get("adc")
        energy = info.get(
            "energy_MeV"
        )

        if (
            energy is None
            or not np.isfinite(energy)
        ):
            return (
                f"{detector_name}: HIT "
                f"| ADC={adc:.1f} "
                f"| E=-- "
                f"| N={count}"
            )

        if energy_filter_enabled[
            "value"
        ]:
            state = (
                "OK"
                if energy
                >= current_threshold[
                    "value"
                ]
                else "REJET"
            )
        else:
            state = "OK"

        return (
            f"{detector_name}: HIT "
            f"| ADC={adc:.1f} "
            f"| E={energy:.4f} MeV "
            f"| {state} "
            f"| N={count}"
        )

    def hud_contains_event(mouse_event):
        """True si le clic souris est à l'intérieur du rectangle du HUD."""
        if mouse_event.x is None or mouse_event.y is None:
            return False

        try:
            renderer = fig.canvas.get_renderer()
            bbox = hud_text.get_window_extent(renderer=renderer)
            return bbox.contains(mouse_event.x, mouse_event.y)
        except Exception:
            return False

    def on_mouse_press(mouse_event):
        # Pas de drag si le HUD est masqué.
        if not overlay_visibility["hud"]:
            return

        if mouse_event.button != 1 or mouse_event.inaxes != ax:
            return

        if not hud_contains_event(mouse_event):
            return

        # Conversion de la position souris en coordonnées normalisées de l'axe.
        mouse_axes = ax.transAxes.inverted().transform(
            (mouse_event.x, mouse_event.y)
        )
        hud_x, hud_y = hud_text.get_position()

        hud_drag["active"] = True
        hud_drag["offset_x"] = float(hud_x - mouse_axes[0])
        hud_drag["offset_y"] = float(hud_y - mouse_axes[1])

        # Pendant le déplacement, cacher l'info-bulle de survol pour éviter
        # qu'elle ne gêne la manipulation du HUD.
        hover_annotation.set_visible(False)
        hover_line.set_visible(False)
        fig.canvas.draw_idle()

    def on_mouse_release(mouse_event):
        if mouse_event.button == 1 and hud_drag["active"]:
            hud_drag["active"] = False
            fig.canvas.draw_idle()

    def on_mouse_move(
        mouse_event
    ):
        # Si le survol est masqué et qu'on ne déplace pas le HUD, ne rien faire.
        if (
            not overlay_visibility["hover"]
            and not hud_drag["active"]
        ):
            return

        # Si le HUD est en cours de drag, on déplace le bloc et on ne fait
        # pas le traitement de survol classique.
        if hud_drag["active"]:
            if mouse_event.x is None or mouse_event.y is None:
                return

            mouse_axes = ax.transAxes.inverted().transform(
                (mouse_event.x, mouse_event.y)
            )

            new_x = float(mouse_axes[0] + hud_drag["offset_x"])
            new_y = float(mouse_axes[1] + hud_drag["offset_y"])

            # Garder le point d'ancrage du HUD dans la zone du graphique.
            # On autorise presque toute la surface, tout en évitant de le perdre
            # complètement hors fenêtre.
            new_x = max(0.005, min(0.97, new_x))
            new_y = max(0.03, min(0.995, new_y))

            hud_text.set_position((new_x, new_y))
            fig.canvas.draw_idle()
            return

        if (
            mouse_event.inaxes != ax
            or mouse_event.xdata is None
        ):
            if (
                hover_annotation.get_visible()
                or hover_line.get_visible()
            ):
                hover_annotation.set_visible(
                    False
                )
                hover_line.set_visible(
                    False
                )
                fig.canvas.draw_idle()

            return

        idx_evt = nearest_event_index(
            float(
                mouse_event.xdata
            )
        )

        if idx_evt is None:
            return

        evt = valid_events[
            idx_evt
        ]

        x_evt = evt[
            "_plot_time_s"
        ]

        raw_timestamp = evt.get(
            "timestamp_ms"
        )

        raw_timestamp_text = (
            "--"
            if raw_timestamp is None
            else str(
                int(
                    round(
                        float(
                            raw_timestamp
                        )
                    )
                )
            )
        )

        info_lines = [
            (
                f"Event #{evt.get('event_number', '--')}   "
                f"t={x_evt:.3f}s"
            ),
            (
                f"{evt.get('timestamp_label', '--')}   "
                f"[{raw_timestamp_text} ms]"
            ),
        ]

        if energy_filter_enabled[
            "value"
        ]:
            info_lines.append(
                f"Seuil : {current_threshold['value']:.6f} MeV"
            )

        info_lines.append(
            "-" * 52
        )

        for detector_name in active_detectors:
            info_lines.append(
                short_detector_line(
                    evt,
                    idx_evt,
                    detector_name
                )
            )

        y0, y1 = ax.get_ylim()

        y_evt = (
            y0
            + 0.72
            * (y1 - y0)
        )

        hover_line.set_xdata([
            x_evt,
            x_evt
        ])

        hover_line.set_visible(
            True
        )

        hover_annotation.xy = (
            x_evt,
            y_evt
        )

        hover_annotation.set_text(
            "\n".join(
                info_lines
            )
        )

        xmin, xmax = ax.get_xlim()

        if (
            xmax > xmin
            and x_evt
            >
            xmin
            + 0.62
            * (xmax - xmin)
        ):
            hover_annotation.set_position(
                (-12, 12)
            )
            hover_annotation.set_ha(
                "right"
            )
        else:
            hover_annotation.set_position(
                (12, 12)
            )
            hover_annotation.set_ha(
                "left"
            )

        hover_annotation.set_visible(
            True
        )

        fig.canvas.draw_idle()

    callback_id = fig.canvas.mpl_connect(
        "motion_notify_event",
        on_mouse_move
    )
    hud_press_callback_id = fig.canvas.mpl_connect(
        "button_press_event",
        on_mouse_press
    )
    hud_release_callback_id = fig.canvas.mpl_connect(
        "button_release_event",
        on_mouse_release
    )

    update_curves(
        initial_threshold
    )

    fig._energy_checkbox = energy_checkbox
    fig._options_checkbox = options_checkbox
    fig._energy_checkbox_ax = checkbox_ax
    fig._energy_filter_enabled = energy_filter_enabled
    fig._trend_enabled = trend_enabled
    fig._trend_lines = trend_lines
    fig._trend_stats = trend_stats
    fig._overlay_visibility = overlay_visibility
    fig._energy_slider = energy_slider
    fig._energy_slider_ax = slider_ax
    fig._energy_slider_value_text = slider_value_text
    fig._energy_hover_callback = on_mouse_move
    fig._energy_hover_callback_id = callback_id
    fig._hud_text = hud_text
    fig._hud_drag = hud_drag
    fig._hud_press_callback = on_mouse_press
    fig._hud_press_callback_id = hud_press_callback_id
    fig._hud_release_callback = on_mouse_release
    fig._hud_release_callback_id = hud_release_callback_id
    fig._energy_hover_annotation = hover_annotation
    fig._energy_hover_line = hover_line
    fig._energy_accepted_cumulative = accepted_cumulative

    return fig

def create_energy_resolved_count_plots(
    detection_events,
    calibration,
    filename
):
    """
    Crée une figure séparée pour chaque détecteur.

    Chaque courbe = nombre cumulé de coups appartenant à UNE classe d'énergie.
    Les classes sont directement dérivées des lignes du fichier de calibration.
    Un événement n'entre dans une classe que si son discriminateur a déclenché.
    """
    if calibration is None:
        return []

    valid_events, event_times_s = _prepare_detection_events_for_plot(
        detection_events
    )
    if not valid_events:
        return []

    t_end_s = max(0.0, event_times_s[-1])
    figures = []

    for detector_name in DETECTORS:
        fig, ax = plt.subplots(1, 1, figsize=(13, 7))
        fig.canvas.manager.set_window_title(
            f'Energy-resolved counts - {detector_name} - {filename}'
        )

        hits = []
        out_of_range = 0

        for evt in valid_events:
            if not evt.get("hits", {}).get(detector_name, False):
                continue

            energy_info = evt.get("energies", {}).get(detector_name)

            if (
                energy_info is None
                or energy_info.get("class_index") is None
            ):
                out_of_range += 1
                continue

            hits.append({
                "event": evt,
                "time_s": evt["_plot_time_s"],
                "class_index": energy_info["class_index"],
                "class_label": energy_info["class_label"],
                "energy_MeV": energy_info["energy_MeV"],
                "adc": energy_info["adc"],
            })

        class_indices = sorted({
            hit["class_index"]
            for hit in hits
        })

        class_counts = {}

        for class_index in class_indices:
            class_hits = [
                hit for hit in hits
                if hit["class_index"] == class_index
            ]

            hit_times = [
                hit["time_s"]
                for hit in class_hits
            ]

            final_count = len(hit_times)
            class_counts[class_index] = final_count

            label = (
                f"{calibration.energy_mev[class_index]:.6f} MeV "
                f"({final_count})"
            )

            ax.step(
                [0.0] + hit_times,
                [0] + list(range(1, final_count + 1)),
                where="post",
                linewidth=1.4,
                label=label,
            )

        if not class_indices:
            ax.text(
                0.5, 0.5,
                "Aucun coup dans la plage de calibration.",
                ha="center",
                va="center",
                transform=ax.transAxes
            )

        ax.set_title(
            f"{detector_name} — nombre cumulé de coups par énergie\n"
            f"{filename}"
        )
        ax.set_xlabel(
            "Temps depuis le premier événement (s) — survol = timestamp / ADC / énergie"
        )
        ax.set_ylabel("Nombre cumulé de coups")
        ax.grid(True, linestyle="--", alpha=0.4)

        if class_indices:
            ax.legend(
                title="Classe énergie",
                fontsize=8,
                ncols=2
            )

        total_hits = sum(class_counts.values())
        summary = (
            f"Coups classés: {total_hits}\n"
            f"Hors plage calibration: {out_of_range}\n"
            f"ADC calibration: {calibration.adc_min:.3f} → {calibration.adc_max:.3f}\n"
            f"E calibration: {calibration.energy_mev[0]:.6f} → "
            f"{calibration.energy_mev[-1]:.6f} MeV"
        )

        ax.text(
            0.02,
            0.98,
            summary,
            transform=ax.transAxes,
            ha="left",
            va="top",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.85)
        )

        # Hover sur l'événement déclenché le plus proche pour CE détecteur.
        hit_times_all = [hit["time_s"] for hit in hits]

        hover_line = ax.axvline(
            0.0,
            linestyle=":",
            linewidth=1.0,
            alpha=0.7,
            visible=False
        )

        hover_annotation = ax.annotate(
            "",
            xy=(0, 0),
            xytext=(14, 14),
            textcoords="offset points",
            ha="left",
            va="bottom",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.95),
            arrowprops=dict(arrowstyle="->", alpha=0.6),
            visible=False,
            zorder=20,
        )

        def nearest_hit_index(x_s, _times=hit_times_all):
            if not _times:
                return None

            pos = bisect_left(_times, x_s)
            if pos <= 0:
                return 0
            if pos >= len(_times):
                return len(_times) - 1

            before = pos - 1
            after = pos
            if abs(_times[after] - x_s) < abs(x_s - _times[before]):
                return after
            return before

        def on_mouse_move(
            mouse_event,
            _ax=ax,
            _fig=fig,
            _hits=hits,
            _hover_line=hover_line,
            _annotation=hover_annotation,
            _nearest=nearest_hit_index,
            _detector=detector_name,
        ):
            if mouse_event.inaxes != _ax or mouse_event.xdata is None:
                if _annotation.get_visible() or _hover_line.get_visible():
                    _annotation.set_visible(False)
                    _hover_line.set_visible(False)
                    _fig.canvas.draw_idle()
                return

            idx_hit = _nearest(float(mouse_event.xdata))
            if idx_hit is None:
                return

            hit = _hits[idx_hit]
            evt = hit["event"]
            x_evt = hit["time_s"]

            raw_timestamp = evt.get("timestamp_ms")
            raw_timestamp_text = (
                "--" if raw_timestamp is None
                else str(int(round(float(raw_timestamp))))
            )

            info = (
                f"{_detector}\n"
                f"Event #{evt.get('event_number', '--')}\n"
                f"t - t0 = {x_evt:.3f} s\n"
                f"Timestamp = {raw_timestamp_text} ms\n"
                f"{evt.get('timestamp_label', '--')}\n"
                f"ADC = {hit['adc']:.3f}\n"
                f"E = {hit['energy_MeV']:.6f} MeV\n"
                f"Classe = {hit['class_label']}"
            )

            y0, y1 = _ax.get_ylim()
            y_evt = y0 + 0.82 * (y1 - y0)

            _hover_line.set_xdata([x_evt, x_evt])
            _hover_line.set_visible(True)
            _annotation.xy = (x_evt, y_evt)
            _annotation.set_text(info)

            xmin, xmax = _ax.get_xlim()
            if xmax > xmin and x_evt > xmin + 0.65 * (xmax - xmin):
                _annotation.set_position((-14, 14))
                _annotation.set_ha("right")
            else:
                _annotation.set_position((14, 14))
                _annotation.set_ha("left")

            _annotation.set_visible(True)
            _fig.canvas.draw_idle()

        callback_id = fig.canvas.mpl_connect(
            "motion_notify_event",
            on_mouse_move
        )

        fig._energy_hover_callback = on_mouse_move
        fig._energy_hover_callback_id = callback_id
        fig._energy_hover_annotation = hover_annotation
        fig._energy_hover_line = hover_line

        plt.tight_layout()
        figures.append(fig)

    return figures

def main():
    """Main program function"""
    base_dir = os.path.join(drct, 'binaryread')
    my_bins = 250

    while True:
        file_selector = FileSelector(base_dir)
        file_selector.create_window()

        if file_selector.selected_file is None:
            print("Exiting program...")
            break

        calibration = None

        if file_selector.calibration_file:
            try:
                calibration = EnergyCalibration(
                    file_selector.calibration_file
                )
                print(
                    f"Calibration loaded: {calibration.path}\n"
                    f"  {len(calibration.adc)} points\n"
                    f"  ADC amplitude {calibration.adc_min:.3f} -> {calibration.adc_max:.3f}\n"
                    f"  Energy {calibration.energy_mev[0]:.6f} -> "
                    f"{calibration.energy_mev[-1]:.6f} MeV"
                )

                if (
                    calibration.fit_a is not None
                    and calibration.fit_b is not None
                ):
                    print(
                        f"  Fit: E[eV] = {calibration.fit_a:.12g} * ADC "
                        f"+ {calibration.fit_b:.12g}"
                    )

            except Exception as e:
                print(f"ERROR loading energy calibration: {e}")
                calibration = None

        num_channels, event_minimums, successful_offset, raw_waveforms, detection_events = load_and_process_single_file(
            file_selector.selected_file,
            base_dir
        )

        if num_channels == 0 or not event_minimums:
            print("No valid data obtained. Try another file.")
            continue

        if calibration is not None:
            apply_energy_calibration(
                detection_events,
                calibration
            )

        print(f"Number of channels detected: {num_channels}")
        for i in range(num_channels):
            print(
                f"Channel {physical_channels_for_count(num_channels)[i] if i < len(physical_channels_for_count(num_channels)) else i}: "
                f"{len(event_minimums[i])} minimum values"
            )
            if event_minimums[i]:
                print(
                    f"  Example values: {event_minimums[i][:5]}"
                )

        formatted_waveforms = [[] for _ in range(num_channels)]

        if not raw_waveforms:
            print(
                "No raw waveform was stored. Cannot display waveforms."
            )
        else:
            print(
                f"Preparing {len(raw_waveforms)} waveforms for display"
            )

            for event_waveforms in raw_waveforms:
                for channel_idx in range(
                    min(num_channels, len(event_waveforms))
                ):
                    formatted_waveforms[channel_idx].append(
                        event_waveforms[channel_idx]
                    )

        fig_mins, interactive_fits_mins, count_histo = create_min_amplitude_histogram(
            event_minimums,
            file_selector.selected_file,
            n_bins=my_bins
        )

        fig_combined = create_combined_triggered_histogram(
            event_minimums,
            file_selector.selected_file,
            n_bins=my_bins
        )

        fig_waveform = create_waveform_display(
            formatted_waveforms,
            file_selector.selected_file,
            max_samples_to_plot=display_samples
        )

        fig_detection = create_detection_count_plot(
            detection_events,
            file_selector.selected_file,
            calibration=calibration
        )

        fig_energy_threshold = create_energy_threshold_count_plot(
            detection_events,
            calibration,
            file_selector.selected_file
        )

        # event_minimums contient un minimum par événement validé par son discri.
        # detection_events est utilisé pour les courbes de comptage et l'énergie.

        plt.ion()
        fig_mins.show()
        fig_combined.show()
        fig_waveform.show()
        fig_detection.show()

        if fig_energy_threshold is not None:
            fig_energy_threshold.show()

        plt.draw()

        print("Press Enter to continue (or close all windows)...")
        plt.ioff()
        plt.show(block=True)


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""
Author  : Djokhar BETELGUERIEV (Simplified)
Date    : 2025-03-18
Description : Simplified WaveCatcher data analysis program.
"""

import matplotlib.pyplot as plt
import numpy as np
import tkinter as tk
from tkinter import ttk
import os
import copy

# Constantes globales
drct = "C:/Program Files (x86)/WaveCatcher_64ch/Run_Data/"
samples = 1024          # nombre de samples réellement lus dans le fichier
display_samples = 1000  # nombre de samples à AFFICHER par événement (<= samples)

fixed_header = 0x186
# fixed_header = 0x17f
max_events_per_file = 100000
possible_offsets = [40,52, 56, 60, 64, 48, 68, 44, 72, 76, 80, 84, 88, 92]

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
    Returns (idx, trigger, amplitudes, NumberOfChannel, hit_counts, rates, current_timestamp, EventNumber, False) si succès,
    Returns (None, None, None, None, None, None, None, None, True) si fin de fichier naturelle
    """
    # Si l'index est au-delà de la fin du fichier ou très proche,
    # c'est probablement une fin de fichier naturelle
    if idx is None or idx >= len(rawdata) - 100:
        return (None, None, None, None, None, None, None, None, True)

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
                if test_number_of_channels is not None and 0 < test_number_of_channels <= 3:
                    # Vérifier si c'est cohérent avec le nombre de canaux attendu
                    if expected_channels is None or test_number_of_channels == expected_channels:
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
        if expected_channels is not None and NumberOfChannel != expected_channels:
            print(f"ALERTE: Nombre de canaux incohérent: attendu {expected_channels}, trouvé {NumberOfChannel}")

            # Essayons de trouver un meilleur index qui donne le bon nombre de canaux
            for test_idx_offset in range(-100, 100, 4):  # Essayer des décalages dans une plage de ±100 octets
                test_idx = idx + test_idx_offset
                if test_idx < 0 or test_idx >= len(rawdata) - 60:
                    continue

                test_number_of_channels = ret_4bytes(rawdata, test_idx + 48)

                if test_number_of_channels == expected_channels:
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
            if NumberOfChannel != expected_channels:
                print(f"ERREUR: Impossible de trouver un index cohérent pour le nombre de canaux attendu")
                return None

        # Validation des données essentielles
        if EventNumber is None or NumberOfChannel is None or NumberOfChannel <= 0:
            print(f"Erreur: Données d'en-tête incomplètes ou invalides à l'index 0x{idx:x}")
            return None

        if Day is None or Hour is None or Minute is None or Second is None or Millisecond is None:
            print(f"Erreur: Données de timestamp incomplètes à l'index 0x{idx:x}")
            return None

        # Calcul du timestamp
        current_timestamp = ((Day * 24 + Hour) * 3600 + Minute * 60 + Second) * 1000 + Millisecond
        print(
            f'EventNumber : {EventNumber}, {NumberOfChannel} channels, {current_timestamp} - {Day}/{Month}/{Year} - {Hour}:{Minute}:{Second}.{Millisecond} - {channel}')

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
        return idx, trigger, amplitudes, NumberOfChannel, hit_counts, rates, current_timestamp, EventNumber, False

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
        "raw_waveforms": []  # To store raw waveforms
    }

    # Try each offset until one works correctly
    for current_offset in possible_offsets:
        print(f"\n===== Trying with header_offset = {current_offset} bytes =====")

        num_channels = None
        event_minimums = []  # List to store minimums per event
        raw_waveforms = []  # To store raw waveforms
        current_idx = idx  # Reset start index
        previous_event_number = None  # To check event continuity
        sequence_error = False  # To detect sequence errors
        events_read = 0  # Event counter

        # Read all events from the file with this offset
        for i in range(max_events_per_file):
            # Use current offset without automatic detection
            readed_event = read_event_fullwave(data, current_idx, [], None, current_offset)

            if readed_event is None:
                # This is a read error (not a natural end of file)
                if i == 0:
                    print(f"Failed to read first event with header_offset = {current_offset}")
                else:
                    print(f"Read error after {events_read} events")
                sequence_error = True  # Mark as error to try next offset
                break

            # Check if it's a natural end of file
            if len(readed_event) == 9 and readed_event[8] is True:
                print(f"Natural end of file reached after {events_read} events")
                # If at least one event was read, it's a success
                if events_read > 0:
                    # Store successful offset
                    successful_offset = current_offset
                    print(f"\n*** Successful read with header_offset = {current_offset} ***")
                    print(f"Number of events read: {events_read}")
                    print("End of file reached naturally without errors. Stop testing offsets.")
                    return num_channels, event_minimums, successful_offset, raw_waveforms
                break

            # An event was successfully read
            events_read += 1

            # Use return structure with event number included (ignore last element which is end-of-file flag)
            current_idx, trigger, amplitudes, NumberOfChannel, hit_counts, rates, current_timestamp, EventNumber, _ = readed_event

            # Store raw waveforms for this event (make a copy)
            raw_waveforms.append(copy.deepcopy(amplitudes))

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

            # Calculate and store minimums for each channel of this event
            for o in range(min(num_channels, len(amplitudes))):
                if amplitudes[o]:
                    wf = amplitudes[o]

                    # nombre de points réellement utilisés pour cet event
                    if display_samples is None:
                        n = len(wf)  # on prend tout
                    else:
                        n = min(display_samples, len(wf))

                    if n > 0:
                        # min seulement sur les n premiers points (ex : 1000)
                        waveform_min = min(wf[:n])
                        event_minimums[o].append(waveform_min)

        # Update best attempt if this one read more events
        if num_channels is not None and events_read > best_attempt["events_read"]:
            best_attempt["offset"] = current_offset
            best_attempt["num_channels"] = num_channels
            best_attempt["event_minimums"] = event_minimums
            best_attempt["events_read"] = events_read
            best_attempt["raw_waveforms"] = raw_waveforms

    # If we get here, none of the offsets allowed to reach the end of file naturally without error
    print("\n===== No offset allowed a perfect read =====")

    # Use best attempt if available
    if best_attempt["num_channels"] > 0:
        print(
            f"Using best result: offset={best_attempt['offset']}, {best_attempt['events_read']} events read")
        return best_attempt["num_channels"], best_attempt["event_minimums"], best_attempt["offset"], best_attempt[
            "raw_waveforms"]

    print("ERROR: Failed to read with all possible offsets")
    return 0, [], None, []
class GaussianFitInteractor:
    """
    Interaction:
    - click sur une courbe => la sélectionne (mise en évidence)
    - click+drag sur l'axe X => définit [x0, x1]
    - release => fit gaussien sur la courbe sélectionnée, dans cette fenêtre
    """

    def __init__(self, fig, ax, curves_dict):
        self.fig = fig
        self.ax = ax
        self.curves = curves_dict  # ch -> {line, x, y}

        self.selected_ch = None
        self._press_x = None
        self._span = None  # patch axvspan pour feedback
        self._fit_lines = {}  # ch -> fitted line (artist)

        # Try to use scipy if available
        try:
            from scipy.optimize import curve_fit  # noqa
            self._has_scipy = True
        except Exception:
            self._has_scipy = False
            print("WARNING: scipy not available -> gaussian fit disabled (install scipy).")

        # Connect events
        self.cid_pick = fig.canvas.mpl_connect("pick_event", self.on_pick)
        self.cid_press = fig.canvas.mpl_connect("button_press_event", self.on_press)
        self.cid_motion = fig.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.cid_release = fig.canvas.mpl_connect("button_release_event", self.on_release)

    def on_pick(self, event):
        # Selection d'une courbe
        artist = event.artist
        for ch, d in self.curves.items():
            if d["line"] is artist:
                self.select_curve(ch)
                break

    def select_curve(self, ch):
        self.selected_ch = ch
        # reset style
        for c, d in self.curves.items():
            d["line"].set_linewidth(2.0)
            d["line"].set_alpha(0.60)
        # highlight selected
        self.curves[ch]["line"].set_linewidth(3.5)
        self.curves[ch]["line"].set_alpha(0.98)
        self.fig.canvas.draw_idle()
        print(f"Selected curve: Channel {ch}")

    def on_press(self, event):
        if event.inaxes != self.ax:
            return
        # bouton gauche uniquement
        if event.button != 1:
            return
        # on ne fait un fit que si une courbe est sélectionnée
        if self.selected_ch is None:
            return

        self._press_x = event.xdata
        if self._press_x is None:
            return

        # feedback span
        if self._span is not None:
            self._span.remove()
            self._span = None
        self._span = self.ax.axvspan(self._press_x, self._press_x, alpha=0.15)

        self.fig.canvas.draw_idle()

    def on_motion(self, event):
        if self._press_x is None or self._span is None:
            return
        if event.inaxes != self.ax:
            return
        if event.xdata is None:
            return

        x0 = self._press_x
        x1 = event.xdata
        # update span
        self._span.remove()
        self._span = self.ax.axvspan(min(x0, x1), max(x0, x1), alpha=0.15)
        self.fig.canvas.draw_idle()

    def on_release(self, event):
        if self._press_x is None:
            return
        if event.inaxes != self.ax:
            self._cleanup_span()
            return
        if event.button != 1:
            self._cleanup_span()
            return
        if self.selected_ch is None:
            self._cleanup_span()
            return
        if not self._has_scipy:
            print("Cannot fit: scipy not available.")
            self._cleanup_span()
            return
        if event.xdata is None:
            self._cleanup_span()
            return

        x0 = float(self._press_x)
        x1 = float(event.xdata)
        lo, hi = (min(x0, x1), max(x0, x1))

        self.fit_selected(lo, hi)
        self._cleanup_span()

    def _cleanup_span(self):
        self._press_x = None
        if self._span is not None:
            self._span.remove()
            self._span = None
        self.fig.canvas.draw_idle()

    def fit_selected(self, lo, hi):
        from scipy.optimize import curve_fit

        ch = self.selected_ch
        d = self.curves[ch]
        x = d["x"]
        y = d["y"]

        mask = (x >= lo) & (x <= hi)
        xf = x[mask]
        yf = y[mask]

        if xf.size < 6:
            print(f"Fit aborted: not enough points in window [{lo:.1f}, {hi:.1f}]")
            return

        # Initial guesses (robustes)
        C0 = float(np.min(yf))
        A0 = float(np.max(yf) - C0)
        mu0 = float(xf[np.argmax(yf)])
        # sigma guess ~ 1/6 of range
        sigma0 = float(max((hi - lo) / 6.0, 1e-6))

        try:
            popt, pcov = curve_fit(
                gaussian, xf, yf,
                p0=[A0, mu0, sigma0, C0],
                maxfev=20000
            )
            A, mu, sigma, C = popt
            print(f"[Ch {ch}] Fit: A={A:.4g}, mu={mu:.4g}, sigma={sigma:.4g}, C={C:.4g}  on [{lo:.1f},{hi:.1f}]")

            # Courbe fitte sur une grille fine
            xx = np.linspace(lo, hi, 400)
            yy = gaussian(xx, A, mu, sigma, C)

            # Supprimer fit précédent de ce channel si existe
            if ch in self._fit_lines and self._fit_lines[ch] is not None:
                try:
                    self._fit_lines[ch].remove()
                except Exception:
                    pass

            # même couleur que la courbe sélectionnée
            color = d["line"].get_color()
            # (fit_line,) = self.ax.plot(xx, yy, linestyle="--", linewidth=3.0, alpha=0.95)
            # fit_line.set_color(color)
            # self._fit_lines[ch] = fit_line
            (fit_line,) = self.ax.plot(xx, yy,
                                       linestyle="--",
                                       linewidth=3.0,
                                       alpha=0.95,
                                       color=color)

            self._fit_lines[ch] = fit_line

            # =========================
            # Affichage μ et σ
            # =========================

            # incertitudes (si covariance OK)
            try:
                perr = np.sqrt(np.diag(pcov))
                mu_err = perr[1]
                sigma_err = perr[2]
            except Exception:
                mu_err = np.nan
                sigma_err = np.nan

            text = (
                f"Ch {ch}\n"
                f"$\\mu$ = {mu:.1f} ± {mu_err:.1f}\n"
                f"$\\sigma$ = {sigma:.1f} ± {sigma_err:.1f}"
            )

            # position automatique verticale
            ypos = 0.95 - 0.12 * list(self.curves.keys()).index(ch)

            self.ax.text(
                0.02,
                ypos,
                text,
                transform=self.ax.transAxes,
                fontsize=11,
                color=color,
                verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.85)
            )
            # Petite annotation (optionnelle)
            # self.ax.text(0.02, 0.95, f"Ch {ch}: μ={mu:.2f}, σ={sigma:.2f}", transform=self.ax.transAxes)

            self.fig.canvas.draw_idle()

        except Exception as e:
            print(f"[Ch {ch}] Fit failed: {e}")
class HistogramOptionsWindow:
    """
    Fenêtre pour :
    - choisir les channels (checkbox)
    - choisir la plage d'amplitude à analyser (min/max)
    - choisir le mode d'affichage (densité / counts)
    - choisir le nombre de bins
    """
    def __init__(self, num_channels, default_bins=250):
        self.num_channels = num_channels
        self.default_bins = default_bins
        self.offsets = {}
        self.selected_channels = None
        self.amp_min = None
        self.amp_max = None
        self.n_bins = default_bins
        self.use_density = True   # recommandé pour overlay (comparable)
        self.ok = False

    def create_window(self):
        self.window = tk.Tk()
        self.window.title("Histogram Options (Min values)")
        self.window.geometry("520x520")

        ttk.Label(self.window, text="Channels to include:").pack(pady=(10, 5), anchor="w", padx=10)

        # Scrollable frame for many channels
        container = ttk.Frame(self.window)
        container.pack(fill="both", expand=False, padx=10)

        canvas = tk.Canvas(container, height=220)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.chan_vars = []
        # default: all checked
        for ch in range(self.num_channels):
            v = tk.BooleanVar(value=True)
            self.chan_vars.append(v)
            # ttk.Checkbutton(scroll_frame, text=f"Channel {ch}", variable=v).pack(anchor="w")
            row = ttk.Frame(scroll_frame)
            row.pack(anchor="w", fill="x", pady=2)

            ttk.Checkbutton(row, text=f"Channel {ch}", variable=v, width=14).pack(side="left")

            e = ttk.Entry(row, width=10)
            e.insert(0, "0")  # offset par défaut
            e.pack(side="left", padx=(10, 0))

            ttk.Label(row, text="offset (ADC)").pack(side="left", padx=(6, 0))

            # stocker l'entry associée au channel
            if not hasattr(self, "offset_entries"):
                self.offset_entries = {}
            self.offset_entries[ch] = e

        # Amplitude range
        ttk.Separator(self.window).pack(fill="x", pady=10, padx=10)

        ttk.Label(self.window, text="Amplitude window (ADC units):").pack(anchor="w", padx=10)
        range_frame = ttk.Frame(self.window)
        range_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(range_frame, text="Min:").grid(row=0, column=0, sticky="w")
        self.entry_min = ttk.Entry(range_frame, width=12)
        self.entry_min.grid(row=0, column=1, padx=(5, 20))

        ttk.Label(range_frame, text="Max:").grid(row=0, column=2, sticky="w")
        self.entry_max = ttk.Entry(range_frame, width=12)
        self.entry_max.grid(row=0, column=3, padx=(5, 0))

        ttk.Label(self.window, text="Leave empty to auto-fit (use data min/max).").pack(anchor="w", padx=10)

        # Bins + density
        ttk.Separator(self.window).pack(fill="x", pady=10, padx=10)

        options_frame = ttk.Frame(self.window)
        options_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(options_frame, text="Bins:").grid(row=0, column=0, sticky="w")
        self.entry_bins = ttk.Entry(options_frame, width=8)
        self.entry_bins.insert(0, str(self.default_bins))
        self.entry_bins.grid(row=0, column=1, padx=(5, 20), sticky="w")

        self.density_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options_frame,
            text="Normalize (density) for overlay comparison",
            variable=self.density_var
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        # Buttons
        ttk.Separator(self.window).pack(fill="x", pady=10, padx=10)

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(pady=10)

        ttk.Button(btn_frame, text="Plot overlay", command=self.on_ok).grid(row=0, column=0, padx=8)
        ttk.Button(btn_frame, text="Cancel", command=self.on_cancel).grid(row=0, column=1, padx=8)

        self.window.mainloop()

    def on_ok(self):
        # channels
        selected = [i for i, v in enumerate(self.chan_vars) if v.get()]
        if not selected:
            print("No channel selected -> cancel")
            self.ok = False
            self.window.destroy()
            return
        self.offsets = {}
        for ch in selected:
            try:
                self.offsets[ch] = float(self.offset_entries[ch].get().strip())
            except Exception:
                self.offsets[ch] = 0.0
        # bins
        try:
            self.n_bins = int(self.entry_bins.get().strip())
            if self.n_bins <= 1:
                raise ValueError
        except Exception:
            self.n_bins = self.default_bins

        # range
        smin = self.entry_min.get().strip()
        smax = self.entry_max.get().strip()
        self.amp_min = float(smin) if smin != "" else None
        self.amp_max = float(smax) if smax != "" else None

        self.use_density = bool(self.density_var.get())
        self.selected_channels = selected
        self.ok = True

        self.window.quit()
        self.window.destroy()

    def on_cancel(self):
        self.ok = False
        self.window.quit()
        self.window.destroy()
class FileSelector:
    """Interface graphique simple pour sélectionner un fichier à analyser"""

    def __init__(self, directory):
        self.directory = directory
        self.selected_file = None

    def create_window(self):
        self.window = tk.Tk()
        self.window.title("File Selector")
        self.window.geometry("400x300")

        label = ttk.Label(self.window, text="Select a file to analyze:")
        label.pack(pady=10)

        self.listbox = tk.Listbox(self.window, width=50)
        self.listbox.pack(pady=10, padx=10)

        files = self.get_files_list()
        for file in files:
            self.listbox.insert(tk.END, file)

        analyze_button = ttk.Button(self.window, text="Analyze", command=self.on_analyze)
        analyze_button.pack(pady=10)

        quit_button = ttk.Button(self.window, text="Quit", command=self.on_quit)
        quit_button.pack(pady=5)

        self.window.mainloop()

    def get_files_list(self):
        # Liste tous les fichiers dans le dossier binaryread
        return [f for f in os.listdir(self.directory)
                if os.path.isfile(os.path.join(self.directory, f))]

    def on_analyze(self):
        if self.listbox.curselection():
            self.selected_file = self.listbox.get(self.listbox.curselection())
            self.window.quit()
            self.window.destroy()

    def on_quit(self):
        self.selected_file = None
        self.window.quit()
        self.window.destroy()

def gaussian(x, A, mu, sigma, C):
    return A * np.exp(-0.5 * ((x - mu) / sigma) ** 2) + C


def create_overlay_min_histograms_lines(event_minimums, filename, channels,
                                        amp_min=None, amp_max=None,
                                        n_bins=250, density=True,
                                        use_abs=True,
                                        title_extra="(windowed, overlay)",
                                        fit_interactive=True, offsets=None):
    """
    Overlay des histogrammes (min-values) sous forme de courbes, pour faciliter:
    - sélection d'une courbe
    - fit gaussien sur une fenêtre choisie à la souris
    """

    data_by_ch = {}
    for ch in channels:
        if 0 <= ch < len(event_minimums) and event_minimums[ch]:
            arr = np.array(event_minimums[ch], dtype=float)
            if use_abs:
                arr = np.abs(arr)
            data_by_ch[ch] = arr

    if not data_by_ch:
        print("No data for selected channels.")
        return None, None

    global_min = min(np.min(v) for v in data_by_ch.values())
    global_max = max(np.max(v) for v in data_by_ch.values())

    if amp_min is None:
        amp_min = float(global_min)
    if amp_max is None:
        amp_max = float(global_max)
    if amp_max <= amp_min:
        amp_min, amp_max = float(global_min), float(global_max)

    bins = np.linspace(amp_min, amp_max, n_bins + 1)
    centers = 0.5 * (bins[:-1] + bins[1:])

    fig = plt.figure(figsize=(11, 6.2))
    ax = fig.add_subplot(1, 1, 1)
    fig.canvas.manager.set_window_title(f'Overlay Min-ADC Histo - {filename}')

    ax.set_title(f"Minimum ADC values histogram overlay — {filename}\n{title_extra}", fontsize=14)
    ax.set_xlabel("Minimum ADC value (ABS + windowed)" if use_abs else "Minimum ADC value (windowed)", fontsize=12)
    ax.set_ylabel("Density" if density else "Counts", fontsize=12)
    ax.grid(True, linestyle="--", alpha=0.35)

    # On trace des courbes step (pickables) + on stocke leurs données
    curves = {}  # ch -> dict(line, x, y)
    for ch, arr in data_by_ch.items():
        off = 0.0 if offsets is None else float(offsets.get(ch, 0.0))
        arr_shifted = arr + off
        w = arr_shifted[(arr_shifted >= amp_min) & (arr_shifted <= amp_max)]
        if w.size == 0:
            continue

        counts, _ = np.histogram(w, bins=bins)
        y = counts.astype(float)
        if density:
            area = np.sum(y) * (bins[1] - bins[0])
            if area > 0:
                y = y / area

        # Courbe step
        # Pour un step correct: on duplique les x/y sur les bords
        x_step = np.repeat(bins, 2)[1:-1]                # taille 2*n_bins
        y_step = np.repeat(y, 2)                         # taille 2*n_bins

        (line,) = ax.plot(x_step, y_step, linewidth=2.0, alpha=0.95, label=f"Ch {ch} (N={w.size})")
        line.set_picker(6)  # tolérance en pixels pour cliquer la courbe

        curves[ch] = {"line": line, "x": centers, "y": y}

    ax.legend(loc="best", fontsize=10, frameon=True)

    info = f"ABS={use_abs} | Window: [{amp_min:.1f}, {amp_max:.1f}] | bins={n_bins} | mode={'density' if density else 'counts'}"
    ax.text(0.01, 0.02, info, transform=ax.transAxes, fontsize=10,
            verticalalignment="bottom",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))

    interactor = None
    if fit_interactive and curves:
        interactor = GaussianFitInteractor(fig, ax, curves)

    plt.tight_layout()
    return fig, interactor
def create_min_amplitude_histogram(event_minimums, filename, n_bins=100):
    """
    Creates a histogram of minimum values per event with enhanced axis values.
    """
    num_channels = len(event_minimums)
    fig, axs = plt.subplots(num_channels, 1, figsize=(10, 5 * num_channels))
    fig.canvas.manager.set_window_title(f'ADC Minimum Values - {filename}')
    fig.suptitle(f'Histogram of Minimum Amplitudes per Event - {filename} - {num_channels} channels')

    if num_channels == 1:
        axs = [axs]

    for idx in range(num_channels):
        if event_minimums[idx]:
            # Create histogram for this channel
            n, bins, patches = axs[idx].hist(event_minimums[idx], bins=n_bins,
                                             label=f'Channel {idx}', alpha=0.6, color='red')
            x = (bins[:-1] + bins[1:]) / 2  # Bin centers for X coordinates

            # Center and adjust display for this specific channel
            min_val = min(event_minimums[idx])
            max_val = max(event_minimums[idx])

            # Calculate margin proportional to data range
            data_range = max_val - min_val
            margin = max(10, data_range * 0.1)

            # Set X limits for this channel only
            axs[idx].set_xlim([min_val - margin, max_val + margin])

            # Adjust Y limits for this channel
            if len(n) > 0:
                max_height = max(n) * 1.1
                axs[idx].set_ylim([0, max_height])

            # Calculate mean and standard deviation (just in case you need it)
            # mean_val = np.mean(event_minimums[idx])
            # std_val = np.std(event_minimums[idx])




            # Find bin with maximum value to highlight (just incase you need it)
            # max_bin_idx = np.argmax(n)
            # max_x = x[max_bin_idx]
            # max_y = n[max_bin_idx]



            axs[idx].legend()
            axs[idx].set_ylabel(f'Channel {idx} - Occurence')
            axs[idx].grid(True, linestyle='--', alpha=0.4)

            # Add title with statistics to channel
            axs[idx].set_title(
                f'Channel {idx} - Min: {min_val:.1f}, Max: {max_val:.1f}, Events: {len(event_minimums[idx])}')
        else:
            axs[idx].text(0.5, 0.5, 'No data available',
                          horizontalalignment='center', verticalalignment='center',
                          transform=axs[idx].transAxes)
            axs[idx].set_ylabel(f'Channel {idx}')

    axs[-1].set_xlabel('Minimum ADC Value')
    plt.subplots_adjust(hspace=0.3)

    return fig, n


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
            print(f'Canal {idx}, événements : {len(all_events[idx])}')

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

                axs[idx].set_title(f'Canal {idx}')
                axs[idx].set_xlabel('Point d\'échantillonnage (x)')
                axs[idx].set_ylabel('Valeur ADC (y)')
                axs[idx].set_ylim(y_min, y_max)
                axs[idx].grid(True, linestyle='--', alpha=0.4)

            except (ValueError, TypeError) as e:
                print(f"Erreur lors du tracé du canal {idx}: {e}")
                axs[idx].set_title(f'Canal {idx} (données manquantes)')
                axs[idx].set_xlabel('Point d\'échantillonnage')
                axs[idx].set_ylabel('Valeur ADC')
                axs[idx].set_ylim(-10000, 10000)
                axs[idx].grid(True, linestyle='--', alpha=0.4)

    plt.tight_layout()
    return fig



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

        num_channels, event_minimums, successful_offset, raw_waveforms = load_and_process_single_file(
            file_selector.selected_file,
            base_dir
        )

        if num_channels == 0 or not event_minimums:
            print("No valid data obtained. Try another file.")
            continue

        print(f"Number of channels detected: {num_channels}")
        for i in range(num_channels):
            print(f"Channel {i}: {len(event_minimums[i])} minimum values")
            if event_minimums[i]:
                print(f"  Example values: {event_minimums[i][:5]}")
        # === NEW: ask user which channels + amplitude window for overlay ===
        opts = HistogramOptionsWindow(num_channels=num_channels, default_bins=my_bins)
        opts.create_window()

        fig_overlay, interactor = create_overlay_min_histograms_lines(
            event_minimums,
            file_selector.selected_file,
            channels=opts.selected_channels,
            amp_min=opts.amp_min,
            amp_max=opts.amp_max,
            n_bins=opts.n_bins,
            density=opts.use_density,
            use_abs=True,
            fit_interactive=True,
            offsets=opts.offsets
        )
        formatted_waveforms = [[] for _ in range(num_channels)]

        if not raw_waveforms:
            print("No raw waveform was stored. Cannot display waveforms.")
        else:
            print(f"Preparing {len(raw_waveforms)} waveforms for display")

            for event_waveforms in raw_waveforms:
                for channel_idx in range(min(num_channels, len(event_waveforms))):

                    formatted_waveforms[channel_idx].append(event_waveforms[channel_idx])

        fig_mins, count_histo = create_min_amplitude_histogram(event_minimums, file_selector.selected_file, n_bins=my_bins)
        fig_waveform = create_waveform_display(
            formatted_waveforms,
            file_selector.selected_file,
            max_samples_to_plot=display_samples  # 1000 points
        )

        #LUCIA min amplitude in ADC are : event_minimums
        #the min values count of the histo is : count_histo


        plt.ion()

        fig_mins.show()
        if fig_overlay is not None:
            fig_overlay.show()
        fig_waveform.show()
        plt.draw()

        print("Press Enter to continue (or close all windows)...")
        plt.ioff()
        plt.show(block=True)


if __name__ == "__main__":
    main()
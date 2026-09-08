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
samples = 1024
fixed_header = 0x1d9
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
                    # Find minimum for this channel for this event
                    waveform_min = min(amplitudes[o])
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


def create_waveform_display(amplitudes, filename):
    """
    Crée une nouvelle fenêtre pour afficher les formes d'onde de chaque canal
    avec mise en évidence des coordonnées x,y.
    """
    num_channels = len(amplitudes)

    fig, axs = plt.subplots(num_channels, 1, figsize=(10, 5 * num_channels))
    fig.canvas.manager.set_window_title(f'Formes d\'onde - {filename}')
    fig.suptitle(f'Formes d\'onde - {filename} - {num_channels} canaux')


    if num_channels == 1:
        axs = [axs]

    x = np.arange(1024)


    all_events = []
    for channel_idx in range(num_channels):
        channel_events = []
        for event_idx in range(len(amplitudes[channel_idx])):
        # for event_idx in range(5000):
            if amplitudes[channel_idx][event_idx]:

                waveform = amplitudes[channel_idx][event_idx][:1024] if len(
                    amplitudes[channel_idx][event_idx]) > 1024 else amplitudes[channel_idx][event_idx]
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


                avg_waveform = np.zeros(1024)
                valid_events = 0

                for event in all_events[idx]:
                    if len(event) == 1024:
                        avg_waveform += np.array(event)
                        valid_events += 1

                if valid_events > 0:
                    avg_waveform /= valid_events




                y_margin = (channel_max - channel_min) * 0.05
                y_min = channel_min - y_margin - 1000
                y_max = channel_max + y_margin + 1000

                for j, event in enumerate(all_events[idx]):
                    if len(event) == len(x):
                        axs[idx].plot(x, event, alpha=0.2, linewidth=0.8)

                info_text = (f"Événements: {len(all_events[idx])}\n"
                             f"Min global: {channel_min:.1f}\n"
                             f"Max global: {channel_max:.1f}")

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

        formatted_waveforms = [[] for _ in range(num_channels)]

        if not raw_waveforms:
            print("No raw waveform was stored. Cannot display waveforms.")
        else:
            print(f"Preparing {len(raw_waveforms)} waveforms for display")

            for event_waveforms in raw_waveforms:
                for channel_idx in range(min(num_channels, len(event_waveforms))):

                    formatted_waveforms[channel_idx].append(event_waveforms[channel_idx])

        fig_mins, count_histo = create_min_amplitude_histogram(event_minimums, file_selector.selected_file, n_bins=my_bins)
        fig_waveform = create_waveform_display(formatted_waveforms, file_selector.selected_file)

        #LUCIA min amplitude in ADC are : event_minimums
        #the min values count of the histo is : count_histo


        plt.ion()
        fig_mins.show()
        fig_waveform.show()
        plt.draw()

        print("Press Enter to continue (or close all windows)...")
        plt.ioff()
        plt.show(block=True)


if __name__ == "__main__":
    main()
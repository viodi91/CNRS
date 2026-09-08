import matplotlib.pyplot as plt
import numpy as np
import re
#import mplcursors      not used because it causes a laggy process
from scipy.optimize import curve_fit
from matplotlib.widgets import RectangleSelector


def parse_header(header_lines, first_timestamp):
    info = {}
    for line in header_lines:
        if "DATA SAMPLES" in line:
            info['samples'] = int(re.search(r'\[(\d+)\]', line).group(1))
            info['channels'] = int(re.search(r'NB OF CHANNELS ACQUIRED: (\d+)', line).group(1))
            info['sampling_period'] = float(re.search(r'Sampling Period: ([\d.]+) ps', line).group(1))
            info['timestamp'] = first_timestamp
    return info


def parse_channel_info(line):
    info = {}
    info['channel'] = int(re.search(r'CH: (\d+)', line).group(1))
    info['event_id'] = int(re.search(r'EVENTID: (\d+)', line).group(1))
    info['fcr'] = int(re.search(r'FCR: (\d+)', line).group(1))
    info['baseline'] = float(re.search(r'Baseline: ([\d.-]+) V', line).group(1))
    info['amplitude'] = float(re.search(r'Amplitude: ([\d.-]+) V', line).group(1))
    info['charge'] = float(re.search(r'Charge:\s+([\d.-]+) pC', line).group(1))
    info['rate_counter'] = float(re.search(r'RateCounter\s+([\d.]+)', line).group(1))
    return info


def read_data(filename):
    with open(filename, 'r') as file:
        content = file.read()

    first_timestamp = None
    timestamp_match = re.search(r'=== UnixTime = ([\d.]+) date = ([\d.]+) time = ([\w.]+)', content)
    if timestamp_match:
        unix_time, date, time = timestamp_match.groups()
        first_timestamp = f"{date} {time}"

    events = re.split(r'=== EVENT \d+ ===', content)[1:]
    header = content.split('=== EVENT')[0].split('\n')
    header_info = parse_header(header, first_timestamp)

    # Première passe pour identifier tous les canaux présents
    all_channels = set()
    for event in events:
        lines = event.split('\n')
        for line in lines:
            if line.startswith('=== CH:'):
                channel_info = parse_channel_info(line)
                all_channels.add(channel_info['channel'])

    # Initialiser les dictionnaires pour tous les canaux trouvés
    all_data = {channel: [] for channel in all_channels}
    all_channel_info = {channel: [] for channel in all_channels}

    # Maintenant traiter les données
    for event in events:
        lines = event.split('\n')
        channel_data = {channel: [] for channel in all_channels}
        current_channel = None

        for line in lines:
            if line.startswith('=== CH:'):
                channel_info = parse_channel_info(line)
                current_channel = channel_info['channel']
                all_channel_info[current_channel].append(channel_info)
            elif line and not line.startswith('===') and current_channel is not None:
                try:
                    values = list(map(float, line.split()))
                    channel_data[current_channel].extend(values)
                except ValueError:
                    continue

        for channel in all_channels:
            if len(channel_data[channel]) == header_info['samples']:
                all_data[channel].append(channel_data[channel])

    # Mettre à jour le nombre de canaux dans header_info
    header_info['channels'] = len(all_channels)
    print(f"Canaux détectés : {sorted(list(all_channels))}")

    return header_info, all_data, all_channel_info


def plot_main_data(header_info, all_data, all_channel_info):
    # Utiliser les canaux disponibles dans all_data
    available_channels = sorted(all_data.keys())
    num_channels = len(available_channels)

    fig = plt.figure(figsize=(15, 5 * num_channels))
    gs = fig.add_gridspec(num_channels, 1)
    axes = [fig.add_subplot(gs[i, 0]) for i in range(num_channels)]

    timestamp = header_info.get('timestamp', 'Unknown')
    fig.suptitle(f"WaveCatcher Data Analysis - {timestamp}")

    x = np.arange(header_info['samples'])
    max_events = max(len(data) for data in all_data.values())
    colors = plt.cm.rainbow(np.linspace(0, 1, max_events))

    lines = []
    # Utiliser l'index de la liste d'axes et le numéro de canal séparément
    for ax_idx, channel in enumerate(available_channels):
        ax = axes[ax_idx]

        for i, event_data in enumerate(all_data[channel]):
            line, = ax.plot(x, event_data, color=colors[i], alpha=0.5, linewidth=0.5)
            lines.append(line)

        ax.set_title(f"Channel {channel}")
        ax.set_xlabel("Sample Number")
        ax.set_ylabel("Amplitude (V)")

    plt.tight_layout()
    return fig

def plot_histograms_with_interactivity(all_data, header_info):
    # Utiliser les canaux disponibles dans all_data
    available_channels = sorted(all_data.keys())
    num_channels = len(available_channels)

    fig, axes = plt.subplots(num_channels, 1, figsize=(10, 5 * num_channels))
    if num_channels == 1:
        axes = [axes]

    fig.suptitle("Interactive Histograms of All Amplitudes")

    # Utiliser l'index de la liste d'axes et le numéro de canal séparément
    for ax_idx, channel in enumerate(available_channels):
        ax = axes[ax_idx]

        if len(all_data[channel]) > 0:
            all_amplitudes = np.concatenate(all_data[channel])


            histogram = InteractiveHistogram(
                ax,
                all_amplitudes,
                title=f"Channel {channel}",
                enable_fitting=True
            )
            enable_curve_removal(fig, ax)
        else:
            print(f"Channel {channel}: No data available.")
            ax.text(0.5, 0.5, "No data available for this channel",
                    ha='center', va='center', transform=ax.transAxes)
            ax.set_title(f"Channel {channel}")

    plt.tight_layout()
    return fig


def gaussian(x, amp, mu, sigma):
    return amp * np.exp(-(x - mu) ** 2 / (2 * sigma ** 2))



def find_peak_value(event_data):
    # Calculer la moyenne des premiers et derniers points pour estimer la ligne de base
    baseline = np.mean(event_data[:10] + event_data[-10:])

    # Soustraire la ligne de base
    baseline_corrected = np.array(event_data) - baseline

    # Trouver l'index de la valeur minimale (pic négatif le plus profond)
    peak_index = np.argmin(baseline_corrected)

    # Retourner la valeur réelle à cet index
    return event_data[peak_index]


def gaussian(x, amp, mu, sigma):
    return amp * np.exp(-(x - mu) ** 2 / (2 * sigma ** 2))


def plot_max_value_histograms(all_data):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10))
    fig.suptitle("Histograms of Negative Peak Values")

    for channel in [0, 1]:
        ax = ax1 if channel == 0 else ax2

        peak_values = [find_peak_value(event) for event in all_data[channel]]

        if peak_values:
            n, bins, _ = ax.hist(peak_values, bins=50, color='skyblue', edgecolor='black', density=False)

            bin_centers = (bins[:-1] + bins[1:]) / 2

            try:
                # Essayer l'ajustement gaussien avec des limites et un nombre maximum d'itérations plus élevé
                popt, _ = curve_fit(gaussian, bin_centers, n,
                                    p0=[max(n), np.mean(peak_values), np.std(peak_values)],
                                    bounds=([0, min(peak_values), 0],
                                            [np.inf, max(peak_values), np.inf]),
                                    maxfev=10000)

                # Tracer l'ajustement
                x_fit = np.linspace(min(peak_values), max(peak_values), 100)
                ax.plot(x_fit, gaussian(x_fit, *popt), 'r--', linewidth=2)

                fit_label = f'Gaussian fit\nsigma = {popt[2]:.3f}\nmean = {popt[1]:.3f}'
            except RuntimeError:
                print(f"L'ajustement gaussien a échoué pour le canal {channel}. Utilisation des statistiques de base.")
                mean = np.mean(peak_values)
                std = np.std(peak_values)
                fit_label = f'Statistiques\nsigma = {std:.3f}\nmean = {mean:.3f}'

            ax.set_title(f"Channel {channel}")
            ax.set_xlabel("Negative Peak Amplitude (V)")
            ax.set_ylabel("Occurrence")
            ax.legend(['Data', fit_label])
        else:
            ax.text(0.5, 0.5, "No data available for this channel",
                    ha='center', va='center', transform=ax.transAxes)
            ax.set_title(f"Channel {channel}")

    plt.tight_layout()
    return fig


class InteractiveHistogram:
    def __init__(self, ax, data, title="Histogram", enable_fitting=False):
        self.ax = ax
        self.data = data
        self.title = title
        self.rect_selector = None
        self.selected_region = None
        self.enable_fitting = enable_fitting
        self.fit_count = 0

        # Liste de couleurs pour les fits
        self.colors = ['red', 'blue', 'green', 'purple', 'orange', 'brown', 'pink', 'gray', 'cyan', 'magenta']

        self.init_plot()

    def init_plot(self):
        self.ax.hist(self.data, bins=100, color='skyblue', edgecolor='black')
        self.ax.set_title(self.title)
        self.ax.set_xlabel("Amplitude (V)")
        self.ax.set_ylabel("Occurrence")

        if self.enable_fitting:
            self.rect_selector = RectangleSelector(
                self.ax,
                self.on_select,
                useblit=True,
                interactive=True,
                button=[1]
            )

    def on_select(self, eclick, erelease):
        if not self.enable_fitting:
            return

        x_min, x_max = eclick.xdata, erelease.xdata
        self.selected_region = (min(x_min, x_max), max(x_min, x_max))
        self.fit_gaussian()

    def fit_gaussian(self):
        if not self.selected_region or not self.enable_fitting:
            return

        x_min, x_max = self.selected_region
        selected_data = self.data[(self.data >= x_min) & (self.data <= x_max)]

        if len(selected_data) == 0:
            print("No data in the selected range.")
            return

        n, bins = np.histogram(selected_data, bins=50,density=False)
        bin_centers = (bins[:-1] + bins[1:]) / 2

        try:
            popt, _ = curve_fit(gaussian, bin_centers, n,
                                p0=[max(n), np.mean(selected_data), np.std(selected_data)],
                                maxfev=10000)

            current_color = self.colors[self.fit_count % len(self.colors)]

            x_fit = np.linspace(x_min, x_max, 100)
            y_fit = gaussian(x_fit, *popt)
            curve_label = f'Gaussian Fit {self.fit_count + 1}'
            self.ax.plot(x_fit, y_fit, '-', color=current_color, label=curve_label, linewidth=2)

            vertical_position = 0.95 - (self.fit_count * 0.15)

            fit_text = self.ax.text(
                0.05, vertical_position-0.1,
                f'Fit {self.fit_count + 1}:\nμ = {popt[1]:.3f}\nσ = {popt[2]:.3f}',
                transform=self.ax.transAxes,
                color=current_color,
                bbox=dict(facecolor='white', alpha=0.7, edgecolor=current_color)
            )
            fit_text.fit_label = True
            fit_text.fit_number = self.fit_count
            fit_text.text_color = current_color

            self.fit_count += 1

            legend = self.ax.legend(loc='upper right')
            for text, line in zip(legend.get_texts(), legend.get_lines()):
                text.set_color(line.get_color())

            self.ax.figure.canvas.draw()

        except RuntimeError:
            print("Gaussian fit failed.")

def enable_curve_removal(fig, ax):
    def on_click(event):
        if event.button == 3:  # Right-click
            for line in ax.get_lines():
                contains, _ = line.contains(event)
                if contains:
                    line.remove()
                    fit_num = int(line.get_label().split()[-1]) - 1

                    texts_to_remove = []
                    for text in ax.texts:
                        if hasattr(text, 'fit_label') and hasattr(text, 'fit_number'):
                            if text.fit_number == fit_num:
                                texts_to_remove.append(text)

                    for text in texts_to_remove:
                        text.remove()

                    if ax.get_legend():
                        ax.get_legend().remove()
                        remaining_lines = [l for l in ax.get_lines() if 'Gaussian Fit' in l.get_label()]
                        if remaining_lines:
                            legend = ax.legend(loc='upper right')
                            for text, line in zip(legend.get_texts(), legend.get_lines()):
                                text.set_color(line.get_color())

                    print("Curve fit and associated information removed.")
                    fig.canvas.draw_idle()
                    break

    fig.canvas.mpl_connect('button_press_event', on_click)


# Main execution
filename = r"C:\Users\higueret_adm\Documents\monoabeasts\Monoabeast3\data\calib20260313163038d40mmDAC244.dat"
header_info, all_data, all_channel_info = read_data(filename)

main_fig = plot_main_data(header_info, all_data, all_channel_info)
hist_fig = plot_histograms_with_interactivity(all_data, header_info)
print(f"Data Samples: {header_info['samples']}")
print(f"Number of Channels: {header_info['channels']}")
print(f"Sampling Period: {header_info['sampling_period']} ps")
print(f"Timestamp: {header_info.get('timestamp', 'Unknown')}")
peak_fig = plot_max_value_histograms(all_data)
plt.show()  # This will display both figures simultaneously

#all_data is a dictionnary, all_data[0] is a list, this list hv sublists representing amplitudes measured for each event
#structure :
# all_data[channel_0_or_1][[amplitudes of event 1],[amplitudes of event 2], [amplitudes of event 3]]


# header_info is a dictionary that store header info of the ascii file.
# structure :
# header_info = {
#     'samples': 1024,  # number of data points per event
#     'channels': 2,    # how many channels of data we have
#     'sampling_period': 312.5 ps,  # time between samples
#     'timestamp': '2024.9.26 16h.31m.32s.622ms'  # when the data was collected
# }

# all_channel_info is a dictionnary that store info for each channel.
# For example, it could look like:
# all_channel_info[channel_0_or_1] = [
#     {'channel': 0, 'event_id': 1, 'baseline': 0.1, 'amplitude': 0.5, ...},  # info for event 1
#     {'channel': 0, 'event_id': 2, 'baseline': 0.2, 'amplitude': 0.6, ...},  # info for event 2
#     ...
# ]

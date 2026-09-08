import os
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
import csv
import re
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector
import matplotlib

"""
Programme d'analyse et de visualisation de données pour l'étude de la relation entre 
le seuil de détection (threshold) et l'énergie dans un système de détection.

Ce programme permet de :
1. Charger et analyser des données à partir de fichiers CSV contenant des mesures 
   de taux de comptage (hit rates) en fonction du seuil pour différents gaps d'air
2. Ajuster une fonction sigmoïde sur les données pour chaque gap d'air
3. Déterminer automatiquement ou manuellement les points d'inflexion des courbes
4. Visualiser les données et les ajustements via une interface graphique avec :
   - Des graphiques 2D pour chaque gap d'air
   - Un graphique 3D montrant la surface complète des données
   - Un graphique d'énergie montrant la relation entre les seuils et l'énergie

Classes principales :
- DataAnalyzer : Gère le chargement et l'analyse des données
- DataVisualizerGUI : Gère l'interface graphique et l'interaction utilisateur
matplotlib.use('TkAgg')
"""

class DataAnalyzer:
    def __init__(self, data_directory):
        self.data_directory = data_directory
        self.data = {}  # {distance: {"thresholds": [], "hit_rates": []}}
        self.validated_fits = {}  # {distance: {"params": [], "inflection": {}, "range": ()}}
        self.energy_data = {
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
            40.00: (165470.33, 51834.72)}
        self.load_data()

    def convert_to_float(self, value):
        """Convert string to float, handling both comma and dot as decimal separator"""
        return float(value.replace(',', '.'))

    def load_data(self):
        """Load all CSV files from the data directory"""
        print("Scanning directory:", self.data_directory)

        for filename in os.listdir(self.data_directory):
            print("Found file:", filename)

            if filename.endswith('.csv'):
                print("Processing CSV file:", filename)

                # Modifié l'expression régulière pour accepter les nombres décimaux
                # gap_match = re.search(r'abeastscandata.*gap(\d+\.\d+)mm\.csv', filename)
                gap_match = re.search(r'gap(\d+(?:\.\d+)?)mm\.csv$', filename, re.IGNORECASE)
                if gap_match:
                    print("Found gap match in:", filename)
                    gap = float(gap_match.group(1))
                    print("Extracted gap:", gap)
                    distance = 62 - gap

                    filepath = os.path.join(self.data_directory, filename)
                    thresholds = []
                    hit_rates = []

                    with open(filepath, 'r') as csvfile:
                        csv_reader = csv.reader(csvfile, delimiter=";")
                        next(csv_reader)  # Skip header
                        for row in csv_reader:
                            try:
                                threshold = self.convert_to_float(row[1])
                                hit_rate = self.convert_to_float(row[5])  # C0 Rate
                                thresholds.append(threshold)
                                hit_rates.append(hit_rate)
                            except Exception as e:
                                print(f"Error processing row: {e}")
                                continue

                    self.data[distance] = {
                        "thresholds": np.array(thresholds),
                        "hit_rates": np.array(hit_rates)
                    }

    def sigmoid(self, x, L, x0, k, b):
        """Sigmoid function for fitting"""
        return L / (1 + np.exp(-k * (x - x0))) + b

    def fit_sigmoid(self, x, y):
        """Fit sigmoid to data with improved parameter estimation"""
        try:
            # Estimate initial parameters
            L = np.max(y) - np.min(y)
            b = np.min(y)
            y_half = (np.max(y) + np.min(y)) / 2
            x0 = x[np.argmin(np.abs(y - y_half))]

            # Estimate k using the steepest part of the curve
            dy = np.diff(y)
            dx = np.diff(x)
            max_slope = np.max(np.abs(dy / dx))
            k = 4 * max_slope / L if L > 0 else 1.0

            p0 = [L, x0, k, b]

            # Define bounds with a small range for b
            bounds = (
                [L * 0.5, min(x), 0, b - 0.1],  # lower bounds
                [L * 1.5, max(x), 10, b + max(y) * 0.1]  # upper bounds
            )

            # Fit with bounds
            popt, _ = curve_fit(self.sigmoid, x, y, p0=p0,
                                bounds=bounds, method='trf')

            print("Fit succeeded!")
            print(f"Final parameters: L={popt[0]:.2f}, x0={popt[1]:.2f}, k={popt[2]:.4f}, b={popt[3]:.2f}")

            return popt

        except Exception as e:
            print(f"Fit failed with error: {e}")
            return None
    def calculate_inflection_point(self, popt):
        """Calculate inflection point and characteristics"""
        L, x0, k, b = popt
        inflection_x = x0
        inflection_y = self.sigmoid(x0, L, x0, k, b)
        max_slope = (k * L) / 4
        return {'x': inflection_x, 'y': inflection_y, 'slope': max_slope}

    def get_available_gaps(self):
        """Return list of available air gaps"""
        return sorted([62 - d for d in self.data.keys()])

    def create_energy_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text='Energy Plot')

        # Controls
        control_frame = ttk.LabelFrame(tab, text="Controls")
        control_frame.pack(fill='x', padx=5, pady=5)

        ttk.Button(control_frame, text="Plot Threshold vs Energy",
                   command=self.plot_energy).pack(padx=5, pady=5)
        ttk.Button(control_frame, text="Save Threshold vs Energy Data",
                   command=self.save_threshold_energy_data).pack(padx=5, pady=5)

        # Plot frame
        self.plot_frame_energy = ttk.Frame(tab)
        self.plot_frame_energy.pack(fill='both', expand=True, padx=5, pady=5)

    def save_threshold_energy_data(self):
        """Save threshold vs energy data"""
        if not self.analyzer.validated_fits:
            messagebox.showwarning("Warning", "No results to save")
            return

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.analyzer.save_threshold_vs_energy(f'threshold_vs_energy_{timestamp}.csv')
            messagebox.showinfo("Success", "Threshold vs Energy data saved successfully")
        except Exception as e:
            print(f"Error saving threshold vs energy data: {e}")
            messagebox.showerror("Error", f"Error saving results: {str(e)}")


class DataVisualizerGUI:
    def __init__(self, root, analyzer):
        self.root = root
        self.analyzer = analyzer
        self.root.title("Data Visualization Tool")

        # Variables for plot navigation
        self.current_gaps = []
        self.current_gap_index = 0

        self.create_gui()

    def create_gui(self):
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)

        # Create tabs
        self.create_3d_tab()
        self.create_2d_tab()
        self.create_energy_tab()

    def create_3d_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text='3D Surface Plot')

        # Controls
        control_frame = ttk.LabelFrame(tab, text="Controls")
        control_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(control_frame, text="Threshold Range:").grid(row=0, column=0, padx=5, pady=5)
        self.min_thresh_3d = ttk.Entry(control_frame, width=10)
        self.max_thresh_3d = ttk.Entry(control_frame, width=10)
        self.min_thresh_3d.grid(row=0, column=1, padx=5, pady=5)
        self.max_thresh_3d.grid(row=0, column=2, padx=5, pady=5)

        ttk.Button(control_frame, text="Plot", command=self.plot_3d).grid(row=0, column=3, padx=5, pady=5)

        # Plot frame
        self.plot_frame_3d = ttk.Frame(tab)
        self.plot_frame_3d.pack(fill='both', expand=True, padx=5, pady=5)

    def reset_data(self):
        """Reset the 2D tab to initial state"""
        # Clear listbox selections
        self.gap_listbox.selection_clear(0, tk.END)

        # Clear threshold range inputs
        self.min_thresh_2d.delete(0, tk.END)
        self.max_thresh_2d.delete(0, tk.END)

        # Clear range info tree
        for item in self.range_info.get_children():
            self.range_info.delete(item)

        # Clear manual threshold
        self.manual_threshold.delete(0, tk.END)

        # Reset variables
        self.current_gaps = []
        self.current_gap_index = 0

        # Clear the plot
        for widget in self.plot_frame_2d.winfo_children():
            if widget != self.current_gap_label:
                widget.destroy()
        self.current_gap_label.config(text="")

        # Clear fits
        if hasattr(self, 'current_fit'):
            delattr(self, 'current_fit')
        if hasattr(self, 'fits_cache'):
            self.fits_cache = {}
    def create_2d_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text='2D Plots')

        # Left panel for controls
        control_frame = ttk.LabelFrame(tab, text="Controls")
        control_frame.pack(side='left', fill='y', padx=5, pady=5)

        # Gap selection
        ttk.Label(control_frame, text="Available Air Gaps:").pack(padx=5, pady=5)
        self.gap_listbox = tk.Listbox(control_frame, selectmode='multiple', height=10)
        self.gap_listbox.pack(fill='x', padx=5, pady=5)

        for gap in self.analyzer.get_available_gaps():
            self.gap_listbox.insert(tk.END, f"{gap:.1f}")

        # Threshold range inputs
        range_frame = ttk.LabelFrame(control_frame, text="Threshold Range")
        range_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(range_frame, text="Min:").grid(row=0, column=0, padx=5, pady=5)
        self.min_thresh_2d = ttk.Entry(range_frame, width=10)
        self.min_thresh_2d.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(range_frame, text="Max:").grid(row=1, column=0, padx=5, pady=5)
        self.max_thresh_2d = ttk.Entry(range_frame, width=10)
        self.max_thresh_2d.grid(row=1, column=1, padx=5, pady=5)

        # Apply range button
        ttk.Button(range_frame, text="Apply Range to Selected",
                   command=self.apply_range_to_selected).grid(row=2, column=0, columnspan=2, pady=5)

        # Range info display
        self.range_info = ttk.Treeview(control_frame, columns=('Gap', 'Range'),
                                       show='headings', height=5)
        self.range_info.heading('Gap', text='Gap')
        self.range_info.heading('Range', text='Threshold Range')
        self.range_info.pack(fill='x', padx=5, pady=5)

        # Start Analysis button
        ttk.Button(control_frame, text="Start Analysis",
                   command=self.start_analysis).pack(fill='x', pady=5)

        # Navigation buttons
        nav_frame = ttk.Frame(control_frame)
        nav_frame.pack(fill='x', padx=5, pady=5)

        self.prev_button = ttk.Button(nav_frame, text="Previous", command=self.show_previous_gap)
        self.next_button = ttk.Button(nav_frame, text="Next", command=self.show_next_gap)
        self.prev_button.pack(side='left', padx=5)
        self.next_button.pack(side='right', padx=5)

        # NOUVEAU : Manual Inflection Point
        inflection_frame = ttk.LabelFrame(control_frame, text="Manual Inflection Point")
        inflection_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(inflection_frame, text="Threshold:").pack(side='left', padx=5)
        self.manual_threshold = ttk.Entry(inflection_frame, width=10)
        self.manual_threshold.pack(side='left', padx=5)

        ttk.Button(inflection_frame, text="Apply", command=self.apply_manual_inflection).pack(side='left', padx=5)

        # MODIFIÉ : Validation buttons avec nouveau bouton Reject Measurement
        val_frame = ttk.Frame(control_frame)
        val_frame.pack(fill='x', padx=5, pady=5)

        ttk.Button(val_frame, text="Accept Fit",
                   command=self.accept_current_fit).pack(fill='x', pady=2)
        ttk.Button(val_frame, text="Reset",
                   command=self.reset_data).pack(fill='x', pady=2)

        # Plot frame
        self.plot_frame_2d = ttk.Frame(tab)
        self.plot_frame_2d.pack(side='right', fill='both', expand=True, padx=5, pady=5)

        # Current gap label
        self.current_gap_label = ttk.Label(self.plot_frame_2d, text="")
        self.current_gap_label.pack(pady=5)

    def apply_range_to_selected(self):
        """Apply current threshold range to selected gaps"""
        try:
            min_thresh = float(self.min_thresh_2d.get())
            max_thresh = float(self.max_thresh_2d.get())
        except ValueError:
            messagebox.showerror("Error", "Please enter valid threshold values")
            return

        selected_indices = self.gap_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Warning", "Please select at least one gap")
            return

        # Store ranges for each selected gap
        for idx in selected_indices:
            gap = self.gap_listbox.get(idx)
            # Remove existing range for this gap if it exists
            for item in self.range_info.get_children():
                if self.range_info.item(item)['values'][0] == gap:
                    self.range_info.delete(item)
            # Add new range
            self.range_info.insert('', 'end', values=(gap, f"{min_thresh:.1f} - {max_thresh:.1f}"))

    def start_analysis(self):
        """Start analysis of selected gaps"""
        # Verify that we have ranges defined
        if len(self.range_info.get_children()) == 0:
            messagebox.showwarning("Warning", "Please define ranges first")
            return

        # Get gaps that have ranges defined
        self.current_gaps = []
        for item in self.range_info.get_children():
            gap = float(self.range_info.item(item)['values'][0])
            self.current_gaps.append(str(gap))

        if not self.current_gaps:
            messagebox.showwarning("Warning", "No gaps with defined ranges found")
            return

        # Sort gaps
        self.current_gaps.sort(key=float)
        self.current_gap_index = 0

        # Show first plot
        self.show_2d_plot()
    def create_energy_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text='Energy Plot')

        # Controls
        control_frame = ttk.LabelFrame(tab, text="Controls")
        control_frame.pack(fill='x', padx=5, pady=5)

        ttk.Button(control_frame, text="Plot Energy vs Hit Rate",
                   command=self.plot_energy).pack(padx=5, pady=5)
        ttk.Button(control_frame, text="Save Results",
                   command=self.save_results).pack(padx=5, pady=5)

        # Plot frame
        self.plot_frame_energy = ttk.Frame(tab)
        self.plot_frame_energy.pack(fill='both', expand=True, padx=5, pady=5)

    def plot_3d(self):
        try:
            # Clear current plot
            for widget in self.plot_frame_3d.winfo_children():
                widget.destroy()

            # Create figure
            fig = Figure(figsize=(10, 8))
            ax = fig.add_subplot(111, projection='3d')

            # Get threshold range
            min_thresh = float(self.min_thresh_3d.get()) if self.min_thresh_3d.get() else None
            max_thresh = float(self.max_thresh_3d.get()) if self.max_thresh_3d.get() else None
            threshold_range = (min_thresh, max_thresh) if min_thresh is not None and max_thresh is not None else None

            # Create surface plot
            distances = sorted(self.analyzer.data.keys())
            gaps = [62 - d for d in distances]

            # Create mesh grid
            all_thresholds = []
            for d in distances:
                all_thresholds.extend(self.analyzer.data[d]["thresholds"])
            all_thresholds = sorted(list(set(all_thresholds)))

            if threshold_range:
                all_thresholds = [t for t in all_thresholds
                                  if threshold_range[0] <= t <= threshold_range[1]]

            X, Y = np.meshgrid(all_thresholds, gaps)
            Z = np.zeros_like(X)

            for i, gap in enumerate(gaps):
                distance = 62- gap
                thresholds = self.analyzer.data[distance]["thresholds"]
                hit_rates = self.analyzer.data[distance]["hit_rates"]

                for j, threshold in enumerate(all_thresholds):
                    idx = np.where(thresholds == threshold)[0]
                    if len(idx) > 0:
                        Z[i, j] = hit_rates[idx[0]]

            surf = ax.plot_surface(X, Y, Z, cmap='viridis')
            fig.colorbar(surf)

            ax.set_xlabel('Threshold')
            ax.set_ylabel('Air Gap (mm)')
            ax.set_zlabel('Hit Rate (hits/s)')

            # Add to GUI
            canvas = FigureCanvasTkAgg(fig, self.plot_frame_3d)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)

            toolbar = NavigationToolbar2Tk(canvas, self.plot_frame_3d)
            toolbar.update()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def show_2d_plot(self):
        if not self.current_gaps:
            return

        try:
            # Clear current plot
            for widget in self.plot_frame_2d.winfo_children():
                if widget != self.current_gap_label:
                    widget.destroy()

            # Get current gap data
            gap = float(self.current_gaps[self.current_gap_index])
            distance = 62- gap
            data = self.analyzer.data[distance]

            # Get range for this gap
            range_str = None
            for item in self.range_info.get_children():
                if float(self.range_info.item(item)['values'][0]) == gap:
                    range_str = self.range_info.item(item)['values'][1]
                    break

            if not range_str:
                messagebox.showerror("Error", f"No range defined for gap {gap}")
                return

            min_thresh, max_thresh = map(float, range_str.split(' - '))

            # Update label
            self.current_gap_label.config(text=f"Current Gap: {gap:.1f} mm")

            # Create figure
            fig = Figure(figsize=(10, 6))
            ax = fig.add_subplot(111)

            # Get and filter data
            mask = (data["thresholds"] >= min_thresh) & (data["thresholds"] <= max_thresh)
            thresholds = data["thresholds"][mask]
            hit_rates = data["hit_rates"][mask]

            # Plot data points
            ax.plot(thresholds, hit_rates, 'bo-', label='Data')

            # Do initial fit if no fit exists for this gap
            if not hasattr(self, 'current_fit') or self.current_gap_index not in self.fits_cache:
                popt = self.analyzer.fit_sigmoid(thresholds, hit_rates)
                if popt is not None:
                    infl = self.analyzer.calculate_inflection_point(popt)
                    self.current_fit = {
                        'params': popt,
                        'inflection': infl,
                        'range': (min_thresh, max_thresh)
                    }
                    if not hasattr(self, 'fits_cache'):
                        self.fits_cache = {}
                    self.fits_cache[self.current_gap_index] = self.current_fit.copy()

            # Plot the current fit
            if hasattr(self, 'current_fit'):
                # Plot sigmoid fit
                t_fit = np.linspace(min_thresh, max_thresh, 1000)
                h_fit = self.analyzer.sigmoid(t_fit, *self.current_fit['params'])
                ax.plot(t_fit, h_fit, 'r-', label='Sigmoid Fit')

                # Plot inflection point
                infl = self.current_fit['inflection']
                ax.plot(infl['x'], infl['y'], 'g*', markersize=10, label='Inflection Point')

                # Add fit information
                fit_info = (f'Fit Parameters:\n'
                          f'L = {self.current_fit["params"][0]:.2f}\n'
                          f'x₀ = {self.current_fit["params"][1]:.2f}\n'
                          f'k = {self.current_fit["params"][2]:.4f}\n'
                          f'b = {self.current_fit["params"][3]:.2f}\n\n'
                          f'Inflection Point:\n'
                          f'Threshold = {infl["x"]:.2f}\n'
                          f'Hit Rate = {infl["y"]:.2f}')

                ax.text(0.02, 0.98, fit_info, transform=ax.transAxes,
                       fontsize=9, verticalalignment='top',
                       bbox=dict(facecolor='white', alpha=0.8))

            # Set axis labels and title
            ax.set_xlim(min_thresh, max_thresh)
            ax.set_xlabel('Threshold')
            ax.set_ylabel('Hit Rate (hits/s)')
            ax.set_title(f'Gap: {gap:.1f} mm')
            ax.grid(True)
            ax.legend()

            # Add to GUI
            canvas = FigureCanvasTkAgg(fig, self.plot_frame_2d)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)

            toolbar = NavigationToolbar2Tk(canvas, self.plot_frame_2d)
            toolbar.update()

        except Exception as e:
            print(f"Error in show_2d_plot: {str(e)}")
            messagebox.showerror("Error", f"Error in plot: {str(e)}")


    def on_select(self, xmin, xmax):
        """Handle range selection for fitting"""
        if not self.current_gaps:
            return

        gap = float(self.current_gaps[self.current_gap_index])
        distance = 62 - gap

        # Get data within selected range
        data = self.analyzer.data[distance]
        mask = (data["thresholds"] >= xmin) & (data["thresholds"] <= xmax)
        thresholds = data["thresholds"][mask]
        hit_rates = data["hit_rates"][mask]

        if len(thresholds) < 4:
            messagebox.showwarning("Warning", "Need at least 4 points for fitting")
            return

        # Fit sigmoid
        popt = self.analyzer.fit_sigmoid(thresholds, hit_rates)
        if popt is None:
            messagebox.showerror("Error", "Could not fit sigmoid to selected range")
            return

        # Calculate inflection point
        inflection = self.analyzer.calculate_inflection_point(popt)

        # Store temporary fit
        self.current_fit = {
            'params': popt,
            'inflection': inflection,
            'range': (xmin, xmax)
        }

        # Update plot
        self.show_2d_plot()

    def show_previous_gap(self):
        if not self.current_gaps:
            return
        self.current_gap_index = (self.current_gap_index - 1) % len(self.current_gaps)
        self.show_2d_plot()

    def show_next_gap(self):
        if not self.current_gaps:
            return
        self.current_gap_index = (self.current_gap_index + 1) % len(self.current_gaps)
        self.show_2d_plot()

    def accept_current_fit(self):
        if not hasattr(self, 'current_fit') or not self.current_gaps:
            messagebox.showwarning("Warning", "No fit to accept")
            return

        gap = float(self.current_gaps[self.current_gap_index])
        distance = 62 - gap

        # Store the validated fit
        self.analyzer.validated_fits[distance] = self.current_fit.copy()

        # Clear the current fit to force a new fit for the next gap
        delattr(self, 'current_fit')

        # Clear this gap from the cache
        if hasattr(self, 'fits_cache'):
            if self.current_gap_index in self.fits_cache:
                del self.fits_cache[self.current_gap_index]

        # Move to next gap and show plot
        self.show_next_gap()

    def apply_manual_inflection(self):
        if not hasattr(self, 'current_fit'):
            messagebox.showwarning("Warning", "No current fit available")
            return

        try:
            x0 = float(self.manual_threshold.get())
            min_thresh, max_thresh = self.current_fit['range']

            if not (min_thresh <= x0 <= max_thresh):
                messagebox.showerror("Error", f"Threshold must be between {min_thresh:.1f} and {max_thresh:.1f}")
                return

            # Keep original parameters but update x0
            L = self.current_fit['params'][0]
            k = self.current_fit['params'][2]
            b = self.current_fit['params'][3]

            # Update parameters with new x0
            new_params = [L, x0, k, b]
            y0 = self.analyzer.sigmoid(x0, *new_params)

            # Update current fit
            self.current_fit['params'] = new_params
            self.current_fit['inflection'] = {'x': x0, 'y': y0, 'slope': (k * L) / 4}

            # Update cache
            self.fits_cache[self.current_gap_index] = self.current_fit.copy()

            # Refresh plot
            self.show_2d_plot()

        except ValueError:
            messagebox.showerror("Error", "Please enter a valid threshold value")
    def reject_measurement(self):
        """Reject current measurement entirely"""
        if not self.current_gaps:
            return

        gap = float(self.current_gaps[self.current_gap_index])
        distance = 62 - gap

        # Stocker les mesures rejetées dans un nouvel attribut
        if not hasattr(self, 'rejected_measurements'):
            self.rejected_measurements = set()

        self.rejected_measurements.add(distance)

        # Supprimer le fit s'il existe
        if distance in self.analyzer.validated_fits:
            del self.analyzer.validated_fits[distance]

        if hasattr(self, 'current_fit'):
            delattr(self, 'current_fit')

        messagebox.showinfo("Success", f"Measurement for gap {gap:.1f}mm rejected")
        self.show_next_gap()

    def plot_energy(self):
        if not self.analyzer.validated_fits:
            print("No validated fits available")
            messagebox.showwarning("Warning", "No validated fits available")
            return

        try:
            # Clear current plot
            for widget in self.plot_frame_energy.winfo_children():
                widget.destroy()

            # Create figure
            fig = Figure(figsize=(10, 6))
            ax = fig.add_subplot(111)

            # Collect data
            gaps = []
            thresholds = []
            energies = []
            energy_stds = []
            threshold_stds = []

            for distance, fit_info in sorted(self.analyzer.validated_fits.items()):
                if hasattr(self, 'rejected_measurements') and distance in self.rejected_measurements:
                    continue

                gap = 62 - float(distance)
                energy, std = self.analyzer.energy_data[gap]
                threshold = fit_info['inflection']['x']
                threshold_std = 5

                gaps.append(gap)
                thresholds.append(threshold)
                energies.append(energy)
                energy_stds.append(std)
                threshold_stds.append(threshold_std)

            if not gaps:
                print("No valid data points to plot")
                messagebox.showwarning("Warning", "No valid data points to plot")
                return

            # Ajouter la zone grisée pour threshold > 245
            threshold_limit = 245
            ymin, ymax = min(energies) * 0.9, max(energies) * 1.1
            ax.fill_between([threshold_limit, max(thresholds) * 1.1],
                            [ymin, ymin],
                            [ymax, ymax],
                            color='gray', alpha=0.3,
                            label='Threshold > Noise')

            # Plot les points sans barres d'erreur
            points = ax.plot(thresholds, energies, 'ko', label='Data points')[0]

            # Ajouter les barres d'erreur séparément avec des couleurs différentes
            # Barres d'erreur horizontales (rouge)
            ax.errorbar(thresholds, energies, xerr=threshold_stds, yerr=None,
                        fmt='none', ecolor='red', capsize=5,
                        label='Threshold σ')

            # Barres d'erreur verticales (bleue)
            ax.errorbar(thresholds, energies, xerr=None, yerr=energy_stds,
                        fmt='none', ecolor='blue', capsize=5,
                        label='Energy σ')

            # Fit linéaire avec prise en compte des erreurs
            weights = 1 / np.array(energy_stds)
            coeffs = np.polyfit(thresholds, energies, 1, w=weights)
            fit_line = np.poly1d(coeffs)
            thresh_range = np.linspace(min(thresholds), max(thresholds), 100)

            # Calculer le coefficient de corrélation
            correlation_coef = np.corrcoef(thresholds, energies)[0, 1]

            # Calcul de l'incertitude sur la pente
            N = len(thresholds)
            sigma_slope = np.sqrt(1 / (N - 2) * np.sum((energies - fit_line(thresholds)) ** 2) /
                                  np.sum((thresholds - np.mean(thresholds)) ** 2))

            ax.plot(thresh_range, fit_line(thresh_range), 'k--',
                    label=f'Linear fit:\ny = ({coeffs[0]:.2e} ± {sigma_slope:.2e})x + {coeffs[1]:.2e}\nR² = {correlation_coef ** 2:.3f}')

            # Add gap annotations
            for g, t, e in zip(gaps, thresholds, energies):
                ax.annotate(f'{g:.1f}mm', (t, e), xytext=(5, 5),
                            textcoords='offset points', fontsize=8)

            # Définir les limites de l'axe x pour inclure la zone grisée
            ax.set_xlim(min(thresholds) * 0.9, 255)
            ax.set_ylim(ymin, ymax)

            ax.set_ylabel('Energy (eV)')
            ax.set_xlabel('Threshold')

            # Créer un deuxième axe Y pour les air gaps
            ax2 = ax.twinx()
            ax2.set_ylim(ax.get_ylim())
            ax2.set_ylabel('Air Gap (mm)')

            # Ajuster les ticks du second axe
            energy_min, energy_max = ax.get_ylim()
            gap_positions = []
            gap_labels = []
            for e, g in zip(energies, gaps):
                if energy_min <= e <= energy_max:
                    gap_positions.append(e)
                    gap_labels.append(f'{g:.1f}')
            ax2.set_yticks(gap_positions)
            ax2.set_yticklabels(gap_labels)

            ax.set_title('Energy vs Threshold with Colored Uncertainties')
            ax.grid(True)

            # Ajuster la position de la légende
            ax.legend(bbox_to_anchor=(1, 1), loc='upper right')

            # Add to GUI
            canvas = FigureCanvasTkAgg(fig, self.plot_frame_energy)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)

            toolbar = NavigationToolbar2Tk(canvas, self.plot_frame_energy)
            toolbar.update()

        except Exception as e:
            print(f"Error in plotting threshold vs energy: {str(e)}")
            messagebox.showerror("Error", f"Error plotting threshold vs energy: {str(e)}")
    def save_results(self):
        """Save threshold vs energy results"""
        if not self.analyzer.validated_fits:
            messagebox.showwarning("Warning", "No results to save")
            return

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f'threshold_energy_results_{timestamp}.csv'

            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Gap (mm)', 'Distance (mm)', 'Threshold', 'Energy (eV)', 'Std Dev'])

                for distance, fit_info in self.analyzer.validated_fits.items():
                    gap = 62 - distance
                    try:
                        energy, std = self.analyzer.energy_data[gap]
                        threshold = fit_info['inflection']['x']
                        writer.writerow(
                            [f"{gap:.1f}", f"{distance:.1f}", f"{threshold:.1f}", f"{energy:.2f}", f"{std:.2f}"])
                    except KeyError:
                        print(f"Warning: No energy data found for gap {gap}")

            messagebox.showinfo("Success", f"Results saved to {filename}")

        except Exception as e:
            print(f"Error saving results: {e}")
            messagebox.showerror("Error", f"Error saving results: {str(e)}")

def main():
    data_dir = r"C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\Gain2_module2_scan2\scan_data_2025 02 20 14 31 29\repetition_1\csv_file_no_break"

    root = tk.Tk()
    root.title("Data Visualization Tool")
    root.state('zoomed')

    analyzer = DataAnalyzer(data_dir)
    app = DataVisualizerGUI(root, analyzer)

    root.mainloop()

if __name__ == "__main__":
    main()
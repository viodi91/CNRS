import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.figure import Figure
import tkinter as tk
from tkinter import ttk, messagebox
import os
import subprocess
import sys
import numpy as np
from datetime import datetime
import csv
import glob
import re
# --- Sigmoïde / fit ---
try:
    from scipy.optimize import curve_fit
    SCIPY_OK = True
except Exception:
    SCIPY_OK = False

# Configuration du style matplotlib
plt.style.use('seaborn-v0_8-darkgrid')

# Chemins des fichiers
CSV_FOLDER = r"C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\scan_data_2025 10 09 17 19 01\repetition_1\csv_files"
WAVECATCHER_FOLDER = r"C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\scan_data_2025 10 09 17 19 01\repetition_1\wavecatcher_files"
SUPERPOSITION_SCRIPT_NAME = "superposition.py"

# Palette de couleurs moderne
COLORS = {
    'primary': '#1e3a8a',
    'secondary': '#3b82f6',
    'accent': '#f59e0b',
    'success': '#10b981',
    'bg_dark': '#1f2937',
    'bg_light': '#f9fafb',
    'text_dark': '#111827',
    'text_light': '#6b7280',
}

# Tableau d'énergie (Gap en mm, Energy en eV, Std Dev)
ENERGY_TABLE = {
    0.50: (2457786.18, 51961.61),
    1.00: (2466401.20, 51092.51),
    1.50: (2488616.49, 51822.08),
    2.00: (2508809.30, 53421.28),
    2.50: (2529995.75, 55679.30),
    3.00: (2550950.52, 54447.29),
    3.50: (2575011.95, 54339.43),
    4.00: (2597552.76, 75948.05),
    4.50: (2621945.24, 57324.54),
    5.00: (2646322.91, 58750.91),
    5.50: (2669168.09, 59839.97),
    6.00: (2701815.28, 63262.60),
    6.50: (2727001.87, 63369.16),
    7.00: (2757586.53, 61736.51),
    7.50: (2786465.16, 67791.66),
    8.00: (2818811.82, 69217.52),
    8.50: (2848916.26, 64578.78),
    9.00: (2883848.77, 76095.79),
    9.50: (2920980.53, 68992.58),
    10.00: (2955659.95, 78556.01),
    10.50: (2989447.44, 69165.63),
    11.00: (3031852.63, 78869.99),
    11.50: (3071659.08, 79734.18),
    12.00: (3116790.38, 77257.72),
    12.50: (3159880.09, 80522.52),
    13.00: (3212904.15, 87341.03),
    13.50: (3256978.77, 83567.89),
    14.00: (3314002.69, 80288.75),
    14.50: (3362131.02, 90265.17),
    15.00: (3415150.44, 84622.17),
    15.50: (3463480.76, 95967.30),
    16.00: (3512625.27, 82227.46),
    16.50: (3550699.74, 94086.81),
    17.00: (3588124.68, 69501.47),
    17.50: (3610370.99, 61647.30),
    18.00: (3615365.84, 52889.00),
    18.50: (3598956.43, 45677.31),
    19.00: (3560514.26, 39930.66),
    19.50: (3512663.82, 39774.25),
    20.00: (3458232.41, 40570.50),
    20.50: (3405738.17, 39897.20),
    21.00: (3345652.42, 38793.89),
    21.50: (3286307.39, 41130.48),
    22.00: (3223938.85, 73884.94),
    22.50: (3161995.98, 70519.92),
    23.00: (3099475.71, 95526.41),
    23.50: (3038046.76, 43217.84),
    24.00: (2973146.78, 42944.24),
    24.50: (2908767.32, 43059.81),
    25.00: (2842735.81, 44594.15),
    25.50: (2778895.88, 44164.51),
    26.00: (2707424.65, 96899.51),
    26.50: (2641863.35, 47674.36),
    27.00: (2573995.40, 45642.89),
    27.50: (2500767.48, 63553.34),
    28.00: (2430912.46, 48288.57),
    28.50: (2357191.01, 53567.17),
    29.00: (2280705.10, 50691.49),
    29.50: (2205019.30, 52555.11),
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


class ScanViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🔬 Analyseur de Scans 3D - Vue Interactive")
        self.root.geometry("1800x950")
        self.root.configure(bg=COLORS['bg_light'])
        self.auto_pick_sigmoid = tk.BooleanVar(value=True)  # activer l’auto pick
        self.sigmoid_cache = {}  # {gap: {'x0':int, 'y0':float, 'params':tuple, 'r2':float}}

        # Données de calibration
        self.calibration_points = {}  # {delta_mm: {'threshold': X, 'energy': Y, 'std': Z}}
        self.current_calibration_delta_index = 0
        self.calibration_deltas = []

        self.setup_style()
        self.load_data()
        self.create_widgets()
        self.plot_3d()
        self.selected_delta = None

    def setup_style(self):
        """Configure le style moderne de l'interface"""
        style = ttk.Style()
        style.theme_use('clam')

        style.configure('Modern.TFrame', background=COLORS['bg_light'])
        style.configure('Card.TFrame', background='white', relief='flat')

        style.configure('Title.TLabel',
                        background='white',
                        foreground=COLORS['primary'],
                        font=('Segoe UI', 16, 'bold'))

    def load_data(self):
        """Charge et prépare les données depuis les fichiers CSV individuels"""
        # Initialiser les variables au cas où aucun fichier ne charge
        self.df = pd.DataFrame()
        self.deltas = []

        # Trouver tous les fichiers CSV
        csv_files = glob.glob(os.path.join(CSV_FOLDER, "*gap*.csv"))

        if not csv_files:
            messagebox.showerror("Erreur", f"Aucun fichier CSV trouvé dans {CSV_FOLDER}")
            return

        print(f"📂 Chargement des données depuis {CSV_FOLDER}")
        print(f"✓ {len(csv_files)} fichiers CSV trouvés\n")

        all_data = []

        for csv_file in csv_files:
            print(f"🔍 Analyse de : {os.path.basename(csv_file)}")

            # Extraire le gap depuis le nom du fichier
            match = re.search(r'gap([\d.]+)mm\.csv', os.path.basename(csv_file))
            if not match:
                print(f"   ⚠️ Impossible d'extraire le gap")
                continue

            gap = float(match.group(1).replace(',', '.'))
            print(f"   Gap extrait : {gap} mm")

            # Lire le CSV avec le bon séparateur (point-virgule) et décimal (virgule)
            try:
                df_gap = pd.read_csv(csv_file, sep=';', decimal=',')
                print(f"   ✓ CSV lu avec {len(df_gap)} lignes")

                # Debug : afficher les colonnes BRUTES
                print(f"   Colonnes brutes : {list(df_gap.columns)}")

                # Nettoyer les noms de colonnes
                df_gap.columns = df_gap.columns.str.strip()
                print(f"   Colonnes nettoyées : {list(df_gap.columns)}")

                # Vérifier que les colonnes nécessaires existent
                required_cols = ['Gap', 'Threshold', 'C0 Rate']
                missing_cols = [col for col in required_cols if col not in df_gap.columns]

                if missing_cols:
                    print(f"   ❌ Colonnes manquantes : {missing_cols}")
                    print(f"   Colonnes disponibles : {list(df_gap.columns)}\n")
                    continue

                # Ajouter les données
                for _, row in df_gap.iterrows():
                    all_data.append({
                        'Delta_mm': gap,
                        'Gap': gap,
                        'Position_mm': gap,
                        'Threshold_DAC': int(row['Threshold']),
                        'C0_Rate': float(row['C0 Rate']),
                        'C0_Hits': int(row['C0 Hits']) if 'C0 Hits' in df_gap.columns else 0,
                        'Fichier': os.path.basename(csv_file),
                        'Status': 'SUCCESS'
                    })

                print(f"   ✓ {len(df_gap)} points ajoutés\n")

            except Exception as e:
                print(f"   ❌ Erreur : {e}\n")
                import traceback
                traceback.print_exc()
                continue

        if not all_data:
            messagebox.showerror("Erreur", "Aucune donnée valide trouvée dans les fichiers CSV")
            return

        # Créer le DataFrame global
        self.df = pd.DataFrame(all_data)
        self.deltas = sorted(self.df['Delta_mm'].unique())

        print(f"\n{'=' * 60}")
        print(f"✓ Total : {len(self.df)} mesures chargées")
        print(f"✓ {len(self.deltas)} valeurs de Gap : {self.deltas}")
        print(f"{'=' * 60}\n")

    # ====== Modèle sigmoïde (4 paramètres) ======
    @staticmethod
    def _logistic4(x, L, x0, k, b):
        # b + L / (1 + exp(k*(x - x0))) ; k < 0 pour chute
        return b + L / (1.0 + np.exp(k * (x - x0)))

    def _initial_sigmoid_guess(self, x, y):
        # x,y triés croissants en x
        y_min, y_max = float(np.min(y)), float(np.max(y))
        L0 = (y_max - y_min) if (y_max > y_min) else 1.0
        y_mid = y_min + 0.5 * L0
        # x0 ≈ abscisse quand y croise la médiane
        idx = np.argmin(np.abs(y - y_mid))
        x0 = float(x[idx])
        # pente locale autour du plus grand gradient (estimation de k)
        dy = np.gradient(y, x)
        k_est = np.clip(dy[np.argmin(y)] if np.any(y) else -0.1, -10, -1e-3)
        k0 = float(k_est) / max(L0, 1e-6)
        # si signe douteux, impose une chute
        if k0 > 0: k0 = -abs(k0) if abs(k0) > 1e-3 else -0.1
        b0 = y_min
        return (L0, x0, k0, b0)

    def _fit_sigmoid_for_gap(self, delta):
        """Retourne dict {'x0','y0','params','r2'} ou None si échec."""
        df_delta = self.df[self.df['Delta_mm'] == delta].sort_values('Threshold_DAC')
        x = df_delta['Threshold_DAC'].to_numpy(dtype=float)
        y = df_delta['C0_Rate'].to_numpy(dtype=float)

        if len(x) < 6:
            return None

        # Si déjà calculé
        if delta in self.sigmoid_cache:
            return self.sigmoid_cache[delta]

        # Normalisation légère des poids (stabilise)
        w = np.ones_like(y)

        # Tentative SciPy
        if SCIPY_OK:
            p0 = self._initial_sigmoid_guess(x, y)
            try:
                # Contraintes douces : L>0, k<0
                bounds_lower = [0.0, min(x) - 50, -100.0, min(y) - abs(np.ptp(y))]
                bounds_upper = [np.ptp(y) * 5 + 1e-6, max(x) + 50, -1e-5, max(y) + abs(np.ptp(y))]
                popt, _ = curve_fit(self._logistic4, x, y, p0=p0,
                                    bounds=(bounds_lower, bounds_upper),
                                    maxfev=20000)
                yhat = self._logistic4(x, *popt)
                # R²
                ss_res = float(np.sum((y - yhat) ** 2))
                ss_tot = float(np.sum((y - np.mean(y)) ** 2)) + 1e-12
                r2 = 1.0 - ss_res / ss_tot
                x0 = float(popt[1])
                y0 = float(self._logistic4(x0, *popt))
                out = {'x0': int(round(x0)), 'y0': y0, 'params': tuple(map(float, popt)), 'r2': float(r2)}
                self.sigmoid_cache[delta] = out
                return out
            except Exception:
                pass

        # Fallback sans SciPy : point d’inflexion ≈ max pente (dérivée)
        try:
            # Lissage par moyenne mobile
            k = min(7, max(3, (len(x) // 20) * 2 + 1))  # fenêtre impaire
            if k > 3:
                y_s = np.convolve(y, np.ones(k) / k, mode='same')
            else:
                y_s = y.copy()
            dy = np.gradient(y_s, x)
            # pente la plus négative (chute)
            idx = int(np.argmin(dy))
            x0 = float(x[idx])
            # Interpole y au x0 pour annotation
            y0 = float(y_s[idx])
            # qualité grossière (corrélation logit)
            y_norm = (y - y.min()) / (y.max() - y.min() + 1e-12)
            mask = (y_norm > 1e-3) & (y_norm < 1 - 1e-3)
            r2 = float(np.corrcoef(x[mask], np.log(y_norm[mask] / (1 - y_norm[mask])))[0, 1] ** 2) if np.any(
                mask) else 0.0
            out = {'x0': int(round(x0)), 'y0': y0, 'params': None, 'r2': r2}
            self.sigmoid_cache[delta] = out
            return out
        except Exception:
            return None

    def _draw_sigmoid_overlay(self, ax, x, y, fitinfo):
        """Trace (optionnel) le fit et marque l’inflexion."""
        if fitinfo is None:
            return
        x0, y0 = fitinfo['x0'], fitinfo['y0']
        # Marqueur du point d’inflexion
        ax.plot([x0], [y0], marker='*', markersize=18, markeredgecolor='yellow',
                markerfacecolor='red', markeredgewidth=2, zorder=5, label=f'Inflexion (DAC={x0})')
        ax.axvline(x0, linestyle='--', alpha=0.6, label=f'x0 ≈ {x0}')
        # Courbe lissée / fit si params connus
        if fitinfo.get('params') is not None:
            xx = np.linspace(min(x), max(x), 400)
            yy = self._logistic4(xx, *fitinfo['params'])
            ax.plot(xx, yy, linewidth=2.0, alpha=0.8, label=f'Fit sigmoïde (R²={fitinfo["r2"]:.3f})')
        ax.legend(fontsize=10)

    def find_closest_energy(self, delta_mm):
        """Trouve l'énergie correspondant au Gap le plus proche"""
        # Delta_mm = Gap directement !
        gap = delta_mm

        # Trouver le gap le plus proche dans la table
        available_gaps = list(ENERGY_TABLE.keys())
        closest_gap = min(available_gaps, key=lambda x: abs(x - gap))

        energy, std = ENERGY_TABLE[closest_gap]

        print(f"✓ Gap={gap:.1f} mm → Closest={closest_gap:.1f} mm → Energy={energy / 1e6:.3f} MeV")

        return energy, std, closest_gap

    def create_widgets(self):
        """Crée l'interface graphique moderne"""
        main_container = tk.Frame(self.root, bg=COLORS['bg_light'])
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Notebook
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Créer les onglets
        self.create_3d_tab()
        self.create_2d_tab()
        self.create_calibration_workflow_tab()  # NOUVEAU

    def auto_pick_all_gaps(self):
        """Calcule et remplit automatiquement le tableau de calibration avec l’inflexion sigmoïde de chaque gap."""
        if not len(self.deltas):
            messagebox.showwarning("Attention", "Aucun gap disponible.")
            return

        self.calibration_points.clear()
        for item in self.calib_tree.get_children():
            self.calib_tree.delete(item)

        count = 0
        for delta in self.deltas:
            info = self._fit_sigmoid_for_gap(delta)
            if info is None:
                continue
            energy, std, gap = self.find_closest_energy(delta)
            thr = int(info['x0'])
            self.calibration_points[delta] = {
                'threshold': thr,
                'energy': energy,
                'std': std,
                'gap': gap,
                'r2': info['r2']
            }
            self.calib_tree.insert('', 'end', values=(f"{delta:.1f}", f"{thr}", f"{energy / 1e6:.3f}"))
            count += 1

        if count == 0:
            messagebox.showwarning("Attention", "Aucun fit utilisable n’a été trouvé.")
        else:
            messagebox.showinfo("OK", f"Inflexions auto ajoutées pour {count} gaps.\n"
                                      f"Vous pouvez encore corriger manuellement gap par gap si besoin.")

    def create_3d_tab(self):
        """Onglet vue 3D"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text='📊 Vue 3D')

        # Container principal
        main_container = tk.Frame(tab, bg=COLORS['bg_light'])
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Zone graphique
        graph_container = tk.Frame(main_container, bg='white', relief='solid', bd=1)
        graph_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.fig_3d = Figure(figsize=(14, 9), facecolor='white')
        self.ax_3d = self.fig_3d.add_subplot(111, projection='3d', facecolor='#f9fafb')

        self.canvas_3d = FigureCanvasTkAgg(self.fig_3d, graph_container)
        self.canvas_3d.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def create_2d_tab(self):
        """Onglet courbes 2D"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text='📈 Courbes 2D (par Gap)')

        # Container principal
        main_container = tk.Frame(tab, bg=COLORS['bg_light'])
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Panneau de contrôle (gauche)
        control_panel = tk.Frame(main_container, bg='white', relief='solid', bd=1)
        control_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        control_panel.config(width=300)
        control_panel.pack_propagate(False)

        # Header
        header = tk.Frame(control_panel, bg=COLORS['primary'], height=80)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        title_label = tk.Label(header,
                               text="📊 Sélection Gap",
                               font=('Segoe UI', 18, 'bold'),
                               bg=COLORS['primary'],
                               fg='white')
        title_label.pack(pady=20)

        # Liste des Delta_mm
        list_container = tk.Frame(control_panel, bg='white')
        list_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        list_label = tk.Label(list_container,
                              text="Gaps disponibles",
                              font=('Segoe UI', 11, 'bold'),
                              bg='white',
                              fg=COLORS['text_dark'])
        list_label.pack(anchor='w', pady=(0, 5))

        list_frame = tk.Frame(list_container, bg='white')
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.delta_listbox = tk.Listbox(list_frame,
                                        yscrollcommand=scrollbar.set,
                                        font=('Consolas', 10),
                                        selectmode=tk.SINGLE,
                                        bg='white',
                                        fg=COLORS['text_dark'],
                                        selectbackground=COLORS['secondary'],
                                        selectforeground='white',
                                        relief='flat',
                                        highlightthickness=1,
                                        highlightcolor=COLORS['secondary'],
                                        highlightbackground='#e5e7eb',
                                        bd=0)
        self.delta_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.delta_listbox.yview)

        for i, delta in enumerate(self.deltas):
            self.delta_listbox.insert(tk.END, f"  Gap={delta:5.1f} mm")
            if i % 2 == 0:
                self.delta_listbox.itemconfig(i, bg='#f9fafb')

        self.delta_listbox.bind('<<ListboxSelect>>', self.on_delta_select)

        # Info
        info_container = tk.Frame(control_panel, bg='white')
        info_container.pack(fill=tk.X, padx=15, pady=(0, 15))

        info_label = tk.Label(info_container,
                              text="ℹ️ Informations",
                              font=('Segoe UI', 11, 'bold'),
                              bg='white',
                              fg=COLORS['text_dark'])
        info_label.pack(anchor='w', pady=(0, 5))

        info_frame = tk.Frame(info_container, bg='#f3f4f6', relief='flat')
        info_frame.pack(fill=tk.BOTH, expand=True)

        self.info_label = tk.Text(info_frame,
                                  height=10,
                                  font=('Consolas', 9),
                                  wrap=tk.WORD,
                                  bg='#f3f4f6',
                                  fg=COLORS['text_dark'],
                                  relief='flat',
                                  bd=5,
                                  state=tk.DISABLED)
        self.info_label.pack(fill=tk.BOTH, expand=True)

        # Zone graphique (droite)
        graph_container = tk.Frame(main_container, bg='white', relief='solid', bd=1)
        graph_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.fig_2d = Figure(figsize=(12, 8), facecolor='white')
        self.ax_2d = self.fig_2d.add_subplot(111, facecolor='white')

        self.canvas_2d = FigureCanvasTkAgg(self.fig_2d, graph_container)
        self.canvas_2d.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.canvas_2d.mpl_connect('button_press_event', self.on_click)

        self.cbar_2d = None
        self.point_data = {}

    def create_calibration_workflow_tab(self):
        """NOUVEAU : Onglet workflow de calibration Energy"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text='⚡ Energy Calibration')

        # Container principal
        main_container = tk.Frame(tab, bg=COLORS['bg_light'])
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Panneau de contrôle (gauche)
        control_panel = tk.Frame(main_container, bg='white', relief='solid', bd=1)
        control_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        control_panel.config(width=350)
        control_panel.pack_propagate(False)

        # Header
        header = tk.Frame(control_panel, bg=COLORS['accent'], height=80)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        title_label = tk.Label(header,
                               text="⚡ Calibration",
                               font=('Segoe UI', 18, 'bold'),
                               bg=COLORS['accent'],
                               fg='white')
        title_label.pack(pady=20)

        # Instructions
        instr_frame = tk.Frame(control_panel, bg='white')
        instr_frame.pack(fill=tk.X, padx=15, pady=15)

        instr_label = tk.Label(instr_frame,
                               text="📋 Workflow :",
                               font=('Segoe UI', 11, 'bold'),
                               bg='white',
                               fg=COLORS['text_dark'])
        instr_label.pack(anchor='w', pady=(0, 5))

        instr_text = """1. Démarrer le processus
2. Pour chaque Delta_mm :
   - Observer la courbe
   - Cliquer sur le point d'inflexion
3. Valider ou passer
4. Tracer la calibration finale"""

        instr_detail = tk.Label(instr_frame,
                                text=instr_text,
                                justify=tk.LEFT,
                                font=('Segoe UI', 9),
                                bg='white',
                                fg=COLORS['text_light'])
        instr_detail.pack(anchor='w')
        auto_frame = tk.Frame(control_panel, bg='white')
        auto_frame.pack(fill=tk.X, padx=15, pady=(0, 6))
        tk.Checkbutton(auto_frame, text="Auto (sigmoïde) : choisir l’inflexion par fit",
                       variable=self.auto_pick_sigmoid, bg='white',
                       anchor='w').pack(fill=tk.X)

        # Bouton démarrer
        ttk.Button(control_panel, text="🚀 Démarrer la calibration",
                   command=self.start_calibration_workflow).pack(fill=tk.X, padx=15, pady=10)

        # Label du Delta actuel
        self.calib_current_label = tk.Label(control_panel,
                                            text="Cliquez sur 'Démarrer' pour commencer",
                                            font=('Segoe UI', 11),
                                            bg='white',
                                            fg=COLORS['text_dark'],
                                            justify=tk.LEFT)
        self.calib_current_label.pack(pady=10, padx=15)

        # Tableau des points calibrés
        tree_frame = tk.Frame(control_panel, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        tk.Label(tree_frame,
                 text="Points de calibration :",
                 font=('Segoe UI', 10, 'bold'),
                 bg='white',
                 fg=COLORS['text_dark']).pack(anchor='w', pady=(0, 5))

        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.calib_tree = ttk.Treeview(tree_frame,
                                       columns=('Gap', 'Threshold', 'Energy'),
                                       show='headings',
                                       yscrollcommand=scrollbar.set,
                                       height=10)
        self.calib_tree.heading('Gap', text='Gap (mm)')
        self.calib_tree.heading('Threshold', text='Threshold DAC')
        self.calib_tree.heading('Energy', text='Energy (MeV)')

        self.calib_tree.column('Gap', width=80)
        self.calib_tree.column('Threshold', width=90)
        self.calib_tree.column('Energy', width=100)

        self.calib_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.calib_tree.yview)

        # Séparateur
        sep = tk.Frame(control_panel, height=2, bg='#e5e7eb')
        sep.pack(fill=tk.X, padx=15, pady=10)

        # Boutons de navigation
        nav_frame = tk.Frame(control_panel, bg='white')
        nav_frame.pack(fill=tk.X, padx=15, pady=5)

        ttk.Button(nav_frame, text="⬅️ Précédent",
                   command=self.previous_calibration_point).pack(fill=tk.X, pady=2)
        ttk.Button(nav_frame, text="✅ Valider & Suivant",
                   command=self.validate_calibration_point).pack(fill=tk.X, pady=2)
        ttk.Button(nav_frame, text="⏭️ Passer",
                   command=self.skip_calibration_point).pack(fill=tk.X, pady=2)

        # Séparateur
        sep2 = tk.Frame(control_panel, height=2, bg='#e5e7eb')
        sep2.pack(fill=tk.X, padx=15, pady=10)


        # Boutons d'action finale
        action_frame = tk.Frame(control_panel, bg='white')
        action_frame.pack(fill=tk.X, padx=15, pady=5)

        ttk.Button(action_frame, text="📊 Tracer la calibration",
                   command=self.plot_final_calibration).pack(fill=tk.X, pady=2)
        ttk.Button(action_frame, text="💾 Sauvegarder",
                   command=self.save_calibration_results).pack(fill=tk.X, pady=2)
        ttk.Button(action_frame, text="▶ Auto pour tous les gaps",
                   command=self.auto_pick_all_gaps).pack(fill=tk.X, pady=2)
        # Zone graphique (droite) - pour afficher le résultat final
        self.graph_container_calib = tk.Frame(main_container, bg='white', relief='solid', bd=1)
        self.graph_container_calib.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Message initial
        self.initial_label_calib = tk.Label(self.graph_container_calib,
                                            text="📊 Workflow de calibration\n\n"
                                                 "1. Cliquez sur 'Démarrer la calibration'\n"
                                                 "2. Pour chaque courbe, cliquez sur le point d'inflexion\n"
                                                 "3. Validez et passez à la suivante\n"
                                                 "4. Tracez le résultat final",
                                            font=('Segoe UI', 12),
                                            bg='white',
                                            fg=COLORS['text_light'],
                                            justify=tk.LEFT)
        self.initial_label_calib.pack(expand=True, pady=50, padx=30)

        self.fig_calib = Figure(figsize=(12, 8), facecolor='white')
        self.ax_calib = self.fig_calib.add_subplot(111, facecolor='white')

        self.canvas_calib = FigureCanvasTkAgg(self.fig_calib, self.graph_container_calib)

        # Connecter l'événement de clic
        self.canvas_calib.mpl_connect('button_press_event', self.on_calibration_click)

        # Variables pour la sélection
        self.selected_inflection_point = None
        self.clicked_threshold = None

    def start_calibration_workflow(self):
        """Démarre le workflow de calibration"""
        self.calibration_deltas = self.deltas.copy()
        self.current_calibration_delta_index = 0
        self.calibration_points = {}

        # Vider le tableau
        for item in self.calib_tree.get_children():
            self.calib_tree.delete(item)

        messagebox.showinfo("Info",
                            f"Calibration démarrée pour {len(self.calibration_deltas)} Gaps\n\nPour chaque courbe :\n1. Cliquez sur le point d'inflexion\n2. Cliquez sur 'Valider & Suivant'")

        # Afficher la première courbe
        self.show_calibration_curve_in_gui()

    def show_calibration_curve_in_gui(self):
        """Affiche la courbe pour le Delta actuel dans l'IHM"""
        if self.current_calibration_delta_index >= len(self.calibration_deltas):
            messagebox.showinfo("Terminé",
                                f"{len(self.calibration_points)} points de calibration collectés !\n\nCliquez sur 'Tracer la calibration' pour voir le résultat.")
            return

        # Supprimer le label initial s'il existe
        if hasattr(self, 'initial_label_calib') and self.initial_label_calib.winfo_exists():
            self.initial_label_calib.destroy()

        # Afficher le canvas s'il ne l'est pas déjà
        if not self.canvas_calib.get_tk_widget().winfo_ismapped():
            self.canvas_calib.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        delta = self.calibration_deltas[self.current_calibration_delta_index]

        # Clear plot
        self.ax_calib.clear()
        self.selected_inflection_point = None
        self.clicked_threshold = None

        # Données
        df_delta = self.df[self.df['Delta_mm'] == delta].sort_values('Threshold_DAC')
        x_arr = df_delta['Threshold_DAC'].to_numpy(float)
        y_arr = df_delta['C0_Rate'].to_numpy(float)

        # Courbe
        self.ax_calib.plot(x_arr, y_arr, 'o-', markersize=10, linewidth=2.5,
                           color=COLORS['secondary'], markeredgecolor='black', markeredgewidth=1.5)

        # Config de base (titre/labels d'abord)
        energy, std, gap = self.find_closest_energy(delta)
        base_title = f"🎯 CLIQUEZ sur le point d'inflexion\n\nGap={delta:.1f} mm"
        self.ax_calib.set_xlabel('Threshold DAC', fontsize=13, fontweight='bold')
        self.ax_calib.set_ylabel('C0 Rate (Hits/s)', fontsize=13, fontweight='bold')
        self.ax_calib.set_title(base_title, fontsize=14, fontweight='bold', color=COLORS['primary'])
        self.ax_calib.grid(True, alpha=0.3, linestyle='--')
        self.ax_calib.invert_xaxis()
        self.ax_calib.set_ylim(0, np.nanmax(y_arr) * 1.1)
        self.ax_calib.set_xlim(np.nanmax(x_arr) * 1.05, 0)

        # Suggestion auto (fit sigmoïde)
        fitinfo = self._fit_sigmoid_for_gap(delta)
        if fitinfo is not None:
            self._draw_sigmoid_overlay(self.ax_calib, x_arr, y_arr, fitinfo)
            if self.auto_pick_sigmoid.get():
                self.clicked_threshold = int(fitinfo['x0'])
                # on complète le titre au lieu de l'écraser
                self.ax_calib.set_title(
                    base_title + f"\nAuto: DAC={self.clicked_threshold} (R²={fitinfo['r2']:.3f})",
                    fontsize=14, fontweight='bold', color=COLORS['primary']
                )

        # Label d’état à gauche
        self.calib_current_label.config(
            text=f"📍 Gap: {delta:.1f} mm\n⚡ Energy: {energy / 1e6:.2f} MeV\n\n"
                 f"Progression: {self.current_calibration_delta_index + 1}/{len(self.calibration_deltas)}"
        )

        self.canvas_calib.draw()

    def on_calibration_click(self, event):
        """Gère le clic sur la courbe de calibration"""
        if event.inaxes != self.ax_calib:
            return

        # Arrondir à l'entier le plus proche (DAC = entier)
        threshold_dac = int(round(event.xdata))

        # Supprimer l'ancien marqueur
        if hasattr(self, 'selected_inflection_point') and self.selected_inflection_point is not None:
            self.selected_inflection_point.remove()

        # Marquer le nouveau point (au DAC entier)
        self.selected_inflection_point = self.ax_calib.plot(threshold_dac, event.ydata,
                                                            'r*', markersize=25,
                                                            markeredgecolor='yellow',
                                                            markeredgewidth=2,
                                                            label=f'Point sélectionné (DAC={threshold_dac})')[0]
        self.ax_calib.legend(fontsize=11)
        self.canvas_calib.draw()

        self.clicked_threshold = threshold_dac
        print(f"✓ Point sélectionné : Threshold DAC = {threshold_dac}")

    def validate_calibration_point(self):
        """Valide le point sélectionné et passe au suivant"""
        if (not hasattr(self, 'clicked_threshold')) or (self.clicked_threshold is None):
            # Si auto activé, on tente l’auto-pick pour ce gap
            if self.auto_pick_sigmoid.get():
                delta = self.calibration_deltas[self.current_calibration_delta_index]
                info = self._fit_sigmoid_for_gap(delta)
                if info is not None:
                    self.clicked_threshold = int(info['x0'])
                else:
                    messagebox.showwarning("Attention", "Veuillez d'abord cliquer sur un point de la courbe")
                    return
            else:
                messagebox.showwarning("Attention", "Veuillez d'abord cliquer sur un point de la courbe")
                return

        delta = self.calibration_deltas[self.current_calibration_delta_index]
        energy, std, gap = self.find_closest_energy(delta)

        self.calibration_points[delta] = {
            'threshold': self.clicked_threshold,
            'energy': energy,
            'std': std,
            'gap': gap
        }

        # Ajouter au tableau
        self.calib_tree.insert('', 'end', values=(
            f"{delta:.1f}",
            f"{int(self.clicked_threshold)}",
            f"{energy / 1e6:.3f}"
        ))

        print(
            f"✓ Point validé : Gap={delta:.1f} mm, Threshold DAC={int(self.clicked_threshold)}, Energy={energy / 1e6:.2f} MeV")

        # Passer au suivant
        self.current_calibration_delta_index += 1
        self.show_calibration_curve_in_gui()

    def skip_calibration_point(self):
        """Passe au Delta suivant sans valider"""
        print(f"⏭️ Gap {self.calibration_deltas[self.current_calibration_delta_index]:.1f} mm ignoré")
        self.current_calibration_delta_index += 1
        self.show_calibration_curve_in_gui()

    def previous_calibration_point(self):
        """Revient au Delta précédent"""
        if self.current_calibration_delta_index > 0:
            self.current_calibration_delta_index -= 1

            # Retirer le dernier point du tableau si nécessaire
            delta = self.calibration_deltas[self.current_calibration_delta_index]
            if delta in self.calibration_points:
                del self.calibration_points[delta]
                # Retirer du tableau
                items = self.calib_tree.get_children()
                if items:
                    self.calib_tree.delete(items[-1])

            self.show_calibration_curve_in_gui()
        else:
            messagebox.showinfo("Info", "Déjà au début")

    def show_calibration_curve_matplotlib(self, delta):
        """Cette fonction n'est plus utilisée"""
        pass

    def plot_final_calibration(self):
        """Trace la courbe de calibration finale Energy vs Threshold"""
        if not self.calibration_points:
            messagebox.showwarning("Attention", "Aucun point de calibration")
            return

        # Supprimer le label initial s'il existe
        if hasattr(self, 'initial_label_calib') and self.initial_label_calib.winfo_exists():
            self.initial_label_calib.destroy()

        # Afficher le canvas s'il ne l'est pas déjà
        if not self.canvas_calib.get_tk_widget().winfo_ismapped():
            self.canvas_calib.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Clear
        self.ax_calib.clear()

        # Préparer les données
        gaps = []
        thresholds = []
        energies = []
        energy_stds = []

        for gap in sorted(self.calibration_points.keys()):
            point = self.calibration_points[gap]
            gaps.append(gap)
            thresholds.append(int(point['threshold']))
            energies.append(point['energy'])
            energy_stds.append(point['std'])

        # Tracer
        threshold_limit = 245
        ymin, ymax = min(energies) * 0.9, max(energies) * 1.1

        self.ax_calib.fill_between([threshold_limit, max(thresholds) * 1.1],
                                   [ymin, ymin],
                                   [ymax, ymax],
                                   color='gray', alpha=0.3,
                                   label='Threshold > Noise')

        self.ax_calib.plot(thresholds, energies, 'ko', markersize=8, label='Data points')

        # Barres d'erreur
        threshold_stds = [5] * len(thresholds)
        self.ax_calib.errorbar(thresholds, energies, xerr=threshold_stds, yerr=None,
                               fmt='none', ecolor='red', capsize=5, label='Threshold σ')
        self.ax_calib.errorbar(thresholds, energies, xerr=None, yerr=energy_stds,
                               fmt='none', ecolor='blue', capsize=5, label='Energy σ')

        # Régression linéaire
        weights = 1 / np.array(energy_stds)
        coeffs = np.polyfit(thresholds, energies, 1, w=weights)
        fit_line = np.poly1d(coeffs)
        thresh_range = np.linspace(min(thresholds), max(thresholds), 100)

        correlation_coef = np.corrcoef(thresholds, energies)[0, 1]
        N = len(thresholds)
        sigma_slope = np.sqrt(1 / (N - 2) * np.sum((energies - fit_line(thresholds)) ** 2) /
                              np.sum((thresholds - np.mean(thresholds)) ** 2))

        self.ax_calib.plot(thresh_range, fit_line(thresh_range), 'k--', linewidth=2,
                           label=f'y = ({coeffs[0]:.2e} ± {sigma_slope:.2e})x + {coeffs[1]:.2e}\nR² = {correlation_coef ** 2:.3f}')

        # Annotations
        for g, t, e in zip(gaps, thresholds, energies):
            self.ax_calib.annotate(f'{g:.1f}mm', (t, e), xytext=(5, 5),
                                   textcoords='offset points', fontsize=9)

        self.ax_calib.set_xlim(min(thresholds) * 0.9, 255)
        self.ax_calib.set_ylim(ymin, ymax)
        self.ax_calib.set_xlabel('Threshold', fontsize=12, fontweight='bold')
        self.ax_calib.set_ylabel('Energy (eV)', fontsize=12, fontweight='bold')
        self.ax_calib.set_title('Energy vs Threshold - Calibration Curve', fontsize=14, fontweight='bold')
        self.ax_calib.grid(True, alpha=0.3)
        self.ax_calib.legend(loc='upper right', fontsize=10)

        # Afficher les infos de la régression
        info_text = (f'Équation : y = ({coeffs[0]:.3e})x + ({coeffs[1]:.3e})\n'
                     f'R² = {correlation_coef ** 2:.4f}\n'
                     f'σ(pente) = {sigma_slope:.3e}')
        self.ax_calib.text(0.02, 0.98, info_text, transform=self.ax_calib.transAxes,
                           fontsize=10, verticalalignment='top',
                           bbox=dict(facecolor='white', alpha=0.8, edgecolor='gray'))

        self.canvas_calib.draw()

        # Ajouter la toolbar si elle n'existe pas
        if not hasattr(self, 'toolbar_calib'):
            self.toolbar_calib = NavigationToolbar2Tk(self.canvas_calib, self.graph_container_calib)
            self.toolbar_calib.update()

        messagebox.showinfo("Succès", f"Calibration tracée avec {len(self.calibration_points)} points !")

    def save_calibration_results(self):
        """Sauvegarder les résultats"""
        if not self.calibration_points:
            messagebox.showwarning("Attention", "Aucun point à sauvegarder")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'energy_calibration_{timestamp}.csv'

        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Gap (mm)', 'Threshold DAC', 'Energy (eV)', 'Std Dev (eV)'])

            for delta in sorted(self.calibration_points.keys()):
                point = self.calibration_points[delta]
                writer.writerow([
                    f"{delta:.1f}",
                    f"{int(point['threshold'])}",
                    f"{point['energy']:.2f}",
                    f"{point['std']:.2f}"
                ])

        messagebox.showinfo("Succès", f"Résultats sauvegardés dans {filename}")

    def plot_3d(self):
        """Trace le graphique 3D"""
        if self.df.empty:
            # Afficher un message dans le canvas
            self.ax_3d.text(0.5, 0.5, 0.5, 'Aucune donnée chargée',
                            transform=self.ax_3d.transAxes,
                            ha='center', va='center', fontsize=14)
            self.canvas_3d.draw()
            return

        self.ax_3d.clear()

        x = self.df['Delta_mm'].values
        y = self.df['Threshold_DAC'].values
        z = self.df['C0_Rate'].values

        scatter = self.ax_3d.scatter(x, y, z, c=z, cmap='plasma', s=50, alpha=0.7,
                                     edgecolors='white', linewidth=0.5, depthshade=True)

        for delta in self.deltas:
            df_delta = self.df[self.df['Delta_mm'] == delta].sort_values('Threshold_DAC')
            self.ax_3d.plot(df_delta['Delta_mm'].values,
                            df_delta['Threshold_DAC'].values,
                            df_delta['C0_Rate'].values,
                            color='#6b7280', alpha=0.3, linewidth=1.5)

        self.ax_3d.set_xlabel('Delta (mm)', fontsize=11, fontweight='bold', labelpad=10)
        self.ax_3d.set_ylabel('Threshold DAC', fontsize=11, fontweight='bold', labelpad=10)
        self.ax_3d.set_zlabel('C0 Rate (Hits/s)', fontsize=11, fontweight='bold', labelpad=10)
        self.ax_3d.set_title('Vue 3D - Ensemble des scans', fontsize=14, fontweight='bold',
                             pad=15, color=COLORS['primary'])

        cbar = self.fig_3d.colorbar(scatter, ax=self.ax_3d, shrink=0.6, aspect=8, pad=0.08)
        cbar.set_label('C0 Rate (Hits/s)', fontsize=10, fontweight='bold')

        self.ax_3d.view_init(elev=25, azim=45)
        self.ax_3d.grid(True, alpha=0.2, linestyle='--', linewidth=0.5)

        self.canvas_3d.draw()

    def on_delta_select(self, event):
        """Callback sélection Delta 2D"""
        selection = self.delta_listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        self.selected_delta = self.deltas[idx]
        self.plot_2d_curve()
        self.update_info()

    def plot_2d_curve(self):
        """Trace la courbe 2D"""
        if self.selected_delta is None:
            return

        # Clear complet de la figure pour éviter les problèmes d'accumulation
        self.ax_2d.clear()
        self.point_data.clear()

        # Supprimer l'ancienne colorbar si elle existe
        if self.cbar_2d is not None:
            try:
                self.cbar_2d.remove()
            except:
                pass
            self.cbar_2d = None

        # Réinitialiser la figure pour éviter les décalages
        self.fig_2d.clear()
        self.ax_2d = self.fig_2d.add_subplot(111, facecolor='white')

        df_delta = self.df[self.df['Delta_mm'] == self.selected_delta].sort_values('Threshold_DAC')

        points = self.ax_2d.scatter(df_delta['Threshold_DAC'], df_delta['C0_Rate'],
                                    c=df_delta['C0_Rate'], cmap='viridis', s=120,
                                    edgecolors='white', linewidth=2, zorder=3, alpha=0.9)

        self.ax_2d.plot(df_delta['Threshold_DAC'], df_delta['C0_Rate'],
                        color=COLORS['secondary'], linewidth=2.5, alpha=0.6, zorder=2)

        for _, row in df_delta.iterrows():
            key = f"{self.selected_delta}_{row['Threshold_DAC']}"
            self.point_data[key] = {
                'x': row['Threshold_DAC'],
                'y': row['C0_Rate'],
                'gap': self.selected_delta,
                'threshold': int(row['Threshold_DAC'])
            }
        # Option : montrer l’inflexion estimée pour ce gap
        fitinfo = self._fit_sigmoid_for_gap(self.selected_delta)
        if fitinfo is not None:
            x_arr = df_delta['Threshold_DAC'].to_numpy(float)
            y_arr = df_delta['C0_Rate'].to_numpy(float)
            self._draw_sigmoid_overlay(self.ax_2d, x_arr, y_arr, fitinfo)

        self.ax_2d.set_xlabel('Threshold DAC', fontsize=12, fontweight='bold')
        self.ax_2d.set_ylabel('C0 Rate (Hits/s)', fontsize=12, fontweight='bold')
        self.ax_2d.set_title(f'Gap={self.selected_delta} mm\nCliquez sur un point pour histogramme',
                             fontsize=12, fontweight='bold', color=COLORS['primary'])
        self.ax_2d.grid(True, alpha=0.2, linestyle='--')
        self.ax_2d.invert_xaxis()

        # Colorbar
        self.cbar_2d = self.fig_2d.colorbar(points, ax=self.ax_2d, aspect=30, pad=0.02)
        self.cbar_2d.set_label('C0 Rate (Hits/s)', fontsize=9, fontweight='bold')

        # IMPORTANT : tight_layout pour éviter les décalages
        self.fig_2d.tight_layout()
        self.canvas_2d.draw()

    def on_click(self, event):
        """Callback clic 2D"""
        if event.inaxes != self.ax_2d or not self.point_data:
            return

        min_dist = float('inf')
        closest_point = None

        for key, data in self.point_data.items():
            xlim = self.ax_2d.get_xlim()
            ylim = self.ax_2d.get_ylim()
            x_norm = (event.xdata - data['x']) / (xlim[0] - xlim[1])
            y_norm = (event.ydata - data['y']) / (ylim[1] - ylim[0])
            dist = x_norm ** 2 + y_norm ** 2

            if dist < min_dist:
                min_dist = dist
                closest_point = key

        if closest_point and min_dist < 0.01:
            gap = self.point_data[closest_point]['gap']
            threshold = self.point_data[closest_point]['threshold']
            self.show_histogram(gap, threshold)

    def show_histogram(self, gap, threshold):
        """Lance superposition.py avec le fichier .dat correspondant"""
        try:
            # Construire le chemin du dossier : wavecatcher_files/gap_XX.Xmm/
            gap_folder = os.path.join(WAVECATCHER_FOLDER, f"gap_{gap}mm")

            if not os.path.exists(gap_folder):
                messagebox.showerror("Erreur", f"Dossier introuvable : {gap_folder}")
                return

            # Chercher le fichier avec le pattern : *DAC{threshold}airgap-{gap}.dat
            # Pattern : abeastscandata*DAC255airgap-29.5.dat
            pattern = f"*DAC{threshold}airgap{gap}.dat"
            dat_files = glob.glob(os.path.join(gap_folder, pattern))

            if not dat_files:
                messagebox.showerror("Erreur",
                                     f"Fichier .dat introuvable pour :\n"
                                     f"Gap = {gap} mm\n"
                                     f"Threshold = {threshold}\n"
                                     f"Dossier : {gap_folder}\n"
                                     f"Pattern : {pattern}")
                return

            # Prendre le premier fichier trouvé
            dat_file = dat_files[0]

            print(f"📊 Ouverture : {os.path.basename(dat_file)}")
            print(f"   Gap={gap} mm, Threshold DAC={threshold}")

            # Lancer superposition.py
            script_dir = os.path.dirname(os.path.abspath(__file__))
            superposition_path = os.path.join(script_dir, SUPERPOSITION_SCRIPT_NAME)

            if os.path.exists(superposition_path):
                subprocess.Popen([sys.executable, superposition_path, dat_file])
            else:
                messagebox.showerror("Erreur", f"Script introuvable : {superposition_path}")

        except Exception as e:
            print(f"❌ Erreur: {e}")
            messagebox.showerror("Erreur", f"Erreur lors de l'ouverture du fichier .dat:\n{e}")

    def update_info(self):
        """Met à jour les infos"""
        if self.selected_delta is None:
            return

        df_delta = self.df[self.df['Delta_mm'] == self.selected_delta]

        info_text = f"""
╔══════════════════════════╗
║   PARAMÈTRES DE MESURE   ║
╚══════════════════════════╝

📏 Gap          : {self.selected_delta:>6.1f} mm
📊 Points       : {len(df_delta):>6} mesures

─────────────────────────────
⚡ Threshold DAC
   • Minimum    : {df_delta['Threshold_DAC'].min():>6.0f}
   • Maximum    : {df_delta['Threshold_DAC'].max():>6.0f}

─────────────────────────────
📈 C0 Rate (Hits/s)
   • Minimum    : {df_delta['C0_Rate'].min():>6.2f}
   • Maximum    : {df_delta['C0_Rate'].max():>6.2f}
   • Moyenne    : {df_delta['C0_Rate'].mean():>6.2f}
        """

        self.info_label.config(state=tk.NORMAL)
        self.info_label.delete(1.0, tk.END)
        self.info_label.insert(1.0, info_text)
        self.info_label.config(state=tk.DISABLED)


def main():
    root = tk.Tk()
    app = ScanViewerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
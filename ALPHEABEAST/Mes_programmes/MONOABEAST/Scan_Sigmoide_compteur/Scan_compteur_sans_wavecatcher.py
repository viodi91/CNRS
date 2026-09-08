# -*- coding: utf-8 -*-
"""
AlphaBeast - Scan compteur sans WaveCatcher

Version simplifiée :
- Pas de pyautogui
- Pas de cv2
- Pas de reconnaissance d'image
- Pas de WaveCatcher

Principe :
1) Home moteur.
2) Aller à 87.3 mm.
3) Pour chaque position jusqu'à 97.3 mm, par pas de 1 mm :
   - scanner les DAC depuis 245 vers le bas ;
   - pour chaque DAC, compter C0 pendant un temps choisi par l'utilisateur ;
   - calculer C0_Hits/s ;
   - arrêter le scan DAC dès que C0_Rate < 1 coup/s.
4) Sauvegarder toutes les mesures dans un CSV.
"""

import csv
import os
import subprocess
import time
from datetime import datetime

import serial
import serial.tools.list_ports


# ============================================================
# PARAMÈTRES GÉNÉRAUX
# ============================================================

ip_add = "192.168.137.2"

MATRIX = 5

# Registres AlphaBeast
VTH_BASELINE_REG = 3
TH0_REG = 4
TH1_REG = 5
TH2_REG = 6

# On mesure TH0 -> compteur C0
THRESHOLD_REG = TH0_REG
COUNTER_INDEX = 0
COUNTER_MODULO = 2 ** 24

VTH_BASELINE_DAC = 107

# Positions moteur
START_POSITION = 87.3
END_POSITION = 97.3
POSITION_STEP = 1.0
MAX_POSITION = 127.3

# Scan DAC
DAC_START = 255
DAC_MIN = 0
DAC_STEP = -1
STOP_RATE = 0.1  # coups/s

# Temps d'attente moteur
MOTOR_BAUDRATE = 115200
HOME_SETTLE_S = 40
START_POSITION_SETTLE_S = 50
STEP_SETTLE_S = 10


# ============================================================
# CSV
# ============================================================

def create_csv_file(base_file_name):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"{base_file_name}_counter_results_{timestamp}.csv"

    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Position_mm",
            "Delta_mm",
            "Threshold_DAC",
            "Temps_integration_demande_s",
            "Temps_mesure_reel_s",
            "C0_initial",
            "C0_final",
            "C0_Hits",
            "C0_Rate",
            "Status",
        ])

    print(f"Fichier CSV créé : {csv_filename}")
    return csv_filename


def append_to_csv(csv_filename, position, delta, threshold, integration_time,
                  measured_time, c0_initial, c0_final, c0_hits, c0_rate,
                  status="SUCCESS"):
    with open(csv_filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            f"{position:.1f}" if position is not None else "NA",
            f"{delta:.1f}" if delta is not None else "NA",
            threshold if threshold is not None else "NA",
            f"{integration_time:.2f}" if integration_time is not None else "NA",
            f"{measured_time:.2f}" if measured_time is not None else "NA",
            c0_initial if c0_initial is not None else "NA",
            c0_final if c0_final is not None else "NA",
            c0_hits if c0_hits is not None else "NA",
            f"{c0_rate:.3f}" if c0_rate is not None else "NA",
            status,
        ])


# ============================================================
# COMMANDES ALPHABEAST VIA SSH
# ============================================================

def run_abeast_command(args):
    """
    Exécute abeast_m5_counter.py sur le Raspberry Pi.

    Cette forme évite les problèmes de chemin :
    on se place d'abord dans ~/abeast, puis on lance le script.
    """
    cmd = f"ssh pi@{ip_add} \"cd ~/abeast && ./abeast_m5_counter.py {args}\""
    return subprocess.check_output(cmd, shell=True).decode("utf-8", errors="ignore")


def load_counter_firmware():
    """
    Équivalent propre de :
    abeast_m5_counter.py -f mypol6_x2
    exécuté depuis ~/abeast.
    """
    print("Chargement/reset firmware compteur AlphaBeast...")
    return run_abeast_command("-f mypol6_x2")


def set_register(matrix, reg, value):
    run_abeast_command(f"-w {matrix} {reg} {value}")


def set_threshold_dac(dac_value):
    set_register(MATRIX, THRESHOLD_REG, dac_value)


def disable_thresholds():
    set_register(MATRIX, TH0_REG, 0)
    time.sleep(0.5)
    set_register(MATRIX, TH1_REG, 0)
    time.sleep(0.5)
    set_register(MATRIX, TH2_REG, 0)
    time.sleep(0.5)


def prepare_abeast():
    print("Configuration AlphaBeast...")

    set_register(MATRIX, VTH_BASELINE_REG, VTH_BASELINE_DAC)
    time.sleep(1)

    disable_thresholds()
    time.sleep(1)

    run_abeast_command(f"-t {MATRIX}")
    time.sleep(1)

    print("Configuration AlphaBeast terminée.")


def read_singlecounter(matrix, cnt):
    """
    Lit un compteur spécifique avec -v.
    cnt = 0 -> C0
    cnt = 1 -> C1
    cnt = 2 -> C2
    """
    output = ""

    try:
        output = run_abeast_command(f"-v {matrix}")
        lines = output.split("\n")

        for i, line in enumerate(lines):
            if "counter0" in line:
                counter_line = lines[i + 2].strip()
                counter_values = [
                    int(x) for x in counter_line.strip("|").split()
                    if x.strip().isdigit()
                ]
                return counter_values[cnt]

        raise ValueError("Impossible de trouver les valeurs des compteurs dans la sortie.")

    except Exception as e:
        print(f"Erreur lors de la lecture du compteur {cnt}: {e}")
        print(f"Sortie complète :\n{output}")
        raise


def compute_counter_delta(initial_count, final_count):
    """
    Gestion de l'overflow compteur 24 bits.
    """
    if final_count >= initial_count:
        return final_count - initial_count
    return COUNTER_MODULO + final_count - initial_count


# ============================================================
# MOTEUR
# ============================================================

def send_serial_command(ser, command, wait_time=0.5):
    ser.reset_input_buffer()

    print(f"Commande moteur : {command}")
    ser.write(f"{command}\r\n".encode())
    time.sleep(wait_time)

    response = ""
    timeout = time.time() + 3

    while time.time() < timeout:
        if ser.in_waiting > 0:
            response += ser.read(ser.in_waiting).decode(errors="ignore")
        time.sleep(0.1)

    if response:
        print(f"Réponse moteur : {response.strip()}")

    return response


def find_motor_serial_port(baudrate=115200):
    print("Recherche du port série du moteur...")
    ports = serial.tools.list_ports.comports()

    if not ports:
        print("Aucun port série détecté sur le système.")
        return None

    print(f"Ports disponibles : {[port.device for port in ports]}")

    for port in ports:
        ser = None

        try:
            print(f"Test du port {port.device}...")
            ser = serial.Serial(port.device, baudrate, timeout=2)
            time.sleep(4)

            response = ""
            while ser.in_waiting > 0:
                response += ser.read(ser.in_waiting).decode(errors="ignore")
                time.sleep(0.1)

            print(f"Réponse du port {port.device} : {response.strip()}")

            if "INITIALIZE" in response or "STARTED" in response:
                print(f"Moteur détecté sur {port.device}")
                return ser

            ser.write(b"help\r\n")
            time.sleep(0.5)

            response = ""
            while ser.in_waiting > 0:
                response += ser.read(ser.in_waiting).decode(errors="ignore")
                time.sleep(0.1)

            if "home" in response.lower() and "move" in response.lower():
                print(f"Moteur détecté sur {port.device}")
                return ser

            ser.close()

        except (serial.SerialException, UnicodeDecodeError) as e:
            print(f"Erreur sur {port.device}: {e}")
            if ser and ser.is_open:
                ser.close()
            continue

    print("Aucun moteur détecté sur les ports disponibles.")
    return None


def init_motor_serial(baudrate=115200):
    ser = find_motor_serial_port(baudrate)
    if ser:
        print("Moteur initialisé avec succès.")
    return ser


def motor_home(ser):
    send_serial_command(ser, "home x", wait_time=2)


def motor_move_relative(ser, distance_mm):
    send_serial_command(ser, f"move x -r {distance_mm}", wait_time=1)


# ============================================================
# MESURE COMPTEUR SANS WAVECATCHER
# ============================================================

def measure_counter_rate(dac_value, integration_time_s):
    """
    Mesure C0 pendant integration_time_s secondes.

    Étapes :
    1) Applique le DAC.
    2) Attend 0.5 s de stabilisation.
    3) Lit C0 initial.
    4) Attend integration_time_s.
    5) Lit C0 final.
    6) Calcule hits et hits/s.
    7) Remet TH0 à 0.
    """
    set_threshold_dac(dac_value)
    time.sleep(0.5)

    c0_initial = read_singlecounter(MATRIX, COUNTER_INDEX)
    start_time = time.time()

    time.sleep(integration_time_s)

    end_time = time.time()
    c0_final = read_singlecounter(MATRIX, COUNTER_INDEX)

    measured_time = end_time - start_time
    c0_hits = compute_counter_delta(c0_initial, c0_final)
    c0_rate = c0_hits / measured_time if measured_time > 0 else 0.0

    set_threshold_dac(0)

    return c0_initial, c0_final, c0_hits, measured_time, c0_rate


def scan_dacs_at_position(position, csv_filename, integration_time_s):
    delta = MAX_POSITION - position
    dac_value = DAC_START

    while dac_value >= DAC_MIN:
        print("\n" + "-" * 60)
        print(f"Position = {position:.1f} mm | Delta = {delta:.1f} mm | DAC = {dac_value}")
        print(f"Temps d'intégration demandé = {integration_time_s:.2f} s")

        try:
            c0_initial, c0_final, c0_hits, measured_time, c0_rate = measure_counter_rate(
                dac_value=dac_value,
                integration_time_s=integration_time_s,
            )

            print(f"C0 initial = {c0_initial}")
            print(f"C0 final   = {c0_final}")
            print(f"C0 hits    = {c0_hits}")
            print(f"Temps réel = {measured_time:.2f} s")
            print(f"C0 rate    = {c0_rate:.3f} coups/s")

            append_to_csv(
                csv_filename=csv_filename,
                position=position,
                delta=delta,
                threshold=dac_value,
                integration_time=integration_time_s,
                measured_time=measured_time,
                c0_initial=c0_initial,
                c0_final=c0_final,
                c0_hits=c0_hits,
                c0_rate=c0_rate,
                status="SUCCESS",
            )

            if c0_rate < STOP_RATE:
                print(f"Arrêt scan DAC : {c0_rate:.3f} coups/s < {STOP_RATE:.3f} coup/s")
                break

        except Exception as e:
            print(f"Erreur mesure position {position:.1f} mm | DAC {dac_value}: {e}")

            append_to_csv(
                csv_filename=csv_filename,
                position=position,
                delta=delta,
                threshold=dac_value,
                integration_time=integration_time_s,
                measured_time=None,
                c0_initial=None,
                c0_final=None,
                c0_hits=None,
                c0_rate=None,
                status="ERROR",
            )

            try:
                set_threshold_dac(0)
            except Exception:
                pass

            break

        dac_value += DAC_STEP

    try:
        set_threshold_dac(0)
    except Exception:
        pass

    return True


# ============================================================
# MAIN
# ============================================================

def main():
    ser = None

    try:
        base_file_name = input("Entrez le nom de base du fichier CSV : ").strip()
        if not base_file_name:
            base_file_name = "alphabeast_counter_scan"

        integration_time_s = float(input("Temps d'intégration par DAC en secondes : ").replace(",", "."))
        if integration_time_s <= 0:
            print("Le temps d'intégration doit être supérieur à 0.")
            return

        csv_filename = create_csv_file(base_file_name)

        ser = init_motor_serial(MOTOR_BAUDRATE)
        if ser is None:
            print("Impossible d'initialiser le moteur. Arrêt du programme.")
            return

        motor_home(ser)
        time.sleep(HOME_SETTLE_S)

        load_counter_firmware()
        time.sleep(40)

        prepare_abeast()

        motor_move_relative(ser, START_POSITION)
        current_position = START_POSITION
        print(f"Moteur initialisé à la position : {current_position:.1f} mm")
        time.sleep(START_POSITION_SETTLE_S)

        while current_position <= END_POSITION + 1e-9:
            print("\n" + "=" * 70)
            print(f"POSITION ACTUELLE : {current_position:.1f} mm")
            print(f"DELTA = {MAX_POSITION - current_position:.1f} mm")
            print("=" * 70)

            scan_dacs_at_position(
                position=current_position,
                csv_filename=csv_filename,
                integration_time_s=integration_time_s,
            )

            next_position = round(current_position + POSITION_STEP, 1)

            if next_position <= END_POSITION + 1e-9:
                print(f"\nAvancement moteur de {POSITION_STEP:.1f} mm vers {next_position:.1f} mm...")
                motor_move_relative(ser, POSITION_STEP)
                current_position = next_position
                time.sleep(STEP_SETTLE_S)
            else:
                break

        print("\nReset final AlphaBeast...")
        load_counter_firmware()

        print("Retour home moteur...")
        motor_home(ser)

        print("\n" + "=" * 70)
        print("Fin du programme.")
        print(f"Résultats enregistrés dans : {csv_filename}")
        print(f"Chemin complet : {os.path.abspath(csv_filename)}")
        print("=" * 70)

    except KeyboardInterrupt:
        print("\nArrêt manuel par l'utilisateur.")

    except ValueError:
        print("Erreur : le temps d'intégration doit être un nombre.")

    except Exception as e:
        print(f"Une erreur inattendue s'est produite : {e}")

    finally:
        try:
            disable_thresholds()
        except Exception:
            pass

        if ser and ser.is_open:
            ser.close()
            print("Connexion série fermée.")


if __name__ == "__main__":
    main()

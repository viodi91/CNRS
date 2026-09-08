import pyautogui
import time
import os
import cv2
import csv
from datetime import datetime
import numpy as np
from Image_process import image_processor
import serial
import serial.tools.list_ports
import subprocess
# Chemins des images
wavecatcher_window = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\wavecatcher_window.png'
green_button = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\play_button.png'
confirmation_window = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\confirmation.png'
save_window = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\save_window.png'
config_button = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\configuration.png'
saving_data_option = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\saving_data_option.png'
raw_rate_checked = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\raw_rate_checked.png'
raw_rate_unchecked = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\raw_rate_unchecked.png'
stop_button = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\stop_button.png'
measurement_button = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\measurement.png'
rate_statistics_button = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\measurement_raw_rate_stat.png'
rate_statistics_checked = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\rate_statistics_checked.png'
rate_statistics_unchecked = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\rate_statistics_unchecked.png'
raw_count_hits_checked = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\raw_hit_checked.png'
raw_count_hits_unchecked = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\raw_hit_unchecked.png'
quit_button = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\quit.png'
end_acquisition_image = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\end3.png'
end_acquisition_image_2 = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\end4.png'
end_acquisition_image_3 = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\endpossible.png'

trigger_window = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\triggerwindow.png'
trigger= r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\trigger.png'
main_window = r'C:\Users\higueret_adm\PycharmProjects\Wave_catch_this\templates_to_find\mainwindow.png'
alfabeastcounter0=[]
#gain fois 1 tableau equivalence dac value et tension R8 = 5
# thresholds = {
#     255: 0,
#     250: -0.013,
#     240: -0.043,
#     230: -0.078,
#     220: -0.109,
#     210: -0.135,
#     200: -0.16,
#     190: -0.175,
#     180: -0.198,
#     170: -0.23,
#     160: -0.258,
#     150: -0.286,
#     140: -0.317,
#     130: -0.343,
#     120: -0.384,
#     100: -0.409,
#     90: -0.443,
#     80: -0.463
# }
ip_add = "192.168.137.2"


def create_csv_file(base_file_name):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"{base_file_name}_results_{timestamp}.csv"

    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Position_mm',
            'Delta_mm',
            'Threshold_DAC',
            'Temps_ecoule_s',
            'C0_Hits',
            'C0_Rate',
            'Fichier',
            'Status'
        ])
    print(f"Fichier CSV créé : {csv_filename}")
    return csv_filename

def append_to_csv(csv_filename, position, delta, threshold, elapsed_time,
                  c0_hits, c0_rate,
                  file_name, status='SUCCESS'):
    """
    Ajoute une ligne avec tous les compteurs au fichier CSV
    """
    with open(csv_filename, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            position,
            delta,
            threshold,
            f"{elapsed_time:.2f}" if elapsed_time is not None else 'NA',
            c0_hits if c0_hits is not None else 'NA',


            f"{c0_rate:.2f}" if c0_rate is not None else 'NA',

            file_name,
            status
        ])
def check_image_exists(image_path):
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"L'image '{image_path}' n'existe pas. Veuillez vérifier le chemin d'accès.")


def wait_for_acquisition_end(end_acquisition_img_proc, timeout=7200):
    print("Attente de la fin de l'acquisition...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        screenshot = pyautogui.screenshot()
        screenshot_np = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        found_images = end_acquisition_img_proc.find_img_in_color_HSV(screenshot_np, 0.99)
        found_images_2 = end_acquisition_img_proc.find_img_in_color_HSV(screenshot_np, 0.99)
        if found_images:
            print("Fin de l'acquisition détectée!")
            return True
        time.sleep(1)
    print(f"Timeout: La fin de l'acquisition n'a pas été détectée après {timeout} secondes.")
    return False


def locate_and_click(img_proc, confidence=0.8, timeout=5, click=True, region=None, double_click=False):
    start_time = time.time()
    while time.time() - start_time < timeout:
        screenshot = pyautogui.screenshot(region=region)
        screenshot_np = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        found_images = img_proc.find_img_in_color_HSV(screenshot_np, confidence)
        if found_images:
            x, y = found_images[0]['X'], found_images[0]['Y']
            if region:
                x += region[0]
                y += region[1]
            if click:
                if double_click:
                    pyautogui.doubleClick(x + img_proc.img_width // 2, y + img_proc.img_height // 2)
                else:
                    pyautogui.click(x + img_proc.img_width // 2, y + img_proc.img_height // 2)
            else:
                pyautogui.moveTo(x + img_proc.img_width // 2, y + img_proc.img_height // 2)
            return True, (x, y)
        time.sleep(0.5)
    print(f"Image '{img_proc.img_name}' non trouvée à l'écran après {timeout} secondes.")
    return False, None


def locate_and_click_with_retry(img_proc, max_retries=3, confidence=0.8, timeout=5, click=True):
    """
    Tente de localiser et cliquer avec plusieurs essais
    """
    for attempt in range(max_retries):
        if attempt > 0:
            print(f"Tentative {attempt + 1}/{max_retries} pour {img_proc.img_name}...")
            time.sleep(2)  # Pause entre les tentatives

        success, pos = locate_and_click(img_proc, confidence, timeout, click)
        if success:
            return True, pos

    print(f"Échec après {max_retries} tentatives pour {img_proc.img_name}")
    return False, None
def alt_tab(times):
    pyautogui.keyDown('alt')
    for _ in range(times):
        pyautogui.press('tab')
        time.sleep(0.1)
    pyautogui.keyUp('alt')
    time.sleep(0.5)
def stop_acquisition():
    """
    Arrête l'acquisition en cours en cliquant sur le bouton stop
    """
    stop_button_img_proc = image_processor(stop_button)
    success, _ = locate_and_click_with_retry(stop_button_img_proc, max_retries=3)
    if success:
        print("Acquisition arrêtée avec succès")
        time.sleep(2)  # Attendre que l'arrêt soit effectif
    else:
        print("⚠️ Impossible d'arrêter l'acquisition, bouton stop non trouvé")
    return success

def find_wavecatcher_window(wavecatcher_img_proc, max_attempts=10):
    for attempt in range(1, max_attempts + 1):
        print(f"Tentative {attempt}")
        alt_tab(attempt)
        time.sleep(1)  # Attendre que la fenêtre soit complètement visible

        success, _ = locate_and_click(wavecatcher_img_proc, confidence=0.8, click=False)
        if success:
            print(f"Fenêtre WaveCatcher trouvée après {attempt} tentatives.")
            return True

        print("Fenêtre non trouvée, passage à la suivante...")

    print("Fenêtre WaveCatcher non trouvée après plusieurs tentatives.")
    return False


def is_checkbox_checked(checked_img_proc, unchecked_img_proc, confidence=0.95, region=None):
    screenshot = pyautogui.screenshot(region=region)
    screenshot_np = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    checked_result = checked_img_proc.find_img_in_color_HSV(screenshot_np, confidence)
    unchecked_result = unchecked_img_proc.find_img_in_color_HSV(screenshot_np, confidence)

    if checked_result and not unchecked_result:
        return True, checked_result[0]
    elif unchecked_result and not checked_result:
        return False, unchecked_result[0]
    else:
        print("État de la case à cocher ambigu ou non détecté.")
        return None, None


def close_window(quit_button_img_proc):
    success, _ = locate_and_click(quit_button_img_proc)
    if success:
        print("Fenêtre fermée avec succès.")
        time.sleep(0.5)  # Attendre que la fenêtre se ferme
    else:
        print("Impossible de fermer la fenêtre. Bouton de fermeture non trouvé.")
    return success


def configure_wavecatcher():
    config_button_img_proc = image_processor(config_button)
    saving_data_option_img_proc = image_processor(saving_data_option)
    raw_rate_checked_img_proc = image_processor(raw_rate_checked)
    raw_rate_unchecked_img_proc = image_processor(raw_rate_unchecked)
    quit_button_img_proc = image_processor(quit_button)
    # Chercher et cliquer sur le bouton de configuration
    success, _ = locate_and_click(config_button_img_proc)
    if not success:
        print("Bouton de configuration non trouvé.")
        return False

    # Chercher et cliquer sur Saving_Data_File_Options
    success, _ = locate_and_click(saving_data_option_img_proc)
    if not success:
        print("Option Saving_Data_File_Options non trouvée.")
        return False

    # Vérifier si la case Raw rate est cochée
    is_checked, checkbox_pos = is_checkbox_checked(raw_rate_checked_img_proc, raw_rate_unchecked_img_proc)
    if is_checked is None:
        return False
    elif not is_checked:
        pyautogui.click(checkbox_pos['X'] + raw_rate_checked_img_proc.img_width // 2,
                        checkbox_pos['Y'] + raw_rate_checked_img_proc.img_height // 2 - 5)
        print("La case Raw rate a été cochée.")
    else:
        print("La case Raw rate est déjà cochée.")
    if not close_window(quit_button_img_proc):
        pyautogui.moveTo(20, 20, 1)
        if not close_window(quit_button_img_proc):
            return False
    # Nouvelles étapes après avoir coché Raw rate
    measurement_button_img_proc = image_processor(measurement_button)
    rate_statistics_button_img_proc = image_processor(rate_statistics_button)
    rate_statistics_checked_img_proc = image_processor(rate_statistics_checked)
    rate_statistics_unchecked_img_proc = image_processor(rate_statistics_unchecked)
    raw_count_hits_checked_img_proc = image_processor(raw_count_hits_checked)
    raw_count_hits_unchecked_img_proc = image_processor(raw_count_hits_unchecked)

    # Cliquer sur le bouton "Measurement"
    success, _ = locate_and_click(measurement_button_img_proc)
    if not success:
        print("Bouton Measurement non trouvé.")
        return False

    # Cliquer sur "Rate Statistics"
    success, _ = locate_and_click(rate_statistics_button_img_proc)
    if not success:
        print("Option Rate Statistics non trouvée.")
        return False

    time.sleep(1)  # Attendre que la nouvelle fenêtre s'ouvre

    # Vérifier et cocher "Rate statistics" si nécessaire
    is_checked, checkbox_pos = is_checkbox_checked(rate_statistics_checked_img_proc, rate_statistics_unchecked_img_proc)
    if is_checked is None:
        print("Impossible de déterminer l'état de la case Rate statistics.")
        return False
    elif not is_checked:
        pyautogui.click(checkbox_pos['X'] + 45 + rate_statistics_checked_img_proc.img_width // 2,
                        checkbox_pos['Y'] + rate_statistics_checked_img_proc.img_height // 2)
        print("La case Rate statistics a été cochée.")

    # Vérifier et cocher "Add raw count hits" si nécessaire
    is_checked, checkbox_pos = is_checkbox_checked(raw_count_hits_checked_img_proc, raw_count_hits_unchecked_img_proc)
    if is_checked is None:
        print("Impossible de déterminer l'état de la case Add raw count hits.")
        return False
    elif not is_checked:
        pyautogui.click(checkbox_pos['X'] + 10 + raw_count_hits_checked_img_proc.img_width // 2,
                        checkbox_pos['Y'] + raw_count_hits_checked_img_proc.img_height // 2)
        print("La case Add raw count hits a été cochée.")
    if not close_window(quit_button_img_proc):
        pyautogui.moveTo(20, 20, 1)
        if not close_window(quit_button_img_proc):
            return False
    return True


def wait_for_acquisition_end(end_acquisition_img_proc, end_acquisition_img_proc_2, end_acquisition_img_proc_3,
                             timeout=1200):
    print("Attente de la fin de l'acquisition...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        screenshot = pyautogui.screenshot()
        screenshot_np = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        found_image_1 = end_acquisition_img_proc.find_img_in_color_HSV(screenshot_np, 0.8)
        found_image_2 = end_acquisition_img_proc_2.find_img_in_color_HSV(screenshot_np, 0.8)
        found_image_3 = end_acquisition_img_proc_3.find_img_in_color_HSV(screenshot_np, 0.8)
        if found_image_1 or found_image_2 or found_image_3:
            print("Fin de l'acquisition détectée!")
            return True
        time.sleep(1)
    print(f"Timeout: La fin de l'acquisition n'a pas été détectée après {timeout} secondes.")
    return False

def read_singlecounter(matrix, cnt):
    """
    Lit un compteur spécifique en utilisant la commande -v qui retourne tous les compteurs
    """
    cmd = f"ssh pi@{ip_add} ''/home/pi/abeast/abeast_m5_counter.py -v {matrix}"
    try:
        output = subprocess.check_output(cmd, shell=True).decode('utf-8')
        # Chercher la ligne qui contient les compteurs
        lines = output.split('\n')
        for i, line in enumerate(lines):
            if 'counter0' in line:
                # La ligne des valeurs est 2 lignes plus loin (à cause de la ligne de séparation)
                counter_line = lines[i + 2].strip()  # Enlever les espaces
                # Extraire les nombres entre les |
                counter_values = [int(x) for x in counter_line.strip('|').split() if x.strip().isdigit()]
                return counter_values[cnt]

        raise ValueError("Impossible de trouver les valeurs des compteurs dans la sortie")
    except Exception as e:
        print(f"Erreur lors de la lecture du compteur {cnt}: {str(e)}")
        print(f"Sortie complète :\n{output}")
        raise

def initialize_wavecatcher(wavecatcher_img_proc):
    if not find_wavecatcher_window(wavecatcher_img_proc):
        return False

    # if not configure_wavecatcher():
    #     print("Erreur lors de la configuration de WaveCatcher.")
    #     return False

    return True


def send_serial_command(ser, command, wait_time=0.5):
    """
    Envoie une commande au moteur et attend la réponse
    """
    # Vider le buffer d'entrée avant d'envoyer
    ser.reset_input_buffer()

    print(f"Envoi commande: {command}")
    ser.write(f"{command}\r\n".encode())
    time.sleep(wait_time)

    # Lire la réponse
    response = ""
    timeout = time.time() + 3  # 3 secondes max pour lire
    while time.time() < timeout:
        if ser.in_waiting > 0:
            response += ser.read(ser.in_waiting).decode(errors='ignore')
        time.sleep(0.1)

    if response:
        print(f"Réponse: {response.strip()}")
    return response


import serial.tools.list_ports


def find_motor_serial_port(baudrate=115200):
    """
    Détecte automatiquement le port série du moteur en testant les ports COM disponibles
    """
    print("Recherche du port série du moteur...")

    # Lister tous les ports COM disponibles
    ports = serial.tools.list_ports.comports()

    if not ports:
        print("Aucun port série détecté sur le système")
        return None

    print(f"Ports disponibles: {[port.device for port in ports]}")

    # Tester chaque port
    for port in ports:
        ser = None
        try:
            print(f"Test du port {port.device}...")
            ser = serial.Serial(port.device, baudrate, timeout=2)
            time.sleep(4)  # Attendre le message d'initialisation

            # Lire le message d'initialisation automatique
            response = ""
            while ser.in_waiting > 0:
                response += ser.read(ser.in_waiting).decode()
                time.sleep(0.1)

            print(f"Réponse du port {port.device}: {response.strip()}")

            # Vérifier si c'est le message d'initialisation du moteur
            if "INITIALIZE" in response or "STARTED" in response:
                print(f"✓ Moteur détecté sur {port.device}")
                return ser  # Retourner directement la connexion série ouverte

            # Si pas de réponse automatique, essayer d'envoyer help
            ser.write(b"help\r\n")
            time.sleep(0.5)

            response = ""
            while ser.in_waiting > 0:
                response += ser.read(ser.in_waiting).decode()
                time.sleep(0.1)

            if "home" in response.lower() and "move" in response.lower():
                print(f"✓ Moteur détecté sur {port.device}")
                return ser

            ser.close()

        except (serial.SerialException, UnicodeDecodeError) as e:
            print(f"Erreur sur {port.device}: {e}")
            if ser and ser.is_open:
                ser.close()
            continue

    print("Aucun moteur détecté sur les ports disponibles")
    return None


def init_motor_serial(baudrate=115200):
    """
    Initialise la connexion série avec détection automatique
    """
    ser = find_motor_serial_port(baudrate)
    if ser:
        print(f"Moteur initialisé avec succès")
    return ser

def motor_home(ser):
    """
    Remet le moteur à la position home (0)
    """
    send_serial_command(ser, "home x", wait_time=2)





def motor_move_relative(ser, position_mm):
    """
    Déplace le moteur à une position relative
    """
    send_serial_command(ser, f"move x -r {position_mm}", wait_time=1)


# def automate_wavecatcher(base_file_name, position, csv_filename, max_position):
#     end_acquisition_img_proc = image_processor(end_acquisition_image)
#     end_acquisition_img_proc_2 = image_processor(end_acquisition_image_2)
#     end_acquisition_img_proc_3 = image_processor(end_acquisition_image_3)
#
#     # Vérifier l'existence de toutes les images
#     all_images = [wavecatcher_window, green_button, confirmation_window, save_window, config_button,
#                   saving_data_option, raw_rate_checked, raw_rate_unchecked, measurement_button,
#                   rate_statistics_button, rate_statistics_checked, rate_statistics_unchecked,
#                   raw_count_hits_checked, raw_count_hits_unchecked, quit_button]
#
#     for image_path in all_images:
#         check_image_exists(image_path)
#
#     wavecatcher_img_proc = image_processor(wavecatcher_window)
#     green_button_img_proc = image_processor(green_button)
#     confirmation_window_img_proc = image_processor(confirmation_window)
#     save_window_img_proc = image_processor(save_window)
#
#     dac_value = 244
#
#     threshold_value = f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 4 {dac_value}"
#     subprocess.check_output(threshold_value, shell=True)
#
#     initial_c0 = read_singlecounter(5, 0)
#     start_time = time.time()
#
#     file_name = f"{base_file_name}at{position}mmthreshold{dac_value}.bin"
#     delta = max_position - position
#
#     time.sleep(0.5)
#
#     if not locate_and_click_with_retry(green_button_img_proc, max_retries=3)[0]:
#         print("Bouton vert non trouvé après plusieurs tentatives.")
#         return False
#
#     if not locate_and_click_with_retry(confirmation_window_img_proc, max_retries=3)[0]:
#         print("Fenêtre de confirmation non trouvée après plusieurs tentatives.")
#         return False
#
#     pyautogui.press('enter')
#
#     if not locate_and_click_with_retry(save_window_img_proc, max_retries=3)[0]:
#         print("Fenêtre d'enregistrement non trouvée après plusieurs tentatives.")
#         return False
#
#     pyautogui.write(file_name)
#     pyautogui.press('enter')
#
#     print(f"Fichier enregistré sous le nom : {file_name}")
#     time.sleep(2)
#
#     if wait_for_acquisition_end(end_acquisition_img_proc, end_acquisition_img_proc_2, end_acquisition_img_proc_3):
#         end_time = time.time()
#
#         final_c0 = read_singlecounter(5, 0)
#         elapsed_time = end_time - start_time
#
#         total_c0 = final_c0 - initial_c0 if final_c0 >= initial_c0 else (2 ** 24 + final_c0 - initial_c0)
#         rate_c0 = total_c0 / elapsed_time
#
#         print(f"Statistiques pour le threshold {dac_value}:")
#         print(f"\t Temps écoulé: {elapsed_time:.2f} secondes")
#         print(f"\t C0: hits = {total_c0}, rate = {rate_c0:.2f} hits/s")
#         print(f"Acquisition du fichier {file_name} terminée avec succès!")
#
#         append_to_csv(csv_filename, position, delta, dac_value,
#                       elapsed_time, total_c0, rate_c0,
#                       file_name, 'SUCCESS')
#
#         subprocess.check_output(f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 4 0", shell=True)
#     else:
#         print(f"Timeout détecté à la position {position}mm, threshold {dac_value}")
#         stop_acquisition()
#
#         append_to_csv(csv_filename, position, delta, dac_value,
#                       None, None, None,
#                       file_name, 'TIMEOUT')
#
#         subprocess.check_output(f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 4 0", shell=True)
#
#     return True
def automate_wavecatcher(base_file_name, position, csv_filename, max_position):
    end_acquisition_img_proc = image_processor(end_acquisition_image)
    end_acquisition_img_proc_2 = image_processor(end_acquisition_image_2)
    end_acquisition_img_proc_3 = image_processor(end_acquisition_image_3)

    all_images = [wavecatcher_window, green_button, confirmation_window, save_window, config_button,
                  saving_data_option, raw_rate_checked, raw_rate_unchecked, measurement_button,
                  rate_statistics_button, rate_statistics_checked, rate_statistics_unchecked,
                  raw_count_hits_checked, raw_count_hits_unchecked, quit_button]

    for image_path in all_images:
        check_image_exists(image_path)

    green_button_img_proc = image_processor(green_button)
    confirmation_window_img_proc = image_processor(confirmation_window)
    save_window_img_proc = image_processor(save_window)

    dac_value = 245
    dac_min = 0
    stop_rate = 1.0

    while dac_value >= dac_min:
        print(f"\nMesure position {position} mm | DAC {dac_value}")

        threshold_value = f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 4 {dac_value}"
        subprocess.check_output(threshold_value, shell=True)

        time.sleep(0.5)

        initial_c0 = read_singlecounter(5, 0)
        start_time = time.time()

        file_name = f"{base_file_name}at{position}mmthreshold{dac_value}.bin"
        delta = max_position - position

        if not locate_and_click_with_retry(green_button_img_proc, max_retries=3)[0]:
            print("Bouton vert non trouvé après plusieurs tentatives.")
            return False

        if not locate_and_click_with_retry(confirmation_window_img_proc, max_retries=3)[0]:
            print("Fenêtre de confirmation non trouvée après plusieurs tentatives.")
            return False

        pyautogui.press('enter')

        if not locate_and_click_with_retry(save_window_img_proc, max_retries=3)[0]:
            print("Fenêtre d'enregistrement non trouvée après plusieurs tentatives.")
            return False

        pyautogui.write(file_name)
        pyautogui.press('enter')

        print(f"Fichier enregistré sous le nom : {file_name}")
        time.sleep(2)

        if wait_for_acquisition_end(end_acquisition_img_proc, end_acquisition_img_proc_2, end_acquisition_img_proc_3):
            end_time = time.time()

            final_c0 = read_singlecounter(5, 0)
            elapsed_time = end_time - start_time

            total_c0 = final_c0 - initial_c0 if final_c0 >= initial_c0 else (2 ** 24 + final_c0 - initial_c0)
            rate_c0 = total_c0 / elapsed_time

            print(f"Statistiques pour DAC {dac_value}:")
            print(f"\tTemps écoulé: {elapsed_time:.2f} secondes")
            print(f"\tC0: hits = {total_c0}, rate = {rate_c0:.2f} hits/s")

            append_to_csv(csv_filename, position, delta, dac_value,
                          elapsed_time, total_c0, rate_c0,
                          file_name, 'SUCCESS')

            subprocess.check_output(f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 4 0", shell=True)

            if rate_c0 < stop_rate:
                print(f"Arrêt scan DAC à {dac_value} : {rate_c0:.2f} coups/s < {stop_rate} coup/s")
                break

        else:
            print(f"Timeout détecté à la position {position} mm, DAC {dac_value}")
            stop_acquisition()

            append_to_csv(csv_filename, position, delta, dac_value,
                          None, None, None,
                          file_name, 'TIMEOUT')

            subprocess.check_output(f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 4 0", shell=True)
            break

        dac_value -= 1

    return True

def main():
    ser = None
    try:
        base_file_name = input("Entrez le nom de base du fichier à enregistrer : ")
        max_position = 127.3  # Position fixe de départ il faut ajouter 2.7 mm
        step = 1
        start_position = 87.3  # delta = 40mm
        end_position = 97.3  # delta = 30mm

        # NOUVEAU : Créer le fichier CSV
        csv_filename = create_csv_file(base_file_name)

        ser = init_motor_serial(115200)
        if ser is None:
            print("Impossible d'initialiser le moteur. Arrêt du programme.")
            return

        motor_home(ser)  # Remise à 0
        reset_init = f"ssh pi@{ip_add} ''/home/pi/abeast/abeast_m5_counter.py -f /home/pi/abeast/mypol6_x2"
        subprocess.check_output(reset_init, shell=True)
        time.sleep(40)  # Attente pour stabilisation du moteur

        # Initialisation du moteur à la position de départ
        motor_move_relative(ser, start_position)
        print(f"Moteur initialisé à la position : {start_position}")
        time.sleep(120)  # Attente pour stabilisation du moteur

        if not initialize_wavecatcher(image_processor(wavecatcher_window)):
            print("Echec de l'initialisation du wavecatcher")
            return

        current_position = start_position
        subprocess.check_output(f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 3 107", shell=True)
        time.sleep(1)
        subprocess.check_output(f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 4 0", shell=True)
        time.sleep(1)
        subprocess.check_output(f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 5 0", shell=True)
        time.sleep(1)
        subprocess.check_output(f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -w 5 6 0", shell=True)
        time.sleep(1)
        subprocess.check_output(f"ssh pi@{ip_add} ''abeast/abeast_m5_counter.py -t 5", shell=True)

        while current_position <= end_position:
            print(f"\n{'=' * 50}")
            print(f"Position actuelle : {current_position} mm")
            # print(f"Delta = {max_position + 2.7 - current_position} mm")
            print(f"Delta = {max_position - current_position} mm")
            print(f"{'=' * 50}\n")

            # MODIFIÉ : Passer csv_filename et max_position
            if automate_wavecatcher(base_file_name, current_position, csv_filename, max_position):
                if current_position < end_position:
                    current_position += step
                    if current_position > end_position:
                        current_position = end_position

                    print(f"Avancement du moteur de {step} mm...")
                    motor_move_relative(ser, step)
                    print(f"Moteur déplacé à la position {current_position} mm")
                    time.sleep(10)
                else:
                    break
            else:
                print(f"Échec de l'acquisition à la position {current_position} mm. Arrêt du programme.")
                break

        reset_init = f"ssh pi@{ip_add} ''/home/pi/abeast/abeast_m5_counter.py -f /home/pi/abeast/mypol6_x2"
        subprocess.check_output(reset_init, shell=True)

        # NOUVEAU : Message final avec emplacement du CSV
        print("\n" + "=" * 50)
        print("Fin du programme d'automatisation.")
        print(f"Résultats enregistrés dans : {csv_filename}")
        print(f"Chemin complet : {os.path.abspath(csv_filename)}")
        print("=" * 50)

    except FileNotFoundError as e:
        print(f"Erreur : {e}")
    except Exception as e:
        print(f"Une erreur inattendue s'est produite : {e}")
    finally:
        if ser and ser.is_open:
            ser.close()
            print("Connexion série fermée.")


if __name__ == "__main__":
    main()
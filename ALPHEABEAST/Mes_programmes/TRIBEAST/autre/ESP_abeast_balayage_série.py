#!/usr/bin/env python3
# ESP_abeast_balayage_série_fixed.py
import os
import time
import paramiko

PI_HOST = "192.168.137.25"
PI_USER = "pi"
PI_PASS = "pi"

# >>> Si tu veux uploader depuis Windows, mets ici le chemin ABSOLU du fichier local
# Exemple: r"C:\Users\higueret_adm\PycharmProjects\ESP_newproject\threshold_sweep_local.py"
LOCAL_SCRIPT = r"C:\Users\higueret_adm\PycharmProjects\ESP_newproject\threshold_sweep_local.py"

REMOTE_PATH = "/home/pi/threshold_sweep_local.py"
REMOTE_OUT_DIR = "/home/pi/threshold_sweep_results"
USE_TMUX = True          # True = lance dans tmux (recommandé)
TMUX_SESSION = "sweep"   # nom de session tmux

def ssh_connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {PI_HOST} ...")
    ssh.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=15)
    return ssh

def run_cmd(ssh, cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode(errors="ignore")
    err = stderr.read().decode(errors="ignore")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err

def ensure_tmux(ssh):
    rc, out, err = run_cmd(ssh, "command -v tmux || true")
    if "tmux" not in out:
        # installer tmux (si sudo sans mot de passe pas possible, basculer sur nohup)
        print("tmux absent -> fallback nohup")
        return False
    return True

def main():
    ssh = ssh_connect()

    # 1) Upload seulement si le fichier local existe
    if os.path.exists(LOCAL_SCRIPT):
        print("Local script found -> uploading to remote...")
        sftp = ssh.open_sftp()
        sftp.put(LOCAL_SCRIPT, REMOTE_PATH)
        sftp.chmod(REMOTE_PATH, 0o755)
        sftp.close()
    else:
        print("Local script NOT found -> skip upload. Will run existing remote script:")
        print("  ", REMOTE_PATH)

    # 2) S’assurer que le script remote est exécutable
    run_cmd(ssh, f"chmod +x {REMOTE_PATH}")
    run_cmd(ssh, f"mkdir -p {REMOTE_OUT_DIR}")

    # 3) Lancer
    if USE_TMUX and ensure_tmux(ssh):
        # Lance dans une session tmux détachée
        cmd = (
            f'tmux new-session -d -s {TMUX_SESSION} '
            f'"python3 {REMOTE_PATH} 2>&1 | tee {REMOTE_OUT_DIR}/tmux_run.log"'
        )
        rc, out, err = run_cmd(ssh, cmd)
        if rc == 0:
            print(f"Lancé dans tmux (session: {TMUX_SESSION}).")
            print(f"Pour suivre: ssh {PI_USER}@{PI_HOST}  ->  tmux attach -t {TMUX_SESSION}")
            print(f"Log live: {REMOTE_OUT_DIR}/tmux_run.log")
        else:
            print("Échec tmux, fallback nohup…", err)
            cmd = (
                f'nohup python3 {REMOTE_PATH} > {REMOTE_OUT_DIR}/nohup.out 2>&1 & echo $!'
            )
            rc, out, err = run_cmd(ssh, cmd)
            print("nohup lancé. PID:", out.strip(), "Log:", f"{REMOTE_OUT_DIR}/nohup.out")
    else:
        # Pas de tmux -> exécution synchrone (bloquante)
        print("Exécution synchrone (sans tmux). Streaming de la sortie...")
        stdin, stdout, stderr = ssh.exec_command(f"python3 {REMOTE_PATH}")
        try:
            while True:
                line = stdout.readline()
                if line:
                    print("[REMOTE]", line.rstrip())
                elif stdout.channel.exit_status_ready():
                    break
                time.sleep(0.1)
            err = stderr.read().decode()
            if err:
                print("[REMOTE-ERR]", err)
        finally:
            pass

    ssh.close()

if __name__ == "__main__":
    main()

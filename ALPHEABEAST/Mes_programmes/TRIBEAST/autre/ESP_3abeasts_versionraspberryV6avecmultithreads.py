#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import queue
from concurrent.futures import Future
import socket
import threading
import time
import select
import re
import os
import csv
import configparser
from dataclasses import dataclass, field
from collections import deque

# =======================
#   CONFIG / CONSTANTES
# =======================
PC_HOST = "0.0.0.0"
PC_PORT = 5001
srv = None
HOST = "0.0.0.0"
PORT = 4210

DEBUG = False

NUM_ABEAST = 3
NUM_COUNTERS_PER_ABEAST = 3

REGISTER_MAP = {
    'vpre_bias': 0,
    'sh_vcm': 1,
    'sh_timebias': 2,
    'vth_baseline': 3,
    'comp_vth_0': 4,
    'comp_vth_1': 5,
    'comp_vth_2': 6,
    'reg_8': 8
}

# Dans ton firmware: counters à partir du registre 9 (3 bytes par compteur)
COUNTER_BASE_ADDR = 9
COUNTER_STRIDE = 3

# =======================
#   OUTILS SOCKET / I/O
# =======================

@dataclass
class EspConn:
    sock: socket.socket
    addr: tuple
    esp_id: str
    desc: str = ""
    mac: str = ""
    ip: str = ""

    rx_lines: deque = field(default_factory=lambda: deque(maxlen=10000))
    rx_lock: threading.Lock = field(default_factory=threading.Lock)
    cmd_lock: threading.RLock = field(default_factory=threading.RLock)

    job_queue: queue.Queue = field(default_factory=queue.Queue)
    worker_thread: threading.Thread | None = None
    worker_alive: bool = True
class TcpMultiEspServer:
    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.server = None
        self.running = False
        self.print_lock = threading.Lock()
        self.current_prompt = "[TCP:none]> "

        self.lock = threading.Lock()
        self.clients = {}  # esp_id -> EspConn
        self.selected = None  # esp_id

        self.accept_thread = None

    def start(self):
        if self.running:
            print("TCP server already running.")
            return True
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((self.host, self.port))
            self.server.listen(20)
            self.running = True
            print(f"🟢 TCP server listening on {self.host}:{self.port}")

            self.accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self.accept_thread.start()
            return True
        except Exception as e:
            print(f"❌ Cannot start TCP server: {e}")
            return False

    def _start_worker_for_ec(self, ec: EspConn):
        if ec.worker_thread and ec.worker_thread.is_alive():
            return

        ec.worker_alive = True
        ec.worker_thread = threading.Thread(
            target=self._esp_worker_loop,
            args=(ec,),
            daemon=True
        )
        ec.worker_thread.start()

    def _stop_worker_for_ec(self, ec: EspConn):
        try:
            ec.worker_alive = False
            ec.job_queue.put(None)
        except:
            pass

    def _esp_worker_loop(self, ec: EspConn):
        while self.running and ec.worker_alive:
            try:
                job = ec.job_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if job is None:
                break

            future = job["future"]
            kind = job["kind"]

            try:
                if kind == "read_reg":
                    result = _direct_read_reg(ec, job["matrix"], job["addr"])
                    future.set_result(result)

                elif kind == "write_reg":
                    result = _direct_write_reg(ec, job["matrix"], job["addr"], job["value"])
                    future.set_result(result)

                elif kind == "read_all_counters":
                    result = _direct_read_all_counters(ec)
                    future.set_result(result)

                elif kind == "reset_matrix":
                    result = _direct_reset_matrix(ec, job["matrix"])
                    future.set_result(result)

                else:
                    future.set_exception(RuntimeError(f"Unknown job kind: {kind}"))

            except Exception as e:
                future.set_exception(e)
    def submit_job(self, ec: EspConn, kind: str, **kwargs):
        fut = Future()
        job = {"kind": kind, "future": fut, **kwargs}
        ec.job_queue.put(job)
        return fut
    def _drop_client(self, esp_id: str, sock_ref=None, reason=""):
        """
        Drop un client proprement (thread-safe).
        sock_ref: optionnel, permet d'éviter de drop si c'est plus le bon socket.
        """
        with self.lock:
            ec = self.clients.get(esp_id)
            if not ec:
                return

            # si on a fourni une référence socket, on vérifie que c'est toujours la même
            if sock_ref is not None and ec.sock is not sock_ref:
                return

            try:
                ec.sock.close()
            except:
                pass

            self.clients.pop(esp_id, None)

            # si c'était le sélectionné, on bascule sur un autre
            if self.selected == esp_id:
                self.selected = next(iter(self.clients.keys()), None)

        # log hors lock
        try:
            self._safe_print(f"❌ ESP dropped: {esp_id} ({reason})")
        except:
            pass

    def _client_reader_loop(self, esp_id: str, sock_ref: socket.socket):
        buf = ""
        try:
            while self.running:
                # stop si client remplacé
                with self.lock:
                    ec = self.clients.get(esp_id)
                    if ec is None or ec.sock is not sock_ref:
                        return

                r, _, _ = select.select([sock_ref], [], [], 0.5)
                if not r:
                    continue

                data = sock_ref.recv(2048)
                if not data:
                    self._drop_client(esp_id, sock_ref=sock_ref, reason="reader FIN")
                    return

                buf += data.decode("utf-8", errors="replace")

                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    # ✅ ignore PING mais on peut répondre pour garder RX/TX vivant
                    if line == "PING":
                        # try:
                        #     sock_ref.sendall(b"PONG\n")
                        # except:
                        #     pass
                        continue

                    # (optionnel) heartbeats
                    if line.startswith("ESP_HEARTBEAT:"):
                        # print léger, ou stocker
                        # self._safe_print(f"❤️ {esp_id}: {line}")
                        continue

                    with ec.rx_lock:
                        ec.rx_lines.append(line)
                    # self._safe_print(f"📩 {esp_id}: {line}")

        except Exception as e:
            # en cas d’erreur, on drop proprement
            self._drop_client(esp_id, sock_ref=sock_ref, reason=f"reader err: {e}")

    def _client_rx_watch(self, esp_id: str, sock_ref: socket.socket):
        """
        Watcher ultra safe:
        - Ne drop QUE si FIN/RST réel
        - Ignore les timeouts/EAGAIN
        - Ne consomme pas la data (MSG_PEEK)
        """
        try:
            while self.running:
                # Vérifie que ce client existe encore et que c'est toujours la même socket
                with self.lock:
                    ec = self.clients.get(esp_id)
                    if ec is None:
                        return
                    if ec.sock is not sock_ref:
                        return  # socket remplacée (reconnect), on stoppe l'ancien watcher

                s = sock_ref

                r, _, _ = select.select([s], [], [], 0.2)
                if r:
                    try:
                        data = s.recv(1, socket.MSG_PEEK)
                        if data == b"":
                            self._drop_client(esp_id, sock_ref=s, reason="rx watch (FIN)")
                            return

                    except socket.timeout:
                        # ✅ timeout = pas une erreur fatale
                        continue
                    except BlockingIOError:
                        # ✅ EAGAIN/EWOULDBLOCK = pas grave
                        continue
                    except ConnectionResetError:
                        self._drop_client(esp_id, sock_ref=s, reason="rx watch (RST)")
                        return
                    except BrokenPipeError:
                        self._drop_client(esp_id, sock_ref=s, reason="rx watch (PIPE)")
                        return
                    except OSError as e:
                        # ✅ certains OSError sont transitoires, on log mais on drop pas direct
                        try:
                            self._safe_print(f"⚠️ rx_watch OSError for {esp_id}: {e}")
                        except:
                            pass
                        # on attend un prochain tour; si c'est vraiment mort, FIN/RST arrivera
                        continue

                time.sleep(0.3)

        except Exception as e:
            try:
                self._safe_print(f"⚠️ rx_watch exception for {esp_id}: {e}")
            except:
                pass
            return

    def _safe_print(self, msg: str):
        with self.print_lock:
            print("\r" + " " * 140 + "\r", end="")
            print(msg)
            # NE PAS réimprimer current_prompt ici

    def stop(self):
        self.running = False
        with self.lock:
            for k, ec in list(self.clients.items()):
                self._stop_worker_for_ec(ec)
                try:
                    ec.sock.close()
                except:
                    pass
            self.clients.clear()
            self.selected = None
        try:
            if self.server:
                self.server.close()
        except:
            pass
        self.server = None
        print("🛑 TCP server stopped.")

    def list_esps(self):
        with self.lock:
            if not self.clients:
                print("❌ Aucun ESP connecté")
                return
            print(f"\n📋 ESP connectés ({len(self.clients)}):")
            print("=" * 60)
            for eid, ec in self.clients.items():
                sel = "🎯" if eid == self.selected else "  "
                info = []
                if ec.ip: info.append(f"ip={ec.ip}")
                if ec.mac: info.append(f"mac={ec.mac}")
                if ec.desc: info.append(f"desc={ec.desc}")
                info_s = " | ".join(info) if info else ""
                print(f"{sel} {eid:16s}  {ec.addr[0]}:{ec.addr[1]}  {info_s}")
            print()

    def select_esp(self, esp_id: str):
        with self.lock:
            if esp_id in self.clients:
                self.selected = esp_id
                print(f"🎯 Selected ESP: {esp_id}")
                return True
            print(f"❌ ESP '{esp_id}' not found.")
            if self.clients:
                print("Available:")
                for k in self.clients.keys():
                    print(f"  - {k}")
            return False

    def get_selected(self):
        with self.lock:
            if not self.selected:
                return None
            ec = self.clients.get(self.selected)
        if ec and not is_socket_alive(ec.sock):
            with self.lock:
                try:
                    ec.sock.close()
                except:
                    pass
                self.clients.pop(ec.esp_id, None)
                if self.selected == ec.esp_id:
                    self.selected = next(iter(self.clients.keys()), None)
            return None
        return ec

    def _accept_loop(self):
        while self.running:
            try:
                client, addr = self.server.accept()
                client.settimeout(None)

                esp_id, meta = self._identify_client(client, addr)
                if not esp_id:
                    try:
                        client.close()
                    except:
                        pass
                    continue

                ec = EspConn(sock=client, addr=addr, esp_id=esp_id,
                             desc=meta.get("desc", ""), mac=meta.get("mac", ""), ip=meta.get("ip", ""))

                with self.lock:
                    old = self.clients.get(esp_id)
                    if old:
                        self._stop_worker_for_ec(old)
                        try:
                            old.sock.close()
                        except:
                            pass
                    self.clients[esp_id] = ec


                    if self.selected is None:
                        self.selected = esp_id
                self._start_worker_for_ec(ec)

                # ✅ Lancer le watcher avec les bons args, et après l’enregistrement
                # threading.Thread(
                #     target=self._client_rx_watch,
                #     args=(esp_id, client),
                #     daemon=True
                # ).start()
                threading.Thread(
                    target=self._client_reader_loop,
                    args=(esp_id, client),
                    daemon=True
                ).start()

                # ✅ Une seule impression
                msg = f"🔁 ESP reconnected: {esp_id}  (selected={self.selected})" if old else f"✅ ESP connected: {esp_id}  (selected={self.selected})"
                self._safe_print(msg)


            except Exception:
                if self.running:
                    time.sleep(0.05)

    def _identify_client(self, sock: socket.socket, addr):
        meta = {}
        esp_id = None
        buf = ""
        start = time.time()
        last_ping = 0.0

        # important : timeout court pour select/recv, pas un gros timeout bloquant
        sock.settimeout(0.5)

        while time.time() - start < 8.0:
            # renvoie une demande d'identification toutes les 0.7s
            if time.time() - last_ping > 3:
                try:
                    sock.sendall(b"ESP_IDENTIFY\n")
                except:
                    return None, {}
                last_ping = time.time()

            try:
                r, _, _ = select.select([sock], [], [], 0.2)
                if not r:
                    continue
                data = sock.recv(1024)
                if not data:
                    break
                buf += data.decode("utf-8", errors="replace")

                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    # parse ESP_ID:...,DESC:...,MAC:...,IP:...
                    if line.startswith("ESP_ID:"):
                        parts = line.split(",")
                        for p in parts:
                            if ":" not in p:
                                continue
                            k, v = p.split(":", 1)
                            k = k.strip().lower()
                            v = v.strip()
                            if k == "esp_id":
                                esp_id = v
                            elif k == "desc":
                                meta["desc"] = v
                            elif k == "mac":
                                meta["mac"] = v
                            elif k == "ip":
                                meta["ip"] = v

                        if esp_id:
                            return esp_id, meta

            except socket.timeout:
                continue
            except:
                break

        return None, {}
class PcCommandServer:
    """
    Petit serveur TCP pour le PC:
      - Le PC se connecte sur PC_PORT (ex: 5001)
      - Envoie: CNTCSV [esp_id]
      - Reçoit: 3 lignes "chip,c0,c1,c2" + "OK CNTCSV"
    """
    def __init__(self, srv: TcpMultiEspServer, host=PC_HOST, port=PC_PORT):
        self.srv = srv
        self.host = host
        self.port = port
        self.running = True

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(10)

        threading.Thread(target=self._accept_loop, daemon=True).start()
        print(f"🟦 PC CMD server listening on {self.host}:{self.port}")

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except:
            pass

    def _accept_loop(self):
        while self.running:
            try:
                c, addr = self.sock.accept()
                c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                threading.Thread(target=self._client_loop, args=(c, addr), daemon=True).start()
                print(f"✅ PC connected: {addr[0]}:{addr[1]}")
            except:
                time.sleep(0.05)

    def _send(self, c: socket.socket, s: str):
        if not s.endswith("\n"):
            s += "\n"
        c.sendall(s.encode("utf-8", errors="replace"))

    def _client_loop(self, c: socket.socket, addr):
        buf = ""
        try:
            c.settimeout(0.5)
            while self.running and self.srv.running:
                try:
                    data = c.recv(2048)
                    if not data:
                        return
                    buf += data.decode("utf-8", errors="replace")
                except socket.timeout:
                    continue

                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    # commandes
                    if line.upper() == "PING":
                        self._send(c, "PONG")
                        continue

                    if line.upper().startswith("CNTCSV"):
                        parts = line.split()
                        esp_id = parts[1] if len(parts) >= 2 else None

                        ec = None
                        if esp_id:
                            with self.srv.lock:
                                ec = self.srv.clients.get(esp_id)
                        else:
                            ec = self.srv.get_selected()

                        if not ec:
                            self._send(c, "ERR NO_ESP")
                            continue

                        try:
                            lines = firmware_cntcsv(ec, timeout=4.0)

                            if not lines:
                                self._send(c, "ERR CNTCSV")
                                continue

                            for l in lines:
                                self._send(c, l)

                        except Exception:
                            self._send(c, "ERR CNTCSV")

                        continue
                    if line.upper().startswith("RESETALL"):
                        parts = line.split()

                        # Cas 1 : RESETALL <esp_id>
                        if len(parts) >= 2:
                            eid = parts[1].strip()

                            with self.srv.lock:
                                ec = self.srv.clients.get(eid)

                            if not ec:
                                self._send(c, "ERR NO_ESP")
                                continue

                            ok = True
                            for m in range(NUM_ABEAST):
                                try:
                                    cmd_reset(ec, m)
                                except:
                                    ok = False

                            self._send(c, "OK RESETALL" if ok else "ERR RESETALL")
                            continue

                        # Cas 2 : RESETALL  => tous les ESP connectés
                        with self.srv.lock:
                            ids = list(self.srv.clients.keys())

                        if not ids:
                            self._send(c, "ERR NO_ESP")
                            continue

                        ok_global = True
                        for eid in ids:
                            with self.srv.lock:
                                ec = self.srv.clients.get(eid)
                            if not ec:
                                ok_global = False
                                continue

                            for m in range(NUM_ABEAST):
                                try:
                                    cmd_reset(ec, m)
                                except:
                                    ok_global = False

                            time.sleep(0.05)

                        self._send(c, "OK RESETALL" if ok_global else "ERR RESETALL")
                        continue

                    if line.upper().startswith("RESET"):
                        # RESET <esp_id>   (reset matrices 0..2 pour CET esp)
                        parts = line.split()
                        if len(parts) < 2:
                            self._send(c, "ERR RESET_USAGE")
                            continue
                        eid = parts[1].strip()

                        with self.srv.lock:
                            ec = self.srv.clients.get(eid)

                        if not ec:
                            self._send(c, "ERR NO_ESP")
                            continue

                        ok = True
                        for m in range(NUM_ABEAST):
                            try:
                                cmd_reset(ec, m)
                            except:
                                ok = False
                        self._send(c, "OK RESET" if ok else "ERR RESET")
                        continue
                    if line.upper().startswith("WR "):
                        # WR <esp_id?> <m> <reg> <val>
                        parts = line.split()
                        # autorise WR m reg val (sur selected) ou WR esp_id m reg val
                        if len(parts) == 5:
                            esp_id = parts[1]
                            m = int(parts[2]); reg = int(parts[3]); val = int(parts[4])
                            with self.srv.lock:
                                ec = self.srv.clients.get(esp_id)
                        elif len(parts) == 4:
                            esp_id = None
                            m = int(parts[1]); reg = int(parts[2]); val = int(parts[3])
                            ec = self.srv.get_selected()
                        else:
                            self._send(c, "ERR WR_USAGE")
                            continue

                        if not ec:
                            self._send(c, "ERR NO_ESP")
                            continue

                        ok = write_reg(ec, m, reg, val)
                        self._send(c, "OK WR" if ok else "ERR WR")
                        continue

                    if line.upper() == "ESPLIST":
                        with self.srv.lock:
                            ids = list(self.srv.clients.keys())
                        self._send(c, "OK ESPLIST " + " ".join(ids))
                        continue
                    if line.upper().startswith("WRITE "):
                        # WRITE <matrix> <reg> <val> [esp_id]
                        parts = line.split()
                        if len(parts) < 4:
                            self._send(c, "ERR WRITE_USAGE")
                            continue
                        try:
                            m = int(parts[1]); reg = int(parts[2]); val = int(parts[3])
                        except:
                            self._send(c, "ERR WRITE_PARSE")
                            continue
                        esp_id = parts[4] if len(parts) >= 5 else None

                        ec = None
                        if esp_id:
                            with self.srv.lock:
                                ec = self.srv.clients.get(esp_id)
                        else:
                            ec = self.srv.get_selected()

                        if not ec:
                            self._send(c, "ERR NO_ESP")
                            continue

                        ok = write_reg(ec, m, reg, val)
                        self._send(c, "OK" if ok else "ERR")
                        continue

                    if line.upper().startswith("THSET "):
                        # THSET <th0> <th1> <th2> [esp_id]
                        parts = line.split()
                        if len(parts) < 4:
                            self._send(c, "ERR THSET_USAGE")
                            continue
                        try:
                            th0 = int(parts[1]); th1 = int(parts[2]); th2 = int(parts[3])
                        except:
                            self._send(c, "ERR THSET_PARSE")
                            continue
                        esp_id = parts[4] if len(parts) >= 5 else None

                        ec = None
                        if esp_id:
                            with self.srv.lock:
                                ec = self.srv.clients.get(esp_id)
                        else:
                            ec = self.srv.get_selected()

                        if not ec:
                            self._send(c, "ERR NO_ESP")
                            continue

                        # reg 4/5/6 = comp_vth_0/1/2
                        ok_all = True
                        for m in range(NUM_ABEAST):
                            ok_all &= write_reg(ec, m, 4, th0)
                            ok_all &= write_reg(ec, m, 5, th1)
                            ok_all &= write_reg(ec, m, 6, th2)

                        self._send(c, "OK" if ok_all else "ERR")
                        continue

                    if line.upper().startswith("SELECT "):
                        _, esp_id = line.split(" ", 1)
                        ok = self.srv.select_esp(esp_id.strip())
                        self._send(c, "OK SELECT" if ok else "ERR SELECT")
                        continue

                    self._send(c, "ERR UNKNOWN_CMD")

        except Exception:
            return
        finally:
            try:
                c.close()
            except:
                pass

# =======================
#   PROTOCOLE ESP
# =======================
def firmware_cntcsv(ec: EspConn, timeout=4.0) -> list[str]:
    with ec.cmd_lock:
        _drain_queue(ec)
        ec.sock.sendall(b"CNTCSV\n")

        lines = []
        start = time.time()

        while time.time() - start < timeout:
            line = _recv_line_ec(ec, timeout=0.5)
            if not line:
                continue

            lines.append(line)

            if line.strip() == "OK CNTCSV":
                break

        return lines
def _direct_send_binary_packet(ec: EspConn, matrix: int, cmd: int, addr: int, val: int, timeout=2.0) -> list[str]:
    with ec.cmd_lock:
        sock = ec.sock
        packet = bytes([0x30, 0x31, matrix & 0xFF, cmd & 0xFF, addr & 0xFF, val & 0xFF, 0xFF])

        _drain_queue(ec)

        try:
            sock.sendall(packet)
        except (BrokenPipeError, ConnectionResetError, OSError):
            try:
                sock.close()
            except:
                pass
            return []

        lines = []
        start = time.time()
        ok_seen = False

        while True:
            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                break

            line = _recv_line_ec(ec, timeout=min(0.6, remaining))
            if line is None or line == "":
                continue

            lines.append(line)

            if line.strip() == "Ok":
                ok_seen = True
                if cmd == 0x00:
                    break
                continue

            if ok_seen and cmd == 0x01 and re.fullmatch(r"-?\d+", line.strip()):
                break

        return lines


def _direct_read_reg(ec: EspConn, matrix: int, addr: int) -> int | None:
    lines = _direct_send_binary_packet(ec, matrix, 0x01, addr, 0x00, timeout=2.5)
    for l in reversed(lines):
        l2 = l.strip()
        if re.fullmatch(r"-?\d+", l2):
            try:
                return int(l2)
            except:
                return None
    return None


def _direct_write_reg(ec: EspConn, matrix: int, addr: int, value: int) -> bool:
    lines = _direct_send_binary_packet(ec, matrix, 0x00, addr, value, timeout=2.0)
    return any(l.strip() == "Ok" for l in lines)


def _direct_read_counter_24(ec: EspConn, matrix: int, counter_index: int) -> int:
    base = COUNTER_BASE_ADDR + COUNTER_STRIDE * counter_index
    low = _direct_read_reg(ec, matrix, base + 0)
    mid = _direct_read_reg(ec, matrix, base + 1)
    high = _direct_read_reg(ec, matrix, base + 2)

    if low is None or mid is None or high is None:
        return 0
    return ((high & 0xFF) << 16) | ((mid & 0xFF) << 8) | (low & 0xFF)


def _direct_read_all_counters(ec: EspConn) -> dict[int, tuple[int, int, int]]:
    out = {}
    for m in range(NUM_ABEAST):
        c0 = _direct_read_counter_24(ec, m, 0)
        c1 = _direct_read_counter_24(ec, m, 1)
        c2 = _direct_read_counter_24(ec, m, 2)
        out[m] = (c0, c1, c2)
    return out


def _direct_reset_matrix(ec: EspConn, m: int) -> bool:
    reg8 = _direct_read_reg(ec, m, 8)
    if reg8 is None:
        return False
    ok1 = _direct_write_reg(ec, m, 8, reg8 | 0x80)
    ok2 = _direct_write_reg(ec, m, 8, reg8 & 0x7F)
    return bool(ok1 and ok2)
def _drain_socket(sock: socket.socket):
    """Vide le buffer RX (non bloquant)."""
    try:
        while True:
            r, _, _ = select.select([sock], [], [], 0.0)
            if not r:
                break
            _ = sock.recv(4096)
            if not _:
                break
    except:
        pass

def _drain_queue(ec: EspConn):
    with ec.rx_lock:
        ec.rx_lines.clear()

def _recv_line_ec(ec: EspConn, timeout=2.0) -> str | None:
    start = time.time()
    while time.time() - start < timeout:
        with ec.rx_lock:
            if ec.rx_lines:
                return ec.rx_lines.popleft()
        time.sleep(0.01)
    return None


def send_text_command(ec: EspConn, line: str, expect_reply=True, timeout=2.0) -> str | None:
    with ec.cmd_lock:
        if not line.endswith("\n"):
            line += "\n"
        _drain_queue(ec)
        ec.sock.sendall(line.encode("utf-8"))
        if not expect_reply:
            return None
        return _recv_line_ec(ec, timeout=timeout)


def send_binary_packet(ec: EspConn, matrix: int, cmd: int, addr: int, val: int, timeout=2.0) -> list[str]:
    with ec.cmd_lock:
        sock = ec.sock
        packet = bytes([0x30, 0x31, matrix & 0xFF, cmd & 0xFF, addr & 0xFF, val & 0xFF, 0xFF])

        _drain_queue(ec)

        try:
            sock.sendall(packet)
        except (BrokenPipeError, ConnectionResetError, OSError):
            try:
                sock.close()
            except:
                pass
            return []

        lines = []
        start = time.time()
        ok_seen = False

        while True:
            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                break

            line = _recv_line_ec(ec, timeout=min(0.6, remaining))
            if line is None or line == "":
                continue

            lines.append(line)

            if line.strip() == "Ok":
                ok_seen = True
                if cmd == 0x00:
                    break
                continue

            if ok_seen and cmd == 0x01 and re.fullmatch(r"-?\d+", line.strip()):
                break

        return lines


def write_reg(ec: EspConn, matrix: int, addr: int, value: int) -> bool:
    fut = srv.submit_job(ec, "write_reg", matrix=matrix, addr=addr, value=value)
    return fut.result(timeout=3.0)


def read_reg(ec: EspConn, matrix: int, addr: int) -> int | None:
    fut = srv.submit_job(ec, "read_reg", matrix=matrix, addr=addr)
    return fut.result(timeout=3.0)
def read_counter_24(ec: EspConn, matrix: int, counter_index: int) -> int:
    """
    Compteur 24-bit:
      low  = reg (9 + 3*i + 0)
      mid  = reg (9 + 3*i + 1)
      high = reg (9 + 3*i + 2)
    """
    base = COUNTER_BASE_ADDR + COUNTER_STRIDE * counter_index
    low = read_reg(ec, matrix, base + 0)
    mid = read_reg(ec, matrix, base + 1)
    high = read_reg(ec, matrix, base + 2)

    if low is None or mid is None or high is None:
        return 0
    return ((high & 0xFF) << 16) | ((mid & 0xFF) << 8) | (low & 0xFF)

def read_all_counters(ec: EspConn) -> dict[int, tuple[int,int,int]]:
    fut = srv.submit_job(ec, "read_all_counters")
    return fut.result(timeout=8.0)

def cfg_snapshot(ec: EspConn) -> dict[int, dict]:
    snap = {}
    for m in range(NUM_ABEAST):
        d = {}
        for name, addr in REGISTER_MAP.items():
            v = read_reg(ec, m, addr)
            d[name] = v if v is not None else "ERR"
        snap[m] = d
    return snap

# =======================
#   COMMANDES "ANCIENNES"
# =======================

def print_help():
    print("\n====== AlphaBeast Raspberry TCP Controller (Pi 5 / TCP only) ======")
    print("Anciennes commandes compatibles (TCP uniquement):")
    print("  help")
    print("  esp list")
    print("  esp select <id>")
    print("  status                  (ESP_STATUS)")
    print("  netinfo                 (ESP_NETWORK_INFO)")
    print("  mux <0-3>               (ESP_MUX_SELECT <ch>)")
    print("  send <ESP_...>          (envoie une commande texte ESP_)")
    print("")
    print("Registres / matrices:")
    print("  read <m> <reg>          (binaire)")
    print("  write <m> <reg> <val>   (binaire)")
    print("  view <m> [counters]     (affiche regs + option compteurs)")
    print("  bias                    (view 0..2)")
    print("  reset <m>               (pulse rst_c bit7 sur reg8)")
    print("  counter <m> <c>         (lit un compteur 0..2)")
    print("  cntcsv                  (lit compteurs via registres et imprime chip,c0,c1,c2)")
    print("  cfgsnap                 (snapshot de config via registres)")
    print("")
    print("Config INI:")
    print("  config show [file.ini]")
    print("  config apply [file.ini]")
    print("  config save [file.ini]")
    print("")
    print("Logs flash (via commandes ESP_):")
    print("  log_status              (ESP_LOG_STATUS)")
    print("  log_enable              (ESP_LOG_ENABLE)")
    print("  log_disable             (ESP_LOG_DISABLE)")
    print("  log_interval <ms>       (ESP_LOG_INTERVAL <ms>)")
    print("  log_read <start> <cnt>  (ESP_LOG_READ ... -> parse LOG_ENTRY ...)")
    print("  log_latest [cnt]        (ESP_LOG_LATEST ...)")
    print("  log_save <start> <cnt>  (sauve CSV)")
    print("  log_save all            (sauve tout depuis 0)")
    print("  log_clear               (ESP_LOG_CLEAR)")
    print("  log_clear_all           (ESP_LOG_CLEAR_ALL)")
    print("")
    print("Quit:")
    print("  exit / quit\n")

def cmd_status(ec: EspConn):
    resp = send_text_command(ec, "ESP_STATUS", expect_reply=True, timeout=2.0)
    print(resp if resp else "No reply")

def cmd_netinfo(ec: EspConn):
    with ec.cmd_lock:
        _drain_queue(ec)
        ec.sock.sendall(b"ESP_NETWORK_INFO\n")
        start = time.time()
        while time.time() - start < 1.5:
            line = _recv_line_ec(ec, timeout=0.4)
            if line:
                print(line)


def cmd_mux(ec: EspConn, ch: int):
    resp = send_text_command(ec, f"ESP_MUX_SELECT {ch}", expect_reply=True, timeout=2.0)
    print(resp if resp else "No reply")

def cmd_send(ec: EspConn, txt: str):
    if not txt.startswith("ESP_"):
        print("❌ En TCP, le firmware ignore les commandes texte qui ne commencent pas par 'ESP_'")
        return

    with ec.cmd_lock:
        _drain_queue(ec)
        ec.sock.sendall((txt.strip() + "\n").encode("utf-8"))

        start = time.time()
        got = False
        while time.time() - start < 1.0:
            line = _recv_line_ec(ec, timeout=0.3)
            if not line:
                continue
            got = True
            print(line)

        if not got:
            print("No reply")


def cmd_read(ec: EspConn, m: int, reg: int):
    v = read_reg(ec, m, reg)
    print(v if v is not None else "ERR")

def cmd_write(ec: EspConn, m: int, reg: int, val: int):
    ok = write_reg(ec, m, reg, val)
    print("OK" if ok else "ERR")

def cmd_view(ec: EspConn, m: int, show_counters: bool):
    # Affichage inspiré de ton ancien print_reg()
    reg8 = read_reg(ec, m, 8)
    if reg8 is None:
        print(f"*** ERREUR: Impossible de lire reg8 (matrix {m}) ***")
        return

    def int2bit(n):
        return [(n >> i) & 1 for i in range(7, -1, -1)]

    rname = ['bdgp', 'cs_pre', 'cs_sh', 'gx2', 'none', 'none', 'none', 'rst_c']
    rname.reverse()
    regname = ['Vpre_B', 'SH_Vcm', 'SH_TB', 'Vth_bl', 'C_Vth0', 'C_Vth1', 'C_Vth2', 'DACMon']

    print('+---------------------------------------------------------+')
    print(f'|        AlphaBeast            matrix : {m:1d}                 |')
    print('+---------------------------------------------------------+')
    print('|                     Register 8                          |')
    print('| Bit  7      6      5      4      3      2      1      0  |')
    print('+---------------------------------------------------------+')
    print('|', end='')
    for n in rname:
        print(f'{n:>6s} ', end='')
    print('|')
    print('+---------------------------------------------------------+')
    print('|', end='')
    for b in int2bit(reg8):
        print(f'{b:6d} ', end='')
    print('|')
    print('+---------------------------------------------------------+')
    print('| Reg  0      1      2      3      4      5      6      7  |')
    print('|', end='')
    for n in regname:
        print(f'{n:>6s} ', end='')
    print('|')
    print('+---------------------------------------------------------+')
    print('|', end='')
    for i in range(0, 8):
        v = read_reg(ec, m, i)
        if v is None:
            print(f'{"ERR":>6s} ', end='')
        else:
            print(f'{v:6d} ', end='')
    print('|')
    print('+---------------------------------------------------------+')

    if show_counters:
        c = (read_counter_24(ec, m, 0), read_counter_24(ec, m, 1), read_counter_24(ec, m, 2))
        print('|     counter0          counter1          counter2         |')
        print('+---------------------------------------------------------+')
        print(f'|{c[0]:17d} {c[1]:17d} {c[2]:17d}   |')
        print('+---------------------------------------------------------+')

def cmd_bias(ec: EspConn):
    for m in range(NUM_ABEAST):
        cmd_view(ec, m, show_counters=True)

def cmd_reset(ec: EspConn, m: int):
    fut = srv.submit_job(ec, "reset_matrix", matrix=m)
    ok = fut.result(timeout=4.0)
    print("OK" if ok else "ERR")

def cmd_counter(ec: EspConn, m: int, c: int):
    v = read_counter_24(ec, m, c)
    print(v)

def cmd_cntcsv(ec: EspConn):
    lines = firmware_cntcsv(ec, timeout=4.0)
    if not lines:
        print("ERR CNTCSV")
        return

    for l in lines:
        print(l)

def cmd_cfgsnap(ec: EspConn):
    snap = cfg_snapshot(ec)
    for m, d in snap.items():
        print(f"ABeast{m}: {d}")

# ====== Config INI ======

def config_show(filename="default.ini"):
    if not os.path.exists(filename):
        print(f"❌ File not found: {filename}")
        return
    cp = configparser.ConfigParser()
    cp.read(filename)
    print(f"📄 {filename}")
    print("=" * 60)
    for sec in cp.sections():
        print(f"\n[{sec}]")
        for k, v in cp[sec].items():
            addr = REGISTER_MAP.get(k, None)
            if addr is None:
                print(f"  {k:<12} = {v:<6} (unknown)")
            else:
                print(f"  {k:<12} = {v:<6} (reg {addr})")
    print("=" * 60)

def config_apply(ec: EspConn, filename="default.ini"):
    if not os.path.exists(filename):
        print(f"❌ File not found: {filename}")
        return False
    cp = configparser.ConfigParser()
    cp.read(filename)

    ok_all = True
    for sec in cp.sections():
        if not sec.lower().startswith("abeast_"):
            continue
        try:
            idx = int(sec.split("_")[1]) - 1
        except:
            print(f"⚠️ Bad section: {sec}")
            ok_all = False
            continue
        if idx < 0 or idx >= NUM_ABEAST:
            print(f"⚠️ Out of range: {sec}")
            ok_all = False
            continue

        print(f"\n🔧 Applying {sec} -> matrix {idx}")
        for k, v in cp[sec].items():
            if k not in REGISTER_MAP:
                print(f"  ⚠️ skip unknown param: {k}")
                continue
            try:
                val = int(v)
            except:
                print(f"  ❌ invalid int: {k}={v}")
                ok_all = False
                continue
            if not (0 <= val <= 255):
                print(f"  ❌ out of range 0..255: {k}={val}")
                ok_all = False
                continue
            addr = REGISTER_MAP[k]
            ok = write_reg(ec, idx, addr, val)
            print(f"  {'✅' if ok else '❌'} {k} (reg {addr}) = {val}")
            if not ok:
                ok_all = False
            time.sleep(0.01)
    return ok_all

def config_save(ec: EspConn, filename="default.ini"):
    cp = configparser.ConfigParser()
    for m in range(NUM_ABEAST):
        sec = f"ABeast_{m+1}"
        cp[sec] = {}
        for k, addr in REGISTER_MAP.items():
            v = read_reg(ec, m, addr)
            cp[sec][k] = str(v if v is not None else 0)

    with open(filename, "w") as f:
        cp.write(f)
    print(f"✅ Saved: {filename}")

# ====== Logs (ESP_...) ======
# Ton firmware renvoie:
#   LOG_DATA_START <start> <count>
#   LOG_ENTRY idx ts c0..c8
#   LOG_DATA_END

def _read_log_block_ec(ec: EspConn, timeout=10.0):
    entries = []
    start = time.time()
    in_block = False
    while time.time() - start < timeout:
        line = _recv_line_ec(ec, timeout=0.6)
        if not line:
            continue
        if line.startswith("LOG_DATA_START"):
            in_block = True
            continue
        if line.startswith("LOG_DATA_END"):
            return entries
        if in_block and line.startswith("LOG_ENTRY"):
            parts = line.split()
            # LOG_ENTRY idx ts 9 counters
            if len(parts) >= 2 + 1 + 9:
                try:
                    idx = int(parts[1])
                    ts = int(parts[2])
                    counters = [int(x) for x in parts[3:12]]
                    entries.append({"index": idx, "timestamp": ts, "counters": counters})
                except:
                    pass

    return entries

def log_status(ec: EspConn):
    resp = send_text_command(ec, "ESP_LOG_STATUS", expect_reply=True, timeout=2.0)
    print(resp if resp else "No reply")

def log_enable(ec: EspConn):
    resp = send_text_command(ec, "ESP_LOG_ENABLE", expect_reply=True, timeout=2.0)
    print(resp if resp else "No reply")

def log_disable(ec: EspConn):
    resp = send_text_command(ec, "ESP_LOG_DISABLE", expect_reply=True, timeout=2.0)
    print(resp if resp else "No reply")

def log_interval(ec: EspConn, ms: int):
    resp = send_text_command(ec, f"ESP_LOG_INTERVAL {ms}", expect_reply=True, timeout=2.0)
    print(resp if resp else "No reply")

def log_read(ec: EspConn, start_i: int, count: int):
    with ec.cmd_lock:
        sock = ec.sock
        _drain_queue(ec)
        sock.sendall(f"ESP_LOG_READ {start_i} {count}\n".encode("utf-8"))
        t = max(12.0, 0.12 * count + 3.0)
        entries = _read_log_block_ec(ec, timeout=t)

        if not entries:
            print("No data")
            return []
        # display
        header = "Index    Timestamp  " + "".join([f"A{i//3}C{i%3}".ljust(9) for i in range(9)])
        print(header)
        print("-" * len(header))
        for e in entries:
            line = f"{e['index']:<8} {e['timestamp']:<10} "
            for c in e["counters"]:
                line += f"{c:<8} "
            print(line)
        return entries
def log_read_chunked(ec: EspConn, start_i: int, count: int, chunk=50):
    with ec.cmd_lock:
        out = []
        i = start_i
        remaining = count
        while remaining > 0:
            c = min(chunk, remaining)
            # timeout proportionnel
            t = max(12.0, 0.12 * c + 3.0)
            _drain_queue(ec)
            ec.sock.sendall(f"ESP_LOG_READ {i} {c}\n".encode("utf-8"))
            part = _read_log_block_ec(ec, timeout=t)
            if not part:
                print(f"⚠️ chunk vide à i={i} c={c}")
                # tu peux break ou retry 1x
                break
            out.extend(part)
            i += c
            remaining -= c
        return out

def log_latest(ec: EspConn, count: int = 10):
    with ec.cmd_lock:
        sock = ec.sock
        _drain_queue(ec)
        sock.sendall(f"ESP_LOG_LATEST {count}\n".encode("utf-8"))

        # timeout un peu plus large que 12s au cas où
        t = max(12.0, 0.12 * count + 3.0)
        entries = _read_log_block_ec(ec, timeout=t)

        if not entries:
            print("No data")
            return []

        header = "Index    Timestamp  " + "".join([f"A{i//3}C{i%3}".ljust(9) for i in range(9)])
        print(header)
        print("-" * len(header))
        for e in entries:
            line = f"{e['index']:<8} {e['timestamp']:<10} "
            for c in e["counters"]:
                line += f"{c:<8} "
            print(line)
        return entries


def log_clear(ec: EspConn):
    resp = send_text_command(ec, "ESP_LOG_CLEAR", expect_reply=True, timeout=2.0)
    print(resp if resp else "No reply")

def log_clear_all(ec: EspConn):
    resp = send_text_command(ec, "ESP_LOG_CLEAR_ALL", expect_reply=True, timeout=4.0)
    # peut être long; on lit quelques lignes
    print(resp if resp else "Command sent (no immediate reply)")
def is_socket_alive(sock: socket.socket) -> bool:
    try:
        r, _, _ = select.select([sock], [], [], 0.0)
        if r:
            data = sock.recv(1, socket.MSG_PEEK)
            if data == b"":
                return False
        return True
    except:
        return False

def log_save_to_csv(entries, filename):
    with open(filename, "w", newline="") as f:
        wr = csv.writer(f)
        header = ["Index", "Timestamp"] + [f"A{i//3}C{i%3}" for i in range(9)]
        wr.writerow(header)
        for e in entries:
            wr.writerow([e["index"], e["timestamp"], *e["counters"]])
    print(f"✅ Saved {len(entries)} entries -> {filename}")

# =======================
#   CLI PRINCIPALE
# =======================

def main():
    global srv
    srv = TcpMultiEspServer(HOST, PORT)
    if not srv.start():
        return
    pc_srv = PcCommandServer(srv, PC_HOST, PC_PORT)

    print("\n====== AlphaBeast Raspberry TCP Controller (Pi 5 / TCP only) ======")
    print("Tape 'help' pour la liste des commandes.\n")

    while True:
        sel = srv.selected if srv.selected else "none"
        try:
            sel = srv.selected if srv.selected else "none"
            srv.current_prompt = f"[TCP:{sel}]> "
            cmdline = input(srv.current_prompt).strip()

            # cmdline = input(f"[TCP:{sel}]> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not cmdline:
            continue

        parts = cmdline.split()
        cmd = parts[0].lower()

        if cmd in ("exit", "quit"):
            break

        if cmd == "help":
            print_help()
            continue

        if cmd == "esp" and len(parts) >= 2:
            sub = parts[1].lower()
            if sub == "list":
                srv.list_esps()
            elif sub == "select" and len(parts) >= 3:
                srv.select_esp(parts[2])
            else:
                print("Usage: esp list | esp select <id>")
            continue

        ec = srv.get_selected()
        if not ec:
            print("❌ No ESP selected/connected.")
            continue

        # --- anciennes commandes ---
        if cmd == "status":
            cmd_status(ec)

        elif cmd == "netinfo":
            cmd_netinfo(ec)

        elif cmd == "mux" and len(parts) == 2:
            try:
                ch = int(parts[1])
                cmd_mux(ec, ch)
            except:
                print("Usage: mux <0-3>")

        elif cmd == "send" and len(parts) >= 2:
            txt = " ".join(parts[1:])
            cmd_send(ec, txt)

        elif cmd == "read" and len(parts) == 3:
            try:
                m = int(parts[1]); reg = int(parts[2])
                cmd_read(ec, m, reg)
            except:
                print("Usage: read <m> <reg>")

        elif cmd == "write" and len(parts) == 4:
            try:
                m = int(parts[1]); reg = int(parts[2]); val = int(parts[3])
                cmd_write(ec, m, reg, val)
            except:
                print("Usage: write <m> <reg> <val>")

        elif cmd == "view" and len(parts) >= 2:
            try:
                m = int(parts[1])
                show_c = (len(parts) >= 3 and parts[2].lower() == "counters")
                cmd_view(ec, m, show_c)
            except Exception as e:
                print(f"view error: {e}")

        elif cmd == "bias":
            cmd_bias(ec)

        elif cmd == "reset" and len(parts) == 2:
            try:
                m = int(parts[1])
                cmd_reset(ec, m)
            except:
                print("Usage: reset <m>")
        elif cmd == "reset_all" and len(parts) == 1:
            try:
                for m in range(3):
                    cmd_reset(ec, m)
            except:
                print("Usage: reset_all")

        elif cmd == "counter" and len(parts) == 3:
            try:
                m = int(parts[1]); c = int(parts[2])
                cmd_counter(ec, m, c)
            except:
                print("Usage: counter <m> <c>")

        elif cmd == "cntcsv":
            cmd_cntcsv(ec)

        elif cmd == "cfgsnap":
            cmd_cfgsnap(ec)

        # --- config ini ---
        elif cmd == "config" and len(parts) >= 2:
            sub = parts[1].lower()
            filename = parts[2] if len(parts) >= 3 else "default.ini"
            if sub == "show":
                config_show(filename)
            elif sub == "apply":
                ok = config_apply(ec, filename)
                print("✅ OK" if ok else "⚠️ Applied with errors")
            elif sub == "save":
                config_save(ec, filename)
            else:
                print("Usage: config show|apply|save [file.ini]")

        # --- logs ---
        elif cmd == "log_status":
            log_status(ec)
        elif cmd == "log_enable":
            log_enable(ec)
        elif cmd == "log_disable":
            log_disable(ec)
        elif cmd == "log_interval" and len(parts) == 2:
            try:
                ms = int(parts[1])
                log_interval(ec, ms)
            except:
                print("Usage: log_interval <ms>")
        elif cmd == "log_read" and len(parts) == 3:
            try:
                s = int(parts[1]); c = int(parts[2])
                log_read(ec, s, c)
            except:
                print("Usage: log_read <start> <count>")
        elif cmd == "log_latest":
            try:
                c = int(parts[1]) if len(parts) >= 2 else 10
                log_latest(ec, c)
            except:
                print("Usage: log_latest [count]")
        elif cmd == "log_save":
            # log_save all  OR log_save <start> <count>
            if len(parts) == 2 and parts[1].lower() == "all":
                # on tente de récupérer "Entries: N" depuis ESP_LOG_STATUS
                resp = send_text_command(ec, "ESP_LOG_STATUS", expect_reply=True, timeout=2.0) or ""
                m = re.search(r"Entries:\s*(\d+)", resp)
                if not m:
                    print("❌ Cannot get Entries from ESP_LOG_STATUS.")
                    continue
                total = int(m.group(1))
                entries = log_read_chunked(ec, 0, total, chunk=50)

                ts = time.strftime("%Y%m%d_%H%M%S")
                fn = f"abeast_logs_{ec.esp_id}_{ts}.csv"
                log_save_to_csv(entries, fn)
            elif len(parts) == 3:
                try:
                    s = int(parts[1]); c = int(parts[2])
                    entries = log_read_chunked(ec, s, c, chunk=50)

                    ts = time.strftime("%Y%m%d_%H%M%S")
                    fn = f"abeast_logs_{ec.esp_id}_{ts}.csv"
                    log_save_to_csv(entries, fn)
                except:
                    print("Usage: log_save <start> <count> | log_save all")
            else:
                print("Usage: log_save <start> <count> | log_save all")

        elif cmd == "log_clear":
            log_clear(ec)
        elif cmd == "log_clear_all":
            log_clear_all(ec)

        else:
            print("Unknown command. Type help.")
    try:
        pc_srv.stop()
    except:
        pass

    srv.stop()

if __name__ == "__main__":
    main()

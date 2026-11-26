#!/usr/bin/env python3
"""
servidor.py - Hilo 3 de ShellDoc Web (Persona 3)

Espera a que el Hilo 2 termine la renderizacion y entonces publica la
presentacion en el navegador.

Estrategia:
  A) quarto preview (subprocess)   -> opcion principal, la que pide el enunciado
  B) http.server de Python         -> respaldo si Quarto no esta o falla

Interfaz que debe usar main.py (Persona 4):

    hilo_servidor(sem_render_listo, estado, stop_event)

    sem_render_listo : threading.Semaphore(0). El Hilo 2 hace release() SIEMPRE
                       al terminar, haya ido bien o mal (evita interbloqueos).
    estado           : dict compartido. El Hilo 2 pone estado["render_ok"] = True/False.
                       Este hilo escribe estado["server_ok"] = True/False.
    stop_event       : threading.Event. main.py lo activa (Ctrl+C) para cerrar.

Prueba solo (sin los demas):
    python3 servidor.py --prueba          # caso normal
    python3 servidor.py --prueba-error    # simula fallo del Hilo 2
"""

import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HTML_POR_DEFECTO = "presentacion.html"
QMD_POR_DEFECTO = "presentacion.qmd"
PUERTO_POR_DEFECTO = 4200
INTENTOS_PUERTO = 10          # prueba puerto, puerto+1, ...
ESPERA_ARRANQUE_QUARTO = 30   # segundos maximos para que quarto abra el puerto


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def log(msg):
    """Mensaje legible con hora y nombre del hilo."""
    nombre = threading.current_thread().name
    print(f"[{time.strftime('%H:%M:%S')}] [{nombre}] {msg}", flush=True)


def puerto_libre(puerto):
    """True si el puerto local esta disponible."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", puerto))
            return True
        except OSError:
            return False


def buscar_puerto(inicial):
    """Devuelve el primer puerto libre a partir de 'inicial', o None."""
    for p in range(inicial, inicial + INTENTOS_PUERTO):
        if puerto_libre(p):
            return p
        log(f"Puerto {p} ocupado, pruebo el siguiente...")
    return None


def puerto_responde(puerto):
    """True si alguien acepta conexiones en el puerto."""
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=0.5):
            return True
    except OSError:
        return False


def html_valido(ruta):
    """Comprueba que el HTML exista, no este vacio y parezca HTML real."""
    if not os.path.isfile(ruta):
        return False, f"no existe '{ruta}'"
    if os.path.getsize(ruta) == 0:
        return False, f"'{ruta}' esta vacio"
    with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
        inicio = f.read(4096).lower()
    if "<html" not in inicio and "<!doctype" not in inicio:
        return False, f"'{ruta}' no parece un documento HTML"
    return True, "HTML valido"


def cerrar_proceso(proc):
    """Cierra quarto y todos sus hijos sin dejar zombis ni el puerto ocupado."""
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)   # grupo completo (quarto lanza hijos)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        log("El proceso no respondio a SIGTERM, uso SIGKILL.")
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


# ----------------------------------------------------------------------
# Opcion A: quarto preview
# ----------------------------------------------------------------------
def iniciar_quarto(qmd, puerto, carpeta):
    """
    Lanza 'quarto preview'. Devuelve el Popen si el servidor quedo arriba,
    o None si no se pudo (para pasar a la opcion B).
    """
    if shutil.which("quarto") is None:
        log("Quarto no esta instalado (quarto --version falla).")
        return None
    if not os.path.isfile(os.path.join(carpeta, qmd)):
        log(f"No encuentro '{qmd}' para quarto preview.")
        return None

    log(f"Lanzando: quarto preview {qmd} --no-browser --port {puerto}")
    proc = subprocess.Popen(
        ["quarto", "preview", qmd, "--no-browser", "--port", str(puerto)],
        cwd=carpeta,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,   # grupo propio para poder cerrarlo completo
    )

    limite = time.time() + ESPERA_ARRANQUE_QUARTO
    while time.time() < limite:
        if proc.poll() is not None:
            log(f"quarto preview termino antes de tiempo (codigo {proc.returncode}).")
            return None
        if puerto_responde(puerto):
            return proc
        time.sleep(0.5)

    log("quarto preview no abrio el puerto a tiempo.")
    cerrar_proceso(proc)
    return None


# ----------------------------------------------------------------------
# Opcion B: http.server
# ----------------------------------------------------------------------
class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, formato, *args):   # evita ruido en consola
        pass


def iniciar_http(carpeta, puerto):
    """Servidor estatico de respaldo. Devuelve (httpd, hilo_http)."""
    handler = partial(_Handler, directory=carpeta)
    httpd = ThreadingHTTPServer(("0.0.0.0", puerto), handler)
    hilo = threading.Thread(target=httpd.serve_forever, name="http-server", daemon=True)
    hilo.start()
    return httpd, hilo


# ----------------------------------------------------------------------
# Hilo 3
# ----------------------------------------------------------------------
def hilo_servidor(sem_render_listo, estado, stop_event,
                  html=HTML_POR_DEFECTO, qmd=QMD_POR_DEFECTO,
                  puerto=PUERTO_POR_DEFECTO, carpeta="."):
    estado["server_ok"] = False
    carpeta = os.path.abspath(carpeta)
    ruta_html = os.path.join(carpeta, html)

    # 1) wait(): esperar al Hilo 2 (con timeout para poder abortar con Ctrl+C)
    log("Esperando el semaforo del Hilo 2 (renderizacion)... [wait]")
    while not sem_render_listo.acquire(timeout=0.5):
        if stop_event.is_set():
            log("Cierre solicitado mientras esperaba. Termino sin iniciar servidor.")
            return
    log("Semaforo recibido del Hilo 2. [wait superado]")

    # 2) El Hilo 2 pudo haber fallado
    if not estado.get("render_ok", False):
        log("El Hilo 2 reporto ERROR. No inicio el servidor y termino de forma controlada.")
        return

    # 3) Validar el HTML antes de servirlo
    ok, motivo = html_valido(ruta_html)
    if not ok:
        log(f"ERROR: {motivo}. No inicio el servidor.")
        return
    log(f"Validacion: {motivo} ({os.path.getsize(ruta_html)} bytes).")

    # 4) Elegir puerto
    puerto_elegido = buscar_puerto(puerto)
    if puerto_elegido is None:
        log(f"ERROR: no hay puertos libres entre {puerto} y {puerto + INTENTOS_PUERTO - 1}.")
        return

    # 5) Iniciar servidor: A (quarto) y, si falla, B (http.server)
    proc = None
    httpd = None
    proc = iniciar_quarto(qmd, puerto_elegido, carpeta)
    if proc is not None:
        modo = "quarto preview"
    else:
        log("Uso el servidor de respaldo (http.server de Python).")
        try:
            httpd, _ = iniciar_http(carpeta, puerto_elegido)
        except OSError as e:
            log(f"ERROR: no pude abrir el puerto {puerto_elegido}: {e}")
            return
        modo = "http.server"

    estado["server_ok"] = True
    estado["server_url"] = f"http://localhost:{puerto_elegido}/{html}"
    log(f"Servidor iniciado ({modo}) -> {estado['server_url']}")
    log("Presiona Ctrl+C en la terminal principal para detenerlo.")

    # 6) Mantenerse vivo hasta que el usuario detenga la aplicacion
    try:
        while not stop_event.wait(timeout=1):
            if proc is not None and proc.poll() is not None:
                log(f"quarto preview se cerro inesperadamente (codigo {proc.returncode}).")
                estado["server_ok"] = False
                break
    finally:
        # 7) Cierre controlado
        log("Deteniendo servidor...")
        if proc is not None:
            cerrar_proceso(proc)
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        log("Servidor detenido de forma controlada. Puerto liberado.")


# ----------------------------------------------------------------------
# Prueba independiente (no la usa main.py)
# ----------------------------------------------------------------------
_HTML_PRUEBA = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Prueba</title></head>
<body style="background:#222;color:#eee;font-family:monospace">
<h1>ShellDoc Web - prueba del Hilo 3</h1><pre>$ whoami
estudiante</pre></body></html>
"""


def _prueba(simular_error=False):
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="shelldoc_")
    with open(os.path.join(carpeta, HTML_POR_DEFECTO), "w", encoding="utf-8") as f:
        f.write(_HTML_PRUEBA)

    sem = threading.Semaphore(0)
    estado = {"render_ok": not simular_error}
    stop = threading.Event()

    t = threading.Thread(target=hilo_servidor, name="Hilo-3-Servidor",
                         args=(sem, estado, stop), kwargs={"carpeta": carpeta})
    t.start()

    print("[main-prueba] Simulo que el Hilo 2 tarda 2 s en renderizar...")
    time.sleep(2)
    print("[main-prueba] Hilo 2 termina -> release()")
    sem.release()

    if simular_error:
        t.join()
    else:
        try:
            while t.is_alive():
                t.join(timeout=0.5)
        except KeyboardInterrupt:
            print("\n[main-prueba] Ctrl+C detectado -> stop_event.set()")
            stop.set()
            t.join()
    shutil.rmtree(carpeta, ignore_errors=True)
    print("[main-prueba] Fin. estado =", estado)


if __name__ == "__main__":
    import sys
    if "--prueba-error" in sys.argv:
        _prueba(simular_error=True)
    elif "--prueba" in sys.argv:
        _prueba()
    else:
        print(__doc__)

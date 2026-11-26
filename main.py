#!/usr/bin/env python3
"""
main.py - Orquestador de hilos y semaforos de ShellDoc Web.

Integra y sincroniza las cuatro etapas del proyecto:
  - Hilo 1: session.txt -> presentacion.qmd
  - Hilo 2: presentacion.qmd -> presentacion.html
  - Hilo 3: servidor web de Quarto
  - Hilo 4: publicacion automatica en GitHub Pages
"""

import os
import sys
import threading
import time

import transformador
import renderizador
from servidor import hilo_servidor

# HILO 4: Importar el publicador
from publicador import hilo_publicador

ARCHIVO_SESION = "session.txt"
ARCHIVO_QMD = "presentacion.qmd"
ARCHIVO_HTML = "presentacion.html"
PUERTO_SERVIDOR = 4200


def log(msg: str) -> None:
    """Imprime un mensaje con hora y nombre del hilo actual."""
    hilo = threading.current_thread().name
    print(f"[{time.strftime('%H:%M:%S')}] [{hilo}] {msg}", flush=True)


def hilo_1_transformacion(
    sem_qmd_listo: threading.Semaphore,
    estado: dict,
    lock_estado: threading.Lock,
    stop_event: threading.Event,
) -> None:

    log("Iniciando transformacion de session.txt a presentacion.qmd...")

    try:
        if stop_event.is_set():
            log("Cierre detectado antes de transformar. Cancelando Hilo 1.")
            with lock_estado:
                estado["transform_ok"] = False
            return

        if not os.path.isfile(ARCHIVO_SESION) or os.path.getsize(ARCHIVO_SESION) == 0:
            raise FileNotFoundError(
                f"No se encontro '{ARCHIVO_SESION}' o el archivo esta vacio. "
                "Ejecuta primero captura.py para registrar la sesion."
            )

        comandos = transformador.leer_sesion(ARCHIVO_SESION)

        if not comandos:
            raise ValueError(
                f"No se identificaron comandos validos dentro de '{ARCHIVO_SESION}'."
            )

        transformador.generar_qmd(comandos, ARCHIVO_QMD)

        if not os.path.isfile(ARCHIVO_QMD) or os.path.getsize(ARCHIVO_QMD) == 0:
            raise RuntimeError(
                f"El archivo '{ARCHIVO_QMD}' no se genero correctamente."
            )

        with lock_estado:
            estado["transform_ok"] = True

        log(f"Transformacion exitosa: '{ARCHIVO_QMD}' generado ({len(comandos)} comandos).")

    except Exception as exc:
        with lock_estado:
            estado["transform_ok"] = False
            estado["error"] = f"Hilo 1: {exc}"

        log(f"ERROR en Hilo 1: {exc}")

    finally:
        log("Liberando semaforo de QMD listo -> release() [signal]")
        sem_qmd_listo.release()


def hilo_2_renderizacion(
    sem_qmd_listo: threading.Semaphore,
    sem_render_listo: threading.Semaphore,
    sem_publicacion: threading.Semaphore,
    estado: dict,
    lock_estado: threading.Lock,
    stop_event: threading.Event,
) -> None:

    log("Esperando semaforo del Hilo 1 (QMD listo)... [wait]")

    try:
        while not sem_qmd_listo.acquire(timeout=0.5):

            if stop_event.is_set():
                log("Cierre solicitado mientras esperaba al Hilo 1. Saliendo...")

                with lock_estado:
                    estado["render_ok"] = False

                return

        log("Semaforo del Hilo 1 adquirido. [wait superado]")

        with lock_estado:
            transform_ok = estado.get("transform_ok", False)

        if stop_event.is_set():
            log("Cierre solicitado. Se omite la renderizacion.")

            with lock_estado:
                estado["render_ok"] = False

            return

        if not transform_ok:
            log("El Hilo 1 reporto fallo. Se omite la renderizacion de forma controlada.")

            with lock_estado:
                estado["render_ok"] = False

            return

        log("Iniciando renderizacion con Quarto (presentacion.qmd -> presentacion.html)...")

        exito_render = renderizador.renderizar()

        if not exito_render:
            raise RuntimeError(
                "La funcion renderizador.renderizar() retorno False."
            )

        with lock_estado:
            estado["render_ok"] = True

        log("Renderizacion finalizada correctamente ('presentacion.html' listo).")

    except Exception as exc:
        with lock_estado:
            estado["render_ok"] = False
            estado["error"] = f"Hilo 2: {exc}"

        log(f"ERROR en Hilo 2: {exc}")

    finally:
        # HILO 4: Notificar al publicador
        log("Liberando semaforo de publicacion -> release() [signal]")
        sem_publicacion.release()


# HILO 4: Ejecutar el publicador y notificar al servidor
def hilo_4_publicacion(
    sem_publicacion,
    sem_render_listo,
    estado,
    lock_estado,
    stop_event,
):

    try:
        hilo_publicador(sem_publicacion, estado)

    except Exception as exc:
        with lock_estado:
            estado["publish_ok"] = False

        log(f"ERROR en Hilo 4: {exc}")

    finally:
        # Permitir que el servidor inicie incluso si GitHub falla.
        # Esto evita que Quarto Preview renderice mientras
        # el publicador esta copiando los archivos.
        log("Liberando semaforo del servidor -> release() [signal]")
        sem_render_listo.release()


def main() -> None:

    carpeta_trabajo = os.path.dirname(os.path.abspath(__file__))
    os.chdir(carpeta_trabajo)

    # Semaforos originales
    sem_qmd_listo = threading.Semaphore(0)
    sem_render_listo = threading.Semaphore(0)

    # HILO 4: Nuevo semaforo
    sem_publicacion = threading.Semaphore(0)

    lock_estado = threading.Lock()
    stop_event = threading.Event()

    estado = {
        "transform_ok": False,
        "render_ok": False,
        "server_ok": False,
        "server_url": None,
        "publish_ok": False,
        "error": None,
    }

    log("=== INICIANDO SHELLDOC WEB ===")

    hilo_1 = threading.Thread(
        target=hilo_1_transformacion,
        name="Hilo-1-Transformador",
        args=(
            sem_qmd_listo,
            estado,
            lock_estado,
            stop_event,
        ),
    )

    hilo_2 = threading.Thread(
        target=hilo_2_renderizacion,
        name="Hilo-2-Renderizador",
        args=(
            sem_qmd_listo,
            sem_render_listo,
            sem_publicacion,
            estado,
            lock_estado,
            stop_event,
        ),
    )

    hilo_3 = threading.Thread(
        target=hilo_servidor,
        name="Hilo-3-Servidor",
        args=(
            sem_render_listo,
            estado,
            stop_event,
        ),
        kwargs={
            "html": ARCHIVO_HTML,
            "qmd": ARCHIVO_QMD,
            "puerto": PUERTO_SERVIDOR,
            "carpeta": carpeta_trabajo,
        },
    )

    # HILO 4: Crear el hilo publicador
    hilo_4 = threading.Thread(
        target=hilo_4_publicacion,
        name="Hilo-4-Publicador",
        args=(
            sem_publicacion,
            sem_render_listo,
            estado,
            lock_estado,
            stop_event,
        ),
    )

    # Iniciar los cuatro hilos
    hilo_1.start()
    hilo_2.start()
    hilo_3.start()
    hilo_4.start()

    hilos = (hilo_1, hilo_2, hilo_3, hilo_4)

    try:
        while any(h.is_alive() for h in hilos):
            for h in hilos:
                h.join(timeout=0.3)

    except KeyboardInterrupt:
        print()
        log("Ctrl+C detectado. Activando stop_event para cierre ordenado...")

        stop_event.set()

        for h in hilos:
            h.join()

    log("=== EJECUCION FINALIZADA ===")
    log(f"Estado final del sistema: {estado}")

    if not estado.get("publish_ok"):
        log("ADVERTENCIA: La publicacion en GitHub no se completo.")

    if estado.get("error") or not estado.get("transform_ok") or not estado.get("render_ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()

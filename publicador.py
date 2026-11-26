import subprocess
import shutil
import threading
import time
import os
from pathlib import Path

# Configuracion de rutas
PROYECTO = Path(__file__).resolve().parent
REPOSITORIO = Path.home() / "ShellDocPublicacion"

URL_PUBLICA = "https://domevalverde1.github.io/shelldoc-web/"


def log(mensaje):
    hora = time.strftime("%H:%M:%S")
    hilo = threading.current_thread().name
    print(f"[{hora}] [{hilo}] {mensaje}", flush=True)


def ejecutar_git(argumentos):
    entorno = os.environ.copy()

    # Evitar solicitudes interactivas de credenciales
    entorno["GIT_TERMINAL_PROMPT"] = "0"

    return subprocess.run(
        ["git"] + argumentos,
        cwd=REPOSITORIO,
        env=entorno,
        check=True,
        timeout=120
    )


def publicar():

    log("Iniciando publicacion automatica...")

    try:
        html = PROYECTO / "presentacion.html"
        recursos = PROYECTO / "presentacion_files"
        css = PROYECTO / "estilos.css"

        # Validar los archivos necesarios
        if not html.is_file() or html.stat().st_size == 0:
            log("ERROR: No existe un HTML valido.")
            return False

        if not recursos.is_dir():
            log("ERROR: No existen los recursos de Quarto.")
            return False

        if not css.is_file():
            log("ERROR: No existe estilos.css.")
            return False

        if not (REPOSITORIO / ".git").is_dir():
            log("ERROR: No existe el repositorio local.")
            return False

        # Actualizar el repositorio local
        log("Actualizando repositorio local...")
        ejecutar_git(["pull", "--ff-only", "origin", "main"])

        # Copiar la presentacion HTML y los estilos
        shutil.copy2(html, REPOSITORIO / "index.html")
        shutil.copy2(css, REPOSITORIO / "estilos.css")

        # Copiar los recursos de Reveal.js
        destino = REPOSITORIO / "presentacion_files"

        if destino.exists():
            shutil.rmtree(destino)

        shutil.copytree(recursos, destino)

        # Evitar procesamiento de Jekyll
        (REPOSITORIO / ".nojekyll").touch()

        log("Archivos preparados para publicar.")

        # Preparar archivos para el commit
        ejecutar_git([
            "add",
            "--",
            "index.html",
            "estilos.css",
            "presentacion_files",
            ".nojekyll"
        ])

        # Comprobar si existen cambios
        resultado = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=REPOSITORIO
        )

        if resultado.returncode == 1:

            ejecutar_git([
                "commit",
                "-m",
                "Actualizacion automatica de ShellDoc Web"
            ])

        elif resultado.returncode == 0:
            log("No existen cambios nuevos.")

        else:
            log("ERROR: No se pudieron verificar los cambios.")
            return False

        # Publicar automaticamente en GitHub
        log("Enviando archivos a GitHub...")

        ejecutar_git(["push", "origin", "main"])

        log("Archivos enviados correctamente a GitHub.")
        log("URL publica: " + URL_PUBLICA)
        log("Despliegue web pendiente de GitHub Pages.")

        return True

    except subprocess.TimeoutExpired:
        log("ERROR: Tiempo de espera de Git agotado.")
        return False

    except subprocess.CalledProcessError as error:
        log(f"ERROR de Git: {error}")
        return False

    except OSError as error:
        log(f"ERROR del sistema: {error}")
        return False


# Hilo 4: Publicacion automatica
def hilo_publicador(sem_publicacion, estado):

    estado["publish_ok"] = False

    log("Esperando semaforo del Hilo 2... [wait]")

    sem_publicacion.acquire()

    log("Semaforo adquirido. [wait superado]")

    # Verificar el resultado del Hilo 2
    if not estado.get("render_ok", False):
        log("Renderizacion fallida. Publicacion cancelada.")
        return

    # Ejecutar la publicacion
    estado["publish_ok"] = publicar()


# Prueba independiente del publicador
if __name__ == "__main__":
    raise SystemExit(0 if publicar() else 1)

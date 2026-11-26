import subprocess
from pathlib import Path
import threading
import time


def log(mensaje):
    nombre = threading.current_thread().name
    hora = time.strftime("%H:%M:%S")
    print(f"[{hora}] [{nombre}] {mensaje}", flush=True)


def renderizar():

    carpeta = Path(__file__).resolve().parent
    archivo_qmd = carpeta / "presentacion.qmd"
    archivo_html = carpeta / "presentacion.html"

    log("Iniciando renderizacion...")

    try:
        # Validar archivo de entrada
        if not archivo_qmd.is_file():
            log("ERROR: No existe presentacion.qmd.")
            return False

        if archivo_qmd.stat().st_size == 0:
            log("ERROR: El archivo QMD esta vacio.")
            return False

        # Eliminar HTML de una ejecucion anterior
        if archivo_html.exists():
            archivo_html.unlink()

        # Ejecutar Quarto
        log("Ejecutando Quarto...")

        subprocess.run(
            ["quarto", "render", "presentacion.qmd"],
            cwd=carpeta,
            check=True
        )

        # Validar archivo de salida
        if not archivo_html.is_file():
            log("ERROR: No se genero el HTML.")
            return False

        if archivo_html.stat().st_size == 0:
            log("ERROR: El HTML esta vacio.")
            return False

        contenido = archivo_html.read_text(
            encoding="utf-8"
        ).lower()

        if "<html" not in contenido:
            log("ERROR: El HTML generado no es valido.")
            return False

        log("Renderizacion exitosa.")
        log(f"HTML generado: {archivo_html.stat().st_size} bytes.")

        return True

    except FileNotFoundError:
        log("ERROR: No se encontro un archivo o Quarto.")
        return False

    except subprocess.CalledProcessError as error:
        log(f"ERROR de Quarto: {error}")
        return False

    except OSError as error:
        log(f"ERROR del sistema: {error}")
        return False


if __name__ == "__main__":
    resultado = renderizar()
    raise SystemExit(0 if resultado else 1)


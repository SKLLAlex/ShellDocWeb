
import re

def leer_sesion(archivo):
    comandos = []
    actual = None
    salida = []

    with open(archivo, encoding="utf-8", errors="replace") as f:
        for linea in f:
            linea = linea.strip("\r\n")
            coincidencia = re.search(r"\$\s*(.+)$", linea)

            if coincidencia:
                if actual:
                    comandos.append((actual, "\n".join(salida)))

                actual = coincidencia.group(1).strip()
                salida = []

                if actual == "exit":
                    actual = None
                    break

            elif actual:
                salida.append(linea)

    if actual:
        comandos.append((actual, "\n".join(salida)))

    return comandos


def generar_qmd(comandos, archivo):
    with open(archivo, "w", encoding="utf-8") as f:
        f.write('''---
title: "ShellDoc Web"
format:
  revealjs:
    theme: dark
    slide-number: true
---

''')

        for numero, (comando, salida) in enumerate(comandos, start=1):
            f.write(f"## Comando {numero}: {comando}\n\n")
            f.write("**Comando ejecutado:**\n\n")
            f.write(f"```bash\n$ {comando}\n```\n\n")
            f.write("**Salida:**\n\n")
            f.write("```text\n")
            f.write((salida if salida else "(Sin salida)") + "\n")
            f.write("```\n\n")

    print("Presentación QMD generada correctamente.")
    print("Total de diapositivas:", len(comandos))


def main():
    comandos = leer_sesion("session.txt")

    if not comandos:
        print("No se encontraron comandos en la sesión.")
        return

    generar_qmd(comandos, "presentacion.qmd")


if __name__ == "__main__":
    main()

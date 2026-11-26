
import subprocess

def iniciar_captura():
    print("       SHELLDOC WEB")
    print("Iniciando captura de sesión Linux...")
    print("Los comandos se guardarán en session.txt")
    print("Escribe 'exit' para finalizar la captura.")
    print("-----------------------------------")

    subprocess.run(["script", "-q", "-c", "bash", "session.txt"])

    print("-----------------------------------")
    print("Captura finalizada correctamente.")

if __name__ == "__main__":
    iniciar_captura()

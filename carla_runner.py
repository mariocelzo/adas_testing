import subprocess
import time
import os
import sys

# Percorso dell'eseguibile di CARLA.
# Assicurati che questo percorso sia ESATTAMENTE quello dove si trova CarlaUE4-Win64-Shipping.exe
CARLA_SERVER_PATH = r"C:\Users\SeSaLab Tesi\Documents\TesistiAntonioTrovato\adas_testing\WindowsNoEditor\CarlaUE4\Binaries\Win64\CarlaUE4-Win64-Shipping.exe"


def start_carla_server():
    """
    Avvia il server CARLA in un nuovo processo e lo lascia in esecuzione.
    """
    if not os.path.exists(CARLA_SERVER_PATH):
        print(f"[ERRORE] Percorso del server CARLA non trovato: {CARLA_SERVER_PATH}")
        print("Assicurati che il percorso sia corretto e che il file esista.")
        sys.exit(1)  # Esci se il percorso non è valido

    print(f"[INFO] Avvio del server CARLA da: {CARLA_SERVER_PATH}")

    # Esegui CARLA. Popen non attende il termine del processo, ma lo avvia in background.
    # cwd imposta la directory di lavoro al percorso dell'eseguibile, utile per CARLA.
    try:
        # Nota: L'output di CARLA andrà alla console dove viene eseguito questo script.
        # Se vuoi sopprimere l'output o reindirizzarlo a un file, puoi usare stdout=subprocess.DEVNULL
        # o un file descriptor. Per debugging, è meglio vederlo.
        process = subprocess.Popen(CARLA_SERVER_PATH, cwd=os.path.dirname(CARLA_SERVER_PATH))
        print(f"[INFO] Server CARLA avviato con PID: {process.pid}")
        print("[INFO] Attendi qualche secondo che il server si inizializzi...")
        time.sleep(10)  # Dai a CARLA il tempo di caricarsi completamente (potrebbe volerci di più)
        print("[INFO] Inizializzazione CARLA completata (presunta).")
        return process
    except Exception as e:
        print(f"[ERRORE] Impossibile avviare il server CARLA: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Esempio di utilizzo:
    carla_process = start_carla_server()

    print("\n[INFO] Il server CARLA è ora in esecuzione. Puoi avviare i tuoi script di simulazione.")
    print("Premi Ctrl+C per terminare questo script e il server CARLA (se avviato da qui).")

    try:
        # Questo blocco mantiene lo script in esecuzione in modo che il processo CARLA non termini.
        # CARLA continuerà a funzionare fino a quando non lo chiudi manualmente o termini questo script.
        while True:
            time.sleep(1)  # Attendi un secondo
            if carla_process.poll() is not None:  # Controlla se il processo CARLA è terminato
                print("[ATTENZIONE] Il server CARLA è terminato inaspettatamente.")
                break  # Esci dal loop se CARLA si chiude da solo
    except KeyboardInterrupt:
        print("\n[INFO] Rilevata interruzione da tastiera (Ctrl+C).")
    finally:
        # Assicurati di terminare il processo CARLA quando lo script Python si chiude
        if carla_process and carla_process.poll() is None:  # Se CARLA è ancora in esecuzione
            print("[INFO] Terminazione del processo del server CARLA...")
            carla_process.terminate()  # Invia un segnale di terminazione gentile
            try:
                carla_process.wait(timeout=5)  # Attendi fino a 5 secondi che termini
            except subprocess.TimeoutExpired:
                print("[ATTENZIONE] Il server CARLA non ha risposto alla terminazione, lo uccido.")
                carla_process.kill()  # Forza la chiusura se non risponde
            print("[INFO] Server CARLA terminato.")
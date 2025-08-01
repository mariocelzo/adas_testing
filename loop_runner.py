import os
import time
import subprocess
import sys

EXAMPLES_DIR = r"C:\Users\SeSaLab Tesi\Documents\TesistiAntonioTrovato\adas_testing\WindowsNoEditor\PythonAPI\examples"
SCRIPT_NAME = "ego_traffic.py"
PYTHON_EXE = sys.executable  # Usa l'interprete attualmente attivo

# Definisci il timeout atteso per lo script di simulazione
EXPECTED_SIMULATION_DURATION = 60  # Secondi, come definito in ego_traffic.py
# Modificato per essere lo stesso del SIMULATION_TIMEOUT nel Python script

# Tempo massimo di attesa tra uno scenario e l'altro se lo scenario finisce prima
MAX_WAIT_BETWEEN_SCENARIOS = 3 # Secondi

while True:
    print("[INFO] Avvio nuovo ciclo di simulazione CARLA...")
    start_run_time = time.time()  # Registra l'ora di inizio dell'esecuzione dello script

    try:
        # Esegui lo script e attendi il suo completamento
        result = subprocess.run(
            [PYTHON_EXE, SCRIPT_NAME],
            cwd=EXAMPLES_DIR,
            check=False,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )

        end_run_time = time.time()
        actual_duration = end_run_time - start_run_time

        print(f"[INFO] Script '{SCRIPT_NAME}' terminato con codice di uscita: {result.returncode}")
        print(f"[INFO] Durata effettiva esecuzione: {actual_duration:.2f} secondi")

        if result.stdout:
            print("\n--- Output dello script CARLA (stdout) ---")
            print(result.stdout)
            print("--- Fine output stdout ---\n")
        if result.stderr:
            print("\n--- Errori dallo script CARLA (stderr) ---")
            print(result.stderr)
            print("--- Fine output stderr ---\n")

        # Se la simulazione è terminata prima del previsto, aspetta un massimo di 3 secondi
        if actual_duration < EXPECTED_SIMULATION_DURATION:
            wait_time_needed = MAX_WAIT_BETWEEN_SCENARIOS # Wait no more than 3 seconds
            print(f"[ATTENZIONE] Lo script ha terminato prima del timeout previsto ({EXPECTED_SIMULATION_DURATION}s).")
            print(f"[INFO] Attendendo un massimo di {wait_time_needed:.2f} secondi prima del prossimo ciclo.")
            time.sleep(wait_time_needed)
        else:
            # Se la simulazione ha raggiunto o superato il timeout previsto, aspetta solo 3 secondi di "buffer"
            print(f"[INFO] La simulazione ha raggiunto o superato il timeout previsto. Attendendo {MAX_WAIT_BETWEEN_SCENARIOS:.2f} secondi prima del prossimo ciclo.")
            time.sleep(MAX_WAIT_BETWEEN_SCENARIOS)


    except Exception as e:
        print(f"[ERRORE] Qualcosa è andato storto durante l'esecuzione di '{SCRIPT_NAME}': {e}")
        print("[INFO] Attendendo un periodo di recupero di 5 secondi a causa dell'errore.\n")
        time.sleep(5)

    print("[INFO] Ciclo di simulazione completato. Riavvio...\n")
    # Il time.sleep(3) finale è ora incorporato nella logica condizionale sopra
    # o si basa sul MAX_WAIT_BETWEEN_SCENARIOS, quindi non è necessario qui
    # time.sleep(3) # Rimosso, la logica di attesa è ora sopra
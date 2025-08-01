import subprocess
import time
import json
import os
import glob
from collections import defaultdict
import socket
import carla  # assicurati che il pacchetto sia importabile

def wait_for_carla_ready(timeout=60):
    print("[ATTESA] Attesa che CARLA sia pronto...")
    start_time = time.time()
    client = carla.Client("localhost", 2000)
    client.set_timeout(2.0)

    while time.time() - start_time < timeout:
        try:
            world = client.get_world()
            if world.get_map():
                print("[OK] CARLA è pronto.")
                return True
        except RuntimeError:
            pass
        except Exception as e:
            print(f"[AVVISO] In attesa del simulatore... ({e})")
        time.sleep(1)

    print("[ERRORE] Timeout: CARLA non ha risposto con un mondo valido.")
    return False

SCENARIO_RUNNER_RESULTS_DIR = os.path.join(os.path.dirname(__file__), "scenario_runner-0.9.15", "results")

# Crea dizionari globali per i 3 obiettivi
execution_time_summary = {}
criticality_summary = {}
diversity_summary = defaultdict(lambda: 0.0)

def run_scenario(file_path, output_dir):
    scenario_name = os.path.basename(file_path)
    base_name = scenario_name.replace('.xosc', '')
    if not wait_for_carla_ready():
        print(f"[ERRORE] CARLA non disponibile, scenario '{scenario_name}' saltato.")
        return

    print(f"[ESECUZIONE] Avvio scenario: {scenario_name}")

    env = os.environ.copy()

    # Percorso personalizzato agli agents della tua build
    agents_path = r"C:\Users\SeSaLab Tesi\Documents\TesistiAntonioTrovato\adas_testing\WindowsNoEditor\PythonAPI\agents"
    carla_pythonapi_path = r"C:\Users\SeSaLab Tesi\Documents\TesistiAntonioTrovato\adas_testing\WindowsNoEditor\PythonAPI"

    env["PYTHONPATH"] = os.pathsep.join([
        agents_path,
        carla_pythonapi_path,
        env.get("PYTHONPATH", "")
    ])

    scenario_runner_path = os.path.abspath("scenario_runner-0.9.15/scenario_runner.py")
    scenario_file_path = os.path.abspath(file_path)

    start = time.time()
    result = subprocess.run(
        [
            "python",
            scenario_runner_path,
            "--openscenario", scenario_file_path,
            "--reloadWorld"
        ],
        env=env
    )
    end = time.time()

    if result.returncode != 0:
        print(f"[ERRORE] Scenario '{scenario_name}' fallito con errore: {result.stderr}")
        return

    execution_time = round(end - start, 2)

    # Lettura del log
    criticality = 0.0
    json_log = os.path.join(SCENARIO_RUNNER_RESULTS_DIR, base_name, "metrics.json")
    if os.path.exists(json_log):
        with open(json_log) as jl:
            data = json.load(jl)
            criticality = data.get("critical_events", 0)
    else:
        # Fallback su log.txt
        text_log = os.path.join(SCENARIO_RUNNER_RESULTS_DIR, f"{base_name}_results.txt")
        if os.path.exists(text_log):
            with open(text_log) as log:
                for line in log:
                    if "Collision" in line:
                        criticality += 0.5

    # Salva risultati singoli
    results = {
        "scenario": scenario_name,
        "execution_time": execution_time,
        "criticality": criticality
    }

    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, f"{base_name}_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    log_path = os.path.join(output_dir, f"{base_name}_log.txt")
    with open(log_path, "w") as log_file:
        log_file.write(f"Scenario completato: {scenario_name}\n")
        log_file.write(f"Tempo di esecuzione: {execution_time}s\n")
        log_file.write(f"Criticità: {criticality}\n")

    print(f"[COMPLETATO] Scenario '{scenario_name}' completato con successo.")

    # Aggiungi ai dizionari cumulativi
    execution_time_summary[scenario_name] = execution_time
    criticality_summary[scenario_name] = criticality

if __name__ == "__main__":
    SCENARIO_DIR = os.path.abspath(
        r"C:\Users\SeSaLab Tesi\Documents\TesistiAntonioTrovato\adas_testing\data\carla_scenarios")
    OUTPUT_DIR = os.path.abspath(
        r"C:\Users\SeSaLab Tesi\Documents\TesistiAntonioTrovato\adas_testing\newtest")

    for file_path in glob.glob(os.path.join(SCENARIO_DIR, "*.xosc")):
        run_scenario(file_path, OUTPUT_DIR)

    # Alla fine: salva i 3 JSON globali
    with open(os.path.join(OUTPUT_DIR, "execution_time.json"), "w") as f:
        json.dump(execution_time_summary, f, indent=2)

    with open(os.path.join(OUTPUT_DIR, "criticality_score.json"), "w") as f:
        json.dump(criticality_summary, f, indent=2)

    with open(os.path.join(OUTPUT_DIR, "diversity_score.json"), "w") as f:
        json.dump(diversity_summary, f, indent=2)

    print("\n[TUTTO COMPLETATO] I file JSON sono stati salvati correttamente!")
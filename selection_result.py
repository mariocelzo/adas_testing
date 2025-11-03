import os
import json
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler, OneHotEncoder
from sklearn.metrics import pairwise_distances
from datetime import datetime


# --- Funzioni di Caricamento e Estrazione Dati ---

def load_scenarios_from_folder(folder_path):
    """
    Carica tutti i file JSON da una cartella specificata, inclusi quelli nelle sottocartelle.
    Ogni file JSON è atteso essere una LISTA di eventi.
    Il codice estrarra' il PRIMO evento come rappresentativo dello scenario.
    """
    scenarios = []
    print(f"Caricamento scenari dalla cartella: {folder_path} (e sottocartelle)")
    if not os.path.exists(folder_path):
        print(f"⚠️ Attenzione: La cartella '{folder_path}' non esiste.")
        return []

    # Utilizza os.walk per attraversare l'albero delle directory
    for root, _, files in os.walk(folder_path):
        for filename in files:
            if filename.endswith(".json"):
                file_path = os.path.join(root, filename)  # Usa 'root' per costruire il percorso completo
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)

                        if isinstance(data, list) and data:
                            if data:  # Assicurati che la lista non sia vuota
                                scenario_event_data = data[0]
                                scenario_event_data['original_filename'] = filename
                                scenarios.append(scenario_event_data)
                            else:
                                print(f"⚠️ Attenzione: Il file {filename} è una lista vuota. Saltato.")
                        else:
                            print(
                                f"❌ Errore: Il file {filename} non contiene una lista valida di eventi o ha un formato inatteso. Saltato.")

                except json.JSONDecodeError as e:
                    print(f"❌ Errore di decodifica JSON nel file {filename}: {e}")
                except Exception as e:
                    print(f"❌ Errore generico durante la lettura/elaborazione del file {filename}: {e}")
    print(f"Caricati {len(scenarios)} scenari.")
    return scenarios


def extract_collisions(scenarios):
    """
    Estrae un flag binario (1 se c'è una collisione, 0 altrimenti) per ogni scenario.
    Controlla 'event_type' direttamente nell'oggetto scenario (che è un singolo evento).
    """
    collision_flags = []
    for s in scenarios:
        has_collision = 1 if s.get("event_type") == "collision" else 0
        collision_flags.append(has_collision)
    return collision_flags


def extract_exec_times(scenarios):
    """
    Estrae il tempo di esecuzione di ciascuno scenario.
    Poiché il JSON non contiene 'simulation_duration_seconds' globale,
    si assume una durata fissa.
    """
    exec_times_list = []
    FIXED_SIM_DURATION = 60.0  # Assumendo una durata fissa per ogni simulazione
    for _ in scenarios:
        exec_times_list.append(FIXED_SIM_DURATION)
    return exec_times_list


# --- Funzione per il Calcolo del Punteggio di Diversità ---

def compute_div_scores(scenarios):
    """
    Calcola il punteggio di diversità (div_score) per ogni scenario.
    Gestisce campi presenti o assenti in base al tipo di evento.
    """
    records = []

    for idx, s in enumerate(scenarios):
        record = {
            "id": idx,
            "town": s.get("town", None),
            "road_type_at_collision": s.get("road_type_at_collision", None)
        }

        record.update(s.get("weather", {}))
        record.update(s.get("town_characteristics", {}))

        records.append(record)

    df = pd.DataFrame(records)

    cat_cols = ['town']
    if 'road_type_at_collision' in df.columns:
        cat_cols.append('road_type_at_collision')

    for col in cat_cols:
        if col in df.columns:
            df[col] = df[col].fillna('Unknown')

    encoder = OneHotEncoder(sparse_output=False, handle_unknown='ignore')
    cat_encoded_df = pd.DataFrame()
    if not df.empty and any(col in df.columns for col in cat_cols):
        actual_cat_cols = [col for col in cat_cols if col in df.columns]
        if actual_cat_cols:
            cat_encoded = encoder.fit_transform(df[actual_cat_cols])
            cat_encoded_df = pd.DataFrame(cat_encoded, columns=encoder.get_feature_names_out(actual_cat_cols))

    all_cols_except_id_cat = [col for col in df.columns if col not in ["id"] + cat_cols]

    numeric_df = df[all_cols_except_id_cat].apply(pd.to_numeric, errors='coerce')
    numeric_df = numeric_df.dropna(axis=1, how='all')
    num_cols_final = numeric_df.columns.tolist()

    scaler = MinMaxScaler()
    num_scaled_df = pd.DataFrame()
    if not numeric_df.empty:
        num_scaled = scaler.fit_transform(numeric_df.fillna(0))
        num_scaled_df = pd.DataFrame(num_scaled, columns=num_cols_final)

    X = pd.concat([num_scaled_df.reset_index(drop=True), cat_encoded_df.reset_index(drop=True)], axis=1)

    if X.empty or X.shape[0] < 2:
        print(
            "Avviso: Meno di 2 scenari o dati insufficienti per calcolare la diversità. Restituendo punteggi di diversità 0.")
        return [0.0] * len(scenarios)

    dist_matrix = pairwise_distances(X, metric='manhattan')

    div_scores = [
        np.mean(np.delete(dist_matrix[i], i))
        for i in range(len(dist_matrix))
    ]

    return div_scores


# --- Algoritmo Additional Greedy ---

def additional_greedy(collisions, exec_times, divs, max_exec_time, all_scenarios):
    """
    Implementa l'algoritmo Additional Greedy per selezionare un sottoinsieme di scenari.
    """
    p = sum(collisions)

    if p == 0:
        print("Nessuna collisione registrata negli scenari di input. Selezionando tutti gli scenari per l'analisi.")
        return list(range(len(all_scenarios)))

    c = 0
    selected_scenarios_indices = []
    already_selected_set = set()

    while c < p:
        weighted_sum_scores = {}
        candidate_indices = [i for i in range(len(all_scenarios)) if i not in already_selected_set]

        if not candidate_indices:
            print("Avviso: Tutti gli scenari sono stati valutati, ma non tutte le collisioni sono state coperte.")
            break

        for scenario_idx in candidate_indices:
            try:
                normalized_exec_time = (exec_times[scenario_idx] / max_exec_time) if max_exec_time > 0 else 1.0
                if normalized_exec_time < 0.0001:
                    normalized_exec_time = 0.0001

                score = ((0.5 * divs[scenario_idx]) + (0.5 * collisions[scenario_idx])) / normalized_exec_time
                weighted_sum_scores[scenario_idx] = score
            except Exception as e:
                print(f"Errore nel calcolo dello score per scenario {scenario_idx}: {e}. Saltando.")
                continue

        if not weighted_sum_scores:
            print("Nessun scenario candidato con uno score valido è stato trovato. Interruzione.")
            break

        best_scenario_idx = max(weighted_sum_scores, key=weighted_sum_scores.get)
        already_selected_set.add(best_scenario_idx)

        if collisions[best_scenario_idx]:
            c += 1

        selected_scenarios_indices.append(best_scenario_idx)

    return selected_scenarios_indices


# --- Esecuzione Completa dello Script ---

if __name__ == "__main__":
    # --- Configurazione Path ---
    input_folder = "/Users/mariocelzo/Library/Mobile Documents/com~apple~CloudDocs/UNIVERSITA/TIROCINIO/adas_testing/simulation_output"

    current_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    analysis_output_folder = f"analysis_results/run_{current_timestamp}"
    os.makedirs(analysis_output_folder, exist_ok=True)
    print(f"\n📁 I risultati dell'analisi verranno salvati in: {os.path.abspath(analysis_output_folder)}")

    # Step 1: Caricamento e pre-processing degli scenari
    all_scenarios = load_scenarios_from_folder(input_folder)

    if not all_scenarios:
        print("Nessuno scenario da analizzare. Termino il programma.")
        exit()

    collisions = extract_collisions(all_scenarios)
    exec_times = extract_exec_times(all_scenarios)
    divs = compute_div_scores(all_scenarios)

    max_exec_time = max(exec_times) if exec_times else 0.0
    if max_exec_time == 0.0 and len(exec_times) > 0:
        max_exec_time = 1.0

    print(f"\n--- Riepilogo Caricamento Dati ---")
    print(f"Numero totale di scenari caricati: {len(all_scenarios)}")
    print(f"Flag collisioni (1=sì, 0=no): {collisions}")
    print(f"Tempi di esecuzione (secondi): {[f'{t:.2f}' for t in exec_times]}")
    print(f"Punteggi di diversità: {[f'{d:.3f}' for d in divs]}")
    print(f"Tempo di esecuzione massimo: {max_exec_time:.2f} secondi")

    # Step 2: Stampa statistiche globali iniziali sull'intera suite
    print("\n--- Statistiche Iniziali dell'Intera Suite di Scenari ---")
    print(f"Totale collisioni rilevate: {sum(collisions)}")
    print(f"Tempo totale di esecuzione combinato: {sum(exec_times):.2f} secondi")
    print(f"Somma dei punteggi di diversità: {sum(divs):.3f}")

    # Step 3: Applicazione dell'algoritmo greedy per la selezione
    print("\n--- Avvio Selezione Scenari con Algoritmo Greedy ---")
    selected_scenario_indices = additional_greedy(collisions, exec_times, divs, max_exec_time, all_scenarios)

    print(f"\n--- Risultati Selezione Greedy ---")
    print(f"Numero di scenari selezionati: {len(selected_scenario_indices)}")
    print(f"Indici degli scenari selezionati: {selected_scenario_indices}")

    # Step 4: Calcolo delle metriche per la suite selezionata
    selected_collisions = [collisions[i] for i in selected_scenario_indices]
    selected_exec_times = [exec_times[i] for i in selected_scenario_indices]
    selected_divs = [divs[i] for i in selected_scenario_indices]

    # Step 5: Stampa statistiche finali della suite selezionata
    print("\n--- Statistiche della Suite di Scenari Selezionata ---")
    print(f"Totale collisioni coperte: {sum(selected_collisions)}")
    print(f"Tempo totale di esecuzione della suite selezionata: {sum(selected_exec_times):.2f} secondi")
    print(f"Somma dei punteggi di diversità della suite selezionata: {sum(selected_divs):.3f}")

    # Step 6: Salvataggio dei risultati in un file JSON
    analysis_results = {
        "input_folder": input_folder,
        "total_scenarios_analyzed": len(all_scenarios),
        "initial_suite_stats": {
            "total_collisions": sum(collisions),
            "total_execution_time_seconds": f"{sum(exec_times):.2f}",
            "sum_diversity_scores": f"{sum(divs):.3f}"
        },
        "selected_suite_stats": {
            "num_selected_scenarios": len(selected_scenario_indices),
            "selected_scenario_indices": selected_scenario_indices,
            "total_collisions_covered": sum(selected_collisions),
            "total_execution_time_seconds": f"{sum(selected_exec_times):.2f}",
            "sum_diversity_scores": f"{sum(selected_divs):.3f}"
        },
        "details_of_selected_scenarios": []
    }

    for idx in selected_scenario_indices:
        scenario_data = all_scenarios[idx]
        analysis_results["details_of_selected_scenarios"].append({
            "index_in_original_list": idx,
            "original_filename": scenario_data.get('original_filename', 'N/A'),
            "event_type": scenario_data.get('event_type', 'N/A'),
            "timestamp_of_event": scenario_data.get('timestamp', 'N/A'),
            "map_town": scenario_data.get('town', 'N/A'),
            "road_type_at_collision": scenario_data.get('road_type_at_collision', 'N/A'),
            "weather_details": scenario_data.get('weather', {}),
            "town_characteristics": scenario_data.get('town_characteristics', {}),
            "diversity_score": f"{divs[idx]:.3f}"
        })

    output_json_filename = os.path.join(analysis_output_folder, 'analysis_report.json')
    with open(output_json_filename, 'w') as f:
        json.dump(analysis_results, f, indent=4)
    print(f"✅ Report di analisi salvato in: {output_json_filename}")
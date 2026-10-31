# tanger_pco_gantt — code source

Code de l'application d'affectation des postes de stationnement (ONDA, aéroport de Tanger Ibn Battouta).
La présentation complète du projet (problème, modèle d'optimisation, résultats, limites) se trouve dans le
[README principal](../README.md) · full project overview in the [main README](../README.md).

## Contenu de `src/`

| Fichier | Rôle |
|---|---|
| `excel_parser.py` | Lecture et normalisation du programme des vols (Excel) |
| `standconfig.py` | Définition des 15 postes et de leurs règles |
| `optimizer.py` | Modèle d'optimisation Google OR-Tools (CP-SAT) |
| `reoptimization.py` | Réaffectation après perturbation |
| `opensky_client.py`, `airplaneslive_client.py`, `aviationstack_client.py` | Sources de suivi temps réel |
| `realtime_tracking.py`, `poll_loop.py`, `registration_matcher.py` | Surveillance des vols et détection d'écarts |
| `gaint.py`, `dailygaint.py` | Génération des diagrammes de Gantt (hebdomadaire / journalier) |
| `app.py` | Interface web Flask (point d'entrée principal) |
| `main.py` | Exécution en ligne de commande de l'optimisation |
| `models.py`, `data_generator.py` | Modèles de données (SQLAlchemy) et générateur de données synthétiques |
| `test*.py` | Scripts de test |

## Lancer

```bash
pip install -r requirements.txt
cd src
python app.py "chemin/vers/programme.xlsx" 04/08/2026
```

Les études d'API (`etude_comparative_APIs.md`, `APIs_validation_encadrant.md`) documentent le choix des sources de données temps réel.

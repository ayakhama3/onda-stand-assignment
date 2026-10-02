# Prototype — Moteur d'optimisation PCO Tanger

Étapes réalisées (voir plan complet dans le document de cadrage principal) :
1. Modèles de données (src/models.py) — schéma SQLAlchemy, SQLite pour le prototype,
   migrable vers PostgreSQL en changeant l'URL de connexion
2. Générateur de données synthétiques (src/data_generator.py) — programme de vol
   hebdomadaire calibré sur les compagnies réelles de Tanger (RAM, Air Arabia Maroc, Ryanair)
3. Moteur d'optimisation (src/optimizer.py) — Google OR-Tools CP-SAT
   - Contraintes dures : pas de chevauchement sur un poste, compatibilité taille avion/poste,
     compatibilité push-back
   - Testé et validé : zéro conflit sur un scénario de 15 vols / 18 postes, statut OPTIMALE
4. Script d'exécution (src/main.py) — démonstration sur une journée

## Lancer le prototype
```
pip install -r requirements.txt
cd src && python3 main.py
```

## Prochaines étapes (suite du plan)
- Étape 6 : ingestion temps réel OpenSky/AviationStack
- Étape 7 : re-optimisation incrémentale sur détection d'écart
- Étape 8 : interface Gantt (Plotly/frappe-gantt)
- Recalibrer generate_parking_stands() et les contraintes dès réception des vraies
  données du PCO (nombre de postes réel, règles de proximité porte/comptoir)

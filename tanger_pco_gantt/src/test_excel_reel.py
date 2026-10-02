"""
Test complet du parser Excel sur un vrai fichier de programme de vol.

Usage :
    python test_excel_reel.py NOM_DU_FICHIER.xlsx [JJ/MM/AAAA]

Si aucune date n'est donnee, affiche les statistiques sur toute la semaine.
Si une date est donnee, tente en plus l'affectation des postes ce jour-la.
"""

import sys
from collections import Counter
from datetime import datetime

from excel_parser import parse_programme_vol
from data_generator import generate_parking_stands
from optimizer import solve_stand_assignment


def main():
    if len(sys.argv) < 2:
        print("Usage : python test_excel_reel.py NOM_DU_FICHIER.xlsx [JJ/MM/AAAA]")
        return

    fichier = sys.argv[1]
    date_cible = None
    if len(sys.argv) >= 3:
        date_cible = datetime.strptime(sys.argv[2], "%d/%m/%Y").date()

    print(f"=== Lecture de {fichier} ===\n")
    vols = parse_programme_vol(fichier)

    print(f"\n--- Statistiques de fiabilite du parsing ---")
    compte = Counter(f["hypothese_horaire"] for f in vols)
    for hyp, n in compte.most_common():
        label = hyp if hyp else "donnee complete (aucune hypothese)"
        pourcentage = 100 * n / len(vols)
        print(f"  {label:<55} {n:>4}  ({pourcentage:.1f}%)")

    if not date_cible:
        print("\nAstuce : relance avec une date (JJ/MM/AAAA) pour tester l'affectation des postes ce jour-la.")
        return

    vols_du_jour = [
        f for f in vols
        if f["heure_prevue_arrivee"].date() == date_cible or f["heure_prevue_depart"].date() == date_cible
    ]

    print(f"\n=== Affectation des postes pour le {date_cible.strftime('%d/%m/%Y')} ===")
    print(f"{len(vols_du_jour)} vols concernes ce jour-la\n")

    if not vols_du_jour:
        print("Aucun vol trouve pour cette date -- verifie le format ou la semaine couverte par le fichier.")
        return

    stands = generate_parking_stands()

    try:
        results, status = solve_stand_assignment(vols_du_jour, stands)
        print(f"Statut : {status}")
        print(f"TOUS les {len(results)} vols ont ete places avec succes.\n")
    except RuntimeError:
        results, status, non_places = solve_stand_assignment(
            vols_du_jour, stands, permettre_non_affectation=True
        )
        print(f"Statut : {status}")
        print(f"{len(results)} vols places, {len(non_places)} non places : {non_places}\n")

    print(f"{'Vol':<20} {'Poste':<6} {'Arrivee':<14} {'Depart':<14}")
    print("-" * 56)
    for r in sorted(results, key=lambda x: x["heure_arrivee"]):
        print(f"{r['numero_vol']:<20} {r['poste_assigne']:<6} "
              f"{r['heure_arrivee'].strftime('%d/%m %H:%M'):<14} "
              f"{r['heure_depart'].strftime('%d/%m %H:%M'):<14}")


if __name__ == "__main__":
    main()
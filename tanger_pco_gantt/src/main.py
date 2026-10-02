"""
Point d'entree principal -- 100% base sur le vrai programme de vol Excel.
Aucune donnee inventee (data_generator.py n'est plus utilise ici).

Usage:
    python main.py "fichier.xlsx" JJ/MM/AAAA
"""

import sys
from datetime import datetime
from excel_parser import parse_programme_vol
from standconfig import generate_parking_stands
from optimizer import solve_stand_assignment


def main():
    if len(sys.argv) < 3:
        print("Usage : python main.py FICHIER.xlsx JJ/MM/AAAA")
        return

    fichier = sys.argv[1]
    date_cible = datetime.strptime(sys.argv[2], "%d/%m/%Y").date()

    stands = generate_parking_stands()  # config REELLE des 15 postes
    tous_les_vols = parse_programme_vol(fichier)  # vols REELS du fichier

    vols_du_jour = [
        f for f in tous_les_vols
        if f["heure_prevue_arrivee"].date() == date_cible or f["heure_prevue_depart"].date() == date_cible
    ]

    print(f"\n{len(vols_du_jour)} vols reels le {date_cible.strftime('%d/%m/%Y')}\n")

    results, status, non_places = solve_stand_assignment(vols_du_jour, stands, permettre_non_affectation=True)

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
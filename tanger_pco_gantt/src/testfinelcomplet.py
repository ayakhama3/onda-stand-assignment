"""
Test final complet -- valide TOUTE la semaine du fichier Excel reel, jour par
jour, avec une verification INDEPENDANTE de chaque regle (pas juste faire
confiance au solveur). Aucune donnee inventee : uniquement stands_config.py
(config reelle) et excel_parser.py (ton vrai fichier).

Usage :
    python test_final_complet.py "fichier.xlsx"
"""

import sys
from collections import defaultdict
from datetime import timedelta

from excel_parser import parse_programme_vol
from standconfig import generate_parking_stands
from optimizer import solve_stand_assignment, BUFFER_MINUTES


def verifier_independamment(results, stands_by_name):
    """Reverifie chaque regle a la main, sans faire confiance au solveur."""
    problemes = []

    by_stand = defaultdict(list)
    for r in results:
        by_stand[r["poste_assigne"]].append(r)

    # 1. Pas de chevauchement + buffer minimum sur un meme poste
    for poste, vols in by_stand.items():
        vols_tries = sorted(vols, key=lambda x: x["heure_arrivee"])
        for i in range(len(vols_tries) - 1):
            fin_1 = vols_tries[i]["heure_depart"]
            debut_2 = vols_tries[i + 1]["heure_arrivee"]
            if fin_1 + timedelta(minutes=BUFFER_MINUTES) > debut_2:
                problemes.append(
                    f"BUFFER/CHEVAUCHEMENT sur {poste} : {vols_tries[i]['numero_vol']} "
                    f"(fin {fin_1.strftime('%H:%M')}) vs {vols_tries[i+1]['numero_vol']} "
                    f"(debut {debut_2.strftime('%H:%M')})"
                )

    # 2. Adjacence push-back : si un vol sans push-back est sur X, le voisin de
    # gauche ne doit avoir aucun vol en chevauchement sur la meme fenetre
    for r in results:
        if r.get("pushback_disponible", True):
            continue
        poste_info = stands_by_name.get(r["poste_assigne"])
        voisin = poste_info["voisin_gauche"] if poste_info else None
        if not voisin:
            continue
        for autre in by_stand.get(voisin, []):
            chevauche = not (r["heure_depart"] <= autre["heure_arrivee"] or
                              autre["heure_depart"] <= r["heure_arrivee"])
            if chevauche:
                problemes.append(
                    f"ADJACENCE VIOLEE : {r['numero_vol']} (sans push-back, poste {r['poste_assigne']}) "
                    f"chevauche {autre['numero_vol']} sur le voisin {voisin}"
                )

    return problemes


def main():
    if len(sys.argv) < 2:
        print("Usage : python test_final_complet.py FICHIER.xlsx")
        return

    fichier = sys.argv[1]
    stands = generate_parking_stands()
    stands_by_name = {s["nom"]: s for s in stands}

    print(f"=== Chargement de {fichier} (aucune donnee inventee) ===")
    tous_les_vols = parse_programme_vol(fichier)

    jours = sorted(set(
        f["heure_prevue_arrivee"].date() for f in tous_les_vols
    ) | set(
        f["heure_prevue_depart"].date() for f in tous_les_vols
    ))

    print(f"\n{'Jour':<14} {'Vols':<8} {'Places':<8} {'Non places':<12} {'Problemes independants':<25}")
    print("-" * 70)

    total_vols = 0
    total_places = 0
    total_non_places = 0
    total_problemes = 0

    for jour in jours:
        vols_du_jour = [
            f for f in tous_les_vols
            if f["heure_prevue_arrivee"].date() == jour or f["heure_prevue_depart"].date() == jour
        ]
        if not vols_du_jour:
            continue

        results, status, non_places = solve_stand_assignment(
            vols_du_jour, stands, permettre_non_affectation=True
        )
        problemes = verifier_independamment(results, stands_by_name)

        total_vols += len(vols_du_jour)
        total_places += len(results)
        total_non_places += len(non_places)
        total_problemes += len(problemes)

        marqueur = "OK" if not non_places and not problemes else "A VERIFIER"
        print(f"{jour.strftime('%a %d/%m'):<14} {len(vols_du_jour):<8} {len(results):<8} "
              f"{len(non_places):<12} {len(problemes):<3} {marqueur}")

        if non_places:
            print(f"   -> non places : {non_places}")
        for p in problemes:
            print(f"   -> {p}")

    print("\n" + "=" * 70)
    print(f"BILAN GLOBAL : {total_vols} vols sur la semaine, {total_places} places, "
          f"{total_non_places} non places, {total_problemes} probleme(s) detecte(s) independamment")
    if total_non_places == 0 and total_problemes == 0:
        print("\n>>> TOUT FONCTIONNE CORRECTEMENT. Systeme pret pour le diagramme de Gantt. <<<")
    else:
        print("\n>>> Des points restent a examiner avant de considerer le systeme totalement fiable. <<<")


if __name__ == "__main__":
    main()
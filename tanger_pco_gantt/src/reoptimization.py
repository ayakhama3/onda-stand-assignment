"""
Réoptimisation incrémentale suite à un retard détecté.

Scénario concret : le vol A est affecté au poste N5, suivi du vol B sur le même
poste plus tard dans la journée (avec le buffer minimum de 1h déjà respecté au
départ). Le vol A prend du retard -> son heure de départ réelle recule -> le
buffer avec l'arrivée du vol B n'est plus respecté, voire chevauchement direct.

Principe : ne PAS tout recalculer. On fige toutes les affectations non
concernées (elles restent exactement comme validées par l'agent), et on ne
laisse le solveur reconsidérer QUE les vols en conflit réel.
"""

from optimizer import solve_stand_assignment, BUFFER_MINUTES


def detecter_conflits(assignments: list[dict], flights_by_num: dict, buffer_minutes=BUFFER_MINUTES):
    """
    assignments : [{'numero_vol':..., 'poste_assigne':...}]
    flights_by_num : {numero_vol: flight_dict} avec les heures À JOUR (après mise à jour du retard)

    Retourne la liste des paires de vols en conflit sur un même poste
    (chevauchement ou buffer insuffisant), après mise à jour des horaires.
    """
    by_stand = {}
    for a in assignments:
        by_stand.setdefault(a["poste_assigne"], []).append(a["numero_vol"])

    conflits = []
    for poste, vols in by_stand.items():
        for i in range(len(vols)):
            for j in range(i + 1, len(vols)):
                f1, f2 = flights_by_num[vols[i]], flights_by_num[vols[j]]
                # écart réel entre les deux occupations, dans les deux sens possibles
                gap_1_avant_2 = (f2["heure_prevue_arrivee"] - f1["heure_prevue_depart"]).total_seconds() / 60
                gap_2_avant_1 = (f1["heure_prevue_arrivee"] - f2["heure_prevue_depart"]).total_seconds() / 60
                if gap_1_avant_2 < buffer_minutes and gap_2_avant_1 < buffer_minutes:
                    conflits.append((vols[i], vols[j], poste))
    return conflits


def reoptimiser_apres_retard(all_flights: list[dict], stands: list[dict],
                              assignments_actuelles: list[dict], vol_retarde: str):
    """
    Reprend l'affectation existante, applique la mise à jour d'horaire (déjà faite
    dans all_flights avant l'appel), détecte les conflits engendrés, et ne relance
    l'optimiseur QUE sur les vols concernés — tout le reste reste figé.
    """
    flights_by_num = {f["numero_vol"]: f for f in all_flights}
    conflits = detecter_conflits(assignments_actuelles, flights_by_num)

    if not conflits:
        return assignments_actuelles, [], []  # rien à changer, aucun vol perdu son poste

    # Vols concernés par au moins un conflit -> à laisser libres pour le solveur
    vols_a_reoptimiser = set()
    for f1, f2, _ in conflits:
        vols_a_reoptimiser.add(f1)
        vols_a_reoptimiser.add(f2)

    # Tous les autres vols gardent leur poste figé
    postes_figes = {
        a["numero_vol"]: a["poste_assigne"]
        for a in assignments_actuelles
        if a["numero_vol"] not in vols_a_reoptimiser
    }

    nouveaux_resultats, status, vols_non_places = solve_stand_assignment(
        all_flights, stands, postes_figes=postes_figes, permettre_non_affectation=True
    )

    if vols_non_places:
        print(f"[reoptimization] ATTENTION : {len(vols_non_places)} vol(s) ne trouvent plus de poste "
              f"apres ce changement -> a signaler a l'agent PCO : {vols_non_places}")

    return nouveaux_resultats, list(vols_a_reoptimiser), vols_non_places

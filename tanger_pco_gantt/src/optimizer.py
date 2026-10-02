"""
Moteur d'optimisation — Aircraft Stand Assignment Problem (Google OR-Tools CP-SAT)
Configuration réelle Tanger Ibn Battouta.

Contraintes dures (jamais violées) :
  - Un poste ne peut accueillir qu'un avion à la fois (pas de chevauchement horaire)
  - Un avion ne peut être affecté qu'à un poste de catégorie compatible
    (poids_lourd -> N1/N2, commercial -> N3..N8, prive -> ECO)
  - Adjacence push-back : un avion SANS capacité de push-back, assigné à un poste X,
    impose que le poste immédiatement à gauche de X reste libre sur la même fenêtre horaire
    (disposition confirmée par le PCO : N8-N7-N6-N5-N4-N3-N2-N1-ECO, de gauche à droite)

Contrainte souple (optimisée, pas obligatoire) :
  - Minimiser l'écart entre le poste assigné et le poste "idéal" (proximité porte/comptoir)
"""

from ortools.sat.python import cp_model
from datetime import datetime


# Compatibilité poste <-> vol : dépend à la fois de la catégorie ET de la taille.
def _est_compatible(flight: dict, stand: dict) -> bool:
    cat_vol = flight["categorie_appareil"]
    taille_vol = flight.get("taille_appareil", "moyen")
    cat_poste = stand["categorie"]

    if cat_poste == "commercial":
        return cat_vol == "commercial" and taille_vol in ("petit", "moyen")
    if cat_poste == "multi_lourd":
        # poids lourd/national (toute taille), cargo uniquement si taille "gros"
        if cat_vol in ("poids_lourd", "national"):
            return True
        if cat_vol == "cargo" and taille_vol == "gros":
            return True
        return False
    if cat_poste == "eco_grand":
        # aviation privée + cargo taille moyenne (A320/A321) + débordement commercial taille moyenne
        if cat_vol == "prive":
            return True
        if cat_vol == "cargo" and taille_vol == "moyen":
            return True
        if cat_vol == "commercial" and taille_vol in ("petit", "moyen"):
            return True  # débordement, pénalisé dans l'objectif
        return False
    if cat_poste == "eco_petit":
        # aviation privee en priorite, MAIS accepte aussi le debordement commercial
        # en dernier recours si eco_grand et N3-N8 sont satures (penalise plus fort)
        if cat_vol == "prive" and taille_vol == "petit":
            return True
        if cat_vol == "commercial" and taille_vol in ("petit", "moyen"):
            return True  # debordement d'urgence, tres penalise dans l'objectif
        return False
    return False


# Compagnies à escale rapide -> préférence forte pour N8 (poste le plus accessible,
# proche des portes 1-4, cohérent avec un objectif de rotation minimale)
COMPAGNIES_ESCALE_RAPIDE = {"Ryanair"}
SEUIL_ESCALE_RAPIDE_MINUTES = 40
PENALITE_ECART_ESCALE_RAPIDE = 3  # poids relatif dans l'objectif

PENALITE_DEBORDEMENT_COMMERCIAL_VERS_ECO = 5

# Durée minimale requise entre le départ d'un vol et l'arrivée du vol suivant
# sur le MÊME poste (temps de préparation/nettoyage du poste)
BUFFER_MINUTES = 60

# Mapping porte d'embarquement -> poste préférentiel (proximité confirmée par le PCO).
# Portes 11-12 (nationales) et postes distants (N4->N1, zone ECO) : pas de proximité
# directe, les passagers utilisent un bus -> aucune préférence à appliquer.
GATE_TO_PREFERRED_STAND = {
    1: "N8", 2: "N8", 3: "N8", 4: "N8",
    5: "N7", 6: "N7",
    7: "N6", 8: "N6",
    9: "N5", 10: "N5",
}

PENALITE_ECART_PROXIMITE_PORTE = 2  # poids relatif dans l'objectif


def _to_minutes(dt: datetime, reference: datetime) -> int:
    return int((dt - reference).total_seconds() // 60)


def solve_stand_assignment(flights: list[dict], stands: list[dict],
                            time_limit_seconds=30, postes_figes: dict = None,
                            permettre_non_affectation: bool = False):
    """
    postes_figes : {numero_vol: nom_du_poste} — force certains vols à garder
    leur poste actuel (utilisé par la réoptimisation incrémentale).

    permettre_non_affectation : si True, le solveur ne plante plus en cas de
    saturation — il place le maximum de vols possible et retourne séparément
    la liste des vols qu'il n'a pas pu placer, plutôt que de lever une erreur.
    À utiliser sur des données réelles où la saturation est un résultat légitime
    à signaler à l'agent, pas une erreur de programmation.
    """
    postes_figes = postes_figes or {}

    reference = min(f["heure_prevue_arrivee"] for f in flights)
    model = cp_model.CpModel()

    n_flights = len(flights)
    stand_index_by_name = {s["nom"]: i for i, s in enumerate(stands)}

    # --- Compatibilité catégorie + taille (contrainte dure, avec débordement autorisé) ---
    compatible_stands = []
    for f in flights:
        compat = [i for i, s in enumerate(stands) if _est_compatible(f, s)]
        compatible_stands.append(compat)

    stand_var = []
    for i, compat in enumerate(compatible_stands):
        if not compat:
            raise ValueError(
                f"Aucun poste compatible pour le vol {flights[i]['numero_vol']} "
                f"(catégorie={flights[i]['categorie_appareil']})"
            )
        stand_var.append(model.NewIntVarFromDomain(
            cp_model.Domain.FromValues(compat), f"stand_flight_{i}"
        ))

    # --- Postes figés : verrouille la variable des vols non concernés par le recalcul ---
    for i, f in enumerate(flights):
        if f["numero_vol"] in postes_figes:
            nom_poste = postes_figes[f["numero_vol"]]
            idx_fige = stand_index_by_name[nom_poste]
            model.Add(stand_var[i] == idx_fige)

    # --- Variables booléennes de réification : assigned[i][s] <=> stand_var[i] == s ---
    assigned = {}
    for i, compat in enumerate(compatible_stands):
        for s_idx in compat:
            b = model.NewBoolVar(f"assigned_{i}_{s_idx}")
            model.Add(stand_var[i] == s_idx).OnlyEnforceIf(b)
            model.Add(stand_var[i] != s_idx).OnlyEnforceIf(b.Not())
            assigned[(i, s_idx)] = b

    # --- Fenêtres horaires ---
    starts = [_to_minutes(f["heure_prevue_arrivee"], reference) for f in flights]
    ends = [_to_minutes(f["heure_prevue_depart"], reference) for f in flights]

    def conflit(i, j):
        """Deux vols sont en conflit sur un même poste s'ils se chevauchent
        OU si le buffer minimum entre eux n'est pas respecté."""
        return not (ends[i] + BUFFER_MINUTES <= starts[j] or ends[j] + BUFFER_MINUTES <= starts[i])

    # --- Vols "placés ou non" (uniquement en mode best-effort) ---
    placed = None
    if permettre_non_affectation:
        placed = [model.NewBoolVar(f"placed_{i}") for i in range(n_flights)]
        for i, f in enumerate(flights):
            if f["numero_vol"] in postes_figes:
                model.Add(placed[i] == 1)  # un vol figé est toujours considéré placé

    # --- Contrainte dure : pas de chevauchement + buffer minimum sur un même poste ---
    for i in range(n_flights):
        for j in range(i + 1, n_flights):
            if conflit(i, j):
                different_stand = model.NewBoolVar(f"diff_{i}_{j}")
                model.Add(stand_var[i] != stand_var[j]).OnlyEnforceIf(different_stand)
                model.Add(stand_var[i] == stand_var[j]).OnlyEnforceIf(different_stand.Not())
                if placed is not None:
                    # La contrainte ne s'applique que si les deux vols sont effectivement placés
                    model.Add(different_stand == 1).OnlyEnforceIf([placed[i], placed[j]])
                else:
                    model.Add(different_stand == 1)

    # --- Contrainte dure : adjacence push-back ---
    # Si le vol i (sans pushback) est assigné au poste s, alors aucun vol j en chevauchement
    # temporel ne peut être assigné au poste "voisin_gauche(s)".
    for i, f in enumerate(flights):
        if f.get("pushback_disponible", True):
            continue  # règle uniquement pour les avions SANS push-back
        for s_idx in compatible_stands[i]:
            voisin_nom = stands[s_idx].get("voisin_gauche")
            if voisin_nom is None:
                continue  # poste le plus à gauche (N8), pas de voisin à libérer
            voisin_idx = stand_index_by_name[voisin_nom]
            for j in range(n_flights):
                if j == i or not conflit(i, j):
                    continue
                if (j, voisin_idx) in assigned:
                    clause = [assigned[(i, s_idx)].Not(), assigned[(j, voisin_idx)].Not()]
                    if placed is not None:
                        clause += [placed[i].Not(), placed[j].Not()]
                    model.AddBoolOr(clause)

    # --- Objectif souple : proximité porte-poste + pénalité de débordement ECO ---
    penalties = []
    for i, f in enumerate(flights):
        # Préférence de proximité selon la porte d'embarquement du vol
        porte = f.get("porte_numero")
        if porte in GATE_TO_PREFERRED_STAND:
            nom_poste_pref = GATE_TO_PREFERRED_STAND[porte]
            if nom_poste_pref in stand_index_by_name:
                idx_pref = stand_index_by_name[nom_poste_pref]
                if (i, idx_pref) in assigned:
                    penalties.append((1 - assigned[(i, idx_pref)]) * PENALITE_ECART_PROXIMITE_PORTE)

        # Pénaliser un vol commercial assigné à un poste ECO (débordement à éviter si possible)
        # eco_petit est pénalisé plus fort qu'eco_grand -> le solveur épuise eco_grand d'abord
        if f["categorie_appareil"] == "commercial":
            for s_idx in compatible_stands[i]:
                if stands[s_idx]["categorie"] == "eco_grand":
                    penalties.append(assigned[(i, s_idx)] * PENALITE_DEBORDEMENT_COMMERCIAL_VERS_ECO)
                elif stands[s_idx]["categorie"] == "eco_petit":
                    penalties.append(assigned[(i, s_idx)] * PENALITE_DEBORDEMENT_COMMERCIAL_VERS_ECO * 3)

        # Préférence forte pour N8 sur les vols à escale rapide (ex: Ryanair, 30 min)
        duree_escale = (f["heure_prevue_depart"] - f["heure_prevue_arrivee"]).total_seconds() / 60
        est_escale_rapide = (
            f.get("compagnie") in COMPAGNIES_ESCALE_RAPIDE or duree_escale <= SEUIL_ESCALE_RAPIDE_MINUTES
        )
        if est_escale_rapide and "N8" in stand_index_by_name:
            idx_n8 = stand_index_by_name["N8"]
            if (i, idx_n8) in assigned:
                penalties.append((1 - assigned[(i, idx_n8)]) * PENALITE_ECART_ESCALE_RAPIDE)

    if permettre_non_affectation and placed is not None:
        # Priorité absolue : maximiser le nombre de vols placés (poids très supérieur
        # aux pénalités de confort), puis optimiser les préférences parmi les vols placés
        POIDS_PLACEMENT = 1000
        model.Maximize(sum(placed) * POIDS_PLACEMENT - sum(penalties))
    elif penalties:
        model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    results = []
    vols_non_places = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for i, f in enumerate(flights):
            if placed is not None and solver.Value(placed[i]) == 0:
                vols_non_places.append(f["numero_vol"])
                continue
            s_idx = solver.Value(stand_var[i])
            results.append({
                "numero_vol": f["numero_vol"],
                "poste_assigne": stands[s_idx]["nom"],
                "pushback_disponible": f.get("pushback_disponible", True),
                "heure_arrivee": f["heure_prevue_arrivee"],
                "heure_depart": f["heure_prevue_depart"],
                "statut": "proposee",
            })
        if permettre_non_affectation:
            return results, status, vols_non_places
        return results, status
    else:
        raise RuntimeError(
            "Aucune solution trouvée respectant les contraintes dures — "
            "vérifier le nombre de postes disponibles, catégories ou contraintes d'adjacence."
        )

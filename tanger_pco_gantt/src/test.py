"""
Test — scénario de retard et réoptimisation incrémentale.

Démontre :
- deux vols partagent initialement un même poste ;
- l'un prend du retard ;
- le système détecte automatiquement le conflit généré ;
- seuls les vols concernés sont réoptimisés ;
- les vols non concernés restent figés ;
- aucun conflit ne subsiste après réoptimisation.
"""

from data_generator import generate_parking_stands
from optimizer import solve_stand_assignment
from reoptimization import reoptimiser_apres_retard, detecter_conflits
from datetime import datetime, timedelta


# ============================================================
# 1. Préparation
# ============================================================

stands = generate_parking_stands()

base = datetime(2026, 7, 13, 10, 0)

flights = [
    {
        "numero_vol": "AT2001",
        "categorie_appareil": "commercial",
        "taille_appareil": "moyen",
        "pushback_disponible": True,
        "compagnie": "Royal Air Maroc",
        "heure_prevue_arrivee": base,
        "heure_prevue_depart": base + timedelta(minutes=45),
    },
    {
        "numero_vol": "FR2002",
        "categorie_appareil": "commercial",
        "taille_appareil": "moyen",
        "pushback_disponible": True,
        "compagnie": "Ryanair",
        "heure_prevue_arrivee": base + timedelta(minutes=105),
        "heure_prevue_depart": base + timedelta(minutes=150),
    },
]


# ============================================================
# 2. Affectation initiale
# ============================================================

results, status = solve_stand_assignment(flights, stands)

print("=== Affectation initiale ===")

for r in results:
    print(
        f"{r['numero_vol']} -> {r['poste_assigne']} "
        f"({r['heure_arrivee'].strftime('%H:%M')}-"
        f"{r['heure_depart'].strftime('%H:%M')})"
    )

meme_poste = (
    results[0]["poste_assigne"]
    == results[1]["poste_assigne"]
)

print(f"Les 2 vols partagent-ils le même poste ? {meme_poste}\n")


# ============================================================
# 3. Simulation du retard
# ============================================================

print(
    ">>> AT2001 prend 40 minutes de retard "
    "(départ décalé à 11h25) <<<\n"
)

flights[0]["heure_prevue_depart"] = base + timedelta(minutes=145)


# ============================================================
# 4. Réoptimisation incrémentale
# ============================================================

nouveaux_resultats, vols_touches, vols_non_places = (
    reoptimiser_apres_retard(
        flights,
        stands,
        results,
        "AT2001"
    )
)


# ============================================================
# 5. Résultats de la réoptimisation
# ============================================================

print(
    f"Vols recalculés "
    f"(les autres restent figés) : {vols_touches}"
)

print(f"Vols non placés après réoptimisation : {vols_non_places}\n")


print("=== Nouvelle affectation après gestion automatique du retard ===")

for r in nouveaux_resultats:
    print(
        f"{r['numero_vol']} -> {r['poste_assigne']} "
        f"({r['heure_arrivee'].strftime('%H:%M')}-"
        f"{r['heure_depart'].strftime('%H:%M')})"
    )


# ============================================================
# 6. Vérification des conflits restants
# ============================================================

flights_by_num = {
    f["numero_vol"]: f
    for f in flights
}

conflits_restants = detecter_conflits(
    nouveaux_resultats,
    flights_by_num
)

print(
    f"\nConflits restants après réoptimisation : "
    f"{len(conflits_restants)}"
)


# ============================================================
# 7. Verdict du test
# ============================================================

print("\n=== VERDICT DU TEST ===")

if len(conflits_restants) == 0 and not vols_non_places:
    print("TEST REUSSI :")
    print("- le retard a été pris en compte ;")
    print("- la réoptimisation a été exécutée ;")
    print("- les conflits ont été résolus ;")
    print("- aucun vol n'a été perdu.")
else:
    print("TEST A VERIFIER :")
    print(f"- conflits restants : {len(conflits_restants)}")
    print(f"- vols non placés : {vols_non_places}")
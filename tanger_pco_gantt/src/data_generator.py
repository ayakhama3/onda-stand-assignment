"""
Générateur de données synthétiques — programme de vol hebdomadaire Tanger (GMTT)

Calibré sur les compagnies réellement basées à Tanger Ibn Battouta
(Royal Air Maroc, Air Arabia Maroc, Ryanair) et un volume de mouvements
plausible pour un aéroport de cette taille (~15-25 mouvements/jour).

À recalibrer dès réception du vrai programme hebdomadaire du handler.
"""

import random
from datetime import datetime, timedelta

# --- Référentiel compagnies / flottes réalistes pour Tanger ---
AIRLINES = [
    {"code": "AT", "nom": "Royal Air Maroc", "flotte": [
        ("B737-800", "code_C"), ("B737-700", "code_C"), ("A321", "code_C")
    ]},
    {"code": "3O", "nom": "Air Arabia Maroc", "flotte": [
        ("A320", "code_C"), ("A321", "code_C")
    ]},
    {"code": "FR", "nom": "Ryanair", "flotte": [
        ("B737-800", "code_C")
    ]},
    {"code": "IB", "nom": "Iberia", "flotte": [
        ("A320", "code_C"), ("A321", "code_C")
    ]},
]

# Compagnies opérant à Tanger SANS capacité de push-back (donnée métier confirmée
# par le PCO — impose la contrainte d'adjacence dans optimizer.py).
# Iberia confirmée. 2ème compagnie à compléter dès confirmation.
COMPAGNIES_SANS_PUSHBACK = {"Iberia"}

DESTINATIONS = [
    "Casablanca", "Paris", "Bruxelles", "Amsterdam", "Madrid",
    "Barcelone", "Marseille", "Londres", "Dusseldorf", "Milan"
]

# Rotation type : durée au sol en minutes
DUREE_ROTATION_RAPIDE = (35, 55)      # min - max, avion repart vite
DUREE_NUITEE_MIN = 8 * 60              # 8h minimum si l'avion reste la nuit


def _random_icao24():
    """Identifiant transpondeur hexadécimal à 6 caractères (format OpenSky)."""
    return "".join(random.choice("0123456789abcdef") for _ in range(6))


def generate_parking_stands():
    """Génère les postes selon la configuration réelle confirmée par le PCO.

    Disposition physique gauche → droite :
      N8 · N7 · N6 · N5 · N4 · N3   (commercial)
      N2 · N1                       (poids lourd + cargo lourd + vols nationaux)
      E7 · E6 · E5 · E4 · E3 · E2 · E1   (ECO)

    Zone ECO affinée :
      - E7 et E1 : "eco_grand" — aviation privée + cargo taille moyenne (A320/A321)
                    + débordement commercial (taille moyenne uniquement)
      - E6 à E2  : "eco_petit" — aviation privée UNIQUEMENT, taille inférieure à A321
    """
    ordre_gauche_droite = [
        ("N8", "commercial"), ("N7", "commercial"), ("N6", "commercial"),
        ("N5", "commercial"), ("N4", "commercial"), ("N3", "commercial"),
        ("N2", "multi_lourd"), ("N1", "multi_lourd"),
        ("E7", "eco_grand"),
        ("E6", "eco_petit"), ("E5", "eco_petit"), ("E4", "eco_petit"),
        ("E3", "eco_petit"), ("E2", "eco_petit"),
        ("E1", "eco_grand"),
    ]

    stands = []
    for i, (nom, categorie) in enumerate(ordre_gauche_droite):
        voisin_gauche = ordre_gauche_droite[i - 1][0] if i > 0 else None

        stands.append({
            "nom": nom,
            "categorie": categorie,     # 'commercial' | 'multi_lourd' | 'eco_grand' | 'eco_petit'
            "voisin_gauche": voisin_gauche,
            "latitude": 35.7269 + random.uniform(-0.002, 0.002),
            "longitude": -5.9169 + random.uniform(-0.003, 0.003),
        })
    return stands


def generate_gates(n=8):
    return [{"nom": f"Porte {chr(65 + i)}"} for i in range(n)]


def generate_checkin_counters(n=20):
    return [{"numero": f"C{i+1:02d}", "zone": "internationale" if i < 12 else "nationale"}
            for i in range(n)]


def generate_weekly_program(start_date: datetime, mouvements_par_jour=20, saison="ete"):
    """Génère un programme de vol sur 7 jours à partir de start_date.

    Répartition des catégories : ~85% commercial, ~8% national, ~4% cargo,
    ~3% privé — à ajuster une fois le vrai programme hebdomadaire obtenu.
    """
    flights = []
    flight_counter = 1000

    for day_offset in range(7):
        day = start_date + timedelta(days=day_offset)
        for _ in range(mouvements_par_jour // 2):
            categorie = random.choices(
                ["commercial", "national", "cargo", "prive"],
                weights=[85, 8, 4, 3],
            )[0]

            if categorie == "commercial":
                airline = random.choice(AIRLINES)
                aircraft_type, _ = random.choice(airline["flotte"])
                compagnie = airline["nom"]
                code = airline["code"]
                taille_appareil = "moyen"   # flotte Tanger = A320/A321/B737, catégorie A321
            elif categorie == "national":
                aircraft_type, compagnie, code = "B737-700", "Royal Air Maroc (domestique)", "AT"
                taille_appareil = "moyen"
            elif categorie == "cargo":
                # Mélange réaliste : cargo léger/moyen (A320/321) et cargo lourd
                if random.random() < 0.6:
                    aircraft_type, compagnie, code, taille_appareil = "A321F", "Cargo Charter", "CG", "moyen"
                else:
                    aircraft_type, compagnie, code, taille_appareil = "B747F", "Cargo Lourd Charter", "CG", "gros"
            else:  # prive
                aircraft_type, compagnie, code = "Cessna Citation", "Aviation privée", "PV"
                taille_appareil = "petit"

            destination = random.choice(DESTINATIONS)
            heure_arrivee = day.replace(
                hour=random.randint(5, 20), minute=random.choice([0, 15, 30, 45])
            )

            est_nuitee = random.random() < 0.2
            if est_nuitee:
                duree = timedelta(minutes=random.randint(DUREE_NUITEE_MIN, DUREE_NUITEE_MIN + 240))
            elif compagnie == "Ryanair":
                duree = timedelta(minutes=30)   # escale rapide caractéristique Ryanair
            else:
                duree = timedelta(minutes=random.randint(*DUREE_ROTATION_RAPIDE))

            heure_depart = heure_arrivee + duree

            flight_counter += 1
            flights.append({
                "numero_vol": f"{code}{flight_counter}",
                "icao24": _random_icao24(),
                "immatriculation": f"CN-{random.choice('ABCDEFG')}{random.choice('WXYZ')}{random.randint(10,99)}",
                "type_appareil": aircraft_type,
                "categorie_appareil": categorie,
                "taille_appareil": taille_appareil,   # 'petit' | 'moyen' | 'gros'
                "pushback_disponible": compagnie not in COMPAGNIES_SANS_PUSHBACK,
                "compagnie": compagnie,
                "saison_iata": saison,
                "date_vol": day,
                "heure_prevue_arrivee": heure_arrivee,
                "heure_prevue_depart": heure_depart,
                "statut": "prevu",
                "destination": destination,
            })

    return flights


if __name__ == "__main__":
    stands = generate_parking_stands()
    program = generate_weekly_program(datetime(2026, 7, 13), mouvements_par_jour=20)
    print(f"{len(stands)} postes générés, {len(program)} vols générés sur 7 jours")
    print("Exemple de vol :", program[0])

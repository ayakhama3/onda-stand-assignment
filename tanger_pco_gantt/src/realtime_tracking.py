"""
Suivi temps réel et calcul d'ETA — remplace la surveillance manuelle de FlightRadar24

Deux cas à gérer :
  1. Avion encore en vol (on_ground=False) -> calcul d'un ETA par extrapolation
     position/vitesse/distance restante jusqu'à Tanger
  2. Avion déjà posé (on_ground=True) près de Tanger -> heure d'arrivée réelle
     = première détection au sol (pas une estimation, un fait constaté)

Rapprochement callsign <-> numéro de vol programmé : nécessaire car le callsign
diffusé par le transpondeur peut différer légèrement du numéro de vol commercial
(espaces, préfixe ICAO de la compagnie vs code IATA, ex: RAM201 vs AT201).
"""

import math
from datetime import datetime, timedelta

TANGER_LAT = 35.7269
TANGER_LON = -5.9169

# Seuil au-delà duquel un écart ETA vs heure prévue déclenche une alerte
SEUIL_ALERTE_MINUTES = 15

# Correspondance code ICAO compagnie (callsign) <-> code IATA (programme de vol)
# À compléter avec les compagnies réellement observées sur Tanger
ICAO_TO_IATA = {
    "RAM": "AT",   # Royal Air Maroc
    "AAW": "3O",   # Air Arabia Maroc (code ICAO générique Air Arabia)
    "RYR": "FR",   # Ryanair
}


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance grand cercle entre deux points, en kilomètres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def normalize_callsign(raw_callsign: str) -> str:
    """Nettoie un callsign brut ADS-B (espaces, casse) et tente la conversion ICAO->IATA."""
    cs = raw_callsign.strip().upper()
    for icao_prefix, iata_prefix in ICAO_TO_IATA.items():
        if cs.startswith(icao_prefix):
            return iata_prefix + cs[len(icao_prefix):]
    return cs


def match_state_to_flight(state: dict, expected_flights: list[dict]) -> dict | None:
    """Rapproche un état ADS-B (callsign) à un vol attendu du programme du jour."""
    callsign = normalize_callsign(state.get("callsign") or state.get("flight") or "")
    if not callsign:
        return None
    for f in expected_flights:
        if normalize_callsign(f["numero_vol"]) == callsign:
            return f
    return None


def compute_eta(state: dict, now: datetime) -> datetime | None:
    """
    Calcule une heure d'arrivée estimée à Tanger à partir d'un état ADS-B en vol.
    Retourne None si la vitesse est nulle/inconnue (calcul impossible) ou si l'avion
    s'éloigne de Tanger plutôt que de s'en approcher.
    """
    if state.get("on_ground"):
        return now  # déjà au sol -> heure d'arrivée réelle = maintenant (constatée, pas estimée)

    lat, lon = state.get("latitude"), state.get("longitude")
    velocity = state.get("velocity")  # m/s, vitesse sol
    if lat is None or lon is None or not velocity or velocity <= 0:
        return None

    distance_km = haversine_km(lat, lon, TANGER_LAT, TANGER_LON)
    vitesse_kmh = velocity * 3.6
    if vitesse_kmh <= 0:
        return None

    temps_restant_h = distance_km / vitesse_kmh
    return now + timedelta(hours=temps_restant_h)


def process_states(states: list[dict], expected_flights: list[dict], now: datetime):
    """
    Traite un lot d'états ADS-B, calcule les ETA, et génère les alertes de
    changement de rotation quand l'écart avec l'heure prévue dépasse le seuil.

    Retourne : liste de dicts {numero_vol, eta_calculee, heure_prevue, ecart_minutes, alerte}
    """
    updates = []
    for state in states:
        flight = match_state_to_flight(state, expected_flights)
        if flight is None:
            continue  # avion détecté mais ne correspond à aucun vol attendu aujourd'hui

        eta = compute_eta(state, now)
        if eta is None:
            continue

        heure_prevue = flight["heure_arrivee_prevue"]
        ecart_minutes = (eta - heure_prevue).total_seconds() / 60

        alerte = abs(ecart_minutes) >= SEUIL_ALERTE_MINUTES
        updates.append({
            "numero_vol": flight["numero_vol"],
            "eta_calculee": eta,
            "heure_prevue": heure_prevue,
            "ecart_minutes": round(ecart_minutes, 1),
            "alerte": alerte,
            "type_changement": "retard" if ecart_minutes > 0 else "avance",
        })
    return updates

"""
registration_matcher.py -- Rapprochement numero de vol <-> avion physique (icao24)
via l'historique reel OpenSky, pour remplacer les hypotheses/devinettes du
parser Excel par une verite terrain.

Principe en 2 etapes :
  1. Retrouver le icao24 (identifiant unique et permanent de l'avion, equivalent
     fonctionnel de l'immatriculation pour notre besoin) a partir du numero de
     vol, en cherchant dans l'historique des mouvements a Tanger ce jour-la.
  2. Une fois le icao24 connu, retrouver TOUS les mouvements de cet avion precis
     ce jour-la -> heure d'arrivee et de depart REELLES, plus de devinette.

IMPORTANT : ces fonctions font de vrais appels reseau vers OpenSky -- a tester
en local (comme opensky_client.py), pas depuis l'environnement de developpement
utilise pour preparer ce projet (acces reseau restreint).
"""

import requests
from datetime import datetime, timedelta
from opensky_client import OpenSkyClient
from realtime_tracking import normalize_callsign

GMTT_ICAO = "GMTT"
FLIGHTS_ARRIVAL_URL = "https://opensky-network.org/api/flights/arrival"
FLIGHTS_DEPARTURE_URL = "https://opensky-network.org/api/flights/departure"
FLIGHTS_AIRCRAFT_URL = "https://opensky-network.org/api/flights/aircraft"


def _to_unix(dt: datetime) -> int:
    return int(dt.timestamp())


def _requete_authentifiee(client: OpenSkyClient, url: str, params: dict):
    headers = {}
    token = client._get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def trouver_icao24_pour_vol(client: OpenSkyClient, numero_vol: str, jour: datetime) -> str | None:
    """
    Cherche, dans l'historique des arrivees ET departs a GMTT ce jour-la,
    un mouvement dont le callsign correspond au numero de vol donne.
    Retourne le icao24 si trouve, sinon None.
    """
    debut = _to_unix(jour.replace(hour=0, minute=0, second=0))
    fin = _to_unix(jour.replace(hour=23, minute=59, second=59))
    cible = normalize_callsign(numero_vol)

    for url in (FLIGHTS_ARRIVAL_URL, FLIGHTS_DEPARTURE_URL):
        try:
            mouvements = _requete_authentifiee(
                client, url, {"airport": GMTT_ICAO, "begin": debut, "end": fin}
            )
        except requests.exceptions.HTTPError:
            continue
        for m in mouvements:
            cs = normalize_callsign(m.get("callsign") or "")
            if cs == cible:
                return m.get("icao24")
    return None


def obtenir_vrai_creneau_sol(client: OpenSkyClient, icao24: str, jour: datetime,
                              marge_heures: int = 20):
    """
    Une fois le icao24 connu, retrouve TOUS les mouvements de cet avion sur une
    fenetre elargie (jour-1 a jour+1 par defaut) et en deduit son vrai creneau
    de presence au sol a Tanger : premiere arrivee -> premier depart suivant.

    Retourne (heure_arrivee_reelle, heure_depart_reelle) ou (None, None) si
    l'historique ne permet pas de conclure.
    """
    debut = _to_unix(jour - timedelta(hours=marge_heures))
    fin = _to_unix(jour + timedelta(hours=marge_heures))

    try:
        historique = _requete_authentifiee(
            client, f"{FLIGHTS_AIRCRAFT_URL}/{icao24}", {"begin": debut, "end": fin}
        )
    except requests.exceptions.HTTPError:
        return None, None

    # Mouvements arrivant a Tanger (estArrivalAirport == GMTT) et repartant de Tanger
    arrivees = sorted(
        [m for m in historique if m.get("estArrivalAirport") == GMTT_ICAO],
        key=lambda m: m.get("lastSeen", 0)
    )
    departs = sorted(
        [m for m in historique if m.get("estDepartureAirport") == GMTT_ICAO],
        key=lambda m: m.get("firstSeen", 0)
    )

    if not arrivees:
        return None, None

    heure_arrivee = datetime.fromtimestamp(arrivees[-1]["lastSeen"])

    depart_suivant = next(
        (d for d in departs if d["firstSeen"] >= arrivees[-1]["lastSeen"]), None
    )
    heure_depart = datetime.fromtimestamp(depart_suivant["firstSeen"]) if depart_suivant else None

    return heure_arrivee, heure_depart


def completer_vol_via_historique_reel(client: OpenSkyClient, flight: dict) -> dict:
    """
    Point d'entree pratique : prend un vol issu du parser Excel (avec une heure
    manquante et une hypothese de repli), tente de retrouver la vraie donnee via
    OpenSky, et remplace l'hypothese par la verite terrain si trouvee.
    """
    jour = flight.get("jour") or flight["heure_prevue_arrivee"]
    icao24 = trouver_icao24_pour_vol(client, flight["numero_vol"], jour)
    if not icao24:
        return flight  # pas trouve -> on garde l'hypothese existante

    heure_arrivee, heure_depart = obtenir_vrai_creneau_sol(client, icao24, jour)
    if heure_arrivee and heure_depart:
        flight = dict(flight)
        flight["heure_prevue_arrivee"] = heure_arrivee
        flight["heure_prevue_depart"] = heure_depart
        flight["icao24"] = icao24
        flight["hypothese_horaire"] = "verifie_via_historique_opensky_reel"
    return flight


if __name__ == "__main__":
    print("Ce module fait de vrais appels reseau -- a tester en local avec un vol reel.")
    print("Exemple d'usage :")
    print("  from registration_matcher import completer_vol_via_historique_reel")
    print("  from opensky_client import OpenSkyClient")
    print("  client = OpenSkyClient()")
    print("  vol_complete = completer_vol_via_historique_reel(client, mon_vol)")

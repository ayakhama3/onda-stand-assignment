"""
Client airplanes.live — source de secours, AUCUNE clé requise.

Utile pour :
  - Tester immédiatement sans inscription
  - Servir de source de secours si OpenSky est indisponible (redondance,
    voir principe de "dégradation propre" du README)

Format de réponse compatible ADS-B Exchange v2 (mêmes champs que ADS-B Exchange).
"""

import requests

BASE_URL = "https://api.airplanes.live/v2/point"

# Coordonnées de Tanger Ibn Battouta (GMTT)
TANGER_LAT = 35.7269
TANGER_LON = -5.9169
RADIUS_NM = 30  # rayon de recherche en milles nautiques


def get_aircraft_near_tanger(radius_nm=RADIUS_NM):
    url = f"{BASE_URL}/{TANGER_LAT}/{TANGER_LON}/{radius_nm}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def test_connectivity():
    try:
        data = get_aircraft_near_tanger()
        aircraft = data.get("ac", [])
        print(f"✅ airplanes.live accessible. {len(aircraft)} appareil(s) détecté(s) "
              f"dans un rayon de {RADIUS_NM} NM autour de Tanger.")
        if aircraft:
            a = aircraft[0]
            print(f"   Exemple : icao24={a.get('hex')}, callsign={a.get('flight', '').strip()}, "
                  f"altitude={a.get('alt_baro')}, sol={a.get('alt_baro') == 'ground'}")
        return True
    except requests.exceptions.HTTPError as e:
        print(f"❌ Erreur HTTP airplanes.live : {e}")
        return False
    except Exception as e:
        print(f"❌ Erreur de connexion airplanes.live : {e}")
        return False


if __name__ == "__main__":
    test_connectivity()

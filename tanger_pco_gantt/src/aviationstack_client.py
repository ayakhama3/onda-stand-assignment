"""
Client AviationStack — attention au quota très restreint (100 requêtes/mois en free tier)

Étapes pour obtenir ta clé :
1. Créer un compte sur https://aviationstack.com
2. Récupérer l'access_key sur le dashboard
"""

import os
import requests

BASE_URL = "https://api.aviationstack.com/v1/flights"


class AviationStackClient:
    def __init__(self, access_key=None):
        self.access_key = access_key or os.environ.get("AVIATIONSTACK_ACCESS_KEY")
        if not self.access_key:
            raise ValueError("Clé API AviationStack manquante (variable AVIATIONSTACK_ACCESS_KEY)")

    def get_flights_tanger(self, direction="arrival"):
        """direction: 'arrival' ou 'departure'. ATTENTION : consomme 1 requête du quota mensuel."""
        params = {
            "access_key": self.access_key,
            "arr_iata" if direction == "arrival" else "dep_iata": "TNG",
        }
        r = requests.get(BASE_URL, params=params, timeout=15)
        r.raise_for_status()
        return r.json()


def test_connectivity(access_key=None):
    """
    ATTENTION : ce test consomme 1 requête sur ton quota mensuel de 100.
    Ne pas lancer en boucle / à répétition pendant les tests.
    """
    try:
        client = AviationStackClient(access_key=access_key)
        data = client.get_flights_tanger()
        count = data.get("pagination", {}).get("total", 0)
        print(f"✅ AviationStack accessible. {count} vol(s) trouvé(s) pour TNG (arrivées).")
        if "error" in data:
            print(f"⚠️  Réponse contenant une erreur : {data['error']}")
        return True
    except requests.exceptions.HTTPError as e:
        print(f"❌ Erreur HTTP AviationStack : {e}")
        return False
    except Exception as e:
        print(f"❌ Erreur de connexion AviationStack : {e}")
        return False


if __name__ == "__main__":
    print("⚠️  Ce test va consommer 1 requête de ton quota mensuel (100/mois en free tier).")
    print("Assure-toi d'avoir défini la variable d'environnement AVIATIONSTACK_ACCESS_KEY.\n")
    test_connectivity()

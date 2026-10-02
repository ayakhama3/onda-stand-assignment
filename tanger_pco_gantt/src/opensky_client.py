"""
Client OpenSky Network — authentification OAuth2 (client_credentials)

IMPORTANT : OpenSky a migré vers OAuth2. L'ancienne authentification
username/password ne fonctionne plus pour les comptes non-legacy.

Étapes pour obtenir tes identifiants :
1. Créer un compte sur https://opensky-network.org
2. Se connecter, aller sur la page "Account"
3. Créer un "API client" -> récupérer client_id et client_secret
"""

import os
import requests
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()  # charge automatiquement le fichier .env s'il existe
except ImportError:
    pass  # python-dotenv non installé -> on continue avec les variables d'environnement classiques

TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
STATES_URL = "https://opensky-network.org/api/states/all"

# Bounding box approximative autour de Tanger Ibn Battouta (GMTT) rectangle geographique 
TANGER_BBOX = {
    "lamin": 35.60, "lamax": 35.90,
    "lomin": -6.10, "lomax": -5.70,
}


class OpenSkyClient:
    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id or os.environ.get("OPENSKY_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("OPENSKY_CLIENT_SECRET")
        self.token = None
        self.expires_at = None

    def _get_token(self):
        if self.token and self.expires_at and datetime.now() < self.expires_at:
            return self.token
        if not self.client_id or not self.client_secret:
            return None  # mode anonyme : pas de token, quota réduit mais fonctionnel
        r = requests.post(TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        r.raise_for_status()
        data = r.json()
        self.token = data["access_token"]
        self.expires_at = datetime.now() + timedelta(seconds=data.get("expires_in", 1800) - 30)
        return self.token

    def get_states_tanger(self):
        """Récupère les positions ADS-B actuelles dans la zone de Tanger."""
        headers = {}
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        r = requests.get(STATES_URL, params=TANGER_BBOX, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()


def test_connectivity():
    """Test simple de disponibilité — fonctionne même sans identifiants (mode anonyme)."""
    client = OpenSkyClient()
    try:
        data = client.get_states_tanger()
        n = len(data.get("states") or [])
        print(f"✅ OpenSky accessible. {n} appareil(s) détecté(s) dans la zone de Tanger.")
        print(f"   Horodatage serveur : {data.get('time')}")
        return True
    except requests.exceptions.HTTPError as e:
        print(f"❌ Erreur HTTP OpenSky : {e}")
        return False
    except Exception as e:
        print(f"❌ Erreur de connexion OpenSky : {e}")
        return False


if __name__ == "__main__":
    test_connectivity()

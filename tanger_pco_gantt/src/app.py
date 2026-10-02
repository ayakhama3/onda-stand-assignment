# -*- coding: utf-8 -*-
"""
Application Flask — Gestion intelligente des postes de stationnement
Aéroport Tanger Ibn Battouta (PCO)

Fonctions :
- lecture du programme Excel réel via excel_parser.py ;
- affectation CP-SAT via optimizer.py ;
- Gantt JOUR : postes sur X, heures sur Y ;
- Gantt SEMAINE : mêmes axes, sur toute la période du programme ;
- tableau opérationnel lisible ;
- suivi temps réel via poll_loop.py si disponible ;
- réoptimisation après retard ;
- bouton de démonstration d'un retard contrôlé.

Lancement :
    python app.py "C:\\chemin\\programme.xlsx" 04/08/2026
"""

import sys
import threading
import time
import logging
import inspect
from datetime import datetime, date, timedelta

from flask import Flask, jsonify, render_template_string, request

from excel_parser import parse_programme_vol
from standconfig import generate_parking_stands
from optimizer import solve_stand_assignment

try:
    from poll_loop import FlightStateStore, run_polling_cycle
except Exception:
    FlightStateStore = None
    run_polling_cycle = None

try:
    from reoptimization import reoptimiser_apres_retard
except Exception:
    reoptimiser_apres_retard = None

try:
    from opensky_client import OpenSkyClient
except Exception:
    OpenSkyClient = None

try:
    from airplaneslive_client import get_aircraft_near_tanger
except Exception:
    get_aircraft_near_tanger = None


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

PORT = 5000
INTERVALLE_POLLING = 60
INTERVALLE_REFRESH_UI = 15
SEUIL_REOPTIMISATION_MINUTES = 20
MAX_ALERTES = 30
ANTI_REPETITION_MINUTES = 10

# Ordre métier des postes, utilisé pour l'axe X.
ORDRE_POSTES = [
    "N8", "N7", "N6", "N5", "N4", "N3", "N2", "N1",
    "E7", "E6", "E5", "E4", "E3", "E2", "E1"
]

COULEURS = {
    "commercial": "#4C8BF5",
    "national": "#34A853",
    "cargo": "#9C27B0",
    "prive": "#FF9800",
    "poids_lourd": "#E53935",
    "inconnu": "#78909C",
}


# ---------------------------------------------------------------------------
# FLASK
# ---------------------------------------------------------------------------

app = Flask(__name__)


# ---------------------------------------------------------------------------
# ETAT GLOBAL
# ---------------------------------------------------------------------------

etat = {
    "pret": False,
    "fichier": None,
    "date_initiale": None,
    "source_temps_reel": "non démarrée",
    "dernier_polling": None,
    "erreur": None,
}

tous_les_vols = []
vols_by_num = {}
stands = []

# Résultats du solveur par date : {"2026-08-04": [resultats...]}
resultats_par_date = {}
non_places_par_date = {}

# Liste complète des dates réellement présentes dans le programme.
dates_programme = []

alertes = []

# numéro_vol -> dernière heure de traitement
dernieres_reoptimisations = {}
derniers_evenements = {}

lock = threading.RLock()

store_temps_reel = None
_thread_polling = None
_stop_polling = False


# ---------------------------------------------------------------------------
# OUTILS GENERIQUES
# ---------------------------------------------------------------------------

def _numero_vol(vol):
    return str(
        vol.get("numero_vol")
        or vol.get("flight_number")
        or vol.get("vol")
        or ""
    ).strip()


def _valeur(vol, *cles, default=None):
    for cle in cles:
        if cle in vol and vol[cle] not in (None, ""):
            return vol[cle]
    return default


def _heure_arrivee(vol):
    # IMPORTANT : le parser réel utilise heure_prevue_arrivee.
    return _valeur(
        vol,
        "heure_prevue_arrivee",
        "heure_arrivee",
        "scheduled_arrival",
        "arrival",
    )


def _heure_depart(vol):
    # IMPORTANT : le parser réel utilise heure_prevue_depart.
    return _valeur(
        vol,
        "heure_prevue_depart",
        "heure_depart",
        "scheduled_departure",
        "departure",
    )


def _to_datetime(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    if isinstance(value, str):
        s = value.strip()

        # ISO classique.
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass

        for fmt in (
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue

    return None


def _format_datetime(value):
    dt = _to_datetime(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else None


def _format_hm(value):
    dt = _to_datetime(value)
    return dt.strftime("%H:%M") if dt else "-"


def _date_key(value):
    dt = _to_datetime(value)
    return dt.strftime("%Y-%m-%d") if dt else None


def _duree_minutes(debut, fin):
    d = _to_datetime(debut)
    f = _to_datetime(fin)
    if not d or not f:
        return None
    return max(0, int((f - d).total_seconds() / 60))


def _safe_status_name(status):
    # Enum OR-Tools -> texte lisible sans dépendre d'un format particulier.
    try:
        return str(status).split(".")[-1]
    except Exception:
        return str(status)


def _normaliser_vol_pour_json(vol):
    """
    Transforme le dictionnaire du parser en structure stable pour le frontend.
    """
    arr = _heure_arrivee(vol)
    dep = _heure_depart(vol)

    resultat = dict(vol)
    resultat["numero_vol"] = _numero_vol(vol)
    resultat["heure_arrivee"] = _format_datetime(arr)
    resultat["heure_depart"] = _format_datetime(dep)
    resultat["heure_prevue_arrivee"] = _format_datetime(arr)
    resultat["heure_prevue_depart"] = _format_datetime(dep)
    resultat["jour"] = _date_key(arr or dep)

    resultat["compagnie"] = _valeur(vol, "compagnie", default="-")
    resultat["categorie_appareil"] = _valeur(
        vol, "categorie_appareil", "categorie", default="inconnu"
    )
    resultat["type_appareil"] = _valeur(vol, "type_appareil", default="-")
    resultat["taille_appareil"] = _valeur(vol, "taille_appareil", default="-")
    resultat["provenance"] = _valeur(vol, "provenance", default="-")
    resultat["destination"] = _valeur(vol, "destination", default="-")
    resultat["handler"] = _valeur(vol, "handler", default="-")

    return resultat


def _normaliser_resultat(resultat):
    """
    Structure stable du résultat optimizer.py.

    optimizer.py retourne exactement :
        results, status

    et en best-effort :
        results, status, vols_non_places
    """
    r = dict(resultat)

    numero = str(r.get("numero_vol", "")).strip()
    source = vols_by_num.get(numero, {})

    arr = r.get("heure_arrivee") or _heure_arrivee(source)
    dep = r.get("heure_depart") or _heure_depart(source)

    r["numero_vol"] = numero
    r["poste_assigne"] = r.get("poste_assigne") or r.get("poste")
    r["heure_arrivee"] = _format_datetime(arr)
    r["heure_depart"] = _format_datetime(dep)

    r["compagnie"] = _valeur(
        source, "compagnie", default=r.get("compagnie", "-")
    )
    r["categorie_appareil"] = _valeur(
        source,
        "categorie_appareil",
        "categorie",
        default=r.get("categorie_appareil", "inconnu"),
    )
    r["type_appareil"] = _valeur(
        source, "type_appareil", default=r.get("type_appareil", "-")
    )
    r["taille_appareil"] = _valeur(
        source, "taille_appareil", default=r.get("taille_appareil", "-")
    )
    r["provenance"] = _valeur(
        source, "provenance", default=r.get("provenance", "-")
    )
    r["destination"] = _valeur(
        source, "destination", default=r.get("destination", "-")
    )
    r["handler"] = _valeur(
        source, "handler", default=r.get("handler", "-")
    )

    r["duree_minutes"] = _duree_minutes(arr, dep)

    # Une escale courte doit rester lisible dans le Gantt.
    r["escale_rapide"] = (
        str(r.get("compagnie", "")).strip().lower() == "ryanair"
        or (
            r["duree_minutes"] is not None
            and r["duree_minutes"] <= 40
        )
    )

    r["statut"] = r.get("statut", "proposee")

    return r


def _resultat_vol(numero, date_str=None):
    numero = str(numero).strip()

    if date_str:
        for r in resultats_par_date.get(date_str, []):
            if r.get("numero_vol") == numero:
                return r

    for liste in resultats_par_date.values():
        for r in liste:
            if r.get("numero_vol") == numero:
                return r

    return None


def _vols_du_jour(date_str):
    """
    Un vol est affiché le jour s'il est présent à un moment quelconque
    pendant cette journée.

    Cela conserve correctement les night-stops :
      arrivée J 14:25 -> départ J+1 09:45
    sera visible le jour J et le jour J+1.
    """
    try:
        jour = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return []

    debut_jour = jour
    fin_jour = jour + timedelta(days=1)

    resultat = []

    for vol in tous_les_vols:
        arr = _to_datetime(_heure_arrivee(vol))
        dep = _to_datetime(_heure_depart(vol))

        if not arr and not dep:
            continue

        debut = arr or dep
        fin = dep or arr

        if fin >= debut_jour and debut <= fin_jour:
            resultat.append(vol)

    return resultat


def _resultats_du_jour(date_str):
    """
    Même logique pour les affectations.
    """
    jour = datetime.strptime(date_str, "%Y-%m-%d")
    debut_jour = jour
    fin_jour = jour + timedelta(days=1)

    resultat = []

    for r in resultats_par_date.get(date_str, []):
        arr = _to_datetime(r.get("heure_arrivee"))
        dep = _to_datetime(r.get("heure_depart"))

        if not arr and not dep:
            continue

        debut = arr or dep
        fin = dep or arr

        if fin >= debut_jour and debut <= fin_jour:
            resultat.append(r)

    return resultat


def _fusionner_vols_resultats(date_str):
    """
    Fusionne programme + affectation pour que le tableau affiche également
    les vols non affectés.
    """
    vols = _vols_du_jour(date_str)
    affectations = {
        r["numero_vol"]: r
        for r in resultats_par_date.get(date_str, [])
    }

    non_places = set(non_places_par_date.get(date_str, []))

    fusion = []

    for vol in vols:
        numero = _numero_vol(vol)

        if numero in affectations:
            item = dict(affectations[numero])
        else:
            item = _normaliser_vol_pour_json(vol)
            item["poste_assigne"] = None
            item["statut"] = (
                "non affecté" if numero in non_places else "non traité"
            )
            item["duree_minutes"] = _duree_minutes(
                _heure_arrivee(vol), _heure_depart(vol)
            )

        fusion.append(_normaliser_resultat(item))

    fusion.sort(
        key=lambda x: (
            _to_datetime(x.get("heure_arrivee"))
            or _to_datetime(x.get("heure_depart"))
            or datetime.max
        )
    )

    return fusion


# ---------------------------------------------------------------------------
# CHARGEMENT / OPTIMISATION
# ---------------------------------------------------------------------------

def charger_donnees(excel_path, date_demandee=None):
    global tous_les_vols
    global vols_by_num
    global stands
    global dates_programme
    global resultats_par_date
    global non_places_par_date

    logging.info("Chargement du programme Excel : %s", excel_path)

    vols = parse_programme_vol(excel_path)

    if not vols:
        raise RuntimeError("Aucun vol exploitable n'a été extrait du programme Excel.")

    tous_les_vols = list(vols)
    vols_by_num = {_numero_vol(v): v for v in tous_les_vols if _numero_vol(v)}

    logging.info("Vols extraits : %d", len(tous_les_vols))

    dates = set()

    for vol in tous_les_vols:
        arr = _date_key(_heure_arrivee(vol))
        dep = _date_key(_heure_depart(vol))

        if arr:
            dates.add(arr)
        if dep:
            dates.add(dep)

    dates_programme = sorted(dates)

    if not dates_programme:
        raise RuntimeError("Aucune date exploitable dans le programme Excel.")

    logging.info("Première date détectée : %s", dates_programme[0])
    logging.info("Dernière date détectée : %s", dates_programme[-1])

    stands = generate_parking_stands()

    # On conserve l'ordre métier si les noms existent dans la configuration.
    index_stand = {s.get("nom"): s for s in stands}
    stands_ordonnes = [
        index_stand[n]
        for n in ORDRE_POSTES
        if n in index_stand
    ]

    # Ajoute éventuellement les postes supplémentaires sans casser la config.
    for s in stands:
        if s not in stands_ordonnes:
            stands_ordonnes.append(s)

    stands = stands_ordonnes

    logging.info("Postes disponibles : %d", len(stands))

    resultats_par_date = {}
    non_places_par_date = {}

    for date_str in dates_programme:
        vols_jour = _vols_du_jour(date_str)

        # Déduplication : un même numéro de vol ne doit pas être envoyé deux fois
        # au solveur à cause d'une ligne doublonnée dans l'Excel.
        uniques = []
        vus = set()

        for vol in vols_jour:
            numero = _numero_vol(vol)
            if not numero or numero in vus:
                continue
            vus.add(numero)
            uniques.append(vol)

        if not uniques:
            resultats_par_date[date_str] = []
            non_places_par_date[date_str] = []
            continue

        logging.info(
            "Optimisation du %s : %d vols",
            date_str,
            len(uniques),
        )

        # Le contrat réel de optimizer.py est :
        #   results, status, vols_non_places
        # lorsque permettre_non_affectation=True.
        sortie = solve_stand_assignment(
            uniques,
            stands,
            time_limit_seconds=30,
            permettre_non_affectation=True,
        )

        if not isinstance(sortie, tuple) or len(sortie) != 3:
            raise RuntimeError(
                "Le retour de optimizer.py est inattendu. "
                "Avec permettre_non_affectation=True, il doit retourner "
                "(results, status, vols_non_places)."
            )

        resultats, status, vols_non_places = sortie

        logging.info(
            "%s : %d affectés, %d non affectés, statut=%s",
            date_str,
            len(resultats),
            len(vols_non_places),
            _safe_status_name(status),
        )

        resultats_par_date[date_str] = [
            _normaliser_resultat(r)
            for r in resultats
        ]

        non_places_par_date[date_str] = list(vols_non_places)

    etat["fichier"] = excel_path
    etat["date_initiale"] = (
        date_demandee
        if date_demandee in dates_programme
        else dates_programme[0]
    )
    etat["pret"] = True
    etat["erreur"] = None


# ---------------------------------------------------------------------------
# ALERTES
# ---------------------------------------------------------------------------

def _ajouter_alerte(message, niveau="info", numero_vol=None):
    with lock:
        alertes.insert(
            0,
            {
                "id": int(time.time() * 1000),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "niveau": niveau,
                "numero_vol": numero_vol,
                "message": message,
            },
        )

        del alertes[MAX_ALERTES:]


def _autoriser_reoptimisation(numero_vol):
    maintenant = datetime.now()

    precedent = dernieres_reoptimisations.get(numero_vol)

    if precedent is not None:
        delta = (maintenant - precedent).total_seconds() / 60
        if delta < ANTI_REPETITION_MINUTES:
            return False

    dernieres_reoptimisations[numero_vol] = maintenant
    return True


# ---------------------------------------------------------------------------
# REOPTIMISATION
# ---------------------------------------------------------------------------

def _reoptimiser_apres_retard(numero_vol, nouveau_depart=None, retard_minutes=0):
    """
    Essaie d'utiliser le module reoptimization.py réel.

    Si le module possède une signature différente, on construit au minimum
    une réoptimisation CP-SAT cohérente avec les données actuellement chargées.
    """
    numero_vol = str(numero_vol).strip()

    source = vols_by_num.get(numero_vol)
    if not source:
        raise ValueError(f"Vol introuvable : {numero_vol}")

    ancien_arr = _to_datetime(_heure_arrivee(source))
    ancien_dep = _to_datetime(_heure_depart(source))

    if nouveau_depart is None:
        if not ancien_dep:
            raise ValueError(f"Heure de départ inconnue pour {numero_vol}")
        nouveau_depart = ancien_dep + timedelta(minutes=retard_minutes)
    else:
        nouveau_depart = _to_datetime(nouveau_depart)

    if nouveau_depart is None:
        raise ValueError("Nouveau départ invalide.")

    # Date opérationnelle du vol.
    date_str = _date_key(ancien_arr or ancien_dep)

    if date_str not in resultats_par_date:
        raise ValueError(f"Aucune affectation disponible pour {date_str}")

    # ------------------------------------------------------------------
    # 1) Mise à jour temporaire du vol perturbé.
    # ------------------------------------------------------------------
    vols_recalcul = []

    for vol in _vols_du_jour(date_str):
        v = dict(vol)

        if _numero_vol(v) == numero_vol:
            v["heure_prevue_depart"] = nouveau_depart

        vols_recalcul.append(v)

    # ------------------------------------------------------------------
    # 2) On essaie d'abord le module de réoptimisation réel.
    # ------------------------------------------------------------------
    if reoptimiser_apres_retard is not None:
        try:
            signature = inspect.signature(reoptimiser_apres_retard)
            noms = list(signature.parameters.keys())

            # Appel explicite pour les signatures connues les plus fréquentes.
            candidats = [
                (
                    vols_recalcul,
                    resultats_par_date[date_str],
                    numero_vol,
                ),
                (
                    vols_recalcul,
                    resultats_par_date[date_str],
                    numero_vol,
                    stands,
                ),
                (
                    vols_recalcul,
                    resultats_par_date[date_str],
                    numero_vol,
                    stands,
                    retard_minutes,
                ),
            ]

            # Ne tente l'appel positionnel que si le nombre de paramètres
            # correspond exactement à la variante.
            for args in candidats:
                if len(noms) == len(args):
                    try:
                        sortie = reoptimiser_apres_retard(*args)
                        if sortie is not None:
                            return _appliquer_sortie_reoptimisation(
                                date_str, sortie, numero_vol, nouveau_depart
                            )
                    except TypeError:
                        continue
                    except Exception as exc:
                        logging.warning(
                            "Réoptimisation module réel échouée : %s",
                            exc,
                        )
                        break
        except Exception as exc:
            logging.warning("Signature reoptimization.py non exploitable : %s", exc)

    # ------------------------------------------------------------------
    # 3) Fallback CP-SAT incrémental robuste.
    #
    # On fige les affectations valides des autres vols et on recalcule
    # le vol perturbé. Cela utilise exactement optimizer.py.
    # ------------------------------------------------------------------
    affectations = resultats_par_date.get(date_str, [])

    postes_figes = {}

    for r in affectations:
        n = r.get("numero_vol")
        p = r.get("poste_assigne")

        if n and p and n != numero_vol:
            postes_figes[n] = p

    sortie = solve_stand_assignment(
        vols_recalcul,
        stands,
        time_limit_seconds=30,
        postes_figes=postes_figes,
        permettre_non_affectation=True,
    )

    if len(sortie) != 3:
        raise RuntimeError("Retour optimizer.py inattendu pendant la réoptimisation.")

    resultats, status, non_places = sortie

    resultats_normalises = [
        _normaliser_resultat(r)
        for r in resultats
    ]

    resultats_par_date[date_str] = resultats_normalises
    non_places_par_date[date_str] = list(non_places)

    return {
        "date": date_str,
        "status": _safe_status_name(status),
        "resultats": resultats_normalises,
        "non_places": list(non_places),
    }


def _appliquer_sortie_reoptimisation(date_str, sortie, numero_vol, nouveau_depart):
    """
    Normalise les sorties éventuelles du module reoptimization.py.
    """
    if isinstance(sortie, tuple):
        if len(sortie) == 3:
            resultats, status, non_places = sortie
        elif len(sortie) == 2:
            resultats, status = sortie
            non_places = []
        else:
            raise RuntimeError("Retour reoptimization.py inattendu.")
    elif isinstance(sortie, list):
        resultats = sortie
        status = "OK"
        non_places = []
    else:
        raise RuntimeError("Retour reoptimization.py inattendu.")

    resultats_normalises = [
        _normaliser_resultat(r)
        for r in resultats
    ]

    resultats_par_date[date_str] = resultats_normalises
    non_places_par_date[date_str] = list(non_places)

    return {
        "date": date_str,
        "status": _safe_status_name(status),
        "resultats": resultats_normalises,
        "non_places": list(non_places),
    }


# ---------------------------------------------------------------------------
# DEMO RETARD
# ---------------------------------------------------------------------------

def simuler_retard(numero_vol=None, retard_minutes=40):
    """
    Démonstration contrôlée.

    Important :
    cette fonction ne prétend pas être un événement ADS-B réel.
    Elle injecte un retard dans le même moteur de réoptimisation.
    """
    with lock:
        if not resultats_par_date:
            raise RuntimeError("Le programme n'est pas chargé.")

        candidat = None

        if numero_vol:
            candidat = _resultat_vol(numero_vol)
        else:
            # Premier vol affecté possédant une heure de départ.
            for date_str in dates_programme:
                for r in resultats_par_date.get(date_str, []):
                    if r.get("heure_depart"):
                        candidat = r
                        break
                if candidat:
                    break

        if not candidat:
            raise RuntimeError("Aucun vol affecté disponible pour la démonstration.")

        numero = candidat["numero_vol"]

        depart = _to_datetime(candidat["heure_depart"])
        nouveau_depart = depart + timedelta(minutes=int(retard_minutes))

        if not _autoriser_reoptimisation(numero):
            raise RuntimeError(
                f"Le vol {numero} a déjà été réoptimisé récemment."
            )

        ancien_poste = candidat.get("poste_assigne")

        sortie = _reoptimiser_apres_retard(
            numero_vol=numero,
            nouveau_depart=nouveau_depart,
            retard_minutes=int(retard_minutes),
        )

        nouveau = _resultat_vol(numero, sortie["date"])
        nouveau_poste = nouveau.get("poste_assigne") if nouveau else None

        _ajouter_alerte(
            (
                f"RETARD SIMULÉ : {numero} +{retard_minutes} min. "
                f"Poste : {ancien_poste or '-'} → {nouveau_poste or '-'}."
            ),
            niveau="warning",
            numero_vol=numero,
        )

        return {
            "numero_vol": numero,
            "retard_minutes": int(retard_minutes),
            "ancien_poste": ancien_poste,
            "nouveau_poste": nouveau_poste,
            "nouveau_depart": _format_datetime(nouveau_depart),
            "reoptimisation": sortie,
        }


# ---------------------------------------------------------------------------
# TEMPS REEL
# ---------------------------------------------------------------------------

def _source_opensky_test():
    """
    Test léger de disponibilité OpenSky.

    Le suivi réel détaillé reste délégué à poll_loop.py.
    """
    if OpenSkyClient is None:
        return False

    try:
        client = OpenSkyClient()

        # Plusieurs implémentations du client sont possibles.
        for nom in (
            "get_states",
            "get_aircraft_states",
            "get_aircraft_near_tanger",
        ):
            methode = getattr(client, nom, None)
            if callable(methode):
                try:
                    resultat = methode()
                    return resultat is not None
                except TypeError:
                    continue

        return False
    except Exception as exc:
        logging.warning("OpenSky indisponible : %s", exc)
        return False


def _vols_a_surveiller():
    """
    Pour le mode temps réel, on ne surveille que les vols proches de la date
    actuelle. Cela évite de demander à OpenSky une position actuelle pour un
    programme historique d'août alors que nous sommes hors de cette période.
    """
    maintenant = datetime.now()

    resultat = []

    for vol in tous_les_vols:
        arr = _to_datetime(_heure_arrivee(vol))
        dep = _to_datetime(_heure_depart(vol))

        dates = [x for x in (arr, dep) if x]
        if not dates:
            continue

        if any(abs((d.date() - maintenant.date()).days) <= 1 for d in dates):
            resultat.append(vol)

    return resultat


def _callback_alerte_polling(*args, **kwargs):
    """
    Callback tolérant pour plusieurs versions de poll_loop.py.

    Si poll_loop transmet un dictionnaire contenant un vol et un retard,
    on tente de déclencher la réoptimisation.
    """
    evenement = None

    for arg in args:
        if isinstance(arg, dict):
            evenement = arg
            break

    if evenement is None:
        evenement = kwargs

    numero = (
        evenement.get("numero_vol")
        or evenement.get("flight_number")
        or evenement.get("vol")
    )

    retard = (
        evenement.get("retard_minutes")
        or evenement.get("delay_minutes")
        or evenement.get("retard")
    )

    if not numero:
        return

    try:
        retard = float(retard or 0)
    except Exception:
        retard = 0

    if retard < SEUIL_REOPTIMISATION_MINUTES:
        return

    if not _autoriser_reoptimisation(str(numero)):
        return

    try:
        sortie = _reoptimiser_apres_retard(
            numero_vol=str(numero),
            retard_minutes=int(retard),
        )

        nouveau = _resultat_vol(str(numero), sortie["date"])
        poste = nouveau.get("poste_assigne") if nouveau else None

        _ajouter_alerte(
            (
                f"RETARD RÉEL : {numero} +{int(retard)} min. "
                f"Réoptimisation effectuée, poste proposé : {poste or 'aucun'}."
            ),
            niveau="danger",
            numero_vol=str(numero),
        )

    except Exception as exc:
        logging.exception("Erreur de réoptimisation temps réel")
        _ajouter_alerte(
            f"Erreur de réoptimisation pour {numero} : {exc}",
            niveau="danger",
            numero_vol=str(numero),
        )


def boucle_surveillance():
    global _stop_polling

    if run_polling_cycle is None:
        etat["source_temps_reel"] = "poll_loop indisponible"
        return

    while not _stop_polling:
        try:
            vols = _vols_a_surveiller()

            if not vols:
                etat["source_temps_reel"] = (
                    "aucun vol à surveiller pour la date actuelle"
                )
                etat["dernier_polling"] = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            else:
                # Heure actuelle utilisée par le cycle de suivi temps réel.
                now = datetime.now()

                # Le module poll_loop attend exactement :
                # run_polling_cycle(states, expected_flights, now, store)
                sortie = run_polling_cycle(
                    vols,
                    vols,
                    now,
                    store_temps_reel,
                )

                if sortie is not None:
                    etat["source_temps_reel"] = (
                        "OpenSky / source configurée"
                    )

                etat["dernier_polling"] = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

        except Exception as exc:
            logging.exception("Erreur pendant le polling temps réel")

            etat["source_temps_reel"] = "indisponible"
            etat["dernier_polling"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            etat["erreur"] = str(exc)

        # Attente avant le prochain cycle de polling.
        for _ in range(INTERVALLE_POLLING):
            if _stop_polling:
                break
            time.sleep(1)


def demarrer_surveillance():
    global _thread_polling
    global store_temps_reel

    if FlightStateStore is not None:
        try:
            store_temps_reel = FlightStateStore()
        except Exception:
            try:
                store_temps_reel = FlightStateStore({})
            except Exception:
                store_temps_reel = None

    if run_polling_cycle is None:
        logging.warning("poll_loop.py non disponible.")
        return

    _thread_polling = threading.Thread(
        target=boucle_surveillance,
        name="surveillance-temps-reel",
        daemon=True,
    )
    _thread_polling.start()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/etat")
def api_etat():
    with lock:
        date_str = request.args.get("date") or etat.get("date_initiale")

        if date_str not in dates_programme and dates_programme:
            date_str = dates_programme[0]

        lignes = _fusionner_vols_resultats(date_str) if date_str else []

        affectes = sum(
            1 for x in lignes if x.get("poste_assigne")
        )

        non_affectes = len(lignes) - affectes

        return jsonify({
            "pret": etat["pret"],
            "fichier": etat["fichier"],
            "date_initiale": etat["date_initiale"],
            "date_selectionnee": date_str,
            "dates": dates_programme,
            "stands": [s.get("nom") for s in stands],
            "vols": lignes,
            "affectes": affectes,
            "non_affectes": non_affectes,
            "total": len(lignes),
            "alertes": list(alertes),
            "source_temps_reel": etat["source_temps_reel"],
            "dernier_polling": etat["dernier_polling"],
            "erreur": etat["erreur"],
        })


@app.get("/api/date/<date_str>")
def api_date(date_str):
    if date_str not in dates_programme:
        return jsonify({"error": "Date absente du programme"}), 404

    return jsonify({
        "date": date_str,
        "vols": _fusionner_vols_resultats(date_str),
        "non_places": non_places_par_date.get(date_str, []),
    })


@app.get("/api/semaine")
def api_semaine():
    toutes = []

    for date_str in dates_programme:
        toutes.extend(_fusionner_vols_resultats(date_str))

    # Un même night-stop peut apparaître deux jours : pour le planning global,
    # on déduplique uniquement les occurrences strictement identiques.
    uniques = []
    clefs = set()

    for r in toutes:
        cle = (
            r.get("numero_vol"),
            r.get("heure_arrivee"),
            r.get("heure_depart"),
            r.get("poste_assigne"),
        )

        if cle in clefs:
            continue

        clefs.add(cle)
        uniques.append(r)

    return jsonify({
        "dates": dates_programme,
        "vols": uniques,
    })


@app.post("/api/demo/retard")
def api_demo_retard():
    data = request.get_json(silent=True) or {}

    numero = data.get("numero_vol")
    retard = data.get("retard_minutes", 40)

    try:
        retard = int(retard)
    except Exception:
        retard = 40

    try:
        resultat = simuler_retard(numero, retard)
        return jsonify({
            "ok": True,
            **resultat,
        })
    except Exception as exc:
        logging.exception("Erreur demo retard")
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400


# ---------------------------------------------------------------------------
# INTERFACE HTML
# ---------------------------------------------------------------------------

HTML = r"""
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>PCO Tanger — Affectation intelligente des postes</title>

<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, Helvetica, sans-serif;
    background: #f4f7fb;
    color: #172033;
}

.header {
    background: #12395b;
    color: white;
    padding: 22px 32px;
}

.header h1 {
    margin: 0 0 7px 0;
    font-size: 25px;
}

.header p {
    margin: 0;
    opacity: .88;
}

.container {
    width: min(1800px, 96%);
    margin: 20px auto 50px;
}

.controls {
    background: white;
    padding: 16px;
    border-radius: 10px;
    box-shadow: 0 2px 10px rgba(0,0,0,.07);
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
}

.controls label {
    font-weight: 700;
}

select, button {
    border: 1px solid #ccd5e0;
    border-radius: 7px;
    padding: 9px 13px;
    background: white;
    cursor: pointer;
}

button.primary {
    background: #12395b;
    color: white;
    border-color: #12395b;
}

button.warning {
    background: #e88900;
    color: white;
    border-color: #e88900;
}

.status {
    margin-left: auto;
    font-size: 13px;
    color: #516174;
}

.cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin: 18px 0;
}

.card {
    background: white;
    border-radius: 10px;
    padding: 18px;
    box-shadow: 0 2px 10px rgba(0,0,0,.07);
}

.card .value {
    font-size: 29px;
    font-weight: 700;
    margin-top: 5px;
}

.card .label {
    color: #66758a;
    font-size: 13px;
}

.section {
    background: white;
    border-radius: 10px;
    margin-top: 18px;
    padding: 18px;
    box-shadow: 0 2px 10px rgba(0,0,0,.07);
}

.section h2 {
    margin: 0 0 10px 0;
    font-size: 20px;
}

.subtitle {
    color: #64748b;
    font-size: 13px;
    margin-bottom: 8px;
}

#ganttJour, #ganttSemaine {
    width: 100%;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    min-width: 1050px;
}

th {
    background: #edf3f8;
    text-align: left;
    padding: 10px;
    font-size: 12px;
    border-bottom: 2px solid #d8e0e8;
    position: sticky;
    top: 0;
}

td {
    padding: 9px 10px;
    border-bottom: 1px solid #e8edf2;
    font-size: 13px;
}

tr:hover {
    background: #f7fafc;
}

.badge {
    display: inline-block;
    padding: 4px 8px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
}

.badge.ok {
    background: #e8f5e9;
    color: #1b6e2b;
}

.badge.warn {
    background: #fff3cd;
    color: #8a5a00;
}

.badge.err {
    background: #fdecec;
    color: #a51f1f;
}

.alert {
    padding: 10px 12px;
    border-left: 4px solid #e88900;
    background: #fff9ed;
    margin-bottom: 8px;
    border-radius: 5px;
    font-size: 13px;
}

.empty {
    color: #7b8794;
    padding: 20px;
    text-align: center;
}

.legend {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin: 8px 0;
}

.legend-item {
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 5px;
}

.legend-dot {
    width: 11px;
    height: 11px;
    border-radius: 3px;
}

@media (max-width: 900px) {
    .cards {
        grid-template-columns: repeat(2, 1fr);
    }

    .status {
        width: 100%;
        margin-left: 0;
    }
}
</style>
</head>

<body>

<div class="header">
    <h1>Gantt de stationnement — PCO Tanger</h1>
    <p>Affectation intelligente des postes et suivi opérationnel</p>
</div>

<div class="container">

    <div class="controls">
        <label for="dateSelector">Date opérationnelle :</label>
        <select id="dateSelector"></select>

        <button class="primary" onclick="actualiser()">Actualiser</button>
        <button class="warning" onclick="simulerRetard()">Simuler un retard +40 min</button>

        <div class="status" id="status">Chargement...</div>
    </div>

    <div class="cards">
        <div class="card">
            <div class="label">Vols de la journée</div>
            <div class="value" id="nbVols">0</div>
        </div>

        <div class="card">
            <div class="label">Vols affectés</div>
            <div class="value" id="nbAffectes">0</div>
        </div>

        <div class="card">
            <div class="label">Non affectés</div>
            <div class="value" id="nbNonAffectes">0</div>
        </div>

        <div class="card">
            <div class="label">Source temps réel</div>
            <div class="value" id="source" style="font-size:17px;">-</div>
        </div>
    </div>

    <div class="section">
        <h2>Planning détaillé de la journée</h2>

        <div class="subtitle">
            Axe X : postes de stationnement · Axe Y : heures ·
            chaque rectangle représente l'occupation réelle du poste par un avion.
        </div>

        <div class="legend">
            <div class="legend-item">
                <span class="legend-dot" style="background:#4C8BF5"></span> Commercial
            </div>
            <div class="legend-item">
                <span class="legend-dot" style="background:#34A853"></span> National
            </div>
            <div class="legend-item">
                <span class="legend-dot" style="background:#9C27B0"></span> Cargo
            </div>
            <div class="legend-item">
                <span class="legend-dot" style="background:#FF9800"></span> Privé
            </div>
        </div>

        <div id="ganttJour"></div>
    </div>

    <div class="section">
        <h2>Planning hebdomadaire</h2>
        <div class="subtitle">
            Même représentation : postes en X et temps en Y.
        </div>
        <div id="ganttSemaine"></div>
    </div>

    <div class="section">
        <h2>Programme des vols</h2>

        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Vol</th>
                        <th>Compagnie</th>
                        <th>Type avion</th>
                        <th>Arrivée</th>
                        <th>Départ</th>
                        <th>Durée parking</th>
                        <th>Poste</th>
                        <th>Provenance</th>
                        <th>Destination</th>
                        <th>Statut</th>
                    </tr>
                </thead>
                <tbody id="tableBody"></tbody>
            </table>
        </div>
    </div>

    <div class="section">
        <h2>Alertes PCO</h2>
        <div id="alertes"></div>
    </div>

</div>

<script>
let dateSelectionnee = null;
let donnees = [];
let donneesSemaine = [];
let datesProgramme = [];
let refreshTimer = null;

const couleurs = {
    commercial: "#4C8BF5",
    national: "#34A853",
    cargo: "#9C27B0",
    prive: "#FF9800",
    poids_lourd: "#E53935",
    inconnu: "#78909C"
};

function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function couleurCategorie(categorie) {
    return couleurs[categorie] || couleurs.inconnu;
}

function formatterDuree(minutes) {
    if (minutes === null || minutes === undefined || isNaN(minutes)) {
        return "-";
    }

    minutes = Number(minutes);

    if (minutes < 60) {
        return `${minutes} min`;
    }

    const h = Math.floor(minutes / 60);
    const m = minutes % 60;

    return `${h} h ${String(m).padStart(2, "0")} min`;
}

function construireDates() {
    const select = document.getElementById("dateSelector");

    select.innerHTML = "";

    datesProgramme.forEach(date => {
        const option = document.createElement("option");
        option.value = date;

        const d = new Date(date + "T00:00:00");

        option.textContent = d.toLocaleDateString(
            "fr-FR",
            {
                weekday: "long",
                day: "2-digit",
                month: "2-digit",
                year: "numeric"
            }
        );

        select.appendChild(option);
    });

    if (!dateSelectionnee || !datesProgramme.includes(dateSelectionnee)) {
        dateSelectionnee = datesProgramme[0] || null;
    }

    if (dateSelectionnee) {
        select.value = dateSelectionnee;
    }

    select.onchange = () => {
        dateSelectionnee = select.value;
        chargerDate();
    };
}

function afficherTableau(vols) {
    const body = document.getElementById("tableBody");

    if (!vols.length) {
        body.innerHTML = `
            <tr>
                <td colspan="10" class="empty">
                    Aucun vol pour cette date.
                </td>
            </tr>
        `;
        return;
    }

    const tries = [...vols].sort((a, b) => {
        const dateA =
            a.heure_arrivee
            ? new Date(a.heure_arrivee)
            : new Date(a.heure_depart);

        const dateB =
            b.heure_arrivee
            ? new Date(b.heure_arrivee)
            : new Date(b.heure_depart);

        return dateA - dateB;
    });

    body.innerHTML = tries.map(v => {
        const statut = v.poste_assigne
            ? `<span class="badge ok">Affecté</span>`
            : `<span class="badge err">Non affecté</span>`;

        return `
            <tr>
                <td><strong>${escapeHtml(v.numero_vol)}</strong></td>
                <td>${escapeHtml(v.compagnie || "-")}</td>
                <td>${escapeHtml(v.type_appareil || "-")}</td>
                <td>${formatHeure(v.heure_arrivee)}</td>
                <td>${formatHeure(v.heure_depart)}</td>
                <td>${formatterDuree(v.duree_minutes)}</td>
                <td><strong>${escapeHtml(v.poste_assigne || "—")}</strong></td>
                <td>${escapeHtml(v.provenance || "-")}</td>
                <td>${escapeHtml(v.destination || "-")}</td>
                <td>${statut}</td>
            </tr>
        `;
    }).join("");
}

function formatHeure(iso) {
    if (!iso) return "-";

    const d = new Date(iso);

    if (isNaN(d.getTime())) return "-";

    return d.toLocaleString(
        "fr-FR",
        {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        }
    );
}

function intervalleVisible(vol, dateMin, dateMax) {
    if (!vol.heure_arrivee && !vol.heure_depart) {
        return null;
    }

    const arr = vol.heure_arrivee
        ? new Date(vol.heure_arrivee)
        : new Date(vol.heure_depart);

    const dep = vol.heure_depart
        ? new Date(vol.heure_depart)
        : new Date(vol.heure_arrivee);

    if (isNaN(arr.getTime()) || isNaN(dep.getTime())) {
        return null;
    }

    let debut = arr;
    let fin = dep;

    if (fin <= debut) {
        fin = new Date(debut.getTime() + 5 * 60000);
    }

    if (dateMin && debut < dateMin) {
        debut = new Date(dateMin);
    }

    if (dateMax && fin > dateMax) {
        fin = new Date(dateMax);
    }

    if (fin <= debut) {
        return null;
    }

    return { debut, fin };
}

function construireGantt(id, vols, titre, dateJour) {

    const element = document.getElementById(id);

    const postes = [
        "N8", "N7", "N6", "N5", "N4", "N3", "N2", "N1",
        "E7", "E6", "E5", "E4", "E3", "E2", "E1"
    ];

    let dateMin = null;
    let dateMax = null;

    if (dateJour && dateSelectionnee) {
        dateMin = new Date(dateSelectionnee + "T00:00:00");
        dateMax = new Date(dateSelectionnee + "T23:59:59");
    }

    const traces = [];
    const shapes = [];

    vols.forEach((vol, index) => {

        const poste = vol.poste_assigne;

        if (!poste) return;

        const position = postes.indexOf(poste);

        if (position < 0) return;

        const intervalle = intervalleVisible(
            vol,
            dateMin,
            dateMax
        );

        if (!intervalle) return;

        const categorie =
            vol.categorie_appareil || "inconnu";

        const couleur =
            couleurCategorie(categorie);

        const debut = intervalle.debut;
        const fin = intervalle.fin;

        /*
         * Rectangle :
         * X = poste
         * Y = heure
         *
         * On utilise un shape numérique pour éviter le problème
         * Plotly "bar + base" qui affichait des durées comme des heures.
         */
        shapes.push({
            type: "rect",
            xref: "x",
            yref: "y",
            x0: position - 0.38,
            x1: position + 0.38,
            y0: debut,
            y1: fin,
            fillcolor: couleur,
            line: {
                color: "#ffffff",
                width: 1
            },
            opacity: 0.92,
            layer: "below"
        });

        /*
         * Trace invisible servant uniquement au hover.
         * Un hover par avion, pas une légende "trace 0", "trace 1", etc.
         */
        traces.push({
            type: "scatter",
            mode: "markers",
            x: [position],
            y: [new Date((debut.getTime() + fin.getTime()) / 2)],
            marker: {
                size: 12,
                color: couleur,
                opacity: 0
            },
            hovertemplate:
                `<b>${escapeHtml(vol.numero_vol)}</b><br>` +
                `Poste : <b>${escapeHtml(poste)}</b><br>` +
                `Arrivée : ${formatHeure(vol.heure_arrivee)}<br>` +
                `Départ : ${formatHeure(vol.heure_depart)}<br>` +
                `Occupation : ${formatterDuree(vol.duree_minutes)}<br>` +
                `Compagnie : ${escapeHtml(vol.compagnie || "-")}<br>` +
                `Avion : ${escapeHtml(vol.type_appareil || "-")}` +
                `<extra></extra>`,
            showlegend: false
        });

        /*
         * Numéro du vol écrit au centre uniquement si le rectangle
         * est suffisamment long.
         */
        const duree = (fin.getTime() - debut.getTime()) / 60000;

        if (duree >= 18) {
            traces.push({
                type: "scatter",
                mode: "text",
                x: [position],
                y: [new Date((debut.getTime() + fin.getTime()) / 2)],
                text: [vol.numero_vol],
                textfont: {
                    color: "#ffffff",
                    size: 11
                },
                hoverinfo: "skip",
                showlegend: false
            });
        }
    });

    const hauteur = dateJour ? 720 : 850;

    let yRange;

    if (dateJour) {
        yRange = [
            dateMin,
            dateMax
        ];
    } else {
        if (vols.length) {
            const dates = [];

            vols.forEach(v => {
                if (v.heure_arrivee) dates.push(new Date(v.heure_arrivee));
                if (v.heure_depart) dates.push(new Date(v.heure_depart));
            });

            if (dates.length) {
                const min = new Date(Math.min(...dates.map(d => d.getTime())));
                const max = new Date(Math.max(...dates.map(d => d.getTime())));

                yRange = [
                    new Date(min.getTime() - 60 * 60000),
                    new Date(max.getTime() + 60 * 60000)
                ];
            }
        }
    }

    if (!yRange) {
        yRange = [
            new Date("2026-01-01T00:00:00"),
            new Date("2026-01-02T00:00:00")
        ];
    }

    const layout = {
        title: {
            text: titre,
            font: { size: 19 }
        },

        height: hauteur,

        margin: {
            l: 80,
            r: 30,
            t: 65,
            b: 75
        },

        xaxis: {
            type: "linear",
            range: [-0.5, postes.length - 0.5],
            tickmode: "array",
            tickvals: postes.map((_, i) => i),
            ticktext: postes,
            title: {
                text: "Postes de stationnement"
            },
            fixedrange: false,
            showgrid: true,
            gridcolor: "#dce3ea"
        },

        yaxis: {
            type: "date",
            range: yRange,
            title: {
                text: "Heure"
            },
            dtick: dateJour ? 60 * 60 * 1000 : 6 * 60 * 60 * 1000,
            tickformat: dateJour
                ? "%H:%M"
                : "%d/%m %H:%M",
            showgrid: true,
            gridcolor: "#dce3ea",
            fixedrange: false
        },

        shapes: shapes,

        plot_bgcolor: "#ffffff",
        paper_bgcolor: "#ffffff",

        hovermode: "closest",

        showlegend: false
    };

    Plotly.react(
        element,
        traces,
        layout,
        {
            responsive: true,
            displaylogo: false
        }
    );
}

function afficherAlertes(alertes) {
    const box = document.getElementById("alertes");

    if (!alertes || !alertes.length) {
        box.innerHTML = `
            <div class="empty">
                Aucune alerte.
            </div>
        `;
        return;
    }

    box.innerHTML = alertes.map(a => `
        <div class="alert">
            <strong>${escapeHtml(a.timestamp)}</strong>
            — ${escapeHtml(a.message)}
        </div>
    `).join("");
}

async function chargerDate() {
    if (!dateSelectionnee) return;

    try {
        const response = await fetch(
            `/api/date/${encodeURIComponent(dateSelectionnee)}`
        );

        const data = await response.json();

        donnees = data.vols || [];

        afficherVues();

    } catch (error) {
        console.error(error);
    }
}

function afficherVues() {

    const volsJourUniques = [];

    const numerosVus = new Set();

    donnees.forEach(v => {
        if (!numerosVus.has(v.numero_vol)) {
            numerosVus.add(v.numero_vol);
            volsJourUniques.push(v);
        }
    });

    document.getElementById("nbVols").innerText =
        volsJourUniques.length;

    document.getElementById("nbAffectes").innerText =
        volsJourUniques.filter(v => v.poste_assigne).length;

    document.getElementById("nbNonAffectes").innerText =
        volsJourUniques.filter(v => !v.poste_assigne).length;

    construireGantt(
        "ganttJour",
        volsJourUniques,
        "Planning détaillé de la journée",
        true
    );

    construireGantt(
        "ganttSemaine",
        donneesSemaine,
        "Planning hebdomadaire",
        false
    );

    afficherTableau(volsJourUniques);
}

async function actualiser() {
    await chargerEtat();
}

async function chargerEtat() {
    try {
        const response = await fetch(
            `/api/etat?date=${encodeURIComponent(dateSelectionnee || "")}`
        );

        const data = await response.json();

        if (!data.pret) {
            document.getElementById("status").innerText =
                "Programme non chargé";
            return;
        }

        datesProgramme = data.dates || [];

        construireDates();

        if (!dateSelectionnee) {
            dateSelectionnee = data.date_initiale;
        }

        const dateResponse = await fetch(
            `/api/date/${encodeURIComponent(dateSelectionnee)}`
        );

        const dateData = await dateResponse.json();

        donnees = dateData.vols || [];

        const semaineResponse =
            await fetch("/api/semaine");

        const semaineData =
            await semaineResponse.json();

        donneesSemaine =
            semaineData.vols || [];

        document.getElementById("source").innerText =
            data.source_temps_reel || "-";

        document.getElementById("status").innerText =
            data.dernier_polling
                ? `Dernier contrôle : ${data.dernier_polling}`
                : "Système prêt";

        afficherAlertes(data.alertes || []);

        afficherVues();

    } catch (error) {
        console.error(error);

        document.getElementById("status").innerText =
            "Erreur de communication avec le serveur";
    }
}

async function simulerRetard() {

    try {
        const response = await fetch(
            "/api/demo/retard",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    retard_minutes: 40
                })
            }
        );

        const data = await response.json();

        if (!data.ok) {
            alert(data.error || "Erreur");
            return;
        }

        alert(
            `Retard simulé : ${data.numero_vol}\n` +
            `Poste avant : ${data.ancien_poste || "-"}\n` +
            `Poste après : ${data.nouveau_poste || "-"}`
        );

        await chargerEtat();

    } catch (error) {
        console.error(error);
        alert("Erreur pendant la simulation.");
    }
}

chargerEtat();

refreshTimer = setInterval(
    chargerEtat,
    15000
);
</script>

</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(HTML)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    global _stop_polling

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if len(sys.argv) < 2:
        print(
            "\nUsage :\n"
            '  python app.py "C:\\chemin\\programme.xlsx" 04/08/2026\n'
        )
        sys.exit(1)

    excel_path = sys.argv[1]

    date_demandee = None

    if len(sys.argv) >= 3:
        try:
            date_demandee = datetime.strptime(
                sys.argv[2],
                "%d/%m/%Y",
            ).strftime("%Y-%m-%d")
        except ValueError:
            print(
                "ERREUR : la date doit être au format JJ/MM/AAAA."
            )
            sys.exit(1)

    try:
        charger_donnees(
            excel_path,
            date_demandee=date_demandee,
        )

    except Exception as exc:
        logging.exception("Impossible de charger le programme.")
        print(f"\nERREUR : {exc}")
        sys.exit(1)

    # Le temps réel est démarré après le chargement du programme.
    demarrer_surveillance()

    date_affichee = etat["date_initiale"]

    print("\n" + "=" * 70)
    print(" APPLICATION PCO TANGER — PRÊTE")
    print("=" * 70)
    print(f"Fichier : {excel_path}")
    print(f"Date affichée : {date_affichee}")
    print(f"Vols : {len(tous_les_vols)}")
    print(f"Postes : {len(stands)}")
    print(f"Dates : {len(dates_programme)}")
    print(f"Interface : http://127.0.0.1:{PORT}")
    print("=" * 70 + "\n")

    try:
        app.run(
            host="127.0.0.1",
            port=PORT,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    finally:
        _stop_polling = True


if __name__ == "__main__":
    main()

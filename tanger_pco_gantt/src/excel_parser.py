"""
excel_parser.py -- Parseur GENERIQUE du programme de vol hebdomadaire ONDA.

Fonctionne sur N'IMPORTE QUEL fichier respectant ce format (colonnes VOL, Type,
Cap, Provenance, H.arr, Destination, H.dep, Hndlr, Obs) -- rien n'est code en
dur pour une semaine particuliere. Le fichier change chaque semaine, ce script
ne change pas : on lui donne un nouveau fichier, il produit une nouvelle liste
de vols, prete a etre passee a optimizer.solve_stand_assignment().
"""

import re
import pandas as pd
from datetime import datetime, timedelta

# --- Referentiels de mapping (deduits du programme reel, a affiner avec le PCO) ---

PREFIXE_COMPAGNIE = {
    "AT": "Royal Air Maroc", "FR": "Ryanair", "3O": "Air Arabia Maroc",
    "IB": "Iberia", "VY": "Vueling", "TO": "Transavia France",
    "AF": "Air France", "HV": "Transavia Netherlands", "U2": "easyJet",
    "DY": "Norwegian", "SN": "Brussels Airlines", "D8": "Norwegian",
    "TB": "TUI Belgium", "RK": "Ryanair UK", "QY": "DHL Cargo",
}

# Compagnies confirmees sans capacite de push-back (Iberia confirmee, 2eme a completer)
COMPAGNIES_SANS_PUSHBACK = {"Iberia"}

# Type d'appareil (colonne "Type") -> taille pour l'optimiseur
TYPE_APPAREIL_TAILLE = {
    "AT7": "petit", "CRK": "petit", "E90": "petit",       # regionaux/petits
    "B738": "moyen", "B737": "moyen", "B7M8": "moyen", "B73H": "moyen",
    "A320": "moyen", "A321": "moyen", "A32N": "moyen", "A21N": "moyen",
    "A223": "moyen", "B734": "moyen",
}

VILLES_MAROCAINES = {
    "casablanca", "agadir", "marrakech", "alhoceima", "rabat", "fes",
    "oujda", "laayoune", "dakhla", "beni-mellal", "béni-mellal", "nador",
}


def _taille_appareil(type_code: str) -> str:
    return TYPE_APPAREIL_TAILLE.get(type_code.strip().upper(), "moyen")


def _est_ville_marocaine(valeur) -> bool:
    if pd.isna(valeur):
        return False
    v = str(valeur).lower()
    return any(ville in v for ville in VILLES_MAROCAINES)


def _compagnie_et_categorie(numero_vol: str, obs: str, provenance, destination):
    premier_segment = numero_vol.split("/")[0]
    match = re.match(r"([A-Z0-9]{2})", premier_segment)
    prefixe = match.group(1) if match else ""
    compagnie = PREFIXE_COMPAGNIE.get(prefixe, f"Compagnie inconnue ({prefixe})")

    obs_clean = (obs or "").strip().lower()
    if "cargo" in obs_clean:
        categorie = "cargo"
    elif _est_ville_marocaine(provenance) or _est_ville_marocaine(destination):
        categorie = "national"
    else:
        categorie = "commercial"

    return compagnie, categorie


def _parse_heure(valeur, jour):
    if pd.isna(valeur):
        return None
    if isinstance(valeur, str):
        m = re.match(r"(\d{1,2}):(\d{2})", valeur.strip())
        if not m:
            return None
        h, mnt = int(m.group(1)), int(m.group(2))
    else:  # deja un datetime.time / datetime
        h, mnt = valeur.hour, valeur.minute
    return jour.replace(hour=h, minute=mnt)


def parse_programme_vol(filepath: str) -> list[dict]:
    """Parse un fichier Excel de programme de vol ONDA (n'importe quelle semaine)
    et retourne une liste de vols au format attendu par optimizer.solve_stand_assignment()."""

    df = pd.read_excel(filepath, header=None)

    header_row_idx = None
    for i, row in df.iterrows():
        if row.astype(str).str.strip().eq("VOL").any():
            header_row_idx = i
            break
    if header_row_idx is None:
        raise ValueError("Impossible de trouver la ligne d'en-tete (colonne 'VOL') dans ce fichier.")

    # Les noms de colonnes ne sont PAS uniques dans ce fichier (plusieurs colonnes
    # vides partagent le nom NaN) -> on travaille par POSITION, pas par nom.
    header = df.iloc[header_row_idx]
    col_pos = {}
    for pos, val in enumerate(header):
        nom = str(val).strip()
        if nom and nom.lower() != "nan":
            col_pos[nom] = pos

    col_hdep_nom = "H.dép" if "H.dép" in col_pos else ("H.dep" if "H.dep" in col_pos else None)
    DATE_COL_POS = 0  # la toute premiere colonne, jamais nommee, contient le jour

    data = df.iloc[header_row_idx + 1:].reset_index(drop=True)

    flights = []
    lignes_ignorees_incompletes = 0
    jour_courant = None

    for _, row in data.iterrows():
        cell_date = row.iloc[DATE_COL_POS]
        if isinstance(cell_date, str) and re.search(r"\d{2}/\d{2}/\d{4}", cell_date):
            m = re.search(r"(\d{2})/(\d{2})/(\d{4})", cell_date)
            if m:
                jour_courant = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))

        numero_vol = row.iloc[col_pos["VOL"]] if "VOL" in col_pos else None
        if pd.isna(numero_vol) or jour_courant is None:
            continue

        numero_vol = str(numero_vol).strip()
        type_appareil = str(row.iloc[col_pos["Type"]]).strip() if "Type" in col_pos else ""
        cap = row.iloc[col_pos["Cap"]] if "Cap" in col_pos else None
        h_arr = row.iloc[col_pos["H.arr"]] if "H.arr" in col_pos else None
        h_dep = row.iloc[col_pos[col_hdep_nom]] if col_hdep_nom else None
        handler = str(row.iloc[col_pos["Hndlr"]]).strip() if "Hndlr" in col_pos else ""
        obs_val = row.iloc[col_pos["Obs"]] if "Obs" in col_pos else None
        obs = "" if pd.isna(obs_val) else str(obs_val).strip()
        provenance = row.iloc[col_pos["Provenance"]] if "Provenance" in col_pos else None
        destination = row.iloc[col_pos["Destination"]] if "Destination" in col_pos else None

        heure_arrivee = _parse_heure(h_arr, jour_courant)
        heure_depart = _parse_heure(h_dep, jour_courant)

        # Correction passage de minuit SUR UNE MEME LIGNE : si l'arrivee et le
        # depart sont tous les deux connus mais que le depart tombe "avant"
        # l'arrivee une fois mis sur le meme jour calendaire, c'est que le
        # depart a en realite lieu apres minuit, le lendemain (ex: arrivee
        # 23h45, depart 00h30 -> le depart est le lendemain, pas le meme jour)
        if heure_arrivee and heure_depart and heure_depart < heure_arrivee:
            heure_depart += timedelta(days=1)

        compagnie, categorie = _compagnie_et_categorie(numero_vol, obs, provenance, destination)
        taille = _taille_appareil(type_appareil)

        flights.append({
            "numero_vol": numero_vol,
            "type_appareil": type_appareil,
            "categorie_appareil": categorie,
            "taille_appareil": taille,
            "capacite": None if pd.isna(cap) else int(cap),
            "provenance": None if pd.isna(provenance) else str(provenance),
            "destination": None if pd.isna(destination) else str(destination),
            "heure_prevue_arrivee": heure_arrivee,   # peut etre None a ce stade
            "heure_prevue_depart": heure_depart,     # peut etre None a ce stade
            "handler": handler,
            "observations": obs,
            "compagnie": compagnie,
            "pushback_disponible": compagnie not in COMPAGNIES_SANS_PUSHBACK,
            "jour": jour_courant,
        })

    flights, lignes_ignorees_incompletes = _reconcilier_et_completer(flights)

    print(f"[excel_parser] {len(flights)} vols extraits, "
          f"{lignes_ignorees_incompletes} ligne(s) ignoree(s) (ni H.arr ni H.dep, aucun rapprochement possible)")
    return flights


def _reconcilier_et_completer(flights_bruts: list[dict]) -> tuple[list[dict], int]:
    """
    Deuxieme passe -- appariement GLOUTON GLOBAL.

    Bug corrige : traiter les arrivees une par une, dans l'ordre du fichier,
    pouvait faire "voler" le bon partenaire d'un vol par un autre vol traite
    avant lui (ex: AT1438 aurait du s'apparier avec AT1439, 40 min d'ecart,
    mais un autre vol traite plus tot avait deja "pris" AT1439, forcant
    AT1438 a se rabattre sur un mauvais candidat 11h plus tard).

    Correction : on liste D'ABORD toutes les paires (arrivee, depart) possibles
    de la meme compagnie, on les trie TOUTES ENSEMBLE par ecart croissant, puis
    on attribue en priorite absolue les paires les plus evidentes (ecart le
    plus petit), quel que soit l'ordre d'origine dans le fichier. Une fois
    qu'une arrivee ou un depart est utilise dans une paire, il n'est plus
    disponible pour une autre paire moins bonne.

    Regles metier confirmees par le PCO pour les vrais restes (aucun partenaire
    trouve) :
      - Arrivee sans depart trouve -> nuitee, poste occupe jusqu'a 8h00 le
        lendemain (plage de nuitee : 21h30 -> 8h00)
      - Depart sans arrivee trouvee -> deja present depuis 21h30 la veille
    """
    completes = [f for f in flights_bruts if f["heure_prevue_arrivee"] and f["heure_prevue_depart"]]
    arrivees_seules = [f for f in flights_bruts if f["heure_prevue_arrivee"] and not f["heure_prevue_depart"]]
    departs_seuls = [f for f in flights_bruts if f["heure_prevue_depart"] and not f["heure_prevue_arrivee"]]
    inexploitables = [f for f in flights_bruts
                       if not f["heure_prevue_arrivee"] and not f["heure_prevue_depart"]]

    ECART_MAX_MINUTES = 30 * 60  # jusqu'à 30h -- permet de traverser minuit

    # --- Etape 1 : lister TOUTES les paires candidates possibles, avec leur écart ---
    paires_candidates = []  # (ecart_minutes, index_arrivee, index_depart)
    for a_idx, arr in enumerate(arrivees_seules):
        for d_idx, dep in enumerate(departs_seuls):
            if dep["compagnie"] != arr["compagnie"]:
                continue  # seule la compagnie doit correspondre, pas le type exact
            ecart = (dep["heure_prevue_depart"] - arr["heure_prevue_arrivee"]).total_seconds() / 60
            if 0 <= ecart <= ECART_MAX_MINUTES:
                paires_candidates.append((ecart, a_idx, d_idx))

    # --- Etape 2 : trier GLOBALEMENT par ecart croissant -- les paires les plus
    # evidentes (ex: 40 min) sont attribuees avant les paires incertaines (ex: 11h) ---
    paires_candidates.sort(key=lambda x: x[0])

    arrivees_appariees = {}   # a_idx -> d_idx
    departs_deja_pris = set()
    arrivees_deja_prises = set()

    for ecart, a_idx, d_idx in paires_candidates:
        if a_idx in arrivees_deja_prises or d_idx in departs_deja_pris:
            continue  # l'un des deux est deja engage dans une meilleure paire
        arrivees_appariees[a_idx] = d_idx
        arrivees_deja_prises.add(a_idx)
        departs_deja_pris.add(d_idx)

    # --- Etape 3 : construire le resultat final ---
    resultat = list(completes)

    for a_idx, arr in enumerate(arrivees_seules):
        if a_idx in arrivees_appariees:
            dep = departs_seuls[arrivees_appariees[a_idx]]
            fusion = dict(arr)
            fusion["heure_prevue_depart"] = dep["heure_prevue_depart"]
            fusion["numero_vol"] = f"{arr['numero_vol']}~{dep['numero_vol']}"
            fusion["hypothese_horaire"] = "fusionne_glouton_global_meilleure_paire"
            resultat.append(fusion)
        else:
            # Aucun partenaire disponible -> nuitee apres arrivee (21h30 -> 8h00)
            arr = dict(arr)
            lendemain = arr["heure_prevue_arrivee"] + timedelta(days=1)
            arr["heure_prevue_depart"] = lendemain.replace(hour=8, minute=0)
            arr["hypothese_horaire"] = "nuitee_apres_arrivee_jusqua_8h_lendemain"
            resultat.append(arr)

    for d_idx, dep in enumerate(departs_seuls):
        if d_idx in departs_deja_pris:
            continue  # deja utilise dans une fusion ci-dessus
        dep = dict(dep)
        veille = dep["heure_prevue_depart"] - timedelta(days=1)
        dep["heure_prevue_arrivee"] = veille.replace(hour=21, minute=30)
        dep["hypothese_horaire"] = "deja_present_depuis_21h30_veille"
        resultat.append(dep)

    for f in completes:
        f.setdefault("hypothese_horaire", None)

    return resultat, len(inexploitables)


if __name__ == "__main__":
    import sys
    filepath = sys.argv[1] if len(sys.argv) > 1 else "programme.xlsx"
    flights = parse_programme_vol(filepath)
    print(f"\n{len(flights)} vols extraits de {filepath}\n")
    for f in flights[:8]:
        print(f"{f['numero_vol']:<14} {f['compagnie']:<20} {f['categorie_appareil']:<10} "
              f"{f['taille_appareil']:<6} {f['heure_prevue_arrivee']} -> {f['heure_prevue_depart']}"
              f"{'  [' + f['hypothese_horaire'] + ']' if f['hypothese_horaire'] else ''}")
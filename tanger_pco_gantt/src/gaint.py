"""
gantt_view.py -- Diagramme de Gantt interactif, axes inverses (postes en X,
heures en Y), couvrant TOUTE la semaine du fichier avec un curseur de
navigation temporelle. Inclut une fonction de reaffectation manuelle pour
gerer les retards/rotations en respectant la disponibilite reelle.

Base entierement sur les vraies donnees (excel_parser.py + stands_config.py).

Usage :
    python gantt_view.py "fichier.xlsx"
    -> genere gantt_semaine.html (toute la semaine, navigable)
"""

import sys
from datetime import timedelta
import plotly.graph_objects as go

from excel_parser import parse_programme_vol
from standconfig import generate_parking_stands
from optimizer import solve_stand_assignment, BUFFER_MINUTES
from reoptimization import reoptimiser_apres_retard

ORDRE_POSTES = ["N8", "N7", "N6", "N5", "N4", "N3", "N2", "N1",
                 "E7", "E6", "E5", "E4", "E3", "E2", "E1"]

COULEUR_PAR_CATEGORIE = {
    "commercial": "#4C8BF5",
    "national": "#34A853",
    "cargo": "#9C27B0",
    "prive": "#FF9800",
}


def calculer_semaine_complete(fichier):
    """Charge tout le fichier et affecte les postes jour par jour, retourne
    la liste consolidee des vols + leurs affectations sur toute la semaine."""
    tous_les_vols = parse_programme_vol(fichier)
    stands = generate_parking_stands()

    jours = sorted(set(f["heure_prevue_arrivee"].date() for f in tous_les_vols) |
                    set(f["heure_prevue_depart"].date() for f in tous_les_vols))

    tous_resultats = []
    tous_non_places = []
    vols_by_num = {}

    for jour in jours:
        vols_du_jour = [f for f in tous_les_vols
                         if f["heure_prevue_arrivee"].date() == jour or f["heure_prevue_depart"].date() == jour]
        if not vols_du_jour:
            continue
        results, status, non_places = solve_stand_assignment(vols_du_jour, stands, permettre_non_affectation=True)
        for f in vols_du_jour:
            vols_by_num[f["numero_vol"]] = f
        tous_resultats.extend(results)
        tous_non_places.extend(non_places)

    return tous_resultats, tous_non_places, vols_by_num, stands, tous_les_vols


def construire_gantt(results, non_places, vols_by_num, titre="Planning complet"):
    """Construit le Gantt AXES INVERSES : postes en X (horizontal), heures en Y (vertical).
    Navigation entre les jours via des boutons (le rangeslider Plotly n'existe
    que sur l'axe X, pas Y -- on obtient le meme resultat autrement)."""
    fig = go.Figure()

    for categorie, couleur in COULEUR_PAR_CATEGORIE.items():
        sous_ensemble = [r for r in results
                          if vols_by_num.get(r["numero_vol"], {}).get("categorie_appareil") == categorie]
        if not sous_ensemble:
            continue

        fig.add_trace(go.Bar(
            x=[r["poste_assigne"] for r in sous_ensemble],
            y=[(r["heure_depart"] - r["heure_arrivee"]).total_seconds() * 1000 for r in sous_ensemble],
            base=[r["heure_arrivee"] for r in sous_ensemble],
            name=categorie,
            marker_color=couleur,
            text=[r["numero_vol"] for r in sous_ensemble],
            textposition="inside",
            hovertext=[
                f"{r['numero_vol']}<br>{vols_by_num.get(r['numero_vol'], {}).get('compagnie', '')}<br>"
                f"{r['heure_arrivee'].strftime('%a %d/%m %H:%M')} -> {r['heure_depart'].strftime('%a %d/%m %H:%M')}"
                for r in sous_ensemble
            ],
            hoverinfo="text",
        ))

    # Boutons de navigation : un par jour + "Semaine complete"
    jours_presents = sorted(set(r["heure_arrivee"].date() for r in results))
    boutons = [dict(
        label="Semaine complete",
        method="relayout",
        args=[{"yaxis.autorange": True}],
    )]
    for jour in jours_presents:
        debut_jour = jour.strftime("%Y-%m-%d")
        fin_jour = (jour + timedelta(days=1)).strftime("%Y-%m-%d")
        boutons.append(dict(
            label=jour.strftime("%a %d/%m"),
            method="relayout",
            args=[{"yaxis.range": [debut_jour, fin_jour], "yaxis.autorange": False}],
        ))

    fig.update_layout(
        title=f"{titre} -- {len(results)} vols places, {len(non_places)} en attente"
              + (f" : {', '.join(non_places)}" if non_places else ""),
        barmode="overlay",
        xaxis=dict(
            title="Poste de stationnement",
            categoryorder="array", categoryarray=ORDRE_POSTES,
        ),
        yaxis=dict(
            title="Date / Heure",
            type="date",
        ),
        updatemenus=[dict(
            type="dropdown", direction="down", showactive=True,
            x=1.0, xanchor="right", y=1.15, yanchor="top",
            buttons=boutons,
        )],
        height=750,
        legend_title="Categorie de vol",
        font=dict(size=12),
    )

    return fig


def changer_poste_manuellement(numero_vol, nouveau_poste, all_flights, stands, results):
    """
    Reaffecte manuellement un vol a un nouveau poste (retard, rotation, decision
    de l'agent) EN VERIFIANT la disponibilite reelle -- pas de chevauchement.

    Le recalcul est limite a la JOURNEE du vol concerne (pas toute la semaine) :
    chaque jour est optimise independamment dans le planning hebdomadaire, donc
    verifier toute la semaine d'un coup peut declencher de faux conflits aux
    frontieres entre deux journees. Un retard un mardi n'a de toute facon aucune
    raison de remettre en cause le planning du dimanche.

    Retourne (resultats_complets_mis_a_jour, vols_touches, vols_non_places).
    """
    vol = next((f for f in all_flights if f["numero_vol"] == numero_vol), None)
    if vol is None:
        raise ValueError(f"Vol {numero_vol} introuvable")

    jour_concerne = vol["heure_prevue_arrivee"].date()

    # On isole les vols et resultats de CETTE journee uniquement
    vols_jour = [f for f in all_flights
                 if f["heure_prevue_arrivee"].date() == jour_concerne
                 or f["heure_prevue_depart"].date() == jour_concerne]
    numeros_jour = {f["numero_vol"] for f in vols_jour}
    resultats_jour = [r for r in results if r["numero_vol"] in numeros_jour]
    resultats_autres_jours = [r for r in results if r["numero_vol"] not in numeros_jour]

    nouveaux_resultats_jour, vols_touches, vols_non_places = reoptimiser_apres_retard(
        vols_jour, stands, resultats_jour, numero_vol
    )

    resultats_complets = resultats_autres_jours + nouveaux_resultats_jour
    return resultats_complets, vols_touches, vols_non_places


def main():
    if len(sys.argv) < 2:
        print("Usage : python gantt_view.py FICHIER.xlsx")
        return

    fichier = sys.argv[1]
    print(f"Chargement de {fichier} et calcul de toute la semaine...")
    results, non_places, vols_by_num, stands, tous_les_vols = calculer_semaine_complete(fichier)

    print(f"\n{len(results)} vols places sur la semaine, {len(non_places)} non places")
    if non_places:
        print(f"  -> {non_places}")

    fig = construire_gantt(results, non_places, vols_by_num)
    fig.write_html("gantt_semaine.html")
    print("\nDiagramme genere : gantt_semaine.html")
    print("Utilise le menu deroulant en haut a droite du graphique pour naviguer entre les jours.")


if __name__ == "__main__":
    main()
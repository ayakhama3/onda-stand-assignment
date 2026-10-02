"""
daily_gantt.py -- Vue Gantt journaliere, pour l'exploitation operationnelle du PCO.

Reutilise les memes constantes que gantt_view.py (ORDRE_POSTES,
COULEUR_PAR_CATEGORIE) -- un seul modele de couleurs/ordre des postes pour
les deux vues (semaine + jour), pas de duplication.

100% base sur les memes donnees reelles que le Gantt hebdomadaire -- aucun
nouveau jeu de donnees, aucune donnee inventee.
"""

from datetime import timedelta
import plotly.graph_objects as go

from gaint import ORDRE_POSTES, COULEUR_PAR_CATEGORIE


def filtrer_par_date(results, date_cible):
    """
    Vols dont l'arrivee OU le depart tombe le jour cible.

    IMPORTANT : un vol dont l'arrivee et le depart sont sur deux dates
    differentes (nuitee) est conserve des qu'UNE des deux dates correspond --
    il n'est jamais supprime pour cause de dates differentes.
    """
    return [r for r in results
            if r["heure_arrivee"].date() == date_cible or r["heure_depart"].date() == date_cible]


def create_daily_gantt(results, vols_by_num, date_cible, alertes_par_vol=None):
    """
    results : liste d'affectations {numero_vol, poste_assigne, heure_arrivee, heure_depart, ...}
    vols_by_num : {numero_vol: vol_dict} (compagnie, categorie_appareil, etc.)
    date_cible : datetime.date -- le jour a afficher
    alertes_par_vol : optionnel, {numero_vol: "texte alerte"} pour enrichir le survol

    Retourne une figure Plotly exploitable directement par write_html() (usage
    autonome en script) ou par fig.to_json() / fig.to_dict() (usage Flask, API).
    """
    alertes_par_vol = alertes_par_vol or {}
    vols_du_jour = filtrer_par_date(results, date_cible)

    fig = go.Figure()

    for categorie, couleur in COULEUR_PAR_CATEGORIE.items():
        sous_ensemble = [r for r in vols_du_jour
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
                f"{r['numero_vol']}<br>"
                f"{vols_by_num.get(r['numero_vol'], {}).get('compagnie', '')}<br>"
                f"Poste {r['poste_assigne']}<br>"
                f"{r['heure_arrivee'].strftime('%H:%M')} -> {r['heure_depart'].strftime('%H:%M')}"
                + (f"<br><b>{alertes_par_vol[r['numero_vol']]}</b>" if r["numero_vol"] in alertes_par_vol else "")
                for r in sous_ensemble
            ],
            hoverinfo="text",
        ))

    fig.update_layout(
        title=f"Journee du {date_cible.strftime('%d/%m/%Y')} -- {len(vols_du_jour)} vol(s)",
        barmode="overlay",
        xaxis=dict(title="Poste de stationnement", categoryorder="array", categoryarray=ORDRE_POSTES),
        yaxis=dict(
            title="Heure", type="date",
            range=[date_cible.isoformat(), (date_cible + timedelta(days=1)).isoformat()],
        ),
        height=700,
        legend_title="Categorie de vol",
        font=dict(size=12),
    )

    return fig


def table_journee(results, vols_by_num, date_cible, etat_vols=None):
    """
    Version tabulaire de la meme journee (liste de dicts), pour l'affichage
    operationnel detaille : arrivee, depart, compagnie, poste, duree,
    categorie, retard eventuel, etat/alerte.
    """
    etat_vols = etat_vols or {}
    vols_du_jour = sorted(filtrer_par_date(results, date_cible), key=lambda x: x["heure_arrivee"])

    lignes = []
    for r in vols_du_jour:
        vol = vols_by_num.get(r["numero_vol"], {})
        duree_min = int((r["heure_depart"] - r["heure_arrivee"]).total_seconds() / 60)
        info = etat_vols.get(r["numero_vol"], {})
        lignes.append({
            "numero_vol": r["numero_vol"],
            "compagnie": vol.get("compagnie", ""),
            "categorie": vol.get("categorie_appareil", ""),
            "poste_assigne": r["poste_assigne"],
            "heure_arrivee": r["heure_arrivee"].isoformat(),
            "heure_depart": r["heure_depart"].isoformat(),
            "duree_minutes": duree_min,
            "ecart_minutes": info.get("ecart_minutes"),
            "statut_temps_reel": info.get("statut", "prevu"),
        })
    return lignes


if __name__ == "__main__":
    import sys
    from datetime import datetime
    from gaint import calculer_semaine_complete

    if len(sys.argv) < 3:
        print("Usage : python daily_gantt.py FICHIER.xlsx JJ/MM/AAAA")
    else:
        fichier = sys.argv[1]
        date_cible = datetime.strptime(sys.argv[2], "%d/%m/%Y").date()
        results, non_places, vols_by_num, stands, tous_les_vols = calculer_semaine_complete(fichier)
        fig = create_daily_gantt(results, vols_by_num, date_cible)
        nom = f"gantt_jour_{date_cible.strftime('%d-%m-%Y')}.html"
        fig.write_html(nom)
        print(f"Diagramme journalier genere : {nom} ({len(filtrer_par_date(results, date_cible))} vols)")
"""
stands_config.py -- Configuration REELLE des postes de stationnement de Tanger.

Contrairement a data_generator.py (qui contient aussi des vols FICTIFS pour
tester sans fichier Excel), ce module ne contient QUE la vraie configuration
des postes, confirmee par le PCO. Aucune donnee inventee ici.
"""

def generate_parking_stands():
    """Postes reels, confirmes par le PCO.

    Disposition physique gauche -> droite :
      N8 . N7 . N6 . N5 . N4 . N3   (commercial)
      N2 . N1                       (multi lourd : poids lourd, national, cargo lourd)
      E7 . E6 . E5 . E4 . E3 . E2 . E1   (E7/E1 = eco_grand, E6-E2 = eco_petit)
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
            "categorie": categorie,
            "voisin_gauche": voisin_gauche,
            "latitude": 35.7269,
            "longitude": -5.9169,
        })
    return stands
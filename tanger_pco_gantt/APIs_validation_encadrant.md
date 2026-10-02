# Validation des sources de données externes
### Système de Gantt de stationnement optimisé — PCO, Aéroport Tanger Ibn Battouta

Document de confirmation à valider avec l'encadrant avant intégration technique.

---

## Tableau de synthèse

| Source | Données couvertes | Rôle dans le projet | Justification du choix | Accès / Coût | Fréquence d'usage |
|---|---|---|---|---|---|
| **OpenSky Network** | Position GPS (latitude/longitude), altitude barométrique, vitesse sol, cap, statut sol/vol, identifiant transpondeur (`icao24`) constant, indicatif d'appel (callsign), horodatage de dernière position | **Source principale de suivi temps réel.** Détecte les atterrissages/décollages, permet de suivre un même avion à travers ses rotations successives (le `icao24` ne change jamais, contrairement au numéro de vol) | Quota quotidien largement suffisant (4 000 à 8 000 crédits/jour) pour un polling continu, contrairement aux alternatives. Couverture correcte sur le Maroc/Europe. Gratuit pour usage non-commercial/recherche, adapté à un projet de stage | Compte gratuit, authentification OAuth2 (`client_id` / `client_secret`) | Continu — interrogation toutes les 2 à 5 minutes |
| **airplanes.live** | Mêmes champs qu'OpenSky (position, altitude, vitesse, statut sol/vol, `icao24`), format compatible ADS-B Exchange | **Source de secours.** Prend automatiquement le relais si OpenSky est temporairement indisponible, pour garantir la continuité du suivi | Aucune inscription ni clé requise — activable immédiatement, aucune démarche administrative. Réseau ADS-B communautaire indépendant, données non filtrées | Gratuit, accès public, aucune clé | En secours uniquement — activé si OpenSky ne répond pas |
| **AviationStack** | Numéro de vol, compagnie, statut officiel (prévu/actif/atterri/**annulé**), horaires programmés vs réels (departure/arrival), aéroport, terminal | **Vérification ponctuelle du statut officiel**, en particulier pour confirmer une annulation — donnée qu'OpenSky ne peut pas fournir (l'absence de position ne prouve pas à elle seule une annulation) | Seule source disponible donnant un statut explicite "annulé" plutôt qu'une simple absence de signal. Utilisée avec parcimonie du fait de son quota restreint | Clé API gratuite — **100 requêtes/mois seulement** | Ponctuel — quelques appels par jour maximum, jamais en polling continu |
| **Open-Meteo** | Température, précipitations, vent, visibilité, prévisions horaires et historique météo | **Variable de contexte optionnelle**, pour documenter si un retard coïncide avec des conditions météo dégradées | Gratuit sans clé, aucune contrainte de quota — s'ajoute sans risque au système | Aucune inscription, aucune clé | Optionnel, faible fréquence |

---

## Points nécessitant confirmation de l'encadrant

1. **Validation du choix architectural** : le suivi temps réel repose sur la position ADS-B (OpenSky + secours), pas sur un service de statut commercial — êtes-vous d'accord avec cette approche ?
2. **AviationStack** : le quota de 100 requêtes/mois est-il suffisant pour vos besoins de vérification ponctuelle, ou faut-il envisager une alternative payante si le volume d'annulations à vérifier est important ?
3. Aucune de ces sources n'accède à un système interne ONDA (SOAM, ivMS-4200) — confirmation que cette approche respecte les contraintes de confidentialité définies en amont ?

## Note technique

Ni l'exécution de code ni les outils de récupération web utilisés pour préparer ce document n'ont pu atteindre ces services depuis l'environnement de développement (accès réseau restreint aux registres de paquets logiciels). La validation de connectivité effective a été faite en local, hors de cet environnement.

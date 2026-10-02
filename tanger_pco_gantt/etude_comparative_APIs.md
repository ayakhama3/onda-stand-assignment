# Étude comparative des APIs de suivi de vol temps réel
### Pour le module PCO — Gantt de stationnement, Aéroport Tanger Ibn Battouta

Document de travail pour analyse de choix technique — toutes les données ont été vérifiées par recherche web au moment de la rédaction (juillet 2026), les tarifs peuvent évoluer.

---

## 1. Les trois familles de sources — comprendre avant de comparer

Toutes les APIs de "suivi de vol" ne se valent pas car elles ne font pas le même métier :

| Famille | Fonctionnement | Exemples |
|---|---|---|
| **ADS-B brut (recherche/communautaire)** | Écoute directe des signaux radio émis par les avions (position, altitude, vitesse). Aucune notion de "programme de vol" ou de compagnie — juste des faits physiques bruts | OpenSky Network, ADS-B Exchange, adsb.fi, airplanes.live |
| **Agrégateur commercial (statut de vol)** | Combine ADS-B + données compagnies + systèmes aéroportuaires pour produire un "statut" (prévu/retardé/annulé), avec horaires programmés | AviationStack, AeroDataBox, Aviation Edge, SkyLink API |
| **Plateforme opérationnelle premium** | Agrégateur + historique profond + ETA prédictifs par machine learning + alertes en streaming | FlightAware AeroAPI/Firehose, Cirium, FlightRadar24 API (entreprise) |

---

## 2. Tableau comparatif détaillé

| API | Type | Attributs fournis | Points forts | Points faibles | Accès / Tarif | Fréquence réaliste |
|---|---|---|---|---|---|---|
| **OpenSky Network** | ADS-B brut | Position (lat/lon), altitude barométrique, vitesse sol, cap, statut sol/vol, `icao24`, callsign, horodatage | Gratuit pour usage recherche/non-commercial, quota généreux (~4000-8000 crédits/jour), couverture correcte Europe/Maroc, historique disponible | Pas de "statut" de vol (annulé/retardé) explicite, pas de programme futur, licence non-commerciale (bloquant si le projet devient un produit vendu), pas de garantie de disponibilité (SLA) | Gratuit, inscription + OAuth2 | Continu, 2-5 min |
| **ADS-B Exchange** | ADS-B brut communautaire | Mêmes champs qu'OpenSky, données non filtrées (n'applique pas les listes de blocage que d'autres respectent) | Données brutes non censurées, bon pour dashboards custom via JSON | Accès API principalement via RapidAPI, plans payants pour usage soutenu | Payant au-delà d'un usage minimal (RapidAPI) | Continu si abonné |
| **adsb.fi** | ADS-B brut communautaire | Similaire à OpenSky/ADS-B Exchange | Gratuit, aucune clé, bon débit | Communauté plus petite, couverture variable | Gratuit, sans clé | Continu |
| **airplanes.live** | ADS-B brut communautaire | Position, altitude, vitesse, callsign — format compatible ADS-B Exchange v2 | **Aucune inscription ni clé requise**, activable immédiatement | Service communautaire bénévole, pas de SLA, couverture dépendante des récepteurs volontaires | Gratuit, aucune clé | Continu — déjà intégré dans notre code |
| **AviationStack** | Agrégateur commercial | Numéro de vol, statut, aéroport, horaires programmés/réels, compagnie, plus 10 endpoints annexes (aéroports, compagnies, taxes...) | Documentation simple, bon pour prototypage rapide, statut "annulé" explicite | **100 requêtes/mois en free tier réel** — inutilisable en polling continu ; tarifs payants jusqu'à 499,99 $/mois pour un usage soutenu | Clé gratuite (très limitée) à 499,99 $/mois | Ponctuel uniquement en gratuit |
| **AeroDataBox** | Agrégateur commercial | Statut de vol, horaires, aéroports, données avion — API-first | Meilleur rapport qualité/quota gratuit qu'AviationStack pour un usage hobby/étudiant, cité comme "budget-friendly" dans les comparatifs 2026 | Moins connu, documentation moins étoffée qu'AviationStack | Freemium, quota gratuit plus généreux qu'AviationStack | Usage modéré possible |
| **Aviation Edge** | Agrégateur commercial | Référentiels riches (compagnies, aéroports, avions, villes) + suivi temps réel + horaires aéroportuaires, données sourcées auprès d'autorités officielles | Bonnes données de référence statiques | **Aucun tier gratuit**, pas de météo aviation décodée | Payant dès le départ | Selon abonnement |
| **SkyLink API** | Agrégateur commercial unifié | Position ADS-B + météo + aéroports en une seule API | Tier gratuit 1000 req/mois (plus généreux qu'AviationStack), pensé pour agents IA (serveur MCP disponible) | Produit récent, moins établi que les autres, positionnement data limité comparé à un vrai flux ADS-B | Gratuit 1000 req/mois, payant dès 18,59 $/mois | Usage modéré |
| **FlightAware AeroAPI** | Plateforme premium | Position, statut, historique depuis 2011, **ETA prédictifs par ML (Foresight)**, alertes en temps réel sur événements (atterrissage, décollage, déroutement) | La référence en fiabilité opérationnelle, ETA prédictifs déjà calculés (pas besoin de les recalculer soi-même), plus de 60 endpoints | Facturation à l'usage complexe à anticiper, "tier gratuit" = seulement 5 $ de crédit/mois, coûteux à l'échelle | Usage-based, ~5 $/mois de crédit gratuit puis facturation à la requête | Excellent mais coûteux en continu |
| **FlightRadar24 API** | Plateforme premium entreprise | Équivalent FlightAware, couverture mondiale reconnue | Marque la plus connue, données de référence dans l'industrie | **Aucun tarif public, accès entreprise/devis uniquement** — hors de portée d'un projet étudiant | Sur devis (entreprise) | Non applicable pour ce projet |
| **Amadeus API** | Données de réservation/tarifs | Inventaire de réservation, tarifs — **pas du suivi position temps réel** | Standard de l'industrie pour la billetterie | Hors sujet pour notre besoin (ce n'est pas un outil de tracking ADS-B) | — | Non applicable |

---

## 3. Ce qui distingue vraiment ces APIs pour NOTRE cas d'usage précis

Notre besoin : suivre en continu la position réelle des avions pour calculer un ETA, sans dépendre d'un accès interne (SOAM), avec un budget étudiant (0 €).

| Critère | Gagnant | Pourquoi |
|---|---|---|
| Coût pour un usage continu | OpenSky / airplanes.live / adsb.fi | Seules options réellement gratuites sans limite bloquante pour du polling toutes les 2-5 min |
| Fiabilité / réputation académique | OpenSky Network | Cité dans la littérature de recherche aéronautique, données ouvertes pour la recherche |
| Simplicité d'accès immédiate | airplanes.live | Aucune inscription, testable en une commande |
| Statut "annulé" explicite | AviationStack ou AeroDataBox | Seule info qu'aucune source ADS-B brute ne peut donner (absence de signal ≠ annulation prouvée) |
| ETA déjà calculé par le fournisseur (pas à coder soi-même) | FlightAware AeroAPI | Mais coût incompatible avec un usage continu étudiant |

---

## 4. Ce qu'aucune de ces APIs ne peut faire (à garder en tête)

Aucune de ces sources — même les payantes — ne peut détecter automatiquement : un changement de rotation décidé en interne par la compagnie, une panne technique, ou un vol cargo ajouté à la dernière minute sans plan de vol déposé publiquement. Ces cas restent du ressort d'une saisie manuelle par l'agent (champ "observations" du programme), quel que soit le budget mis dans les APIs.

## 5. Ressource pour approfondir toi-même

Si tu veux creuser un fournisseur en particulier avant de trancher, voici où regarder en priorité pour chacun : la page "pricing" officielle (les chiffres évoluent vite dans ce secteur), et les comparatifs indépendants publiés courant 2026 qui recoupent plusieurs fournisseurs sur les mêmes critères (latence, disponibilité, coût réel) plutôt que le discours marketing de chaque site.

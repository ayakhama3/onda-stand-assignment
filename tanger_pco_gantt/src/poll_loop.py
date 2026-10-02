
from datetime import datetime
from realtime_tracking import match_state_to_flight, compute_eta, SEUIL_ALERTE_MINUTES


class FlightStateStore:
    def __init__(self):
        self._last_on_ground = {}

    def was_on_ground(self, numero_vol: str):
        return self._last_on_ground.get(numero_vol)

    def update(self, numero_vol: str, on_ground: bool):
        self._last_on_ground[numero_vol] = on_ground


def run_polling_cycle(states, expected_flights, now, store):
    events = []

    for state in states:
        flight = match_state_to_flight(state, expected_flights)
        if flight is None:
            continue

        numero_vol = flight["numero_vol"]
        on_ground_now = bool(state.get("on_ground"))
        was_on_ground = store.was_on_ground(numero_vol)

        if on_ground_now and not was_on_ground:
            events.append({
                "type": "arrivee_confirmee",
                "numero_vol": numero_vol,
                "heure_arrivee_reelle": now,
                "heure_prevue": flight["heure_arrivee_prevue"],
            })
        elif not on_ground_now:
            eta = compute_eta(state, now)
            if eta is not None:
                ecart = (eta - flight["heure_arrivee_prevue"]).total_seconds() / 60
                events.append({
                    "type": "eta_mise_a_jour",
                    "numero_vol": numero_vol,
                    "eta_calculee": eta,
                    "ecart_minutes": round(ecart, 1),
                })
                if abs(ecart) >= SEUIL_ALERTE_MINUTES:
                    events.append({
                        "type": "alerte_retard" if ecart > 0 else "alerte_avance",
                        "numero_vol": numero_vol,
                        "ecart_minutes": round(ecart, 1),
                        "eta_calculee": eta,
                    })

        store.update(numero_vol, on_ground_now)

    return events

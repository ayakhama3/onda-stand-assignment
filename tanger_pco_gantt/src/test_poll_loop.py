from poll_loop import FlightStateStore, run_polling_cycle
from datetime import datetime, timedelta

store = FlightStateStore()
expected_flights = [
    {"numero_vol": "AT1050", "heure_arrivee_prevue": datetime(2026, 7, 13, 14, 30)},
]

t0 = datetime(2026, 7, 13, 14, 0)

scenarios = [
    (0,  38.0,   -5.9,   220, False),
    (1,  37.5,   -5.9,   220, False),
    (2,  37.0,   -5.9,   220, False),
    (10, 35.75,  -5.92,  40,  False),
    (11, 35.727, -5.917, 0,   True),
    (12, 35.727, -5.917, 0,   True),
    (13, 35.727, -5.917, 0,   True),
]

for minute, lat, lon, vel, on_ground in scenarios:
    now = t0 + timedelta(minutes=minute)
    states = [{"callsign": "RAM1050", "latitude": lat, "longitude": lon,
               "velocity": vel, "on_ground": on_ground}]
    events = run_polling_cycle(states, expected_flights, now, store)
    print(f"--- Cycle minute {minute} ---")
    if not events:
        print("  (aucun evenement)")
    for e in events:
        print(f"  -> {e['type']}: {e}")

print("Fin du test")
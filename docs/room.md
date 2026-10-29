# Monitored room

Living room, measured 2026-10-21. Photos stay local in `room_pics/` (gitignored); this file is the reference for
the analysis (air volume) and the dashboard's 3D model.

## Geometry

| Quantity | Value |
|---|---|
| Length × width | 6.5 m × 4.0 m (floor area 26 m²) |
| Ceiling height | 2.40–2.50 m (2.45 m used) |
| Air volume | ≈ 64 m³ (room only; see the door below) |
| Internal door | in the wall opposite the balcony, in the corner by the couch; opens into the room, hinges on the couch-wall side, rests against that wall; almost never closed; glazed side panel and a radiator next to it (photo 2026-10-22) |
| Balcony screen | on the long (6.5 m) outside wall: double French doors (handle and lock on the right leaf) between two tall side panels, each fixed glass below and an opening window above; curtains. Widths estimated from a photo [open: measure] |
| Fireplace | middle of a short (4 m) wall, adjacent to the balcony wall |
| Floor | wooden planks running parallel to the balcony wall |
| Wall vent | grille near the ceiling beside the French doors |

The internal door is usually open, so the room exchanges air with the hallway. CO2 decay and moisture balances then
describe the room plus part of the house, not 64 m³ alone. The door is almost never closed, so this holds nearly always.

## Features relevant to moisture

- **Ceiling stain** near the wall-to-ceiling junction (tide-mark rings). Tide marks usually come from liquid water
  (leak from above or roof) rather than condensation; confirm the cause before reading it as a mould signal [open].
- Narrow window behind the hanging rug, left of the balcony screen: fabric over cold glass traps moist air against
  it, a likely condensation spot [assumed] [open: does it open?].
- Fireplace with mantel (type and whether the chimney is open [open]).
- Radiators: one beside the internal door, one on the end wall by the shoe rack.
- Laundry dries in another room; it can still raise this room's humidity through the open door.

## Furniture (for the 3D model)

Desk in the corner by the balcony wall and the fireplace wall, facing the balcony (monitor, microcontrollers, the
room node). Couch in the middle facing a table with a TV.

## Building and heating (answers 2026-10-22)

- **Outside wall:** only the balcony wall (the long wall with the French doors) faces outside. All other walls are
  internal, so the wall probe goes on this wall. Compass direction [open: phone compass, facing out of the balcony].
- **Above the room:** another floor (rooms and a corridor), not a roof. The ceiling tide marks are therefore more
  likely a leak from above than roof water [assumed]; the junction of the balcony wall with the ceiling and floor
  slabs is still a likely cold spot (slab edges are typical thermal bridges) [assumed].
- **Heating:** electric central heating with the two radiators, on a timer (not set up yet); hot water from a
  separate boiler.
- **Wall probe:** taped in the top corner of the right-hand side window's plastered reveal, by the desk, about
  30 cm left of the wall vent (2026-10-22). The vent's slider position changes the draught at
  that corner: keep it as it normally is, and note it if it is changed.

## Still needed

- Where each sensor sits (filled in when mounted); candidate spots for the wall probe in `docs/hardware.md`
- Widths of the doors and side panels, and whether the window behind the rug opens [open]

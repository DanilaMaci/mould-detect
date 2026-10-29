// The monitored room as data (dimensions from docs/room.md, metres). The 3D scene, labels and panels are built
// from this file: add a sensor, a piece of furniture or a hotspot here rather than in the scene code.
//
// Axes: origin at the floor centre, y up. x runs along the balcony (back) wall, left to right as seen from inside;
// z points from the balcony wall into the room. The cutaway shows the floor, the balcony wall (z = -width/2) and
// the fireplace wall on its right (x = +length/2).

export const ROOM = {
  name: 'Living room',
  length: 6.5,          // x: balcony wall
  width: 4.0,           // z: fireplace wall
  height: 2.45,
  wallThickness: 0.14,

  // Balcony wall: outside wall. x is the opening's centre along the wall. The balcony screen (photo 2026-10-22) is
  // double French doors between two tall side panels; each panel is fixed glass below and an opening casement above
  // `split` (handle on the side towards the doors). Widths estimated from the photo [assumed: measure].
  backWall: {
    openings: [
      { id: 'narrowWindow', x: -2.15, width: 0.45, height: 2.0, sill: 0.15, coveredByRug: true },
      { id: 'sideWindowLeft', x: -1.325, width: 0.45, height: 2.1, sill: 0, split: 0.88, handle: 'right' },
      { id: 'frenchDoors', x: -0.45, width: 1.3, height: 2.1, sill: 0 },
      { id: 'sideWindowRight', x: 0.425, width: 0.45, height: 2.1, sill: 0, split: 0.88, handle: 'left' },
    ],
  },

  // The front wall (opposite the balcony, z = +width/2) and the couch's wall (x = -length/2) are cut away; they are
  // drawn as low cut walls of this height so the door and its state read clearly.
  cutWallHeight: 0.3,

  // Room door in the front wall, in the corner by the couch (photo 2026-10-22): opens into the room with its hinges
  // on the couch-wall side ('left' = -x), resting against that wall when open. x = centre of the doorway.
  // A glazed side panel and a radiator follow towards +x. Widths estimated [assumed: measure].
  door: { x: -2.73, width: 0.8, hinge: 'left' },

  // Electric radiators: the one beside the door (photo); the second ("end wall by the shoe rack") is not placed yet.
  // Heating schedule (06–07 and 21–22) as planned, not running yet: used for the radiator animation only.
  heating: {
    radiators: [{ x: -1.25, width: 0.7, height: 0.5 }],   // against the front wall
    schedule: [[6, 7], [21, 22]],
  },

  // Compass bearing the balcony faces (for the sun's direction) [assumed: south until checked with a compass]
  balconyFacingDeg: 180,

  // DS18B20 probes. Wall: taped in the top corner of the right-hand side window's plastered reveal, next to the wall
  // vent (photos setup1/3_v1, 2026-10-22). Outdoor: in a radiation shield on the balcony, `out` metres from the wall, its cable coming in through
  // the hinge side of the right-hand side window.
  probes: { wall: { x: 0.69, y: 2.06 }, outdoor: { x: 1.1, y: 1.2, out: 0.25 } },

  // Fireplace wall: the fireplace sits in the middle
  rightWall: {
    fireplace: { z: 0, width: 1.35, height: 1.15 },
  },

  // Footprints: x, z = centre; size = [along local x, along local z] in metres; rotationY in radians
  // (multiples of 90°). tests/room-model.test.js checks that nothing overlaps.
  furniture: {
    desk: { x: 2.53, z: -1.62, size: [1.4, 0.6], rotationY: 0 },               // IKEA desk in the corner, facing the
                                                                                 // balcony; 5-shelf unit on its right
    chair: { x: 2.33, z: -0.86, size: [0.68, 0.82], rotationY: 0 },            // IKEA Poäng, facing the desk
    guitars: { x: -2.85, z: -1.8, size: [0.76, 0.3], rotationY: 0 },          // left of the balcony doors
    couch: { x: -2.77, z: 0.15, size: [2.0, 0.85], rotationY: -Math.PI / 2 },   // opposite the fireplace, facing it;
                                                                                 // its end just clears the open door
    mediaTable: { x: -0.95, z: 0.35, size: [1.3, 0.6], rotationY: -Math.PI / 2 }, // TV and PS5, screen towards the couch
    sideTable: { x: 2.98, z: 1.25, size: [0.45, 0.45], rotationY: 0 },        // 3D printer, beside the fireplace
  },

  // Easter egg: the 2-wheel LiDAR robot, driving an ellipse around the media table
  robot: { center: [-0.95, 0.35], radiusX: 0.85, radiusZ: 1.05, speed: 0.22, radius: 0.1 },

  // Supabase device_id per data stream
  devices: { room: 'node1' },

  // Clickable things: where the floating tag sits and where the camera flies to when selected
  hotspots: {
    climate: {
      title: 'Room node',
      subtitle: 'BME280 · temperature, humidity, pressure',
      anchor: [2.08, 1.3, -1.5],
      view: { position: [-0.1, 1.95, 1.3], target: [2.1, 0.9, -1.5] },
    },
    co2: {
      title: 'CO₂ sensor',
      subtitle: 'SCD-40 · CO₂ with its own temperature and humidity',
      anchor: [2.55, 1.65, -1.45],
      view: { position: [0.4, 1.9, 1.3], target: [2.5, 0.9, -1.5] },
    },
    outdoor: {
      title: 'Outside',
      subtitle: 'Balcony probe and Open-Meteo hourly weather',
      anchor: [-0.45, 2.3, -1.95],
      view: { position: [0.5, 2.2, 2.6], target: [-0.45, 1.2, -2.6] },
    },
    wall: {
      title: 'Wall & mould risk',
      subtitle: 'DS18B20 probe on the cold balcony wall',
      anchor: [0.9, 2.32, -1.95],
      view: { position: [-0.4, 1.9, 1.2], target: [0.72, 1.7, -2.0] },
    },
  },
};

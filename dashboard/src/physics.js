// Psychrometrics for the dashboard: pure functions, no DOM, tested in tests/physics.test.js.
// Magnus formula over water with Sonntag (1990) constants: within about 0.4 % of steam-table saturation pressures
// between -40 and 50 °C (0.3 % at 20 °C, i.e. about 0.04 °C in dew point, far below sensor accuracy).

const A = 17.62;
const B = 243.12;   // °C
const E0 = 6.112;   // hPa

/** Saturation vapour pressure over water, hPa. */
export const satVapourPressure = (tC) => E0 * Math.exp((A * tC) / (B + tC));

/** Actual vapour pressure from temperature and relative humidity, hPa. */
export const vapourPressure = (tC, rh) => (rh / 100) * satVapourPressure(tC);

/** Dew point, °C. */
export function dewPoint(tC, rh) {
  const g = Math.log(rh / 100) + (A * tC) / (B + tC);
  return (B * g) / (A - g);
}

/** Absolute humidity, g/m³ (ideal gas, water vapour R = 461.5 J/(kg·K)). */
export const absoluteHumidity = (tC, rh) => (216.7 * vapourPressure(tC, rh)) / (273.15 + tC);

/** Relative humidity, %, of air with absolute humidity ah (g/m³) at temperature tC. */
export const rhFromAbsolute = (tC, ah) => (100 * ah * (273.15 + tC)) / (216.7 * satVapourPressure(tC));

/** Temperature at which the saturation vapour pressure equals e (hPa): the inverse of satVapourPressure. */
export function tempForSatPressure(e) {
  const g = Math.log(e / E0);
  return (B * g) / (A - g);
}

/**
 * Surface temperature at which room air (tAir, rh) reaches targetRh at that surface. With targetRh = 80 this is
 * the "mould-critical" wall temperature; with 100 it is the dew point.
 */
export const surfaceTempForRH = (tAir, rh, targetRh) => tempForSatPressure(vapourPressure(tAir, rh) / (targetRh / 100));

/** Relative humidity at a surface of temperature tSurface touched by room air (tAir, rh), capped at 100 %. */
export const surfaceRH = (tAir, rh, tSurface) =>
  Math.min(100, (100 * vapourPressure(tAir, rh)) / satVapourPressure(tSurface));

// Advice thresholds
const CO2_AIR_OUT = 1000;     // ppm: common indoor air-quality guideline
const RH_HIGH = 60;           // %: room air at which airing to dry the room is worth it
const DRYING_MIN = 1.0;       // g/m³: minimum indoor-outdoor absolute humidity difference that dries the room

/**
 * Should the windows be opened now?
 * indoor: { t, rh, co2 }, outdoor: { t, rh } (outdoor may be null).
 * Returns { action: 'open' | 'keep' | 'unknown', reasons: string[], dryingGain: g/m³ or null }.
 */
export function ventilationAdvice({ indoor, outdoor }) {
  if (!indoor || indoor.t == null || indoor.rh == null) return { action: 'unknown', reasons: [], dryingGain: null };

  const reasons = [];
  const dryingGain = outdoor && outdoor.t != null && outdoor.rh != null
    ? absoluteHumidity(indoor.t, indoor.rh) - absoluteHumidity(outdoor.t, outdoor.rh)
    : null;

  const stale = indoor.co2 != null && indoor.co2 >= CO2_AIR_OUT;
  const humid = indoor.rh >= RH_HIGH;
  const dries = dryingGain != null && dryingGain >= DRYING_MIN;

  if (stale) reasons.push(`CO₂ is ${Math.round(indoor.co2)} ppm (air out above ${CO2_AIR_OUT})`);
  if (humid && dries) reasons.push(`outside air holds ${dryingGain.toFixed(1)} g/m³ less water: airing dries the room`);
  if (humid && dryingGain != null && !dries) reasons.push('room is humid, but outside air is about as wet: airing barely dries it');
  if (!stale && !humid) reasons.push('CO₂ and humidity are fine');

  return { action: stale || (humid && dries) ? 'open' : 'keep', reasons, dryingGain };
}

/**
 * Inside surface temperature of glazing, °C: steady state through a pane of transmittance u (W/m²K) with the inside
 * surface resistance rsi (m²K/W): θsi = θi − U·Rsi·(θi − θe), i.e. temperature factor fRsi = 1 − U·Rsi.
 * Defaults: older double glazing (U ≈ 2.8) and EN ISO 6946's Rsi = 0.13 for horizontal heat flow [assumed glazing].
 */
export const glassSurfaceTemp = (tIn, tOut, { u = 2.8, rsi = 0.13 } = {}) => tIn - u * rsi * (tIn - tOut);

/** How fogged the glass looks, 0..1: starts at 85 % humidity at the glass, full at condensation (100 %). */
export function glassFog(tIn, rhIn, tOut) {
  if (![tIn, rhIn, tOut].every(Number.isFinite)) return 0;
  const rh = surfaceRH(tIn, rhIn, glassSurfaceTemp(tIn, tOut));
  return Math.min(1, Math.max(0, (rh - 85) / 15));
}

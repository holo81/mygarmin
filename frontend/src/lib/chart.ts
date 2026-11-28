// Shared axis helpers: evenly spaced, round ticks.

export interface Axis {
  domain: [number, number];
  ticks: number[];
}

/** 'Nice' value axis (step 1/2/5 x 10^n) covering [lo, hi]. */
export function niceAxis(lo: number, hi: number, n = 5): Axis {
  if (!(hi > lo)) {
    lo -= 1;
    hi += 1;
  }
  const raw = (hi - lo) / n;
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  const a = Math.floor(lo / step + 1e-9) * step;
  const b = Math.ceil(hi / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = a; v <= b + step / 2; v += step) ticks.push(+v.toFixed(10));
  return { domain: [a, b], ticks };
}

const TIME_STEPS = [60, 300, 600, 900, 1800, 3600, 7200, 10800, 21600];

/** Time axis in seconds: ticks on round minute/hour multiples, domain = [min, max]. */
export function timeAxis(min: number, max: number, maxTicks = 6): Axis {
  const step = TIME_STEPS.find((s) => (max - min) / s <= maxTicks) ?? 21600;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) ticks.push(v);
  return { domain: [min, max], ticks };
}

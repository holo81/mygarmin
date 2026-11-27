// Composite scores computed in the browser from the Overview payload. They are OUR
// estimates, not Garmin's. Missing inputs yield null (never 0); a score needs enough
// available contributors, otherwise it is null ("No data").
import type { Overview } from "../api/types";

export interface Contributor {
  label: string;
  value: number | null; // 0-100, null = no data
  detail: string;
}
export interface Score {
  score: number | null;
  max: number; // 100 for recovery/sleep, 21 for strain
  /** "estimate" (ours) or "Garmin score" (taken straight from the device). */
  source: "estimate" | "Garmin score";
  contributors: Contributor[];
}

const clamp = (v: number, lo = 0, hi = 100) => Math.min(hi, Math.max(lo, v));
const mean = (xs: (number | null | undefined)[]) => {
  const v = xs.filter((x): x is number => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
};

/** Weighted average over the contributors that have a value; null below `min` available. */
function weighted(cs: Contributor[], weights: number[], min: number): number | null {
  const avail = cs.map((c, i) => ({ v: c.value, w: weights[i] })).filter((x) => x.v != null);
  if (avail.length < min) return null;
  const wsum = avail.reduce((a, x) => a + x.w, 0);
  return Math.round(avail.reduce((a, x) => a + (x.v as number) * x.w, 0) / wsum);
}

type Today = Overview["today"];

export function recoveryScore(today: Today, sevenDay: Overview["sevenDay"]): Score {
  const { daily, sleep, hrv } = today;
  const hrvNow = hrv?.lastNightAvgMs ?? null;
  const hrvRef =
    hrv?.weeklyAvgMs ??
    (hrv?.baselineLowMs != null && hrv.baselineHighMs != null
      ? (hrv.baselineLowMs + hrv.baselineHighMs) / 2
      : null);
  const rhr = daily?.restingHrBpm ?? null;
  const rhrAvg = mean(sevenDay.map((d) => d.restingHrBpm));
  const bb = daily?.bodyBatteryHigh ?? null;
  const sleepScore = sleep?.overallScoreValue ?? null;

  const cs: Contributor[] = [
    {
      label: "HRV vs baseline",
      value: hrvNow != null && hrvRef ? Math.round(clamp(75 + (hrvNow / hrvRef - 1) * 250)) : null,
      detail: hrvNow != null && hrvRef ? `${Math.round(hrvNow)} ms vs ${Math.round(hrvRef)} ms` : "No data",
    },
    {
      label: "Resting HR vs 7-day avg",
      value: rhr != null && rhrAvg != null ? Math.round(clamp(75 + (rhrAvg - rhr) * 8)) : null,
      detail: rhr != null && rhrAvg != null ? `${rhr} bpm vs ${Math.round(rhrAvg)} bpm` : "No data",
    },
    {
      label: "Body battery high",
      value: bb,
      detail: bb != null ? `${bb} / 100` : "No data",
    },
    {
      label: "Sleep score",
      value: sleepScore,
      detail: sleepScore != null ? `${sleepScore} / 100` : "No data",
    },
  ];
  return { score: weighted(cs, [0.4, 0.25, 0.2, 0.15], 2), max: 100, source: "estimate", contributors: cs };
}

export function sleepScore(sleep: Today["sleep"]): Score {
  const stages = sleep
    ? [sleep.deepSeconds, sleep.lightSeconds, sleep.remSeconds, sleep.awakeSeconds]
    : [];
  const total = stages.every((s) => s != null) && stages.length ? stages.reduce((a, b) => a! + b!, 0)! : null;
  const pct = (s: number | null | undefined) => (total && s != null ? (s / total) * 100 : null);
  const dur = sleep?.durationSeconds ?? null;
  const deep = pct(sleep?.deepSeconds);
  const rem = pct(sleep?.remSeconds);
  const awake = pct(sleep?.awakeSeconds);

  const cs: Contributor[] = [
    {
      label: "Duration vs 8h",
      value: dur != null ? Math.round(clamp((dur / 28800) * 100)) : null,
      detail: dur != null ? `${(dur / 3600).toFixed(1)} h` : "No data",
    },
    {
      label: "Deep sleep",
      value: deep != null ? Math.round(clamp((deep / 20) * 100)) : null,
      detail: deep != null ? `${deep.toFixed(0)}% (target 20%)` : "No data",
    },
    {
      label: "REM sleep",
      value: rem != null ? Math.round(clamp((rem / 22) * 100)) : null,
      detail: rem != null ? `${rem.toFixed(0)}% (target 22%)` : "No data",
    },
    {
      label: "Awake time",
      value: awake != null ? Math.round(clamp(100 - awake * 8)) : null,
      detail: awake != null ? `${awake.toFixed(0)}% of night` : "No data",
    },
  ];
  const garmin = sleep?.overallScoreValue ?? null;
  if (garmin != null) return { score: garmin, max: 100, source: "Garmin score", contributors: cs };
  return { score: weighted(cs, [0.4, 0.25, 0.25, 0.1], 2), max: 100, source: "estimate", contributors: cs };
}

export function strainScore(today: Today, sevenDay: Overview["sevenDay"]): Score {
  const d = today.daily;
  const im = d?.intensityMinutes ?? null;
  const kcal = d?.activeKilocalories ?? null;
  const steps = d?.steps ?? null;
  // Relative to the 7-day average: 100 = 1.5x (or more) your usual.
  const vsAvg = (now: number | null, key: "intensityMinutes" | "activeKilocalories") => {
    const a = mean(sevenDay.map((x) => x[key]));
    return now != null && a ? Math.round(clamp((now / (a * 1.5)) * 100)) : null;
  };
  const cs: Contributor[] = [
    {
      label: "Intensity minutes",
      value: vsAvg(im, "intensityMinutes"),
      detail: im != null ? `${im} min` : "No data",
    },
    {
      label: "Active calories",
      value: vsAvg(kcal, "activeKilocalories"),
      detail: kcal != null ? `${Math.round(kcal)} kcal` : "No data",
    },
    {
      label: "Steps vs goal",
      value: steps != null && d?.stepsGoal ? Math.round(clamp((steps / d.stepsGoal) * 100)) : null,
      detail: steps != null ? `${steps.toLocaleString()}${d?.stepsGoal ? ` / ${d.stepsGoal.toLocaleString()}` : ""}` : "No data",
    },
  ];
  // Whoop-style 0-21 log-ish curve; null when neither load input exists.
  const raw = im == null && kcal == null ? null : (im ?? 0) + (kcal ?? 0) / 10;
  const score = raw == null ? null : Math.round(21 * (1 - Math.exp(-raw / 60)) * 10) / 10;
  return { score, max: 21, source: "estimate", contributors: cs };
}

/** One-line rule-based daily insight; null when recovery is unknown. */
export function dailyInsight(recovery: Score, hrv: Today["hrv"]): string | null {
  const r = recovery.score;
  if (r == null) return null;
  const pct =
    hrv?.lastNightAvgMs != null && hrv.weeklyAvgMs
      ? Math.round((hrv.lastNightAvgMs / hrv.weeklyAvgMs - 1) * 100)
      : null;
  if (r >= 67) {
    return pct != null && pct >= 5
      ? `HRV ${pct}% above your weekly average - good day to push.`
      : "Recovery is high - good day to push.";
  }
  if (r >= 34) return "Recovery is moderate - steady training is fine.";
  return pct != null && pct <= -5
    ? `HRV ${Math.abs(pct)}% below your weekly average - keep it easy.`
    : "Recovery is low - keep it easy.";
}

// Run: npm run check:scores  (Node 22.6+ with --experimental-strip-types)
import assert from "node:assert/strict";
import { dailyInsight, recoveryScore, sleepScore, strainScore } from "./scores.ts";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const any = (o: unknown) => o as any;
const empty = any({ daily: null, sleep: null, hrv: null });

// Nothing in -> null scores, never 0.
assert.equal(recoveryScore(empty, []).score, null);
assert.equal(sleepScore(null).score, null);
assert.equal(strainScore(empty, []).score, null);
assert.equal(dailyInsight(recoveryScore(empty, []), null), null);

// A single available input is below the 2-contributor minimum.
assert.equal(recoveryScore(any({ daily: { bodyBatteryHigh: 80 }, sleep: null, hrv: null }), []).score, null);

// Bounds.
const good = recoveryScore(
  any({
    daily: { restingHrBpm: 40, bodyBatteryHigh: 100 },
    sleep: { overallScoreValue: 100 },
    hrv: { lastNightAvgMs: 200, weeklyAvgMs: 50 },
  }),
  any([{ restingHrBpm: 60 }])
);
assert.equal(good.score, 100);
const bad = recoveryScore(
  any({ daily: { restingHrBpm: 90, bodyBatteryHigh: 0 }, sleep: { overallScoreValue: 0 }, hrv: { lastNightAvgMs: 1, weeklyAvgMs: 50 } }),
  any([{ restingHrBpm: 50 }])
);
assert.equal(bad.score, 0);
assert.match(dailyInsight(good, null)!, /push/);
assert.match(dailyInsight(bad, null)!, /easy/);

// Sleep: Garmin score wins; otherwise estimate from stages.
assert.equal(sleepScore(any({ overallScoreValue: 82 })).score, 82);
const est = sleepScore(any({ durationSeconds: 28800, deepSeconds: 5760, lightSeconds: 14400, remSeconds: 6336, awakeSeconds: 0 }));
assert.equal(est.source, "estimate");
assert.ok(est.score! >= 0 && est.score! <= 100);

// Strain stays within 0-21 and grows with load.
const base = any([{ intensityMinutes: 30, activeKilocalories: 500 }]);
const lo = strainScore(any({ daily: { intensityMinutes: 0, activeKilocalories: 0 } }), base).score!;
const hi = strainScore(any({ daily: { intensityMinutes: 5000, activeKilocalories: 50000 } }), base).score!;
assert.equal(lo, 0);
assert.ok(hi > 20 && hi <= 21);

console.log("scores.check OK");

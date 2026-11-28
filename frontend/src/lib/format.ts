// Presentation helpers. Unit conversions happen here, never on stored data.
// A null input yields a clear "no data" dash so missing != zero.

export const DASH = "—";

export function isNil(v: unknown): v is null | undefined {
  return v === null || v === undefined;
}

export function fmtInt(v: number | null | undefined): string {
  if (isNil(v)) return DASH;
  return Math.round(v).toLocaleString();
}

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (isNil(v)) return DASH;
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtDistance(meters: number | null | undefined, unit: string): string {
  if (isNil(meters)) return DASH;
  if (unit === "imperial") {
    const miles = meters / 1609.344;
    return `${miles.toFixed(2)} mi`;
  }
  if (meters >= 1000) return `${(meters / 1000).toFixed(2)} km`;
  return `${Math.round(meters)} m`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (isNil(seconds)) return DASH;
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export function fmtHoursMinutes(seconds: number | null | undefined): string {
  if (isNil(seconds)) return DASH;
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m.toString().padStart(2, "0")}m`;
}

export function fmtPace(minPerKm: number | null | undefined, unit: string): string {
  if (isNil(minPerKm) || minPerKm <= 0) return DASH;
  let value = minPerKm;
  let suffix = "/km";
  if (unit === "imperial") {
    value = minPerKm * 1.609344;
    suffix = "/mi";
  }
  const m = Math.floor(value);
  const sec = Math.round((value - m) * 60);
  const secStr = sec === 60 ? "00" : sec.toString().padStart(2, "0");
  const minStr = sec === 60 ? m + 1 : m;
  return `${minStr}:${secStr} ${suffix}`;
}

/** m:ss for chart axes/tooltips (no unit suffix); converts for imperial. */
export function fmtPaceClock(minPerKm: number, unit: string): string {
  const v = unit === "imperial" ? minPerKm * 1.609344 : minPerKm;
  let m = Math.floor(v);
  let sec = Math.round((v - m) * 60);
  if (sec === 60) { m += 1; sec = 0; }
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

export function fmtSpeedKmh(mps: number | null | undefined, unit: string): string {
  if (isNil(mps)) return DASH;
  if (unit === "imperial") return `${(mps * 2.2369363).toFixed(1)} mph`;
  return `${(mps * 3.6).toFixed(1)} km/h`;
}

export function fmtElevation(meters: number | null | undefined, unit: string): string {
  if (isNil(meters)) return DASH;
  if (unit === "imperial") return `${Math.round(meters * 3.28084)} ft`;
  return `${Math.round(meters)} m`;
}

// Format a device-local ISO string (which already carries the correct offset).
export function fmtLocalDateTime(iso: string | null | undefined): string {
  if (isNil(iso)) return DASH;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return DASH;
  return d.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtLocalDate(iso: string | null | undefined): string {
  if (isNil(iso)) return DASH;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return DASH;
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

export function fmtDateShort(ymd: string | null | undefined): string {
  if (isNil(ymd)) return DASH;
  const d = new Date(`${ymd}T00:00:00`);
  if (isNaN(d.getTime())) return ymd;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function activityTypeLabel(t: string | null | undefined): string {
  if (isNil(t)) return "Activity";
  return t
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const ACTIVITY_ICONS: Record<string, string> = {
  RUNNING: "🏃",
  CYCLING: "🚴",
  WALKING: "🚶",
  HIKING: "🥾",
  LAP_SWIMMING: "🏊",
  OPEN_WATER_SWIMMING: "🏊",
  SWIMMING: "🏊",
  STRENGTH_TRAINING: "🏋️",
  YOGA: "🧘",
  CARDIO: "💓",
};

export function activityIcon(t: string | null | undefined): string {
  if (isNil(t)) return "🏅";
  return ACTIVITY_ICONS[t.toUpperCase()] ?? "🏅";
}

// Types where pace/speed and elevation are meaningful (moving outdoors over distance).
export function isMovingType(t: string | null | undefined): boolean {
  return !isNil(t) && /RUN|WALK|HIK|CYCL|BIK/i.test(t);
}

// "time ago" from an ISO UTC timestamp, for sync freshness.
export function timeAgo(iso: string | null | undefined): string {
  if (isNil(iso)) return "never";
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();
  if (isNaN(then)) return DASH;
  const diff = Date.now() - then;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const ACTIVITY_COLORS: Record<string, string> = {
  RUNNING: "var(--str-a)",
  CYCLING: "var(--accent-2)",
  WALKING: "var(--rec-a)",
  HIKING: "var(--good)",
  LAP_SWIMMING: "var(--accent)",
  OPEN_WATER_SWIMMING: "var(--accent)",
  SWIMMING: "var(--accent)",
  STRENGTH_TRAINING: "var(--slp-b)",
  YOGA: "var(--slp-a)",
  CARDIO: "var(--hrt-a)",
};

// CSS color for an activity type's icon chip / banner.
export function activityColor(t: string | null | undefined): string {
  return (t && ACTIVITY_COLORS[t.toUpperCase()]) || "var(--text-dim)";
}

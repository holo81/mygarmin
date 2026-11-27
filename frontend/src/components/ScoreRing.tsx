import { useEffect, useState } from "react";
import type { Score } from "../lib/scores";

const R = 60;
const C = 2 * Math.PI * R;
const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

/** Animated gradient ring. A null score renders an empty track and "No data". */
export function ScoreRing({
  label,
  score,
  grad,
  open,
  onClick,
}: {
  label: string;
  score: Score;
  grad: "rec" | "slp" | "str";
  open: boolean;
  onClick: () => void;
}) {
  const target = score.score;
  const [shown, setShown] = useState(0); // animated value (count-up + arc)

  useEffect(() => {
    if (target == null) return;
    if (reduced()) {
      setShown(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / 1100);
      setShown(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);

  const id = `ring-${grad}`;
  const frac = target == null ? 0 : shown / score.max;
  const text = target == null ? null : score.max === 21 ? shown.toFixed(1) : Math.round(shown);

  return (
    <button
      type="button"
      className={`card ring-card${open ? " open" : ""}`}
      style={{ ["--ring-a" as string]: `var(--${grad}-a)` }}
      onClick={onClick}
      aria-expanded={open}
    >
      <div className="ring-label">{label}</div>
      <div className="ring-wrap">
        <svg viewBox="0 0 140 140" aria-hidden>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" style={{ stopColor: `var(--${grad}-a)` }} />
              <stop offset="100%" style={{ stopColor: `var(--${grad}-b)` }} />
            </linearGradient>
          </defs>
          <circle className="ring-track" cx="70" cy="70" r={R} strokeWidth="11" />
          {target != null && (
            <circle
              className="ring-arc"
              cx="70"
              cy="70"
              r={R}
              strokeWidth="11"
              stroke={`url(#${id})`}
              strokeDasharray={C}
              strokeDashoffset={C * (1 - frac)}
              style={{ transition: "none" }}
            />
          )}
        </svg>
        <div className={`ring-num${target == null ? " nodata" : ""}`}>
          {target == null ? (
            <b>No data</b>
          ) : (
            <>
              <b>{text}</b>
              <small>/ {score.max}</small>
            </>
          )}
        </div>
      </div>
      <div className="ring-cap">{target == null ? "needs more inputs" : score.source}</div>
    </button>
  );
}

/** Horizontal gradient bars explaining a score. */
export function Contributors({ title, score, grad }: { title: string; score: Score; grad: string }) {
  return (
    <div className="card contrib">
      <div className="card-title">
        {title} contributors <span className="faint">{score.source === "estimate" ? "estimate" : ""}</span>
      </div>
      {score.contributors.map((c) => (
        <div key={c.label} className={`contrib-row${c.value == null ? " nodata" : ""}`}>
          <div className="k">{c.label}</div>
          <div className="bar" role="img" aria-label={c.value == null ? "No data" : `${c.value} of 100`}>
            {c.value != null && <i style={{ width: `${c.value}%`, background: `var(--g-${grad})` }} />}
          </div>
          <div className="d">{c.detail}</div>
        </div>
      ))}
    </div>
  );
}

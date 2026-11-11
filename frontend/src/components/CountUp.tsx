import { useEffect, useRef, useState } from "react";

/** Animate only when the browser supports matchMedia and the user has not asked for reduced motion. */
const canAnimate = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" &&
  !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A number that counts up to its value. Driven by a timer, not requestAnimationFrame, so it still
 *  finishes in a background or hidden tab. Always lands exactly on `value`. */
export function CountUp({ value, format = (n: number) => String(n), duration = 700 }:
  { value: number; format?: (n: number) => string; duration?: number }) {
  const [shown, setShown] = useState(() => (canAnimate() ? 0 : value));
  const latest = useRef(shown);
  latest.current = shown;

  useEffect(() => {
    if (!canAnimate()) { setShown(value); return; }
    const from = latest.current;
    const start = Date.now();
    const timer = setInterval(() => {
      const t = Math.min(1, (Date.now() - start) / duration);
      setShown(t >= 1 ? value : from + (value - from) * (1 - (1 - t) ** 3)); // ease-out
      if (t >= 1) clearInterval(timer);
    }, 16);
    return () => clearInterval(timer);
  }, [value, duration]);

  return <span data-testid="countup">{format(Math.round(shown))}</span>;
}

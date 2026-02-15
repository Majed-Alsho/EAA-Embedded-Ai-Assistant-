export function clamp(n: number, a: number, b: number) {
  return Math.max(a, Math.min(b, n));
}

export function roundTo(n: number, step: number) {
  if (step <= 0) return n;
  return Math.round(n / step) * step;
}

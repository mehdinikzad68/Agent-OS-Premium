/**
 * Mulberry32: Deterministic 32-bit PRNG
 * Replaces non-deterministic random generation for reproducible canvas rendering.
 */
export function createMulberry32(seed: number = 0x4f88bc12) {
  let s = seed >>> 0;
  return function next(): number {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const deterministicRandom = createMulberry32(0x4f88bc12);
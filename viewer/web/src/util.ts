import { Json, JsonObject } from "./api";

export function isEmptyObject(o: JsonObject | null | undefined): boolean {
  return !o || Object.keys(o).length === 0;
}

function isPlainObject(v: Json | undefined): v is JsonObject {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Copy of `base` with `over` merged in; nested objects merge, everything else replaces. */
export function deepMerge(base: JsonObject, over: JsonObject): JsonObject {
  const out: JsonObject = structuredClone(base);
  for (const [k, v] of Object.entries(over)) {
    const cur = out[k];
    out[k] = isPlainObject(v) && isPlainObject(cur) ? deepMerge(cur, v) : structuredClone(v);
  }
  return out;
}

/** The parts of `value` that differ from `base` (so presets only store what was changed). */
export function deepDiff(value: JsonObject, base: JsonObject): JsonObject {
  const out: JsonObject = {};
  for (const [k, v] of Object.entries(value)) {
    const b = base[k];
    if (isPlainObject(v) && isPlainObject(b)) {
      const d = deepDiff(v, b);
      if (Object.keys(d).length) out[k] = d;
    } else if (JSON.stringify(v) !== JSON.stringify(b)) {
      out[k] = structuredClone(v);
    }
  }
  return out;
}

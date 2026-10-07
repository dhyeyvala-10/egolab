/** Pick known string params from Next's searchParams (arrays keep the first value). */
export function pickQuery(
  params: Record<string, string | string[] | undefined>,
  keys: readonly string[],
): Record<string, string | undefined> {
  const out: Record<string, string | undefined> = {};
  for (const key of keys) {
    const value = params[key];
    const first = Array.isArray(value) ? value[0] : value;
    if (first) out[key] = first;
  }
  return out;
}

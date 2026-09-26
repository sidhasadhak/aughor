/**
 * React keys for a list whose items carry no guaranteed-unique identity.
 *
 * A key must be unique among its siblings. A field that names a KIND is not an identity
 * however it is spelled: a report can hold two `decomposition` phases, an aggregate can
 * hold the same metric name twice, and React then warns "two children with the same key"
 * and may drop or duplicate a row. This repo fixed that one field at a time at least seven
 * times. The rule is written in web/AGENTS.md and enforced twice: `listKeys.test.ts` (no
 * new list keyed bare by a kind or a display text) and `vitest.setup.ts` (a component test
 * that renders a duplicate key fails).
 *
 * Returns `[key, item]` pairs, so a render reads `withUniqueKeys(list, x => x.kind)
 * .map(([key, x]) => <Row key={key} … />)`. `keyOf(item)` is the natural key. The first
 * occurrence keeps it, so a list without repeats keys exactly as before; a repeat gets
 * `#2`, `#3`, … (skipping any suffix the list already uses), so every key is unique while
 * staying stable for as long as the list's order is.
 */
export function withUniqueKeys<T>(items: readonly T[], keyOf: (item: T) => string): Array<[string, T]> {
  const used = new Set<string>();
  const seen = new Map<string, number>();
  return items.map((item): [string, T] => {
    const natural = keyOf(item);
    let n = seen.get(natural) ?? 0;
    let key = natural;
    while (used.has(key)) {
      n += 1;
      key = `${natural}#${n + 1}`;
    }
    seen.set(natural, n);
    used.add(key);
    return [key, item];
  });
}

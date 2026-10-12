/** Классы через пробел; пустые, false, null и undefined пропускаются. */
export function cls(...xs: (string | false | null | undefined)[]): string {
  return xs.filter(Boolean).join(" ");
}

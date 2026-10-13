// Заголовок вкладки браузера: сборка идёт — её ход («Готовлю презентацию 42 % · Verstka»: 3–4 минуты в фоновой вкладке
// видно, сколько осталось); открыта презентация — её название; иначе — «Verstka».

export function tabTitle(o: { building: boolean; progress: number; screen: string; deck: string | null }): string {
  if (o.building) return `Готовлю презентацию ${Math.round(Math.min(1, Math.max(0, o.progress || 0)) * 100)} % · Verstka`;
  if (o.screen === "result" && o.deck) return `${o.deck} · Verstka`;
  return "Verstka";
}

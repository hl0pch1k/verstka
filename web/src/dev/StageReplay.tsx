// Dev only (/?replay=<generation id>[&speed=3]): a finished build played again on the build screen. Never in the
// production bundle: main.tsx imports it only under import.meta.env.DEV.
// Пока заглушка: старый экран сборки удалён вместе со старым интерфейсом, реплей переписывается под новую плиту
// «Сборка» (Task 15). Сценарий событий прежнего реплея — в git (HEAD до «Слоёв»: web/src/dev/StageReplay.tsx).
export default function StageReplay(_props: { gid: string; speed: number }) {
  return (
    <div className="p2-root" style={{ padding: 24 }}>
      <p style={{ margin: 0, color: "#5A6272" }}>Реплей сборки появится вместе с новым экраном сборки</p>
    </div>
  );
}

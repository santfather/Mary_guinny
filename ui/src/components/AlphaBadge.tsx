export function AlphaBadge({ hasAlpha }: { hasAlpha: boolean | null }) {
  if (hasAlpha === true) {
    return <span className="badge badge--ok">Альфа-канал</span>;
  }
  if (hasAlpha === false) {
    return <span className="badge badge--warn">Без прозрачности</span>;
  }
  return <span className="badge badge--muted">Альфа не определена</span>;
}

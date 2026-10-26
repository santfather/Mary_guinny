import type { CompositionWarning } from "../api/types";

const WARNING_LABELS: Record<string, string> = {
  opaque_character_reference: "Персонаж без альфа-канала",
  layer_without_alpha: "Слой без прозрачности",
};

export function WarningList({ warnings }: { warnings: CompositionWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <ul className="warnings" role="status">
      {warnings.map((warning) => (
        <li key={`${warning.code}-${warning.z_index}`}>
          <span className="badge badge--warn">
            {WARNING_LABELS[warning.code] ?? warning.code}
          </span>
          <span className="muted">
            z={warning.z_index} · {warning.message}
          </span>
        </li>
      ))}
    </ul>
  );
}

import type { ReferenceAsset } from "../api/types";
import { canApproveReference, canRejectReference, poseLabel, viewLabel } from "../labels";
import { AlphaBadge } from "./AlphaBadge";
import { StatusBadge } from "./StatusBadge";

interface ReferenceCardProps {
  asset: ReferenceAsset;
  pending: boolean;
  onOpen: (asset: ReferenceAsset) => void;
  onApprove: (asset: ReferenceAsset) => void;
  onReject: (asset: ReferenceAsset) => void;
  extraAction?: { label: string; onSelect: (asset: ReferenceAsset) => void };
}

export function ReferenceCard({
  asset,
  pending,
  onOpen,
  onApprove,
  onReject,
  extraAction,
}: ReferenceCardProps) {
  const details = [viewLabel(asset.view), poseLabel(asset.pose), asset.expression].filter(
    (value): value is string => value !== null && value !== "",
  );
  const size =
    asset.width !== null && asset.height !== null
      ? `${asset.width}×${asset.height}`
      : "размер неизвестен";

  return (
    <article className="reference">
      <button
        type="button"
        className="reference__image"
        onClick={() => onOpen(asset)}
        aria-label="Открыть референс"
      >
        <img
          src={asset.content_url}
          alt={`Референс ${asset.sha256.slice(0, 8)}`}
          loading="lazy"
        />
      </button>

      <div className="reference__meta">
        <StatusBadge status={asset.status} />
        <AlphaBadge hasAlpha={asset.has_alpha} />
        {asset.role === "primary" && <span className="badge badge--ok">основной</span>}
      </div>

      {details.length > 0 && <p className="muted">{details.join(" · ")}</p>}
      <p className="muted mono">{size}</p>

      <div className="reference__actions">
        <button
          type="button"
          className="button button--small button--ghost"
          onClick={() => onOpen(asset)}
        >
          Открыть
        </button>
        {extraAction !== undefined && (
          <button
            type="button"
            className="button button--small"
            disabled={pending}
            onClick={() => extraAction.onSelect(asset)}
          >
            {extraAction.label}
          </button>
        )}
        {canApproveReference(asset.status) && (
          <button
            type="button"
            className="button button--small button--ok"
            disabled={pending}
            onClick={() => onApprove(asset)}
          >
            {pending ? "…" : "Утвердить"}
          </button>
        )}
        {canRejectReference(asset.status) && (
          <button
            type="button"
            className="button button--small button--danger"
            disabled={pending}
            onClick={() => onReject(asset)}
          >
            Отклонить
          </button>
        )}
      </div>
    </article>
  );
}

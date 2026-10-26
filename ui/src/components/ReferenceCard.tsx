import type { ReferenceAsset } from "../api/types";
import { poseLabel, viewLabel } from "../labels";
import { AlphaBadge } from "./AlphaBadge";
import { StatusBadge } from "./StatusBadge";

interface ReferenceCardProps {
  asset: ReferenceAsset;
  pending: boolean;
  onOpen: (asset: ReferenceAsset) => void;
  onApprove: (asset: ReferenceAsset) => void;
  onReject: (asset: ReferenceAsset) => void;
}

export function ReferenceCard({
  asset,
  pending,
  onOpen,
  onApprove,
  onReject,
}: ReferenceCardProps) {
  const details = [viewLabel(asset.view), poseLabel(asset.pose), asset.expression].filter(
    (value): value is string => value !== null && value !== "",
  );
  const canApprove = asset.status === "draft" || asset.status === "rejected";
  const canReject = asset.status === "draft" || asset.status === "approved";
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
        {canApprove && (
          <button
            type="button"
            className="button button--small button--ok"
            disabled={pending}
            onClick={() => onApprove(asset)}
          >
            {pending ? "…" : "Утвердить"}
          </button>
        )}
        {canReject && (
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

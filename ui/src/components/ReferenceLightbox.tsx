import { useEffect, useState } from "react";

import type { ReferenceAsset } from "../api/types";
import { canApproveReference, canRejectReference, poseLabel, viewLabel } from "../labels";
import { AlphaBadge } from "./AlphaBadge";
import { StatusBadge } from "./StatusBadge";

interface ReferenceLightboxProps {
  asset: ReferenceAsset;
  pending: boolean;
  onClose: () => void;
  onApprove: (asset: ReferenceAsset) => void;
  onReject: (asset: ReferenceAsset) => void;
  onMultiViewChange: (asset: ReferenceAsset, value: boolean) => Promise<void>;
}

export function ReferenceLightbox({
  asset,
  pending,
  onClose,
  onApprove,
  onReject,
  onMultiViewChange,
}: ReferenceLightboxProps) {
  const [multiViewBusy, setMultiViewBusy] = useState(false);
  const [multiViewError, setMultiViewError] = useState<string | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const canApprove = canApproveReference(asset.status);
  const canReject = canRejectReference(asset.status);
  const canRelabel = asset.status === "draft" || asset.status === "rejected";
  const view = viewLabel(asset.view);
  const pose = poseLabel(asset.pose);

  async function handleMultiView(checked: boolean): Promise<void> {
    setMultiViewBusy(true);
    setMultiViewError(null);
    try {
      await onMultiViewChange(asset, checked);
    } catch (error) {
      setMultiViewError(error instanceof Error ? error.message : String(error));
    } finally {
      setMultiViewBusy(false);
    }
  }

  return (
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label="Просмотр референса"
      onClick={onClose}
    >
      <div className="lightbox__body" onClick={(event) => event.stopPropagation()}>
        <button
          type="button"
          className="button button--ghost lightbox__close"
          onClick={onClose}
          aria-label="Закрыть"
        >
          ×
        </button>

        <img
          className="lightbox__image"
          src={asset.content_url}
          alt={`Референс ${asset.sha256.slice(0, 8)}`}
        />

        <div className="lightbox__meta">
          <StatusBadge status={asset.status} />
          <AlphaBadge hasAlpha={asset.has_alpha} />
          {asset.width !== null && asset.height !== null && (
            <span className="muted">
              {asset.width}×{asset.height}
            </span>
          )}
          {view !== null && <span className="muted">{view}</span>}
          {pose !== null && <span className="muted">{pose}</span>}
          {asset.expression !== null && <span className="muted">{asset.expression}</span>}
          {asset.multi_view && <span className="badge badge--warn">многоракурсная</span>}
          <span className="mono muted">{asset.sha256.slice(0, 16)}</span>
          <div className="lightbox__actions">
            {canApprove && (
              <button
                type="button"
                className="button button--ok"
                disabled={pending}
                onClick={() => onApprove(asset)}
              >
                {pending ? "…" : "Утвердить"}
              </button>
            )}
            {canReject && (
              <button
                type="button"
                className="button button--danger"
                disabled={pending}
                onClick={() => onReject(asset)}
              >
                Отклонить
              </button>
            )}
          </div>
        </div>

        <label className="lightbox__toggle">
          <input
            type="checkbox"
            checked={asset.multi_view}
            disabled={!canRelabel || multiViewBusy}
            onChange={(event) => void handleMultiView(event.currentTarget.checked)}
          />
          <span>
            Многоракурсная карточка — нельзя использовать как стартовый кадр
            {canRelabel ? "" : " (approved не редактируется)"}
          </span>
        </label>
        {multiViewError !== null && (
          <p className="alert" role="alert">
            {multiViewError}
          </p>
        )}
      </div>
    </div>
  );
}

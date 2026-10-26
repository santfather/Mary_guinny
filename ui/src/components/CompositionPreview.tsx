import type { CompositionRender, CompositionSummary } from "../api/types";
import { StatusBadge } from "./StatusBadge";
import { WarningList } from "./WarningList";

interface CompositionPreviewProps {
  composition: CompositionSummary;
  rendered: CompositionRender | null;
  busy: boolean;
  onEdit: () => void;
  onRender: () => void;
  onApprove: () => void;
  onSupersede: () => void;
}

export function CompositionPreview({
  composition,
  rendered,
  busy,
  onEdit,
  onRender,
  onApprove,
  onSupersede,
}: CompositionPreviewProps) {
  const previewUrl = rendered?.content_url ?? composition.preview_content_url;
  const warnings = rendered?.warnings ?? [];
  const isDraft = composition.status === "draft";
  const isApproved = composition.status === "approved";
  const canApprove = isDraft && composition.preview_artifact_id !== null;

  return (
    <article className="composition">
      <div className="card__head">
        <h3>Ревизия {composition.revision}</h3>
        <StatusBadge status={composition.status} />
      </div>

      {previewUrl === null ? (
        <div className="composition__empty">Предпросмотр не отрендерен</div>
      ) : (
        <img
          className="composition__image"
          src={previewUrl}
          alt={`Композиция, ревизия ${composition.revision}`}
        />
      )}

      <p className="muted">
        {composition.width}×{composition.height} · слоёв: {composition.layer_count}
      </p>

      <WarningList warnings={warnings} />

      <div className="reference__actions">
        {isDraft && (
          <button
            type="button"
            className="button button--small"
            disabled={busy}
            onClick={onEdit}
          >
            Редактировать
          </button>
        )}
        {!isApproved && (
          <button
            type="button"
            className="button button--small"
            disabled={busy}
            onClick={onRender}
          >
            Рендер
          </button>
        )}
        {canApprove && (
          <button
            type="button"
            className="button button--small button--ok"
            disabled={busy}
            onClick={onApprove}
          >
            Утвердить
          </button>
        )}
        {isApproved && (
          <button
            type="button"
            className="button button--small button--danger"
            disabled={busy}
            onClick={onSupersede}
          >
            Заменить
          </button>
        )}
      </div>
    </article>
  );
}

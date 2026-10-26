import type {
  CompositionRender,
  CompositionSummary,
  LayoutExport,
} from "../api/types";
import { StatusBadge } from "./StatusBadge";
import { WarningList } from "./WarningList";

interface CompositionPreviewProps {
  composition: CompositionSummary;
  rendered: CompositionRender | null;
  exported: LayoutExport | null;
  busy: boolean;
  onEdit: () => void;
  onRender: () => void;
  onApprove: () => void;
  onSupersede: () => void;
  onExport: (size: number, mode: "crop" | "pad") => void;
}

export function CompositionPreview({
  composition,
  rendered,
  exported,
  busy,
  onEdit,
  onRender,
  onApprove,
  onSupersede,
  onExport,
}: CompositionPreviewProps) {
  const previewUrl = rendered?.content_url ?? composition.preview_content_url;
  const warnings = rendered?.warnings ?? [];
  const isDraft = composition.status === "draft";
  const isApproved = composition.status === "approved";
  const canApprove = isDraft && composition.preview_artifact_id !== null;
  const isLayoutMockup =
    composition.layout_mockup || rendered?.is_layout_mockup === true;
  const canExport = composition.preview_artifact_id !== null || rendered !== null;

  return (
    <article className="composition">
      <div className="card__head">
        <h3>Ревизия {composition.revision}</h3>
        <div className="reference__meta">
          <StatusBadge status={composition.status} />
          {isLayoutMockup && <span className="badge badge--warn">layout mockup</span>}
        </div>
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

      {isLayoutMockup && (
        <p className="warn">
          layout mockup: непрозрачный персонаж закрывает фон. Кадр не считается финальным
          keyframe; matting — отдельный эксперимент.
        </p>
      )}

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

      {canExport && (
        <div className="export">
          <p className="muted">Экспорт для LTX PoC: 512×512 без растяжения.</p>
          <div className="reference__actions">
            <button
              type="button"
              className="button button--small"
              disabled={busy}
              onClick={() => onExport(512, "crop")}
            >
              Экспорт 512 crop
            </button>
            <button
              type="button"
              className="button button--small"
              disabled={busy}
              onClick={() => onExport(512, "pad")}
            >
              Экспорт 512 pad
            </button>
          </div>
          {exported !== null && (
            <p className="muted">
              {exported.size}×{exported.size} · {exported.mode} ·{" "}
              <a className="link" href={exported.content_url} target="_blank" rel="noreferrer">
                открыть файл
              </a>
              {exported.is_layout_mockup && " · layout mockup"}
            </p>
          )}
        </div>
      )}
    </article>
  );
}

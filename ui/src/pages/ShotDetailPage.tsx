import { useEffect, useState } from "react";

import { api } from "../api/client";
import type {
  Composition,
  CompositionRender,
  LayoutExport,
  ReferenceAsset,
  ShotDetail,
} from "../api/types";
import { CompositionEditor } from "../components/CompositionEditor";
import { CompositionPreview } from "../components/CompositionPreview";
import { ReferencePicker } from "../components/ReferencePicker";
import { ScenePlanPanel } from "../components/ScenePlanPanel";
import { ShotReferences } from "../components/ShotReferences";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";
import { useAsync } from "../hooks/useAsync";

function layerAssets(assets: ReferenceAsset[]): ReferenceAsset[] {
  return assets.filter((asset) => asset.status === "approved" || asset.kind === "uploaded");
}

export function ShotDetailPage({ shotId }: { shotId: string }) {
  const detail = useAsync(() => api.shot(shotId), [shotId]);
  const [snapshot, setSnapshot] = useState<ShotDetail | null>(null);

  useEffect(() => {
    if (detail.state.status === "ready") setSnapshot(detail.state.data);
  }, [detail.state]);

  const shot = snapshot !== null && snapshot.id === shotId ? snapshot : null;

  if (shot === null) {
    if (detail.state.status === "error") {
      return (
        <StateView
          kind="error"
          title="Не удалось загрузить шот"
          message={detail.state.error.message}
          onRetry={detail.reload}
        />
      );
    }
    return <StateView kind="loading" title="Загрузка шота" />;
  }
  return <ShotDetailBody shot={shot} onReload={detail.reload} />;
}

function ShotDetailBody({ shot, onReload }: { shot: ShotDetail; onReload: () => void }) {
  const references = useAsync(
    () => api.projectReferences(shot.project_id),
    [shot.project_id],
  );
  const assets = references.state.status === "ready" ? references.state.data : [];
  const availableAssets = layerAssets(assets);

  const [editing, setEditing] = useState<Composition | null | "new">(null);
  const [rendered, setRendered] = useState<Record<number, CompositionRender>>({});
  const [exports, setExports] = useState<Record<number, LayoutExport>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const approvedRevision =
    shot.composition_revisions.find(
      (composition) => composition.status === "approved" && composition.preview_artifact_id,
    ) ?? null;

  async function run(
    key: string,
    action: () => Promise<unknown>,
    after?: (result: unknown) => void,
  ): Promise<void> {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      const result = await action();
      after?.(result);
      onReload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }

  function edit(revision: number): void {
    void run(`edit-${revision}`, () => api.composition(shot.id, revision), (result) =>
      setEditing(result as Composition),
    );
  }

  function render(revision: number): void {
    void run(
      `render-${revision}`,
      () => api.renderComposition(shot.id, revision),
      (result) =>
        setRendered((current) => ({
          ...current,
          [revision]: result as CompositionRender,
        })),
    );
  }

  function exportLayout(revision: number, size: number, mode: "crop" | "pad"): void {
    void run(
      `export-${revision}`,
      () => api.exportLayout(shot.id, revision, size, mode),
      (result) =>
        setExports((current) => ({
          ...current,
          [revision]: result as LayoutExport,
        })),
    );
  }

  function createKeyframe(): void {
    const revision = approvedRevision?.revision ?? null;
    void run(
      "keyframe",
      () => api.keyframe(shot.id, revision),
      (result) => {
        const keyframe = result as { attempt_id: string; composition_revision: number };
        setNotice(
          `Создан keyframe из ревизии ${keyframe.composition_revision}. Сделайте его стартовым.`,
        );
      },
    );
  }

  function queueRender(): void {
    void run("queue", () => api.renderShot(shot.id), (result) => {
      const queued = result as { job_id: string };
      setNotice(`Рендер поставлен в очередь: job ${queued.job_id}`);
    });
  }

  return (
    <section className="page">
      <a className="back" href="#/shots">
        ← К шотам
      </a>

      <header className="page__head">
        <div>
          <h1>Шот {shot.sequence_no}</h1>
          <p className="muted">
            {shot.target_duration_frames === null
              ? "длительность не задана"
              : `${shot.target_duration_frames} кадров`}
            {shot.timeline_fps !== null && ` · ${shot.timeline_fps} fps`}
          </p>
        </div>
        <StatusBadge status={shot.status} />
      </header>

      {error !== null && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      {notice !== null && <p className="notice">{notice}</p>}

      <section className="panel">
        <div className="panel__head">
          <h2>Стартовый кадр</h2>
          {shot.start_keyframe_artifact_id !== null && (
            <span className="badge badge--ok">подтверждён</span>
          )}
        </div>

        <div className="shot-keyframe">
          {shot.start_keyframe_content_url === null ? (
            <div className="composition__empty">Стартовый кадр не выбран</div>
          ) : (
            <img
              className="composition__image"
              src={shot.start_keyframe_content_url}
              alt="Стартовый кадр шота"
            />
          )}

          <div className="shot-keyframe__meta">
            <p className="muted">
              {approvedRevision === null
                ? "Нет утверждённой ревизии композиции с предпросмотром."
                : `Утверждена ревизия ${approvedRevision.revision}.`}
            </p>
            {approvedRevision?.layout_mockup === true && (
              <p className="warn">
                Утверждённая композиция помечена как layout mockup: непрозрачный персонаж
                закрывает фон. Это не финальный keyframe — нужен отдельный matting.
              </p>
            )}
            <div className="reference__actions">
              <button
                type="button"
                className="button button--small"
                disabled={busy !== null || approvedRevision === null}
                onClick={createKeyframe}
              >
                {busy === "keyframe" ? "…" : "Создать keyframe"}
              </button>
              <button
                type="button"
                className="button button--small button--ok"
                disabled={busy !== null || shot.start_keyframe_artifact_id === null}
                onClick={queueRender}
              >
                {busy === "queue" ? "…" : "Запустить рендер"}
              </button>
            </div>
            {shot.start_keyframe_artifact_id === null && (
              <p className="muted">
                Рендер видео недоступен: сначала подтвердите стартовый кадр.
              </p>
            )}
          </div>
        </div>
      </section>

      <ShotReferences
        shotId={shot.id}
        links={shot.references}
        assets={availableAssets}
        onChanged={onReload}
      />

      <ReferencePicker
        projectId={shot.project_id}
        assets={assets}
        onChanged={references.reload}
      />

      <ScenePlanPanel shotId={shot.id} assets={availableAssets} onChanged={onReload} />

      <section className="panel">
        <div className="panel__head">
          <h2>Композиции</h2>
          <button
            type="button"
            className="button button--small"
            disabled={busy !== null || availableAssets.length === 0}
            onClick={() => setEditing("new")}
          >
            Новая ревизия
          </button>
        </div>

        {editing !== null && (
          <CompositionEditor
            shotId={shot.id}
            composition={editing === "new" ? null : editing}
            assets={availableAssets}
            onCancel={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              onReload();
            }}
          />
        )}

        {shot.composition_revisions.length === 0 ? (
          <StateView
            kind="empty"
            title="Ревизий нет"
            message="Соберите композицию из утверждённых референсов персонажа и локации."
          />
        ) : (
          <div className="compositions">
            {shot.composition_revisions.map((composition) => (
              <CompositionPreview
                key={composition.revision}
                composition={composition}
                rendered={rendered[composition.revision] ?? null}
                exported={exports[composition.revision] ?? null}
                busy={busy !== null}
                onEdit={() => edit(composition.revision)}
                onRender={() => render(composition.revision)}
                onExport={(size, mode) => exportLayout(composition.revision, size, mode)}
                onApprove={() =>
                  void run(`approve-${composition.revision}`, () =>
                    api.approveComposition(shot.id, composition.revision),
                  )
                }
                onSupersede={() =>
                  void run(`supersede-${composition.revision}`, () =>
                    api.supersedeComposition(shot.id, composition.revision),
                  )
                }
              />
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2>Попытки</h2>
          <span className="muted">{shot.attempts.length}</span>
        </div>

        {shot.attempts.length === 0 ? (
          <p className="muted">Попыток ещё нет.</p>
        ) : (
          <ul className="list">
            {shot.attempts.map((attempt) => (
              <li key={attempt.id} className="list__item">
                {attempt.artifact_content_url !== null && (
                  <img
                    className="thumb"
                    src={attempt.artifact_content_url}
                    alt="Кадр попытки"
                  />
                )}
                <div className="list__main">
                  <div className="list__meta">
                    <strong>{attempt.kind}</strong>
                    <StatusBadge status={attempt.status} />
                    {attempt.composition_revision !== null && (
                      <span className="muted">ревизия {attempt.composition_revision}</span>
                    )}
                    {attempt.visual_plan_revision !== null && (
                      <span className="muted">план {attempt.visual_plan_revision}</span>
                    )}
                    {attempt.job_id !== null && (
                      <span className="muted mono">job {attempt.job_id.slice(0, 8)}</span>
                    )}
                  </div>
                  <span className="muted">
                    {new Date(attempt.created_at).toLocaleString()}
                  </span>
                </div>
                {attempt.kind === "keyframe" && attempt.status === "completed" && (
                  <button
                    type="button"
                    className="button button--small"
                    disabled={
                      busy !== null || shot.start_keyframe_attempt_id === attempt.id
                    }
                    onClick={() =>
                      void run(`promote-${attempt.id}`, () =>
                        api.promoteKeyframe(shot.id, attempt.id),
                      )
                    }
                  >
                    Сделать стартовым
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}

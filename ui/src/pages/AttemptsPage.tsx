import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { AttemptListItem, SceneSummary } from "../api/types";
import { attemptMeta, isPreviewAttempt } from "../attemptMeta";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";
import { useAsync } from "../hooks/useAsync";

const PAGE_SIZE = 20;

const KIND_OPTIONS = [
  ["", "Все типы"],
  ["video", "Видео"],
  ["keyframe", "Keyframe"],
  ["postprocess", "Postprocess"],
] as const;

const STATUS_OPTIONS = [
  ["", "Все статусы"],
  ["pending", "В очереди"],
  ["running", "Идёт"],
  ["completed", "Завершён"],
  ["failed", "Ошибка"],
  ["cancelled", "Отменён"],
] as const;

/** Сравнивать можно только завершённые видео-попытки с артефактом. */
function comparable(attempt: AttemptListItem): boolean {
  // Preview-попытка — не кандидат в финальный ролик (WP-THERMAL-03/T-07).
  return (
    attempt.kind === "video" &&
    attempt.status === "completed" &&
    attempt.artifact_content_url !== null &&
    !isPreviewAttempt(attempt)
  );
}

function shotOptions(
  scenes: SceneSummary[],
  sceneId: string,
): { id: string; label: string }[] {
  return scenes
    .filter((scene) => sceneId === "" || scene.id === sceneId)
    .flatMap((scene) =>
      scene.shots.map((shot) => ({
        id: shot.id,
        label: `Сцена ${scene.sequence_no} · шот ${shot.sequence_no}`,
      })),
    );
}

export function AttemptsPage({ projectId }: { projectId: string }) {
  const [sceneId, setSceneId] = useState("");
  const [shotId, setShotId] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const scenes = useAsync(() => api.scenes(projectId), [projectId]);
  const attempts = useAsync(
    () =>
      api.projectAttempts(projectId, {
        scene_id: sceneId || undefined,
        shot_id: shotId || undefined,
        kind: kind || undefined,
        status: status || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    [projectId, sceneId, shotId, kind, status, offset],
  );

  // Выбор для сравнения относится к текущей странице и текущим фильтрам.
  useEffect(() => {
    setCompareIds([]);
  }, [projectId, sceneId, shotId, kind, status, offset]);

  const page = attempts.state.status === "ready" ? attempts.state.data : null;
  const sceneList = scenes.state.status === "ready" ? scenes.state.data : [];
  const items = page?.items ?? [];
  const compared = compareIds
    .map((id) => items.find((item) => item.id === id))
    .filter((item): item is AttemptListItem => item !== undefined);

  function reset(): void {
    setSceneId("");
    setShotId("");
    setKind("");
    setStatus("");
    setOffset(0);
  }

  function toggleCompare(attempt: AttemptListItem): void {
    setCompareIds((current) => {
      if (current.includes(attempt.id)) {
        return current.filter((id) => id !== attempt.id);
      }
      return [...current, attempt.id].slice(-2);
    });
  }

  async function makeCurrent(attempt: AttemptListItem): Promise<void> {
    setBusy(attempt.id);
    setError(null);
    setNotice(null);
    try {
      await api.approveAttempt(attempt.shot_id, attempt.id);
      setNotice(`Дубль шота ${attempt.shot_sequence_no} стал текущим.`);
      attempts.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="page">
      <header className="page__head">
        <div>
          <h1>Попытки</h1>
          <p className="muted">
            Все дубли проекта: метаданные, сравнение двух видео и выбор текущего.
          </p>
        </div>
      </header>

      <section className="panel">
        <div className="filters">
          <label className="field">
            <span>Сцена</span>
            <select
              value={sceneId}
              onChange={(event) => {
                setSceneId(event.target.value);
                setShotId("");
                setOffset(0);
              }}
            >
              <option value="">Все сцены</option>
              {sceneList.map((scene) => (
                <option key={scene.id} value={scene.id}>
                  Сцена {scene.sequence_no}
                  {scene.title !== null && ` · ${scene.title}`}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Шот</span>
            <select
              value={shotId}
              onChange={(event) => {
                setShotId(event.target.value);
                setOffset(0);
              }}
            >
              <option value="">Все шоты</option>
              {shotOptions(sceneList, sceneId).map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Тип</span>
            <select
              value={kind}
              onChange={(event) => {
                setKind(event.target.value);
                setOffset(0);
              }}
            >
              {KIND_OPTIONS.map(([option, label]) => (
                <option key={option} value={option}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Статус</span>
            <select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setOffset(0);
              }}
            >
              {STATUS_OPTIONS.map(([option, label]) => (
                <option key={option} value={option}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="button button--ghost" onClick={reset}>
            Сбросить
          </button>
        </div>
      </section>

      {error !== null && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      {notice !== null && <p className="notice">{notice}</p>}

      {compared.length === 2 && (
        <section className="panel">
          <div className="panel__head">
            <h2>Сравнение</h2>
            <button
              type="button"
              className="button button--small"
              onClick={() => setCompareIds([])}
            >
              Очистить
            </button>
          </div>
          <div className="compare">
            {compared.map((attempt) => {
              const meta = attemptMeta(attempt);
              return (
                <article key={attempt.id} className="compare__item">
                  <video
                    className="compare__video"
                    controls
                    preload="metadata"
                    src={attempt.artifact_content_url ?? undefined}
                  />
                  <div className="list__meta">
                    <strong>Шот {attempt.shot_sequence_no}</strong>
                    {isPreviewAttempt(attempt) && <span className="badge">preview</span>}
                    {attempt.approved && <span className="badge badge--ok">текущий дубль</span>}
                    {attempt.composition_revision !== null && (
                      <span className="muted">ревизия {attempt.composition_revision}</span>
                    )}
                  </div>
                  <span className="muted">
                    {new Date(attempt.created_at).toLocaleString()}
                  </span>
                  {meta.summary.length > 0 && (
                    <span className="muted mono">{meta.summary.join(" · ")}</span>
                  )}
                  {meta.parameters.length > 0 && (
                    <span className="attempt__params mono muted">
                      {meta.parameters.join(" · ")}
                    </span>
                  )}
                  <div className="reference__actions">
                    {!isPreviewAttempt(attempt) && (
                      <button
                        type="button"
                        className="button button--small button--ok"
                        disabled={busy !== null || attempt.approved}
                        onClick={() => void makeCurrent(attempt)}
                      >
                        {attempt.approved ? "Текущий" : "Сделать текущей"}
                      </button>
                    )}
                    <a className="button button--small" href={`#/shots/${attempt.shot_id}`}>
                      К шоту
                    </a>
                    <a className="button button--small" href={attempt.artifact_content_url ?? "#"}>
                      Артефакт
                    </a>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {attempts.state.status === "loading" && (
        <StateView kind="loading" title="Загрузка попыток" />
      )}

      {attempts.state.status === "error" && (
        <StateView
          kind="error"
          title="Не удалось загрузить попытки"
          message={attempts.state.error.message}
          onRetry={attempts.reload}
        />
      )}

      {page !== null && page.total === 0 && (
        <StateView
          kind="empty"
          title="Попыток нет"
          message="Измените фильтры или запустите рендер шота."
        />
      )}

      {page !== null && page.items.length > 0 && (
        <>
          <ul className="list">
            {page.items.map((attempt) => {
              const meta = attemptMeta(attempt);
              const isVideo = attempt.kind === "video";
              const selected = compareIds.includes(attempt.id);
              const canCompare = comparable(attempt);
              return (
                <li key={attempt.id} className="list__item list__item--attempt">
                  {attempt.artifact_content_url !== null &&
                    (isVideo ? (
                      <video
                        className="attempt-video"
                        controls
                        preload="metadata"
                        src={attempt.artifact_content_url}
                      />
                    ) : (
                      <img
                        className="thumb"
                        src={attempt.artifact_content_url}
                        alt="Кадр попытки"
                      />
                    ))}
                  <div className="list__main">
                    <div className="list__meta">
                      <a href={`#/shots/${attempt.shot_id}`}>
                        <strong>Шот {attempt.shot_sequence_no}</strong>
                      </a>
                      {attempt.scene_title !== null && (
                        <span className="muted">{attempt.scene_title}</span>
                      )}
                      <span className="muted">{attempt.kind}</span>
                      <StatusBadge status={attempt.status} />
                      {isPreviewAttempt(attempt) && <span className="badge">preview</span>}
                      {attempt.approved && (
                        <span className="badge badge--ok">утверждённый дубль</span>
                      )}
                      {attempt.job_id !== null && (
                        <span className="muted mono">job {attempt.job_id.slice(0, 8)}</span>
                      )}
                    </div>
                    <span className="muted">
                      {new Date(attempt.created_at).toLocaleString()}
                    </span>
                    {meta.summary.length > 0 && (
                      <span className="muted mono">{meta.summary.join(" · ")}</span>
                    )}
                    {meta.parameters.length > 0 && (
                      <span className="attempt__params mono muted">
                        {meta.parameters.join(" · ")}
                      </span>
                    )}
                  </div>
                  <div className="list__actions">
                    {canCompare && (
                      <label className="field field--inline">
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={!selected && compareIds.length >= 2}
                          onChange={() => toggleCompare(attempt)}
                        />
                        <span>Сравнить</span>
                      </label>
                    )}
                    {canCompare && (
                      <button
                        type="button"
                        className="button button--small button--ok"
                        disabled={busy !== null || attempt.approved}
                        onClick={() => void makeCurrent(attempt)}
                      >
                        {attempt.approved ? "Текущий" : "Сделать текущей"}
                      </button>
                    )}
                    <a className="button button--small" href={`#/shots/${attempt.shot_id}`}>
                      К шоту
                    </a>
                  </div>
                </li>
              );
            })}
          </ul>

          <div className="pager">
            <button
              type="button"
              className="button button--small"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              ← Назад
            </button>
            <span className="muted">
              {offset + 1}–{Math.min(offset + page.limit, page.total)} из {page.total}
            </span>
            <button
              type="button"
              className="button button--small"
              disabled={offset + page.limit >= page.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Вперёд →
            </button>
          </div>
        </>
      )}
    </section>
  );
}

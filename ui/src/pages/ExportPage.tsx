import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";

import { api } from "../api/client";
import type { ExportResult } from "../api/types";
import { StateView } from "../components/StateView";
import { useAsync } from "../hooks/useAsync";

interface Candidate {
  shotId: string;
  attemptId: string;
  sceneNo: number;
  shotNo: number;
  durationS: number | null;
  seed: number | null;
}

/** Шоты с утверждённым дублем в порядке сцен и шотов. */
async function loadCandidates(projectId: string): Promise<Candidate[]> {
  const scenes = await api.scenes(projectId);
  const approved = scenes.flatMap((scene) =>
    scene.shots
      .filter((shot) => shot.approved_attempt_id !== null)
      .map((shot) => ({ sceneNo: scene.sequence_no, shot })),
  );
  const details = await Promise.all(approved.map(({ shot }) => api.shot(shot.id)));
  return approved.flatMap(({ sceneNo, shot }, index) => {
    const attempt = details[index].attempts.find(
      (item) => item.id === shot.approved_attempt_id,
    );
    if (attempt === undefined || attempt.artifact_content_url === null) return [];
    return [
      {
        shotId: shot.id,
        attemptId: attempt.id,
        sceneNo,
        shotNo: shot.sequence_no,
        durationS: attempt.duration_s,
        seed: attempt.seed,
      },
    ];
  });
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

/** Сборка вертикального MP4 из утверждённых попыток (WP-M2). */
export function ExportPage({ projectId }: { projectId: string }) {
  const candidates = useAsync(() => loadCandidates(projectId), [projectId]);
  const exportsList = useAsync(() => api.exports(projectId), [projectId]);

  const [selected, setSelected] = useState<string[]>([]);
  const [initialized, setInitialized] = useState(false);
  const [audio, setAudio] = useState<{ id: string; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ExportResult | null>(null);

  const data = candidates.state.status === "ready" ? candidates.state.data : [];

  useEffect(() => {
    setInitialized(false);
    setSelected([]);
    setAudio(null);
    setResult(null);
  }, [projectId]);

  useEffect(() => {
    if (initialized || candidates.state.status !== "ready") return;
    setSelected(candidates.state.data.map((item) => item.shotId));
    setInitialized(true);
  }, [initialized, candidates.state]);

  function toggle(shotId: string): void {
    setSelected((current) =>
      current.includes(shotId)
        ? current.filter((value) => value !== shotId)
        : [...current, shotId],
    );
  }

  async function pickAudio(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    if (file === undefined) return;
    setBusy(true);
    setError(null);
    try {
      const artifact = await api.uploadArtifact(file, "export_audio");
      setAudio({ id: artifact.id, name: file.name });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  async function build(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const clips = data
        .filter((item) => selected.includes(item.shotId))
        .map((item) => ({ shot_id: item.shotId, attempt_id: item.attemptId }));
      const created = await api.createExport(projectId, {
        clips,
        audio_artifact_id: audio?.id,
      });
      setResult(created);
      exportsList.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  if (candidates.state.status === "loading" || exportsList.state.status === "loading") {
    return <StateView kind="loading" title="Загрузка данных для сборки" />;
  }
  if (candidates.state.status === "error") {
    return (
      <StateView
        kind="error"
        title="Не удалось загрузить шоты"
        message={candidates.state.error.message}
        onRetry={candidates.reload}
      />
    );
  }

  const ordered = data.filter((item) => selected.includes(item.shotId));
  const totalSeconds = ordered.reduce((sum, item) => sum + (item.durationS ?? 0), 0);
  const exports = exportsList.state.status === "ready" ? exportsList.state.data : [];

  return (
    <section className="page">
      <header className="page__head">
        <div>
          <h1>Сборка</h1>
          <p className="muted">
            Вертикальный MP4 1080×1920, 24 fps из утверждённых дублей. Исходные ролики
            не изменяются; каждый клип вписывается в кадр без растяжения.
          </p>
        </div>
      </header>

      <section className="panel">
        <div className="panel__head">
          <h2>Клипы</h2>
          <span className="muted">
            выбрано {ordered.length} из {data.length}
          </span>
        </div>
        {data.length === 0 ? (
          <p className="notice">
            Нет утверждённых дублей. Утвердите видео на странице шота — здесь появится клип.
          </p>
        ) : (
          <ul className="list">
            {data.map((item) => (
              <li key={item.shotId} className="list__item">
                <label className="list__main">
                  <span>
                    <input
                      type="checkbox"
                      checked={selected.includes(item.shotId)}
                      onChange={() => toggle(item.shotId)}
                    />{" "}
                    <strong>
                      Сцена {item.sceneNo} · шот {item.shotNo}
                    </strong>
                  </span>
                  <span className="muted">
                    {item.durationS === null ? "длительность неизвестна" : `${item.durationS.toFixed(2)} с`}
                    {item.seed !== null && ` · seed ${item.seed}`}
                  </span>
                </label>
                <a className="link" href={`#/shots/${item.shotId}`}>
                  к шоту
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2>Звук</h2>
        <p className="muted">
          Без файла сохраняется звук клипов (у клипов без аудио — тишина). Загруженная
          дорожка заменяет звук целиком и обрезается по длине видео.
        </p>
        <div className="form-row">
          <label className="field field--grow">
            <span>Музыкальная дорожка</span>
            <input type="file" accept="audio/*" onChange={(event) => void pickAudio(event)} />
          </label>
          {audio !== null && (
            <div className="list__actions">
              <span className="muted">{audio.name}</span>
              <button type="button" className="button button--ghost" onClick={() => setAudio(null)}>
                Убрать
              </button>
            </div>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2>Собрать</h2>
          <span className="muted">
            {ordered.length} клип(ов) · ≈ {totalSeconds.toFixed(1)} с
          </span>
        </div>
        <div className="actions">
          <button
            type="button"
            className="button button--ok"
            disabled={busy || ordered.length === 0}
            onClick={() => void build()}
          >
            {busy ? "Собираю…" : "Собрать MP4"}
          </button>
        </div>
        {error !== null && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        {result !== null && (
          <div className="list__item list__item--attempt">
            <div className="list__main">
              <strong>Готовый ролик</strong>
              <span className="muted">
                {result.width}×{result.height} · {result.fps} fps ·{" "}
                {result.duration_s.toFixed(2)} с · {formatBytes(result.bytes)} ·{" "}
                {result.clip_count} клип(ов)
              </span>
              <span className="muted mono">sha256 {result.sha256.slice(0, 12)}…</span>
              {result.audio_artifact_id !== null && (
                <span className="muted">внешняя звуковая дорожка</span>
              )}
            </div>
            <video className="attempt-video" controls preload="metadata" src={result.content_url} />
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Экспорты проекта</h2>
        {exports.length === 0 ? (
          <p className="muted">Пока ничего не собрано.</p>
        ) : (
          <ul className="list">
            {exports.map((item) => (
              <li key={item.artifact_id} className="list__item list__item--attempt">
                <div className="list__main">
                  <strong>
                    {item.width}×{item.height} · {item.clip_count} клип(ов)
                  </strong>
                  <span className="muted">
                    {item.duration_s.toFixed(2)} с · {formatBytes(item.bytes)} ·{" "}
                    {new Date(item.created_at).toLocaleString("ru-RU")}
                  </span>
                  <span className="muted mono">sha256 {item.sha256.slice(0, 12)}…</span>
                </div>
                <video className="attempt-video" controls preload="metadata" src={item.content_url} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}

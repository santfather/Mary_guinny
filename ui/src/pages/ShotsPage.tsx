import { useState } from "react";
import type { FormEvent } from "react";

import { api } from "../api/client";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";
import { useAsync } from "../hooks/useAsync";

export function ShotsPage({ projectId }: { projectId: string }) {
  const scenes = useAsync(() => api.scenes(projectId), [projectId]);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await action();
      scenes.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  function addScene(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const value = title.trim();
    void run(async () => {
      await api.createScene(projectId, { title: value === "" ? null : value });
      setTitle("");
    });
  }

  return (
    <section className="page">
      <header className="page__head">
        <div>
          <h1>Шоты</h1>
          <p className="muted">
            Сцены и шоты проекта: привязка референсов, композиция и стартовый кадр.
          </p>
        </div>
      </header>

      <form className="panel" onSubmit={addScene}>
        <h2>Новая сцена</h2>
        <div className="form-row">
          <label className="field field--grow">
            <span>Название</span>
            <input
              type="text"
              value={title}
              placeholder="Сцена без названия"
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <button type="submit" className="button button--ok" disabled={busy}>
            {busy ? "…" : "Создать сцену"}
          </button>
        </div>
      </form>

      {error !== null && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      {scenes.state.status === "loading" && <StateView kind="loading" title="Загрузка сцен" />}

      {scenes.state.status === "error" && (
        <StateView
          kind="error"
          title="Не удалось загрузить сцены"
          message={scenes.state.error.message}
          onRetry={scenes.reload}
        />
      )}

      {scenes.state.status === "ready" && scenes.state.data.length === 0 && (
        <StateView
          kind="empty"
          title="Сцен нет"
          message="Создайте первую сцену, затем добавьте в неё шоты."
        />
      )}

      {scenes.state.status === "ready" &&
        scenes.state.data.map((scene) => (
          <section key={scene.id} className="panel">
            <div className="panel__head">
              <h2>
                Сцена {scene.sequence_no}
                {scene.title !== null && ` · ${scene.title}`}
              </h2>
              <button
                type="button"
                className="button button--small"
                disabled={busy}
                onClick={() => void run(() => api.createShot(scene.id, {}))}
              >
                Добавить шот
              </button>
            </div>

            {scene.shots.length === 0 ? (
              <p className="muted">В сцене пока нет шотов.</p>
            ) : (
              <ul className="list">
                {scene.shots.map((shot) => (
                  <li key={shot.id}>
                    <a className="list__item" href={`#/shots/${shot.id}`}>
                      <div className="list__main">
                        <strong>Шот {shot.sequence_no}</strong>
                        <span className="muted">
                          {shot.target_duration_frames === null
                            ? "длительность не задана"
                            : `${shot.target_duration_frames} кадров`}
                          {" · "}
                          {shot.start_keyframe_content_url === null
                            ? "стартовый кадр не выбран"
                            : "стартовый кадр есть"}
                        </span>
                      </div>
                      <StatusBadge status={shot.status} />
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
    </section>
  );
}

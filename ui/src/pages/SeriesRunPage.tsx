import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { SeriesRun } from "../api/types";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";

const POLL_MS = 3000;

/** Прогон серии (WP-N4): прогресс и управление последовательной генерацией. */
export function SeriesRunPage({ runId }: { runId: string }) {
  const [run, setRun] = useState<SeriesRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.seriesRun(runId).then(
      (data) => {
        setRun(data);
        setError(null);
      },
      (failure: unknown) =>
        setError(failure instanceof Error ? failure.message : String(failure)),
    );
  }, [runId]);

  useEffect(() => {
    load();
  }, [load]);

  const active = run !== null && (run.status === "running" || run.status === "stopping");

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, load]);

  async function act(action: string): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      setRun(await api.seriesAction(runId, action));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  if (error !== null && run === null) {
    return (
      <StateView
        kind="error"
        title="Не удалось загрузить прогон"
        message={error}
        onRetry={load}
      />
    );
  }

  if (run === null) {
    return <StateView kind="loading" title="Загрузка прогона" />;
  }

  const finished = run.counts.completed + run.counts.failed + run.counts.skipped;
  const percent = run.total_items === 0 ? 0 : Math.round((finished / run.total_items) * 100);

  return (
    <section className="page">
      <header className="page__head">
        <div>
          <h1>{run.title ?? "Прогон серии"}</h1>
          <p className="muted">
            Одна тяжёлая job за раз. <a href="#/shots">← к шотам</a>
          </p>
        </div>
        <StatusBadge status={run.status} />
      </header>

      <section className="panel">
        <div className="panel__head">
          <h2>
            {run.counts.completed} из {run.total_items}
          </h2>
          <span className="muted">ошибок: {run.counts.failed}</span>
        </div>
        <div className="progress" role="progressbar" aria-valuenow={percent}>
          <div className="progress__bar" style={{ width: `${percent}%` }} />
        </div>
        <p className="muted">
          В очереди: {run.counts.pending} · идёт: {run.counts.running} · пропущено:{" "}
          {run.counts.skipped} · остановка при ошибке:{" "}
          {run.stop_on_error ? "да" : "нет"}
        </p>
        <div className="actions">
          <button
            type="button"
            className="button button--ok"
            disabled={busy || (run.status !== "draft" && run.status !== "paused")}
            onClick={() => void act("start")}
          >
            Запустить
          </button>
          <button
            type="button"
            className="button"
            disabled={busy || run.status !== "running"}
            onClick={() => void act("pause")}
          >
            Пауза
          </button>
          <button
            type="button"
            className="button"
            disabled={busy || run.status !== "paused"}
            onClick={() => void act("resume")}
          >
            Продолжить
          </button>
          <button
            type="button"
            className="button"
            disabled={busy || run.status !== "running"}
            onClick={() => void act("stop-after-current")}
          >
            Остановить после текущего
          </button>
          <button
            type="button"
            className="button button--danger"
            disabled={busy || run.status === "cancelled" || run.status === "completed"}
            onClick={() => void act("cancel")}
          >
            Отменить
          </button>
        </div>
        {error !== null && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
      </section>

      <ul className="list">
        {run.items.map((item) => (
          <li key={item.order}>
            <a className="list__item" href={`#/shots/${item.shot_id}`}>
              <div className="list__main">
                <strong>
                  {item.order}. Шот {item.shot_sequence_no}
                </strong>
                <span className="muted">
                  {item.job_status === null ? "job не создана" : `job: ${item.job_status}`}
                  {item.progress !== null && ` · ${Math.round(item.progress * 100)}%`}
                  {item.error_code !== null && ` · ${item.error_code}`}
                </span>
              </div>
              <StatusBadge status={item.status} />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

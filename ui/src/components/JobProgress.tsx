import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { JobDetail } from "../api/types";
import { stageLabel, statusLabel } from "../labels";
import { StatusBadge } from "./StatusBadge";

const POLL_MS = 3000;
const ACTIVE = new Set([
  "pending",
  "leased",
  "running",
  "retry_wait",
  "cancel_requested",
  "lease_expired",
]);

/** Длительность job: для активной — до текущего момента, для завершённой — до `updated_at`. */
function elapsedLabel(start: string, end: string): string {
  const seconds = Math.max(
    0,
    Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000),
  );
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes > 0 ? `${minutes} мин ${rest} с` : `${rest} с`;
}

/**
 * Прогресс одиночной job: поллинг `GET /api/jobs/{id}`.
 * `progress` — этапная оценка воркера, а не точный процент модели.
 */
export function JobProgress({
  jobId,
  onSettled,
}: {
  jobId: string;
  onSettled: () => void;
}) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wasActive = useRef(false);

  const load = useCallback(() => {
    api.job(jobId).then(
      (data) => {
        setJob(data);
        setError(null);
      },
      (failure: unknown) =>
        setError(failure instanceof Error ? failure.message : String(failure)),
    );
  }, [jobId]);

  useEffect(() => {
    setJob(null);
    wasActive.current = false;
    load();
  }, [load]);

  const active = job !== null && ACTIVE.has(job.status);

  useEffect(() => {
    if (!active) return;
    wasActive.current = true;
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, load]);

  useEffect(() => {
    if (job !== null && !ACTIVE.has(job.status) && wasActive.current) {
      wasActive.current = false;
      onSettled();
    }
  }, [job, onSettled]);

  if (error !== null && job === null) {
    return (
      <section className="panel">
        <div className="panel__head">
          <h2>Рендер</h2>
        </div>
        <p className="alert" role="alert">
          {error}
        </p>
      </section>
    );
  }

  if (job === null) {
    return (
      <section className="panel">
        <div className="panel__head">
          <h2>Рендер</h2>
        </div>
        <p className="muted">Загрузка статуса job…</p>
      </section>
    );
  }

  const progress = job.last_event?.progress ?? null;
  const percent = progress === null ? null : Math.round(progress * 100);
  const elapsed = elapsedLabel(
    job.created_at,
    active ? new Date().toISOString() : job.updated_at,
  );

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Рендер</h2>
        <StatusBadge status={job.status} />
      </div>
      <div
        className="progress"
        role="progressbar"
        aria-valuenow={percent ?? 0}
        aria-label="Этап рендера"
      >
        <div
          className="progress__bar"
          style={{ width: `${percent ?? 0}%` }}
        />
      </div>
      <p className="muted">
        {percent === null
          ? active
            ? "прогресс ещё не поступал"
            : statusLabel(job.status)
          : `этап ${percent}%`}
        {job.last_event?.stage != null && ` · ${stageLabel(job.last_event.stage)}`}
        {` · попытка ${job.attempts} из ${job.max_attempts}`}
        {` · ${elapsed}`}
        {job.error_code !== null && ` · ${job.error_code}`}
      </p>
      <p className="muted mono">job {job.id.slice(0, 8)} · {statusLabel(job.status)}</p>
    </section>
  );
}

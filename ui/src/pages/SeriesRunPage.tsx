import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { RenderAgentStatus, SeriesRun } from "../api/types";
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

      <RenderAgentPanel />
    </section>
  );
}

/** Read-only состояние thermal-контроля (WP-THERMAL-02, Q-29; WP-THERMAL-03). */
const PROFILE_LABELS: Record<string, string> = {
  eco: "Eco",
  balanced: "Balanced",
  off: "Off",
};

const THERMAL_LABELS: Record<string, string> = {
  nominal: "Nominal",
  fair: "Fair",
  serious: "Serious",
  critical: "Critical",
  unknown: "Unknown",
};

const POWER_LABELS: Record<string, string> = {
  ac: "сеть",
  battery: "батарея",
  unknown: "Unknown",
};

const PRESSURE_LABELS: Record<string, string> = {
  normal: "Normal",
  warning: "Warning",
  critical: "Critical",
  unknown: "Unknown",
};

function label(map: Record<string, string>, value: string | null | undefined): string {
  // Неизвестное значение — Unknown, а не пустая строка и не догадка.
  if (value === null || value === undefined || value === "") return "Unknown";
  return map[value] ?? value;
}

function humanWait(seconds: number | null): string {
  if (seconds === null || seconds <= 0) return "сейчас";
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `${minutes} мин`;
  return `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`;
}

/** Причины блокировки из `worker/thermal.py`; неизвестная причина показывается как есть. */
const REASON_LABELS: Record<string, string> = {
  guard_disabled: "защита выключена",
  thermal_nominal: "thermal: Nominal",
  thermal_fair: "thermal: Fair",
  thermal_serious: "перегрев (Serious)",
  thermal_critical: "критический перегрев (Critical)",
  thermal_unknown: "thermal: Unknown",
  thermal_recovery: "ждём восстановления thermal",
  power_not_ac: "нет питания от сети",
  power_unknown: "источник питания неизвестен",
  battery_low: "низкий заряд батареи",
  memory_pressure_critical: "критическое давление на память",
  memory_pressure_warning: "повышенное давление на память",
  memory_low: "мало свободной памяти",
  cooldown: "cooldown между шотами",
  job_failed: "job завершилась ошибкой",
};

function lowPowerLabel(value: boolean | null): string {
  if (value === null) return "Unknown";
  return value ? "включён" : "выключен";
}

function admissionLabel(allowed: boolean | null): string {
  if (allowed === null) return "Unknown";
  return allowed ? "разрешён" : "заблокирован";
}

function labelBlockReason(reason: string | null | undefined): string {
  if (reason === null || reason === undefined || reason === "") return "Unknown";
  return REASON_LABELS[reason] ?? reason;
}

function RenderAgentPanel() {
  const [status, setStatus] = useState<RenderAgentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      api.renderAgentStatus().then(
        (data) => {
          if (cancelled) return;
          setStatus(data);
          setError(null);
        },
        (failure: unknown) => {
          if (cancelled) return;
          setError(failure instanceof Error ? failure.message : String(failure));
        },
      );
    };
    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const lastEvent =
    status !== null && status.last_events.length > 0
      ? status.last_events[status.last_events.length - 1]
      : null;

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Термозащита</h2>
        <span className="muted">
          {status === null
            ? "нет данных"
            : status.worker_online
              ? "воркер на связи"
              : "воркер не активен"}
        </span>
      </div>
      {error !== null && <p className="alert">{error}</p>}
      {status !== null && (
        <>
          <p className="muted">
            Профиль: {label(PROFILE_LABELS, status.profile)} · thermal:{" "}
            {label(THERMAL_LABELS, status.thermal.state)} ({status.thermal.source})
            {status.stale && status.updated_at !== null && " · данные устарели"}
          </p>
          <p className="muted">
            Питание: {label(POWER_LABELS, status.power.source)}
            {status.power.battery_percent !== null &&
              ` · заряд ${status.power.battery_percent}%`}{" "}
            · Low Power Mode: {lowPowerLabel(status.power.low_power_mode)}
          </p>
          <p className="muted">
            Память: {label(PRESSURE_LABELS, status.memory.pressure)}
            {status.memory.available_mb !== null &&
              ` · свободно ${status.memory.available_mb} МБ`}
          </p>
          <p className="muted">
            Партия: {status.batch.index ?? 0}/{status.batch.size ?? 0} · очередь:{" "}
            {status.queue.active_render_jobs} активно, {status.queue.pending_render_jobs} ждёт
            {status.rendering && ` · рендер идёт (${status.current_job_id ?? "job"})`}
          </p>
          <p className="muted">
            Допуск: {admissionLabel(status.admission.allowed)} · до следующего задания:{" "}
            {humanWait(status.admission.wait_seconds ?? status.cooldown.remaining_seconds)}
          </p>
          {status.pause.active ? (
            <p className="alert">
              Пауза термозащиты: {labelBlockReason(status.pause.reason)}
              {status.pause.since !== null && ` · с ${status.pause.since}`}
              {status.pause.waited_seconds !== null &&
                ` · ожидание ${humanWait(status.pause.waited_seconds)}`}
              {status.cooldown.remaining_seconds !== null &&
                ` · до следующего шота ${humanWait(status.cooldown.remaining_seconds)}`}
            </p>
          ) : (
            status.admission.allowed === false && (
              <p className="alert">
                Следующее задание заблокировано: {labelBlockReason(status.admission.reason)}
                {status.queue.pending_render_jobs > 0 &&
                  ` · в очереди ${status.queue.pending_render_jobs}`}
              </p>
            )
          )}
          {lastEvent !== null && (
            <p className="muted">
              Последнее событие: {lastEvent.event ?? "Unknown"}
              {lastEvent.reason !== null && ` · ${labelBlockReason(lastEvent.reason)}`}
              {lastEvent.ts !== null && ` · ${lastEvent.ts}`}
            </p>
          )}
        </>
      )}
    </section>
  );
}

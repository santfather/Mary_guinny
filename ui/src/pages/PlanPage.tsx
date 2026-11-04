import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";

import { ApiError, api } from "../api/client";
import type { PlanWarning, ProductionPlan, ProjectAudio, Timeline } from "../api/types";
import { StateView } from "../components/StateView";
import { useAsync } from "../hooks/useAsync";

const SOURCE_LABELS: Record<string, string> = {
  llm: "LLM",
  manual: "каркас сервера",
  fallback: "fallback",
};

function clock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function WarningList({ warnings }: { warnings: PlanWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <ul className="list list--warnings">
      {warnings.map((warning, index) => (
        <li key={`${warning.code}-${index}`} className="list__item">
          <div className="list__main">
            <span className="mono">{warning.code}</span>
            <span className="muted">{warning.message}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function TimelineBar({ timeline }: { timeline: Timeline }) {
  const scale = timeline.duration_s > 0 ? timeline.duration_s : 1;
  return (
    <div className="timeline" role="img" aria-label="Энергетические секции песни">
      {timeline.sections.map((section, index) => {
        const width = ((section.end_s - section.start_s) / scale) * 100;
        return (
          <div
            key={`${section.start_s}-${index}`}
            className={`timeline__section timeline__section--${section.energy_tier}`}
            style={{ width: `${width}%` }}
            title={`${clock(section.start_s)}–${clock(section.end_s)} · ${section.energy_tier}`}
          >
            <span>{clock(section.start_s)}</span>
          </div>
        );
      })}
    </div>
  );
}

function PlanBody({ plan }: { plan: ProductionPlan }) {
  return (
    <div className="plan">
      <div className="list__meta">
        <span className="badge badge--muted">ревизия {plan.revision}</span>
        <span className="badge badge--muted">{plan.status}</span>
        <span className="badge badge--muted">
          {SOURCE_LABELS[plan.source] ?? plan.source}
        </span>
        {plan.plan.needs_review && <span className="badge badge--warn">нужна проверка</span>}
      </div>
      {plan.plan.logline !== "" && <p>{plan.plan.logline}</p>}
      {plan.plan.scenes.map((scene) => (
        <article key={scene.order} className="plan-scene">
          <header className="plan-scene__head">
            <strong>
              {scene.order}. {scene.title}
            </strong>
            <span className="muted">
              {clock(scene.start_s)}–{clock(scene.end_s)} · {scene.energy_tier}
            </span>
          </header>
          {scene.intent !== "" && <p className="muted">{scene.intent}</p>}
          <ul className="list">
            {scene.shots.map((shot) => (
              <li key={shot.order} className="list__item">
                <div className="list__main">
                  <span>
                    <strong>Шот {shot.order}</strong>{" "}
                    <span className="muted">
                      {clock(shot.start_s)}–{clock(shot.end_s)} · {shot.framing} /{" "}
                      {shot.camera_movement}
                    </span>
                  </span>
                  <span>{shot.action === "" ? <span className="muted">действие не задано</span> : shot.action}</span>
                  <span className="mono muted">{shot.prompt}</span>
                </div>
              </li>
            ))}
          </ul>
        </article>
      ))}
      {plan.plan.notes.length > 0 && (
        <div>
          <h3>Заметки</h3>
          <ul className="list">
            {plan.plan.notes.map((note, index) => (
              <li key={index} className="list__item">
                <span className="muted">{note}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Песня, таймлайн и черновой производственный план (WP-M3). */
export function PlanPage({ projectId }: { projectId: string }) {
  const plans = useAsync(() => api.productionPlans(projectId), [projectId]);

  const [audio, setAudio] = useState<ProjectAudio | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(true);
  const [brief, setBrief] = useState("");
  const [useLlm, setUseLlm] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setAudio(null);
    setTimeline(null);
    setError(null);
    setSelectedId(null);
    setLoadingAudio(true);
    api
      .projectAudio(projectId)
      .then(async (current) => {
        if (cancelled) return;
        setAudio(current);
        const analysis = await api.projectTimeline(projectId);
        if (!cancelled) setTimeline(analysis);
      })
      .catch((failure: unknown) => {
        if (cancelled) return;
        if (failure instanceof ApiError && failure.status === 409) return;
        setError(failure instanceof Error ? failure.message : String(failure));
      })
      .finally(() => {
        if (!cancelled) setLoadingAudio(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function uploadAudio(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    if (file === undefined) return;
    setBusy(true);
    setError(null);
    try {
      const artifact = await api.uploadArtifact(file, "project_audio");
      const attached = await api.attachProjectAudio(projectId, artifact.id);
      setAudio(attached);
      setTimeline(await api.projectTimeline(projectId));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  async function generate(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const created = await api.generateProductionPlan(projectId, {
        brief: brief.trim() === "" ? undefined : brief.trim(),
        use_llm: useLlm,
      });
      setSelectedId(created.id);
      plans.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  if (plans.state.status === "loading" || loadingAudio) {
    return <StateView kind="loading" title="Загрузка плана проекта" />;
  }
  if (plans.state.status === "error") {
    return (
      <StateView
        kind="error"
        title="Не удалось загрузить планы"
        message={plans.state.error.message}
        onRetry={plans.reload}
      />
    );
  }

  const revisions = plans.state.data;
  const selected = revisions.find((item) => item.id === selectedId) ?? revisions[0] ?? null;

  return (
    <section className="page">
      <header className="page__head">
        <div>
          <h1>План производства</h1>
          <p className="muted">
            Таймлайн строится из песни локально (FFmpeg), план — черновик: сцены и
            утверждённые записи не меняются. Границы секций эвристические — проверяйте
            вручную.
          </p>
        </div>
      </header>

      <section className="panel">
        <h2>Песня</h2>
        {audio === null ? (
          <p className="notice">Песня не привязана к проекту. Загрузите аудиофайл.</p>
        ) : (
          <div className="list__main">
            <span className="muted">
              {audio.mime_type} · {clock(audio.duration_s)} ·{" "}
              {Math.round(audio.bytes / 1024)} КБ
            </span>
            <audio className="plan-audio" controls preload="metadata" src={audio.content_url} />
          </div>
        )}
        <div className="form-row">
          <label className="field field--grow">
            <span>{audio === null ? "Аудиофайл" : "Заменить песню"}</span>
            <input type="file" accept="audio/*" onChange={(event) => void uploadAudio(event)} />
          </label>
        </div>
      </section>

      <section className="panel">
        <h2>Таймлайн</h2>
        {timeline === null ? (
          <p className="muted">Таймлайн появится после загрузки песни.</p>
        ) : (
          <>
            <div className="plan-stats">
              <span>
                длительность <strong>{clock(timeline.duration_s)}</strong>
              </span>
              <span>
                BPM{" "}
                <strong>{timeline.bpm === null ? "не определён" : timeline.bpm.toFixed(1)}</strong>
                {timeline.bpm !== null && ` · уверенность ${Math.round(timeline.bpm_confidence * 100)}%`}
              </span>
              <span>
                размер <strong>{timeline.meter}</strong>
              </span>
              <span>
                биты <strong>{timeline.beats.length}</strong> · секции{" "}
                <strong>{timeline.sections.length}</strong>
              </span>
            </div>
            <TimelineBar timeline={timeline} />
            <WarningList warnings={timeline.warnings} />
          </>
        )}
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2>Генерация плана</h2>
          <span className="muted">новая ревизия не меняет существующие данные</span>
        </div>
        <div className="form-row">
          <label className="field field--grow">
            <span>Замысел (необязательно)</span>
            <textarea
              rows={3}
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              placeholder="Например: ночной концерт, кот-гитарист ведёт группу"
            />
          </label>
        </div>
        <label className="list__main">
          <span>
            <input
              type="checkbox"
              checked={useLlm}
              onChange={(event) => setUseLlm(event.target.checked)}
            />{" "}
            Использовать LLM (Ollama); без него сохраняется детерминированный каркас
          </span>
        </label>
        <div className="actions">
          <button
            type="button"
            className="button button--ok"
            disabled={busy || audio === null}
            onClick={() => void generate()}
          >
            {busy ? "Генерирую…" : "Сгенерировать план"}
          </button>
        </div>
        {error !== null && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2>Черновик плана</h2>
          {selected !== null && <span className="muted">ревизия {selected.revision}</span>}
        </div>
        {selected === null ? (
          <p className="muted">Планов пока нет.</p>
        ) : (
          <>
            <WarningList warnings={selected.warnings} />
            <PlanBody plan={selected} />
          </>
        )}
      </section>

      <section className="panel">
        <h2>Ревизии</h2>
        {revisions.length === 0 ? (
          <p className="muted">Пока ничего не сгенерировано.</p>
        ) : (
          <div className="plan-revisions">
            {revisions.map((item) => (
              <button
                key={item.id}
                type="button"
                className={
                  item.id === selected?.id ? "button button--small" : "button button--small button--ghost"
                }
                onClick={() => setSelectedId(item.id)}
              >
                #{item.revision} · {item.status} · {SOURCE_LABELS[item.source] ?? item.source}
              </button>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}

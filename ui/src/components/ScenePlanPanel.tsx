import { useState } from "react";

import { api } from "../api/client";
import type { ReferenceAsset, ScenePlan } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import {
  framingLabel,
  movementLabel,
  planRoleLabel,
  planSourceLabel,
  referenceKindLabel,
} from "../labels";
import { ScenePlanEditor } from "./ScenePlanEditor";
import { StateView } from "./StateView";
import { StatusBadge } from "./StatusBadge";

interface ScenePlanPanelProps {
  shotId: string;
  assets: ReferenceAsset[];
  onChanged: () => void;
}

export function ScenePlanPanel({ shotId, assets, onChanged }: ScenePlanPanelProps) {
  const plans = useAsync(() => api.scenePlans(shotId), [shotId]);
  const [editing, setEditing] = useState<ScenePlan | "new" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const history = plans.state.status === "ready" ? plans.state.data : [];
  const approved = history.find((plan) => plan.status === "approved") ?? null;

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await action();
      plans.reload();
      onChanged();
      setNotice(success);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }

  function assetLabel(assetId: string): string {
    const asset = assets.find((item) => item.id === assetId);
    if (asset === undefined) return `${assetId.slice(0, 8)} (недоступен)`;
    return `${referenceKindLabel(asset.kind)} · ${asset.sha256.slice(0, 8)}`;
  }

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Visual Scene Plan</h2>
        <button
          type="button"
          className="button button--small"
          disabled={busy !== null}
          onClick={() => setEditing("new")}
        >
          Новый план
        </button>
      </div>

      <p className="muted">
        План связывает реальные референсы с ролями и действиями. Композиция собирается
        только из утверждённого плана; ревизии не перезаписываются.
      </p>

      {editing !== null && (
        <ScenePlanEditor
          shotId={shotId}
          plan={editing === "new" ? null : editing}
          assets={assets}
          onCancel={() => setEditing(null)}
          onSaved={(saved) => {
            setEditing(null);
            plans.reload();
            onChanged();
            setNotice(`Сохранена ревизия плана ${saved.revision} (${planSourceLabel(saved.source)}).`);
          }}
        />
      )}

      {error !== null && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {notice !== null && <p className="notice">{notice}</p>}

      {history.length === 0 ? (
        <StateView
          kind="empty"
          title="Плана ещё нет"
          message="Соберите план из утверждённых референсов: роли, действия и камера сохраняются ревизией."
        />
      ) : (
        <div className="plans">
          {history.map((plan) => (
            <article key={plan.id} className="plan">
              <div className="card__head">
                <h3>Ревизия {plan.revision}</h3>
                <div className="reference__meta">
                  <StatusBadge status={plan.status} />
                  {plan.plan.needs_review && (
                    <span className="badge badge--warn">нужна проверка</span>
                  )}
                </div>
              </div>

              <p className="muted">
                {planSourceLabel(plan.source)} · {plan.plan.canvas.width}×
                {plan.plan.canvas.height} · {framingLabel(plan.plan.camera.framing)},{" "}
                {movementLabel(plan.plan.camera.movement)} · референсов:{" "}
                {plan.plan.references.length}
              </p>

              {plan.warnings.length > 0 && (
                <ul className="warnings" role="status">
                  {plan.warnings.map((warning) => (
                    <li key={warning.code}>
                      <span className="badge badge--warn">{warning.code}</span>
                      <span className="muted">{warning.message}</span>
                    </li>
                  ))}
                </ul>
              )}

              <details className="plan__details">
                <summary>Детали плана</summary>
                <ul className="plan__refs">
                  {plan.plan.references.map((reference) => (
                    <li key={reference.alias}>
                      <span className="mono">{reference.alias}</span>
                      <span className="muted">
                        {planRoleLabel(reference.role)} · {assetLabel(reference.asset_id)}
                      </span>
                    </li>
                  ))}
                </ul>
                <p>
                  <strong>Motion prompt:</strong> {plan.plan.motion_prompt}
                </p>
                {plan.plan.initial_state.length > 0 && (
                  <>
                    <p>
                      <strong>Начальное состояние</strong>
                    </p>
                    <ul className="plan__refs">
                      {plan.plan.initial_state.map((entry, index) => (
                        <li key={index}>
                          <span className="mono">{entry.subject}</span>
                          <span className="muted">
                            {entry.position} {entry.action}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {plan.plan.action_beats.length > 0 && (
                  <>
                    <p>
                      <strong>Действия</strong>
                    </p>
                    <ul className="plan__refs">
                      {plan.plan.action_beats.map((beat) => (
                        <li key={beat.order}>
                          <span className="mono">
                            {beat.order}. {beat.subject}
                          </span>
                          <span className="muted">
                            {beat.action}
                            {beat.target === null ? "" : ` → ${beat.target}`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                <p className="muted">
                  Создан {new Date(plan.created_at).toLocaleString()}
                  {plan.approved_at === null
                    ? ""
                    : ` · утверждён ${new Date(plan.approved_at).toLocaleString()}`}
                </p>
              </details>

              <div className="reference__actions">
                {plan.status === "draft" && (
                  <>
                    <button
                      type="button"
                      className="button button--small"
                      disabled={busy !== null}
                      onClick={() => setEditing(plan)}
                    >
                      Редактировать
                    </button>
                    <button
                      type="button"
                      className="button button--small button--ok"
                      disabled={busy !== null || approved !== null}
                      title={
                        approved === null
                          ? undefined
                          : "Сначала замените утверждённую ревизию"
                      }
                      onClick={() =>
                        void run(
                          `approve-${plan.revision}`,
                          () => api.approveScenePlan(shotId, plan.revision),
                          `План ревизии ${plan.revision} утверждён.`,
                        )
                      }
                    >
                      Утвердить
                    </button>
                  </>
                )}
                {plan.status === "approved" && (
                  <>
                    <button
                      type="button"
                      className="button button--small button--ok"
                      disabled={busy !== null}
                      onClick={() =>
                        void run(
                          `composition-${plan.revision}`,
                          () => api.compositionFromPlan(shotId, plan.revision),
                          `Создана композиция из плана ревизии ${plan.revision}.`,
                        )
                      }
                    >
                      Создать композицию
                    </button>
                    <button
                      type="button"
                      className="button button--small button--danger"
                      disabled={busy !== null}
                      onClick={() =>
                        void run(
                          `supersede-${plan.revision}`,
                          () => api.supersedeScenePlan(shotId, plan.revision),
                          `План ревизии ${plan.revision} заменён.`,
                        )
                      }
                    >
                      Заменить
                    </button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

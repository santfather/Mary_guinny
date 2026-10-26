import { useState } from "react";
import type { FormEvent } from "react";

import { api } from "../api/client";
import type {
  CameraFraming,
  CameraMovement,
  PlanRole,
  ReferenceAsset,
  ScenePlan,
  ScenePlanWarning,
  ScenePlanWrite,
} from "../api/types";
import {
  framingLabel,
  movementLabel,
  planRoleLabel,
  planSourceLabel,
  referenceKindLabel,
} from "../labels";

const ROLES: PlanRole[] = ["character", "location", "prop", "style", "storyboard"];
const FRAMINGS: CameraFraming[] = ["wide", "medium", "close_up", "other"];
const MOVEMENTS: CameraMovement[] = [
  "static",
  "pan",
  "tilt",
  "dolly",
  "zoom",
  "handheld",
  "other",
];
const ALIAS_PATTERN = /^[a-z][a-z0-9_]{1,31}$/;

type PlanSource = "manual" | "llm" | "fallback";

interface ReferenceRow {
  asset_id: string;
  role: PlanRole;
  alias: string;
}

interface StateRow {
  subject: string;
  position: string;
  action: string;
}

interface BeatRow {
  subject: string;
  action: string;
  target: string;
}

interface ScenePlanEditorProps {
  shotId: string;
  plan: ScenePlan | null;
  assets: ReferenceAsset[];
  onCancel: () => void;
  onSaved: (plan: ScenePlan) => void;
}

function nextAlias(role: PlanRole, rows: ReferenceRow[]): string {
  let index = rows.filter((row) => row.role === role).length + 1;
  let alias = `${role}_${index}`;
  while (rows.some((row) => row.alias === alias)) {
    index += 1;
    alias = `${role}_${index}`;
  }
  return alias;
}

function motionPrompt(
  framing: CameraFraming,
  movement: CameraMovement,
  action: string,
): string {
  const base = `${framing} shot, ${movement} camera`;
  return action.trim() === "" ? base : `${base}; ${action.trim()}`;
}

export function ScenePlanEditor({
  shotId,
  plan,
  assets,
  onCancel,
  onSaved,
}: ScenePlanEditorProps) {
  const stored = plan?.plan ?? null;
  const [width, setWidth] = useState(stored?.canvas.width ?? 768);
  const [height, setHeight] = useState(stored?.canvas.height ?? 512);
  const [rows, setRows] = useState<ReferenceRow[]>(
    stored?.references.map((reference) => ({
      asset_id: reference.asset_id,
      role: reference.role,
      alias: reference.alias,
    })) ?? [],
  );
  const [framing, setFraming] = useState<CameraFraming>(stored?.camera.framing ?? "wide");
  const [movement, setMovement] = useState<CameraMovement>(
    stored?.camera.movement ?? "static",
  );
  const [action, setAction] = useState("");
  const [motion, setMotion] = useState(stored?.motion_prompt ?? "");
  const [states, setStates] = useState<StateRow[]>(
    stored?.initial_state.map((entry) => ({ ...entry })) ?? [],
  );
  const [beats, setBeats] = useState<BeatRow[]>(
    stored?.action_beats.map((beat) => ({
      subject: beat.subject,
      action: beat.action,
      target: beat.target ?? "",
    })) ?? [],
  );
  const [preserveIdentity, setPreserveIdentity] = useState(
    stored?.constraints.preserve_character_identity ?? true,
  );
  const [preserveLayout, setPreserveLayout] = useState(
    stored?.constraints.preserve_location_layout ?? true,
  );
  const [noExtraCharacters, setNoExtraCharacters] = useState(
    stored?.constraints.no_unreferenced_characters ?? true,
  );
  const [needsReview, setNeedsReview] = useState(stored?.needs_review ?? false);
  const [useVision, setUseVision] = useState(true);
  const [source, setSource] = useState<PlanSource>(
    (plan?.source as PlanSource | undefined) ?? "manual",
  );
  const [warnings, setWarnings] = useState<ScenePlanWarning[]>(plan?.warnings ?? []);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const aliases = rows.map((row) => row.alias);

  function update(index: number, patch: Partial<ReferenceRow>): void {
    setRows((current) =>
      current.map((row, position) => (position === index ? { ...row, ...patch } : row)),
    );
  }

  function addRow(): void {
    const asset = assets[0];
    if (asset === undefined) {
      setError("Нет утверждённых или загруженных референсов для плана.");
      return;
    }
    setRows((current) => [
      ...current,
      { asset_id: asset.id, role: "character", alias: nextAlias("character", current) },
    ]);
  }

  function updateState(index: number, patch: Partial<StateRow>): void {
    setStates((current) =>
      current.map((row, position) => (position === index ? { ...row, ...patch } : row)),
    );
  }

  function updateBeat(index: number, patch: Partial<BeatRow>): void {
    setBeats((current) =>
      current.map((row, position) => (position === index ? { ...row, ...patch } : row)),
    );
  }

  function buildWrite(): ScenePlanWrite | null {
    if (rows.length === 0) {
      setError("Добавьте хотя бы один референс.");
      return null;
    }
    const seen = new Set<string>();
    for (const row of rows) {
      if (!ALIAS_PATTERN.test(row.alias)) {
        setError(
          `Alias '${row.alias}' недопустим: латиница в нижнем регистре, цифры и _, начинается с буквы.`,
        );
        return null;
      }
      if (seen.has(row.alias)) {
        setError(`Alias '${row.alias}' повторяется.`);
        return null;
      }
      seen.add(row.alias);
    }
    if (motion.trim() === "") {
      setError("Заполните motion prompt.");
      return null;
    }
    return {
      canvas: { width, height },
      references: rows.map((row) => ({
        asset_id: row.asset_id,
        role: row.role,
        entity_id: null,
        alias: row.alias,
      })),
      camera: { framing, movement },
      initial_state: states,
      action_beats: beats.map((beat, index) => ({
        order: index + 1,
        subject: beat.subject,
        action: beat.action,
        target: beat.target === "" ? null : beat.target,
      })),
      constraints: {
        preserve_character_identity: preserveIdentity,
        preserve_location_layout: preserveLayout,
        no_unreferenced_characters: noExtraCharacters,
      },
      motion_prompt: motion,
      needs_review: needsReview,
    };
  }

  async function generate(): Promise<void> {
    setError(null);
    setNotice(null);
    if (rows.length === 0) {
      setError("Сначала добавьте референсы и alias.");
      return;
    }
    setBusy("generate");
    try {
      const candidate = await api.generateScenePlan(shotId, {
        action,
        references: rows.map((row) => ({
          asset_id: row.asset_id,
          role: row.role,
          entity_id: null,
          alias: row.alias,
        })),
        camera: { framing, movement },
        canvas: { width, height },
        use_vision: useVision,
      });
      setWidth(candidate.plan.canvas.width);
      setHeight(candidate.plan.canvas.height);
      setRows(
        candidate.plan.references.map((reference) => ({
          asset_id: reference.asset_id,
          role: reference.role,
          alias: reference.alias,
        })),
      );
      setFraming(candidate.plan.camera.framing);
      setMovement(candidate.plan.camera.movement);
      setStates(candidate.plan.initial_state);
      setBeats(
        candidate.plan.action_beats.map((beat) => ({
          subject: beat.subject,
          action: beat.action,
          target: beat.target ?? "",
        })),
      );
      setPreserveIdentity(candidate.plan.constraints.preserve_character_identity);
      setPreserveLayout(candidate.plan.constraints.preserve_location_layout);
      setNoExtraCharacters(candidate.plan.constraints.no_unreferenced_characters);
      setMotion(candidate.plan.motion_prompt);
      setNeedsReview(candidate.plan.needs_review);
      setSource(candidate.source as PlanSource);
      setWarnings(candidate.warnings);
      setNotice(
        candidate.source === "llm"
          ? "Предложение vision готово: проверьте геометрию и объекты, затем сохраните ревизию."
          : candidate.source === "fallback"
            ? "Vision недоступен: собран детерминированный план. Проверьте вручную."
            : "Собран детерминированный план без vision.",
      );
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    const write = buildWrite();
    if (write === null) return;
    setBusy("save");
    try {
      const saved =
        plan === null
          ? await api.createScenePlan(shotId, { plan: write, source, warnings })
          : await api.updateScenePlan(shotId, plan.revision, write);
      onSaved(saved);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }

  return (
    <form className="editor" onSubmit={(event) => void save(event)}>
      <div className="panel__head">
        <h3>
          {plan === null ? "Новый Visual Scene Plan" : `Правка плана ревизии ${plan.revision}`}
        </h3>
        <button
          type="button"
          className="button button--small button--ghost"
          onClick={onCancel}
        >
          Отмена
        </button>
      </div>

      <datalist id="plan-alias-options">
        {aliases.map((alias) => (
          <option key={alias} value={alias} />
        ))}
      </datalist>

      <div className="form-row">
        <label className="field field--narrow">
          <span>Ширина</span>
          <input
            type="number"
            min={1}
            max={16384}
            value={width}
            onChange={(event) => setWidth(Number(event.target.value))}
          />
        </label>
        <label className="field field--narrow">
          <span>Высота</span>
          <input
            type="number"
            min={1}
            max={16384}
            value={height}
            onChange={(event) => setHeight(Number(event.target.value))}
          />
        </label>
        <label className="field field--grow">
          <span>Действие сцены</span>
          <input
            type="text"
            value={action}
            placeholder="Guinness подходит к Marija"
            onChange={(event) => setAction(event.target.value)}
          />
        </label>
        <label className="field field--inline">
          <span>Vision (gemma3:4b)</span>
          <input
            type="checkbox"
            checked={useVision}
            onChange={(event) => setUseVision(event.target.checked)}
          />
        </label>
        <button
          type="button"
          className="button button--small"
          disabled={busy !== null}
          onClick={() => void generate()}
        >
          {busy === "generate" ? "…" : "Предложить план"}
        </button>
      </div>
      <p className="muted">
        Vision — только предложение по геометрии и объектам; утверждение всегда вручную.
        Без модели используется детерминированный fallback.
      </p>

      <div className="panel__head">
        <h3>Референсы</h3>
        <button
          type="button"
          className="button button--small"
          disabled={assets.length === 0}
          onClick={addRow}
        >
          Добавить референс
        </button>
      </div>

      {assets.length === 0 && (
        <p className="alert" role="status">
          Нет утверждённых или загруженных референсов: сначала загрузите и утвердите
          изображения персонажей и локации.
        </p>
      )}

      {rows.length > 0 && (
        <div className="layers">
          {rows.map((row, index) => (
            <div key={index} className="layer-row">
              <label className="field field--grow">
                <span>Референс</span>
                <select
                  value={row.asset_id}
                  onChange={(event) => update(index, { asset_id: event.target.value })}
                >
                  {assets.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {referenceKindLabel(asset.kind)} · {asset.status} ·{" "}
                      {asset.sha256.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Роль</span>
                <select
                  value={row.role}
                  onChange={(event) =>
                    update(index, { role: event.target.value as PlanRole })
                  }
                >
                  {ROLES.map((role) => (
                    <option key={role} value={role}>
                      {planRoleLabel(role)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Alias</span>
                <input
                  type="text"
                  value={row.alias}
                  pattern="[a-z][a-z0-9_]{1,31}"
                  onChange={(event) => update(index, { alias: event.target.value })}
                />
              </label>
              <button
                type="button"
                className="button button--small button--danger"
                onClick={() =>
                  setRows((current) => current.filter((_, position) => position !== index))
                }
              >
                Убрать
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="form-row">
        <label className="field">
          <span>Кадр</span>
          <select
            value={framing}
            onChange={(event) => setFraming(event.target.value as CameraFraming)}
          >
            {FRAMINGS.map((item) => (
              <option key={item} value={item}>
                {framingLabel(item)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Движение камеры</span>
          <select
            value={movement}
            onChange={(event) => setMovement(event.target.value as CameraMovement)}
          >
            {MOVEMENTS.map((item) => (
              <option key={item} value={item}>
                {movementLabel(item)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="button button--small"
          onClick={() => setMotion(motionPrompt(framing, movement, action))}
        >
          Собрать motion prompt
        </button>
      </div>

      <label className="field">
        <span>Motion prompt</span>
        <textarea
          className="textarea"
          rows={3}
          maxLength={4000}
          value={motion}
          onChange={(event) => setMotion(event.target.value)}
        />
      </label>

      <div className="panel__head">
        <h3>Начальное состояние</h3>
        <button
          type="button"
          className="button button--small"
          disabled={aliases.length === 0}
          onClick={() =>
            setStates((current) => [
              ...current,
              { subject: aliases[0] ?? "", position: "", action: "" },
            ])
          }
        >
          Добавить
        </button>
      </div>
      {states.map((entry, index) => (
        <div key={index} className="layer-row">
          <label className="field">
            <span>Субъект</span>
            <input
              type="text"
              list="plan-alias-options"
              value={entry.subject}
              onChange={(event) => updateState(index, { subject: event.target.value })}
            />
          </label>
          <label className="field field--grow">
            <span>Позиция</span>
            <input
              type="text"
              value={entry.position}
              onChange={(event) => updateState(index, { position: event.target.value })}
            />
          </label>
          <label className="field field--grow">
            <span>Действие</span>
            <input
              type="text"
              value={entry.action}
              onChange={(event) => updateState(index, { action: event.target.value })}
            />
          </label>
          <button
            type="button"
            className="button button--small button--danger"
            onClick={() =>
              setStates((current) => current.filter((_, position) => position !== index))
            }
          >
            Убрать
          </button>
        </div>
      ))}

      <div className="panel__head">
        <h3>Действия по порядку</h3>
        <button
          type="button"
          className="button button--small"
          disabled={aliases.length === 0}
          onClick={() =>
            setBeats((current) => [
              ...current,
              { subject: aliases[0] ?? "", action: "", target: "" },
            ])
          }
        >
          Добавить
        </button>
      </div>
      {beats.map((beat, index) => (
        <div key={index} className="layer-row">
          <label className="field">
            <span>Субъект</span>
            <input
              type="text"
              list="plan-alias-options"
              value={beat.subject}
              onChange={(event) => updateBeat(index, { subject: event.target.value })}
            />
          </label>
          <label className="field field--grow">
            <span>Действие</span>
            <input
              type="text"
              value={beat.action}
              onChange={(event) => updateBeat(index, { action: event.target.value })}
            />
          </label>
          <label className="field">
            <span>Цель</span>
            <input
              type="text"
              list="plan-alias-options"
              value={beat.target}
              onChange={(event) => updateBeat(index, { target: event.target.value })}
            />
          </label>
          <button
            type="button"
            className="button button--small button--danger"
            onClick={() =>
              setBeats((current) => current.filter((_, position) => position !== index))
            }
          >
            Убрать
          </button>
        </div>
      ))}

      <div className="form-row">
        <label className="field field--inline">
          <span>Сохранять идентичность персонажей</span>
          <input
            type="checkbox"
            checked={preserveIdentity}
            onChange={(event) => setPreserveIdentity(event.target.checked)}
          />
        </label>
        <label className="field field--inline">
          <span>Сохранять планировку локации</span>
          <input
            type="checkbox"
            checked={preserveLayout}
            onChange={(event) => setPreserveLayout(event.target.checked)}
          />
        </label>
        <label className="field field--inline">
          <span>Без персонажей вне референсов</span>
          <input
            type="checkbox"
            checked={noExtraCharacters}
            onChange={(event) => setNoExtraCharacters(event.target.checked)}
          />
        </label>
        <label className="field field--inline">
          <span>Требует ручной проверки</span>
          <input
            type="checkbox"
            checked={needsReview}
            onChange={(event) => setNeedsReview(event.target.checked)}
          />
        </label>
      </div>

      <p className="muted">
        Источник: {planSourceLabel(source)} · canvas {width}×{height}
      </p>

      {warnings.length > 0 && (
        <ul className="warnings" role="status">
          {warnings.map((warning) => (
            <li key={warning.code}>
              <span className="badge badge--warn">{warning.code}</span>
              <span className="muted">{warning.message}</span>
            </li>
          ))}
        </ul>
      )}

      {error !== null && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {notice !== null && <p className="notice">{notice}</p>}

      <div className="form-row">
        <button type="submit" className="button button--ok" disabled={busy !== null}>
          {busy === "save" ? "…" : plan === null ? "Сохранить ревизию" : "Сохранить правку"}
        </button>
      </div>
    </form>
  );
}

import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type {
  MouthAnimationResult,
  MouthCalibration,
  MouthCalibrationInput,
  ShotAudio,
  ShotDetail,
  VisemeSetReport,
  VisemeVariant,
} from "../api/types";
import { useAsync } from "../hooks/useAsync";
import {
  canApproveReference,
  canRejectReference,
  purposeLabel,
} from "../labels";
import { StatusBadge } from "./StatusBadge";

/** Один approved-кадр, к которому можно привязать калибровку рта. */
interface MouthSource {
  key: string;
  label: string;
  referenceAssetId: string | null;
  imageUrl: string | null;
}

/** Поля формы в процентах кадра: так их проще вводить руками. */
interface MouthForm {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  max_open: number;
  sensitivity: number;
  smoothing: number;
}

const DEFAULT_FORM: MouthForm = {
  x: 38,
  y: 55,
  width: 24,
  height: 16,
  rotation: 0,
  max_open: 0.8,
  sensitivity: 1,
  smoothing: 0.5,
};

const VISEME_STATES = [
  "closed",
  "small_open",
  "medium_open",
  "wide_open",
  "rounded",
] as const;

const VISEME_LABELS: Record<string, string> = {
  closed: "closed — губы сомкнуты",
  small_open: "small_open — чуть открыт",
  medium_open: "medium_open — открыт",
  wide_open: "wide_open — широко открыт",
  rounded: "rounded — округлён (О/У)",
};

type Engine = "mouth_animation_mvp" | "viseme_frame_blend_v1";

function mouthSources(shot: ShotDetail): MouthSource[] {
  const sources: MouthSource[] = shot.references
    .filter(
      (link) =>
        link.reference.status === "approved" &&
        !link.reference.multi_view &&
        (link.reference.mime_type === null ||
          link.reference.mime_type.startsWith("image/")),
    )
    .map((link) => ({
      key: `ref:${link.reference.id}`,
      label: `${purposeLabel(link.purpose)} · ${link.reference.sha256.slice(0, 8)}`,
      referenceAssetId: link.reference.id,
      imageUrl: link.reference.content_url,
    }));

  if (
    shot.start_keyframe_artifact_id !== null &&
    shot.start_keyframe_content_url !== null
  ) {
    sources.unshift({
      key: "keyframe",
      label: "Стартовый кадр шота",
      referenceAssetId: null,
      imageUrl: shot.start_keyframe_content_url,
    });
  }
  return sources;
}

function round(value: number, digits = 1): number {
  return Number(value.toFixed(digits));
}

function formFromCalibration(row: MouthCalibration | null): MouthForm {
  if (row === null) return DEFAULT_FORM;
  return {
    x: round(row.x * 100),
    y: round(row.y * 100),
    width: round(row.width * 100),
    height: round(row.height * 100),
    rotation: row.rotation,
    max_open: row.max_open,
    sensitivity: row.sensitivity,
    smoothing: row.smoothing,
  };
}

function inputFromForm(form: MouthForm, shot: ShotDetail, source: MouthSource): MouthCalibrationInput {
  return {
    ...(source.referenceAssetId !== null
      ? { reference_asset_id: source.referenceAssetId }
      : { keyframe_artifact_id: shot.start_keyframe_artifact_id ?? undefined }),
    x: round(form.x / 100, 4),
    y: round(form.y / 100, 4),
    width: round(form.width / 100, 4),
    height: round(form.height / 100, 4),
    rotation: form.rotation,
    max_open: form.max_open,
    sensitivity: form.sensitivity,
    smoothing: form.smoothing,
  };
}

function regionInvalid(form: MouthForm): boolean {
  return (
    form.x < 0 ||
    form.y < 0 ||
    form.width <= 0 ||
    form.height <= 0 ||
    form.x + form.width > 100 ||
    form.y + form.height > 100
  );
}

function isDirty(form: MouthForm, row: MouthCalibration | null): boolean {
  if (row === null) return true;
  const saved = formFromCalibration(row);
  return (
    Math.abs(form.x - saved.x) > 0.05 ||
    Math.abs(form.y - saved.y) > 0.05 ||
    Math.abs(form.width - saved.width) > 0.05 ||
    Math.abs(form.height - saved.height) > 0.05 ||
    Math.abs(form.rotation - saved.rotation) > 0.05 ||
    Math.abs(form.max_open - saved.max_open) > 0.005 ||
    Math.abs(form.sensitivity - saved.sensitivity) > 0.005 ||
    Math.abs(form.smoothing - saved.smoothing) > 0.005
  );
}

function Waveform({ peaks }: { peaks: number[] }) {
  if (peaks.length === 0) return null;
  const max = Math.max(...peaks, 1e-9);
  return (
    <svg
      className="waveform"
      viewBox={`0 0 ${peaks.length} 100`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Огибающая записи"
    >
      {peaks.map((peak, index) => {
        const height = Math.max(2, (peak / max) * 96);
        return (
          <rect
            key={index}
            x={index + 0.1}
            y={(100 - height) / 2}
            width={0.8}
            height={height}
          />
        );
      })}
    </svg>
  );
}

function timingError(text: string): string | null {
  if (text.trim() === "") return null;
  try {
    JSON.parse(text);
    return null;
  } catch {
    return "viseme timing JSON не разбирается";
  }
}

function percent(value: number | undefined): string {
  return value === undefined ? "—" : `${(value * 100).toFixed(2)}%`;
}

interface MouthAnimationPanelProps {
  shot: ShotDetail;
  onChanged: () => void;
}

/**
 * WP-VOICE-02: «Озвучка» в Shot Editor.
 *
 * Импорт готовой записи (оригинал не меняется), библиотека записей с ручным
 * утверждением, калибровка области рта, предпросмотр закрытого/открытого рта и
 * Talking Preview `mouth_animation_mvp`. Результат — обычная видео-попытка,
 * которую человек утверждает существующим review.
 */
export function MouthAnimationPanel({ shot, onChanged }: MouthAnimationPanelProps) {
  const library = useAsync(() => api.shotAudio(shot.id), [shot.id]);
  const calibrations = useAsync(() => api.mouthCalibrations(shot.id), [shot.id]);

  const sources = mouthSources(shot);
  const [sourceKey, setSourceKey] = useState(sources[0]?.key ?? "");
  const [audioId, setAudioId] = useState("");
  const [form, setForm] = useState<MouthForm>(DEFAULT_FORM);
  const [previews, setPreviews] = useState<{
    closed: string | null;
    open: string | null;
  }>({ closed: null, open: null });
  const [result, setResult] = useState<MouthAnimationResult | null>(null);
  const [engine, setEngine] = useState<Engine>("mouth_animation_mvp");
  const [timingText, setTimingText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const source = sources.find((item) => item.key === sourceKey) ?? sources[0] ?? null;
  const audio = library.state.status === "ready" ? library.state.data : [];
  const chosen =
    audio.find((item) => item.reference_asset_id === audioId) ??
    audio.find((item) => item.selected) ??
    null;
  const rows = calibrations.state.status === "ready" ? calibrations.state.data : [];
  const calibration =
    source === null
      ? null
      : (rows.find((row) =>
          source.referenceAssetId !== null
            ? row.reference_asset_id === source.referenceAssetId
            : row.keyframe_artifact_id === shot.start_keyframe_artifact_id,
        ) ?? null);

  const waveform = useAsync(
    () =>
      chosen === null
        ? Promise.resolve(null)
        : api.shotAudioWaveform(shot.id, chosen.reference_asset_id, 400),
    [shot.id, chosen?.reference_asset_id ?? ""],
  );

  // WP-VOICE-06: набор viseme-кадров проверяется для выбранного источника и калибровки.
  const visemeReport = useAsync<VisemeSetReport | null>(
    () =>
      source === null || calibration === null
        ? Promise.resolve(null)
        : api.visemeSet(
            shot.id,
            source.referenceAssetId ?? undefined,
            calibration.id,
          ),
    [shot.id, source?.key ?? "", calibration?.id ?? ""],
  );
  const viseme =
    visemeReport.state.status === "ready" ? visemeReport.state.data : null;

  const peaks =
    waveform.state.status === "ready" && waveform.state.data !== null
      ? waveform.state.data.peaks
      : [];

  // Источник мог исчезнуть после reload (например, keyframe заменили).
  const sourceKeys = sources.map((item) => item.key).join("|");
  useEffect(() => {
    if (sources.length > 0 && !sources.some((item) => item.key === sourceKey)) {
      setSourceKey(sources[0].key);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKeys, sourceKey]);

  // Выбранная запись: серверный флаг selected, иначе самая свежая.
  const audioIds = audio.map((item) => item.reference_asset_id).join("|");
  useEffect(() => {
    if (audio.length === 0) return;
    if (audio.some((item) => item.reference_asset_id === audioId)) return;
    const fallback = audio.find((item) => item.selected) ?? audio[0];
    setAudioId(fallback.reference_asset_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioIds, audioId]);

  // Сохранённая калибровка подставляется в форму при смене источника/записи.
  const calibrationKey =
    calibration === null ? "none" : `${calibration.id}:${calibration.updated_at}`;
  const appliedCalibration = useRef("");
  useEffect(() => {
    const key = `${source?.key ?? "none"}|${calibrationKey}`;
    if (appliedCalibration.current === key) return;
    appliedCalibration.current = key;
    setForm(formFromCalibration(calibration));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source?.key, calibrationKey]);

  const previewRef = useRef(previews);
  previewRef.current = previews;
  useEffect(
    () => () => {
      for (const url of Object.values(previewRef.current)) {
        if (url !== null) URL.revokeObjectURL(url);
      }
    },
    [],
  );

  async function run(
    key: string,
    action: () => Promise<void>,
  ): Promise<void> {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }

  function upload(file: File | null): void {
    if (file === null) return;
    void run("upload", async () => {
      const item = await api.uploadShotAudio(shot.id, file);
      setAudioId(item.reference_asset_id);
      library.reload();
      onChanged();
      setNotice(
        item.status === "approved"
          ? "Такая запись уже утверждена — она выбрана для шота."
          : "Запись добавлена черновиком: оригинал сохранён без изменений, утвердите его вручную.",
      );
    });
  }

  function reviewAudio(item: ShotAudio, decision: "approve" | "reject"): void {
    void run(`${decision}-${item.reference_asset_id}`, async () => {
      if (decision === "approve") await api.approve(item.reference_asset_id);
      else await api.reject(item.reference_asset_id);
      library.reload();
      onChanged();
      if (decision === "approve") setAudioId(item.reference_asset_id);
      setNotice(
        decision === "approve"
          ? "Запись утверждена и стала выбранной для шота. Прежние записи не удалены."
          : "Запись отклонена. Утверждённая запись остаётся выбранной.",
      );
    });
  }

  function saveCalibration(): void {
    if (source === null) return;
    void run("calibration", async () => {
      const saved = await api.saveMouthCalibration(
        shot.id,
        inputFromForm(form, shot, source),
      );
      calibrations.reload();
      setNotice(
        `Калибровка сохранена (${saved.id.slice(0, 8)}). Approved-изображение не изменялось.`,
      );
    });
  }

  function preview(state: "closed" | "open"): void {
    if (source === null) return;
    void run(`preview-${state}`, async () => {
      const url = await api.mouthCalibrationPreview(
        shot.id,
        inputFromForm(form, shot, source),
        state,
      );
      setPreviews((current) => {
        const previous = current[state];
        if (previous !== null) URL.revokeObjectURL(previous);
        return { ...current, [state]: url };
      });
    });
  }

  function uploadViseme(state: string, file: File | null): void {
    if (file === null) return;
    void run(`viseme-${state}`, async () => {
      const variant = await api.uploadViseme(shot.id, state, file);
      visemeReport.reload();
      setNotice(
        variant.status === "approved"
          ? `${state}: этот кадр уже утверждён и взят в набор.`
          : `${state}: кадр добавлен черновиком. Approved-источник не изменялся.`,
      );
    });
  }

  function reviewViseme(
    variant: VisemeVariant,
    decision: "approve" | "reject",
  ): void {
    const assetId = variant.reference_asset_id;
    if (assetId === null) return;
    void run(`${decision}-viseme-${variant.state}`, async () => {
      if (decision === "approve") await api.approve(assetId);
      else await api.reject(assetId);
      visemeReport.reload();
      onChanged();
      setNotice(
        decision === "approve"
          ? `${variant.state}: кадр утверждён человеком.`
          : `${variant.state}: кадр отклонён и не попадёт в набор.`,
      );
    });
  }

  function generate(): void {
    if (source === null || chosen === null || calibration === null) return;
    void run("generate", async () => {
      let timing: unknown;
      if (engine === "viseme_frame_blend_v1" && timingText.trim() !== "") {
        try {
          timing = JSON.parse(timingText);
        } catch {
          throw new Error("viseme timing JSON не разбирается: исправьте текст");
        }
      }
      const created = await api.createMouthAnimation(shot.id, {
        source_kind: "image",
        reference_asset_id: source.referenceAssetId ?? undefined,
        audio_asset_id: chosen.reference_asset_id,
        calibration_id: calibration.id,
        engine,
        ...(timing === undefined ? {} : { timing }),
      });
      setResult(created);
      onChanged();
      setNotice(
        engine === "viseme_frame_blend_v1"
          ? "Сборка из viseme-кадров создана как видео-попытка: утвердите или отклоните её в блоке «Попытки»."
          : "Talking Preview создан как обычная видео-попытка: утвердите или отклоните его в блоке «Попытки».",
      );
    });
  }

  const blockers: string[] = [];
  if (source === null) {
    blockers.push("нужен approved-референс изображения или утверждённый стартовый кадр");
  }
  if (chosen === null) {
    blockers.push("запись не выбрана: импортируйте аудио");
  } else if (chosen.status !== "approved") {
    blockers.push("запись не утверждена человеком");
  }
  if (calibration === null) {
    blockers.push("калибровка области рта не сохранена");
  } else if (regionInvalid(form)) {
    blockers.push("область рта выходит за кадр");
  } else if (isDirty(form, calibration)) {
    blockers.push("есть несохранённые изменения калибровки — сохраните её");
  }
  if (engine === "viseme_frame_blend_v1") {
    if (source === null || calibration === null) {
      blockers.push("нужны источник и калибровка, чтобы проверить набор viseme");
    } else if (viseme === null) {
      blockers.push("отчёт набора viseme не загружен — обновите его");
    } else if (!viseme.ready) {
      blockers.push("набор viseme не прошёл проверку совместимости");
    }
    if (timingText.trim() === "") {
      blockers.push("нужен viseme timing JSON");
    } else {
      const message = timingError(timingText);
      if (message !== null) blockers.push(message);
    }
  }
  const blocked = blockers.length > 0;

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Озвучка: Talking Preview</h2>
        <span className="badge">{engine}</span>
      </div>
      <p className="muted">
        Готовая запись + approved-изображение → MP4, локально и без GPU. Legacy
        `mouth_animation_mvp` считает раскрытие рта по громкости; новый
        `viseme_frame_blend_v1` собирает кадры из пяти согласованных изображений
        морды и не рисует маску поверх кадра.
      </p>

      <div className="mouth-block">
        <h3>1. Источник кадра</h3>
        {sources.length === 0 ? (
          <p className="warn">
            Нет approved-изображения: привяжите и утвердите референс персонажа или
            подтвердите стартовый кадр шота.
          </p>
        ) : (
          <div className="form-row">
            <label className="field field--grow">
              <span>Режим</span>
              <select value="image" disabled>
                <option value="image">Image Talking (mouth_animation_mvp)</option>
                <option value="video">Video Talking — Not Supported</option>
              </select>
            </label>
            <label className="field field--grow">
              <span>Кадр</span>
              <select
                value={source?.key ?? ""}
                onChange={(event) => setSourceKey(event.target.value)}
              >
                {sources.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        <p className="muted">
          Video Talking не поддерживается: надёжного tracking морды в проекте нет,
          поэтому статичная маска на движущееся видео не накладывается. Используйте
          image-режим.
        </p>
      </div>

      <div className="mouth-block">
        <div className="panel__head">
          <h3>2. Запись (Import Audio / Audio Library)</h3>
          <span className="muted">{audio.length}</span>
        </div>
        <div className="form-row">
          <label className="field field--grow">
            <span>Import Audio: WAV, MP3, M4A, AAC</span>
            <input
              type="file"
              accept=".wav,.mp3,.m4a,.aac,audio/wav,audio/x-wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/aac"
              disabled={busy !== null}
              onChange={(event) => {
                upload(event.target.files?.[0] ?? null);
                event.target.value = "";
              }}
            />
          </label>
        </div>

        {library.state.status === "error" && (
          <p className="alert" role="alert">
            {library.state.error.message}
          </p>
        )}

        {audio.length === 0 ? (
          <p className="muted">
            Записей нет. Импортируйте готовый файл: оригинал сохраняется без
            изменений, рядом создаётся рабочая копия 48 кГц mono.
          </p>
        ) : (
          <ul className="list">
            {audio.map((item) => {
              const active = chosen?.reference_asset_id === item.reference_asset_id;
              return (
                <li key={item.link_id} className="list__item list__item--attempt">
                  <div className="list__main">
                    <div className="list__meta">
                      <label className="mouth-pick">
                        <input
                          type="radio"
                          name="shot-audio"
                          checked={active}
                          onChange={() => setAudioId(item.reference_asset_id)}
                        />
                        <strong>
                          {item.original_name ?? item.sha256.slice(0, 8)}
                        </strong>
                      </label>
                      <StatusBadge status={item.status} />
                      {item.selected && (
                        <span className="badge badge--ok">выбрана</span>
                      )}
                    </div>
                    <span className="muted">
                      {item.duration_s.toFixed(2)} с ·{" "}
                      {item.sample_rate ?? "?"} Гц · {item.channels ?? "?"} кан. ·{" "}
                      {item.codec ?? "?"}
                      {item.speech_ratio !== null &&
                        ` · речь ${Math.round(item.speech_ratio * 100)}%`}
                    </span>
                    <span className="muted mono">{item.sha256.slice(0, 16)}</span>
                    <audio
                      className="audio-inline"
                      controls
                      preload="none"
                      src={item.content_url}
                    />
                  </div>
                  <div className="list__actions">
                    <button
                      type="button"
                      className="button button--small button--ok"
                      disabled={busy !== null || !canApproveReference(item.status)}
                      onClick={() => reviewAudio(item, "approve")}
                    >
                      Approve Audio
                    </button>
                    <button
                      type="button"
                      className="button button--small button--danger"
                      disabled={busy !== null || !canRejectReference(item.status)}
                      onClick={() => reviewAudio(item, "reject")}
                    >
                      Отклонить
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {chosen !== null && (
          <div className="mouth-audio">
            <Waveform peaks={peaks} />
            <span className="muted">
              {chosen.duration_s.toFixed(2)} с · рабочая копия{" "}
              {chosen.work_sample_rate} Гц / {chosen.work_channels} кан. · речевых
              участков {chosen.speech_segments.length}, пауз{" "}
              {chosen.silence_segments.length}
            </span>
          </div>
        )}
      </div>

      <div className="mouth-block">
        <h3>3. Калибровка рта (Calibrate Mouth)</h3>
        {source === null ? (
          <p className="muted">Сначала выберите источник кадра.</p>
        ) : (
          <>
            <div className="mouth-grid">
              <div className="mouth-canvas">
                <img src={source.imageUrl ?? ""} alt="Источник кадра" />
                <span
                  className="mouth-region"
                  style={{
                    left: `${form.x}%`,
                    top: `${form.y}%`,
                    width: `${form.width}%`,
                    height: `${form.height}%`,
                    transform: `rotate(${form.rotation}deg)`,
                  }}
                />
              </div>
              <div className="mouth-form">
                <div className="form-row">
                  <label className="field">
                    <span>X, %</span>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={form.x}
                      onChange={(event) =>
                        setForm({ ...form, x: Number(event.target.value) })
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Y, %</span>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={form.y}
                      onChange={(event) =>
                        setForm({ ...form, y: Number(event.target.value) })
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Ширина, %</span>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      step={1}
                      value={form.width}
                      onChange={(event) =>
                        setForm({ ...form, width: Number(event.target.value) })
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Высота, %</span>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      step={1}
                      value={form.height}
                      onChange={(event) =>
                        setForm({ ...form, height: Number(event.target.value) })
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Поворот, °</span>
                    <input
                      type="number"
                      min={-180}
                      max={180}
                      step={1}
                      value={form.rotation}
                      onChange={(event) =>
                        setForm({ ...form, rotation: Number(event.target.value) })
                      }
                    />
                  </label>
                </div>
                <label className="field">
                  <span>max_open: {form.max_open.toFixed(2)}</span>
                  <input
                    type="range"
                    min={0.05}
                    max={1}
                    step={0.05}
                    value={form.max_open}
                    onChange={(event) =>
                      setForm({ ...form, max_open: Number(event.target.value) })
                    }
                  />
                </label>
                <label className="field">
                  <span>sensitivity: {form.sensitivity.toFixed(2)}</span>
                  <input
                    type="range"
                    min={0.2}
                    max={3}
                    step={0.1}
                    value={form.sensitivity}
                    onChange={(event) =>
                      setForm({ ...form, sensitivity: Number(event.target.value) })
                    }
                  />
                </label>
                <label className="field">
                  <span>smoothing: {form.smoothing.toFixed(2)}</span>
                  <input
                    type="range"
                    min={0}
                    max={0.95}
                    step={0.05}
                    value={form.smoothing}
                    onChange={(event) =>
                      setForm({ ...form, smoothing: Number(event.target.value) })
                    }
                  />
                </label>

                <div className="reference__actions">
                  <button
                    type="button"
                    className="button button--small"
                    disabled={busy !== null || regionInvalid(form)}
                    onClick={saveCalibration}
                  >
                    {busy === "calibration" ? "…" : "Сохранить калибровку"}
                  </button>
                  <button
                    type="button"
                    className="button button--small"
                    disabled={busy !== null || regionInvalid(form)}
                    onClick={() => preview("closed")}
                  >
                    Рот закрыт
                  </button>
                  <button
                    type="button"
                    className="button button--small"
                    disabled={busy !== null || regionInvalid(form)}
                    onClick={() => preview("open")}
                  >
                    Рот открыт
                  </button>
                </div>
                {calibration !== null && (
                  <span className="muted mono">
                    калибровка {calibration.id.slice(0, 8)}
                  </span>
                )}
              </div>
            </div>

            {(previews.closed !== null || previews.open !== null) && (
              <div className="mouth-previews">
                {previews.closed !== null && (
                  <figure>
                    <img src={previews.closed} alt="Предпросмотр: рот закрыт" />
                    <figcaption className="muted">закрытый рот</figcaption>
                  </figure>
                )}
                {previews.open !== null && (
                  <figure>
                    <img src={previews.open} alt="Предпросмотр: рот открыт" />
                    <figcaption className="muted">открытый рот</figcaption>
                  </figure>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <div className="mouth-block">
        <div className="panel__head">
          <h3>4. Viseme-кадры (photorealistic)</h3>
          <span className="badge">viseme_frame_blend_v1</span>
        </div>
        <p className="muted">
          Пять кадров одной морды: closed, small_open, medium_open, wide_open,
          rounded. Кадры готовятся вне системы и импортируются как файлы:
          approved-источник не изменяется, автоматической генерации нет.
        </p>
        {source === null || calibration === null ? (
          <p className="muted">
            Сначала выберите источник кадра и сохраните калибровку области рта.
          </p>
        ) : (
          <>
            {visemeReport.state.status === "error" && (
              <p className="alert" role="alert">
                {visemeReport.state.error.message}
              </p>
            )}
            <ul className="viseme-set">
              {VISEME_STATES.map((state) => {
                const variant =
                  viseme?.variants.find((item) => item.state === state) ?? null;
                return (
                  <li key={state} className="viseme-slot">
                    {variant === null || variant.content_url === "" ? (
                      <div className="viseme-slot__empty">нет кадра</div>
                    ) : (
                      <img src={variant.content_url} alt={`viseme ${state}`} />
                    )}
                    <div className="list__meta">
                      <strong>{VISEME_LABELS[state]}</strong>
                      {variant !== null && <StatusBadge status={variant.status} />}
                      {variant?.implicit === true && (
                        <span className="badge">из источника</span>
                      )}
                    </div>
                    {variant !== null && (
                      <span className="muted mono">
                        {variant.width ?? "?"}×{variant.height ?? "?"} ·{" "}
                        {variant.sha256.slice(0, 8)}
                      </span>
                    )}
                    <input
                      type="file"
                      accept=".png,.jpg,.jpeg,image/png,image/jpeg"
                      disabled={busy !== null}
                      onChange={(event) => {
                        uploadViseme(state, event.target.files?.[0] ?? null);
                        event.target.value = "";
                      }}
                    />
                    {variant !== null && variant.reference_asset_id !== null && (
                      <div className="reference__actions">
                        <button
                          type="button"
                          className="button button--small button--ok"
                          disabled={
                            busy !== null ||
                            variant.approved ||
                            !canApproveReference(variant.status)
                          }
                          onClick={() => reviewViseme(variant, "approve")}
                        >
                          Утвердить
                        </button>
                        <button
                          type="button"
                          className="button button--small button--danger"
                          disabled={
                            busy !== null || !canRejectReference(variant.status)
                          }
                          onClick={() => reviewViseme(variant, "reject")}
                        >
                          Отклонить
                        </button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>

            {viseme !== null && (
              <div className="viseme-report">
                <div className="list__meta">
                  <span
                    className={
                      viseme.ready ? "badge badge--ok" : "badge badge--danger"
                    }
                  >
                    {viseme.ready ? "набор совместим" : "генерация заблокирована"}
                  </span>
                  <span className="muted">
                    вне морды ≤ {percent(viseme.metrics.outside_ratio_max)} ·
                    мерцание {percent(viseme.metrics.flicker_ratio)}
                  </span>
                </div>
                {viseme.missing.length > 0 && (
                  <p className="warn">нет кадров: {viseme.missing.join(", ")}</p>
                )}
                {viseme.blockers.length > 0 && (
                  <ul className="required__list">
                    {viseme.blockers.map((blocker, index) => (
                      <li key={`${blocker.code}-${blocker.state}-${index}`}>
                        <span className="badge badge--danger">
                          {blocker.message}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <img
                  className="viseme-sheet"
                  src={viseme.preview_url}
                  alt="Лист сравнения: источник и пять viseme-кадров"
                />
                <a href={viseme.preview_url} target="_blank" rel="noreferrer">
                  Открыть лист сравнения в новой вкладке
                </a>
              </div>
            )}
          </>
        )}
      </div>

      {error !== null && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {notice !== null && <p className="notice">{notice}</p>}

      <div className="mouth-block">
        <div className="panel__head">
          <h3>5. Talking Preview</h3>
          <span className="muted">
            {chosen === null
              ? "запись не выбрана"
              : `${chosen.duration_s.toFixed(2)} с записи`}
          </span>
        </div>
        <div className="form-row">
          <label className="field field--grow">
            <span>Движок</span>
            <select
              value={engine}
              disabled={busy !== null}
              onChange={(event) => setEngine(event.target.value as Engine)}
            >
              <option value="mouth_animation_mvp">
                mouth_animation_mvp — legacy, раскрытие по громкости
              </option>
              <option value="viseme_frame_blend_v1">
                viseme_frame_blend_v1 — сборка из пяти кадров морды
              </option>
            </select>
          </label>
        </div>
        {engine === "viseme_frame_blend_v1" && (
          <label className="field field--grow">
            <span>Viseme timing JSON (start / end / viseme)</span>
            <textarea
              rows={6}
              value={timingText}
              disabled={busy !== null}
              placeholder='{"visemes": [{"start": 0.0, "end": 0.2, "viseme": "closed"}]}'
              onChange={(event) => setTimingText(event.target.value)}
            />
          </label>
        )}
        {blocked && (
          <div className="required">
            <h3>Генерация заблокирована</h3>
            <ul className="required__list">
              {blockers.map((reason) => (
                <li key={reason}>
                  <span className="badge badge--danger">{reason}</span>
                </li>
              ))}
            </ul>
            <p className="muted">
              Пустой MP4 не создаётся: запрос уходит на сервер только когда все
              входы готовы.
            </p>
          </div>
        )}
        <div className="reference__actions">
          <button
            type="button"
            className="button button--ok"
            disabled={busy !== null || blocked}
            onClick={generate}
          >
            {busy === "generate" ? "Генерация…" : "Сделать Talking Preview"}
          </button>
        </div>

        {result !== null && (
          <div className="mouth-result">
            <video controls preload="metadata" src={result.content_url} />
            <div className="list__main">
              <div className="list__meta">
                <span className="badge">{result.mode}</span>
                <span className="muted">
                  {result.width}×{result.height} · {result.fps} fps ·{" "}
                  {result.frames} кадров · {result.duration_s.toFixed(2)} с
                </span>
              </div>
              <span className="muted mono">
                attempt {result.attempt_id.slice(0, 8)} · job{" "}
                {result.job_id.slice(0, 8)} · {result.sha256.slice(0, 16)}
              </span>
              <span className="warn">{result.limitation}</span>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

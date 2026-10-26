import { useState } from "react";
import type { FormEvent } from "react";

import { api } from "../api/client";
import type { Composition, ReferenceAsset } from "../api/types";
import { referenceKindLabel } from "../labels";

interface LayerDraft {
  reference_asset_id: string;
  z_index: number;
  x: number;
  y: number;
  scale: number;
  rotation: number;
  opacity: number;
}

interface CompositionEditorProps {
  shotId: string;
  composition: Composition | null;
  assets: ReferenceAsset[];
  onCancel: () => void;
  onSaved: (composition: Composition) => void;
}

function toDraft(composition: Composition): LayerDraft[] {
  return composition.layers.map((layer) => ({
    reference_asset_id: layer.reference.id,
    z_index: layer.z_index,
    x: layer.x,
    y: layer.y,
    scale: layer.scale,
    rotation: layer.rotation,
    opacity: layer.opacity,
  }));
}

function firstAsset(assets: ReferenceAsset[]): ReferenceAsset | null {
  return assets[0] ?? null;
}

export function CompositionEditor({
  shotId,
  composition,
  assets,
  onCancel,
  onSaved,
}: CompositionEditorProps) {
  const fallback = firstAsset(assets);
  const [width, setWidth] = useState(
    composition?.width ?? fallback?.width ?? 1024,
  );
  const [height, setHeight] = useState(
    composition?.height ?? fallback?.height ?? 1024,
  );
  const [layers, setLayers] = useState<LayerDraft[]>(() => {
    if (composition !== null) return toDraft(composition);
    if (fallback === null) return [];
    return [
      {
        reference_asset_id: fallback.id,
        z_index: 0,
        x: 0,
        y: 0,
        scale: 1,
        rotation: 0,
        opacity: 1,
      },
    ];
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update(index: number, patch: Partial<LayerDraft>): void {
    setLayers((current) =>
      current.map((layer, position) =>
        position === index ? { ...layer, ...patch } : layer,
      ),
    );
  }

  function addLayer(): void {
    const asset = fallback;
    if (asset === null) return;
    const nextZ = layers.reduce((max, layer) => Math.max(max, layer.z_index), -1) + 1;
    setLayers((current) => [
      ...current,
      {
        reference_asset_id: asset.id,
        z_index: nextZ,
        x: 0,
        y: 0,
        scale: 1,
        rotation: 0,
        opacity: 1,
      },
    ]);
  }

  function removeLayer(index: number): void {
    setLayers((current) => current.filter((_, position) => position !== index));
  }

  async function save(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (layers.length === 0) {
      setError("Добавьте хотя бы один слой.");
      return;
    }
    const zIndexes = layers.map((layer) => layer.z_index);
    if (new Set(zIndexes).size !== zIndexes.length) {
      setError("z-порядок слоёв должен быть уникальным.");
      return;
    }
    setBusy(true);
    setError(null);
    const body = { width, height, layers };
    try {
      const saved =
        composition === null
          ? await api.createComposition(shotId, body)
          : await api.updateComposition(shotId, composition.revision, body);
      onSaved(saved);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="editor" onSubmit={(event) => void save(event)}>
      <div className="panel__head">
        <h3>
          {composition === null
            ? "Новая ревизия композиции"
            : `Правка ревизии ${composition.revision}`}
        </h3>
        <button type="button" className="button button--small button--ghost" onClick={onCancel}>
          Отмена
        </button>
      </div>

      <div className="form-row">
        <label className="field">
          <span>Ширина</span>
          <input
            type="number"
            min={1}
            max={16384}
            value={width}
            onChange={(event) => setWidth(Number(event.target.value))}
          />
        </label>
        <label className="field">
          <span>Высота</span>
          <input
            type="number"
            min={1}
            max={16384}
            value={height}
            onChange={(event) => setHeight(Number(event.target.value))}
          />
        </label>
        <button
          type="button"
          className="button button--small"
          disabled={fallback === null}
          onClick={addLayer}
        >
          Добавить слой
        </button>
      </div>

      {assets.length === 0 && (
        <p className="muted">
          Нет доступных референсов: слой можно собрать только из утверждённых или
          загруженных ассетов.
        </p>
      )}

      {layers.length > 0 && (
        <div className="layers">
          {layers.map((layer, index) => (
            <div key={index} className="layer-row">
              <label className="field field--grow">
                <span>Референс</span>
                <select
                  value={layer.reference_asset_id}
                  onChange={(event) =>
                    update(index, { reference_asset_id: event.target.value })
                  }
                >
                  {assets.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {referenceKindLabel(asset.kind)} · {asset.status} ·{" "}
                      {asset.sha256.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field--narrow">
                <span>z</span>
                <input
                  type="number"
                  min={0}
                  value={layer.z_index}
                  onChange={(event) => update(index, { z_index: Number(event.target.value) })}
                />
              </label>
              <label className="field field--narrow">
                <span>x</span>
                <input
                  type="number"
                  step="1"
                  value={layer.x}
                  onChange={(event) => update(index, { x: Number(event.target.value) })}
                />
              </label>
              <label className="field field--narrow">
                <span>y</span>
                <input
                  type="number"
                  step="1"
                  value={layer.y}
                  onChange={(event) => update(index, { y: Number(event.target.value) })}
                />
              </label>
              <label className="field field--narrow">
                <span>scale</span>
                <input
                  type="number"
                  step="0.01"
                  min={0.01}
                  value={layer.scale}
                  onChange={(event) => update(index, { scale: Number(event.target.value) })}
                />
              </label>
              <label className="field field--narrow">
                <span>град.</span>
                <input
                  type="number"
                  step="1"
                  value={layer.rotation}
                  onChange={(event) => update(index, { rotation: Number(event.target.value) })}
                />
              </label>
              <label className="field field--narrow">
                <span>opacity</span>
                <input
                  type="number"
                  step="0.1"
                  min={0}
                  max={1}
                  value={layer.opacity}
                  onChange={(event) => update(index, { opacity: Number(event.target.value) })}
                />
              </label>
              <button
                type="button"
                className="button button--small button--danger"
                onClick={() => removeLayer(index)}
              >
                Убрать
              </button>
            </div>
          ))}
        </div>
      )}

      {error !== null && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      <div className="form-row">
        <button type="submit" className="button button--ok" disabled={busy || layers.length === 0}>
          {busy ? "…" : composition === null ? "Сохранить ревизию" : "Сохранить правку"}
        </button>
      </div>
    </form>
  );
}

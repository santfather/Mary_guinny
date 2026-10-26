import { useState } from "react";

import { api } from "../api/client";
import type { ReferenceAsset, ShotReference } from "../api/types";
import { purposeLabel, referenceKindLabel } from "../labels";
import { StatusBadge } from "./StatusBadge";

const PURPOSES = ["character", "location", "prop", "style", "other"] as const;

interface ShotReferencesProps {
  shotId: string;
  links: ShotReference[];
  assets: ReferenceAsset[];
  onChanged: () => void;
}

export function ShotReferences({ shotId, links, assets, onChanged }: ShotReferencesProps) {
  const [assetId, setAssetId] = useState("");
  const [purpose, setPurpose] = useState<string>("character");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = assets.find((asset) => asset.id === assetId) ?? assets[0] ?? null;

  async function run(action: () => Promise<unknown>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Референсы шота</h2>
        <span className="muted">{links.length}</span>
      </div>

      {links.length === 0 ? (
        <p className="muted">Привязанных референсов нет.</p>
      ) : (
        <ul className="list">
          {links.map((link) => (
            <li key={link.id} className="list__item">
              <img
                className="thumb"
                src={link.reference.content_url}
                alt={`Референс ${link.reference.sha256.slice(0, 8)}`}
              />
              <div className="list__main">
                <div className="list__meta">
                  <strong>{purposeLabel(link.purpose)}</strong>
                  <StatusBadge status={link.reference.status} />
                  <span className="muted">
                    {referenceKindLabel(link.reference.kind)}
                  </span>
                </div>
                <span className="muted mono">{link.reference.sha256.slice(0, 16)}</span>
              </div>
              <button
                type="button"
                className="button button--small button--danger"
                disabled={busy}
                onClick={() => void run(() => api.detachReference(shotId, link.id))}
              >
                Отвязать
              </button>
            </li>
          ))}
        </ul>
      )}

      {error !== null && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      {assets.length === 0 ? (
        <p className="muted">
          Нет доступных референсов: нужен утверждённый или загруженный ассет проекта.
        </p>
      ) : (
        <div className="form-row">
          <label className="field field--grow">
            <span>Референс</span>
            <select
              value={selected?.id ?? ""}
              onChange={(event) => setAssetId(event.target.value)}
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
            <select value={purpose} onChange={(event) => setPurpose(event.target.value)}>
              {PURPOSES.map((value) => (
                <option key={value} value={value}>
                  {purposeLabel(value)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button"
            disabled={busy || selected === null}
            onClick={() => {
              if (selected === null) return;
              void run(() =>
                api.attachReference(shotId, {
                  reference_asset_id: selected.id,
                  purpose,
                }),
              );
            }}
          >
            Привязать
          </button>
        </div>
      )}
    </section>
  );
}

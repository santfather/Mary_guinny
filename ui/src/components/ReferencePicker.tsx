import { useRef, useState } from "react";
import type { FormEvent } from "react";

import { api } from "../api/client";
import type { ReferenceAsset } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { poseLabel, referenceKindLabel, viewLabel } from "../labels";
import { StatusBadge } from "./StatusBadge";

const VIEWS = ["front", "side", "three_quarter", "back", "other"] as const;
const POSES = ["stand", "sit", "walk", "lie", "sleep", "custom"] as const;
const UPLOAD_KINDS = [
  "character_reference",
  "location_reference",
  "prop_reference",
  "uploaded",
] as const;

type UploadKind = (typeof UPLOAD_KINDS)[number];

const OWNER_FIELD: Record<UploadKind, "character_id" | "location_id" | "prop_id" | null> =
  {
    character_reference: "character_id",
    location_reference: "location_id",
    prop_reference: "prop_id",
    uploaded: null,
  };

interface ReferencePickerProps {
  projectId: string;
  assets: ReferenceAsset[];
  onChanged: () => void;
}

export function ReferencePicker({ projectId, assets, onChanged }: ReferencePickerProps) {
  const characters = useAsync(() => api.characters(projectId), [projectId]);
  const locations = useAsync(() => api.locations(projectId), [projectId]);
  const props = useAsync(() => api.props(projectId), [projectId]);

  const [kind, setKind] = useState<UploadKind>("character_reference");
  const [ownerId, setOwnerId] = useState("");
  const [view, setView] = useState<string>("");
  const [pose, setPose] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const characterList = characters.state.status === "ready" ? characters.state.data : [];
  const locationList = locations.state.status === "ready" ? locations.state.data : [];
  const propList = props.state.status === "ready" ? props.state.data : [];

  const ownerField = OWNER_FIELD[kind];
  const ownerOptions =
    ownerField === "character_id"
      ? characterList.map((item) => ({ id: item.id, name: item.name }))
      : ownerField === "location_id"
        ? locationList.map((item) => ({ id: item.id, name: item.name }))
        : ownerField === "prop_id"
          ? propList.map((item) => ({ id: item.id, name: item.name }))
          : [];

  const missingFront = characterList.filter(
    (character) =>
      !assets.some(
        (asset) =>
          asset.kind === "character_reference" &&
          asset.character_id === character.id &&
          asset.status === "approved" &&
          asset.view === "front",
      ),
  );
  const missingLocation = locationList.filter(
    (location) =>
      !assets.some(
        (asset) =>
          asset.kind === "location_reference" &&
          asset.location_id === location.id &&
          asset.status === "approved",
      ),
  );

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await action();
      onChanged();
      setNotice(success);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    if (file === null) {
      setError("Выберите файл PNG или JPEG.");
      return;
    }
    if (ownerField !== null && ownerId === "") {
      setError("Выберите владельца референса.");
      return;
    }
    setBusy("upload");
    setError(null);
    setNotice(null);
    try {
      const asset = await api.uploadReference(
        projectId,
        {
          kind,
          character_id: ownerField === "character_id" ? ownerId : undefined,
          location_id: ownerField === "location_id" ? ownerId : undefined,
          prop_id: ownerField === "prop_id" ? ownerId : undefined,
          view: view === "" ? undefined : view,
          pose: pose === "" ? undefined : pose,
        },
        file,
      );
      form.reset();
      setFile(null);
      setOwnerId("");
      setView("");
      setPose("");
      onChanged();
      setNotice(
        asset.status === "approved"
          ? "Такой файл уже загружен и утверждён — референс переиспользован."
          : "Файл загружен как черновик. Отметьте front при необходимости и утвердите вручную.",
      );
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }

  function describe(asset: ReferenceAsset): string {
    const parts = [
      referenceKindLabel(asset.kind),
      asset.status,
      viewLabel(asset.view) ?? "",
      poseLabel(asset.pose) ?? "",
    ];
    if (asset.has_alpha === false) parts.push("без альфа-канала");
    return parts.filter((part) => part !== "").join(" · ");
  }

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Референсы: загрузка и утверждение</h2>
        <span className="muted">{assets.length}</span>
      </div>

      <div className="required">
        <h3>Обязательные входы</h3>
        {characterList.length === 0 && (
          <p className="alert" role="status">
            В проекте нет персонажей: для плана сцены нужен хотя бы один персонаж с
            утверждённым front-референсом.
          </p>
        )}
        {characterList.length > 0 && (
          <ul className="required__list">
            {characterList.map((character) => {
              const filled = !missingFront.some((item) => item.id === character.id);
              return (
                <li key={character.id}>
                  <span>{character.name}</span>
                  {filled ? (
                    <span className="badge badge--ok">front утверждён</span>
                  ) : (
                    <span className="badge badge--danger">нужен front-референс</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {locationList.length === 0 ? (
          <p className="warn" role="status">
            Локация не задана: загрузите реальное изображение локации. Пустая локация —
            незаполненный обязательный вход приёмочного сценария.
          </p>
        ) : (
          <ul className="required__list">
            {locationList.map((location) => {
              const filled = !missingLocation.some((item) => item.id === location.id);
              return (
                <li key={location.id}>
                  <span>{location.name}</span>
                  {filled ? (
                    <span className="badge badge--ok">референс утверждён</span>
                  ) : (
                    <span className="badge badge--danger">нужен референс локации</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <form className="form-row" onSubmit={(event) => void upload(event)}>
        <label className="field field--grow">
          <span>Файл PNG/JPEG</span>
          <input
            ref={inputRef}
            type="file"
            accept="image/png,image/jpeg"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <label className="field">
          <span>Тип</span>
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as UploadKind);
              setOwnerId("");
            }}
          >
            {UPLOAD_KINDS.map((item) => (
              <option key={item} value={item}>
                {referenceKindLabel(item)}
              </option>
            ))}
          </select>
        </label>
        {ownerField !== null && (
          <label className="field field--grow">
            <span>Владелец</span>
            <select value={ownerId} onChange={(event) => setOwnerId(event.target.value)}>
              <option value="">— выберите —</option>
              {ownerOptions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="field">
          <span>Ракурс</span>
          <select value={view} onChange={(event) => setView(event.target.value)}>
            <option value="">—</option>
            {VIEWS.map((item) => (
              <option key={item} value={item}>
                {viewLabel(item)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Поза</span>
          <select value={pose} onChange={(event) => setPose(event.target.value)}>
            <option value="">—</option>
            {POSES.map((item) => (
              <option key={item} value={item}>
                {poseLabel(item)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="button button--ok" disabled={busy !== null}>
          {busy === "upload" ? "…" : "Загрузить"}
        </button>
      </form>

      {error !== null && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {notice !== null && <p className="notice">{notice}</p>}

      {assets.length === 0 ? (
        <p className="muted">
          В проекте ещё нет файлов: загрузите реальные PNG/JPEG персонажей и локации.
          Ничего не подставляется автоматически.
        </p>
      ) : (
        <div className="grid">
          {assets.map((asset) => {
            const editable = asset.status === "draft" || asset.status === "rejected";
            const canReject = asset.status === "draft" || asset.status === "approved";
            return (
              <article key={asset.id} className="reference">
                <div className="reference__image">
                  <img src={asset.content_url} alt={describe(asset)} />
                </div>
                <div className="reference__meta">
                  <StatusBadge status={asset.status} />
                  {asset.view === "front" && <span className="badge badge--ok">front</span>}
                  {asset.has_alpha === false && (
                    <span className="badge badge--warn">без альфы</span>
                  )}
                </div>
                <p className="muted mono">{describe(asset)}</p>
                <p className="muted mono">
                  {asset.width ?? "?"}×{asset.height ?? "?"} · {asset.sha256.slice(0, 8)}
                </p>
                <div className="reference__actions">
                  {editable && asset.character_id !== null && asset.view !== "front" && (
                    <button
                      type="button"
                      className="button button--small"
                      disabled={busy !== null}
                      onClick={() =>
                        void run(
                          `front-${asset.id}`,
                          () => api.relabel(asset.id, { view: "front" }),
                          "Референс отмечен как front. Утвердите его вручную.",
                        )
                      }
                    >
                      Сделать front
                    </button>
                  )}
                  {editable && (
                    <button
                      type="button"
                      className="button button--small button--ok"
                      disabled={busy !== null}
                      onClick={() =>
                        void run(
                          `approve-${asset.id}`,
                          () => api.approve(asset.id),
                          "Референс утверждён.",
                        )
                      }
                    >
                      Утвердить
                    </button>
                  )}
                  {canReject && (
                    <button
                      type="button"
                      className="button button--small button--danger"
                      disabled={busy !== null}
                      onClick={() =>
                        void run(
                          `reject-${asset.id}`,
                          () => api.reject(asset.id),
                          "Референс отклонён.",
                        )
                      }
                    >
                      Отклонить
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

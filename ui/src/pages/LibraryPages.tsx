import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { api, libraryApi } from "../api/client";
import type { ReferenceUploadParams } from "../api/client";
import type {
  LibraryEntityDetail,
  LibraryKind,
  ReferenceAsset,
} from "../api/types";
import { ReferenceCard } from "../components/ReferenceCard";
import { ReferenceLightbox } from "../components/ReferenceLightbox";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";
import { useAsync } from "../hooks/useAsync";
import { useReferenceReview } from "../hooks/useReferenceReview";
import { canApproveReference } from "../labels";

interface LibraryCopy {
  title: string;
  subtitle: string;
  createLabel: string;
  emptyTitle: string;
  emptyMessage: string;
  uploadHint: string;
}

const COPY: Record<LibraryKind, LibraryCopy> = {
  location: {
    title: "Локации",
    subtitle: "Места проекта: описание и утверждённые референсы для композиции и плана сцены.",
    createLabel: "Новая локация",
    emptyTitle: "Локаций нет",
    emptyMessage: "Создайте первую локацию: название, описание и изображения.",
    uploadHint: "PNG или JPEG. Альфа-канал для локации не требуется.",
  },
  prop: {
    title: "Предметы",
    subtitle: "Реквизит проекта: описание и утверждённые референсы для композиции и плана сцены.",
    createLabel: "Новый предмет",
    emptyTitle: "Предметов нет",
    emptyMessage: "Создайте первый предмет: название, описание и изображения.",
    uploadHint: "PNG с альфа-каналом предпочтителен: без него композиция покажет предупреждение.",
  },
};

const BASE_HASH: Record<LibraryKind, string> = {
  location: "#/locations",
  prop: "#/props",
};

function errorText(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}

export function LibraryListPage({
  kind,
  projectId,
}: {
  kind: LibraryKind;
  projectId: string;
}) {
  const copy = COPY[kind];
  const client = libraryApi[kind];
  const { state, reload } = useAsync(() => client.list(projectId), [kind, projectId]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (name.trim() === "") {
      setError("Укажите название.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await client.create(projectId, {
        name: name.trim(),
        description: description.trim() === "" ? undefined : description.trim(),
      });
      setName("");
      setDescription("");
      reload();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <header className="page__head">
        <div>
          <h1>{copy.title}</h1>
          <p className="muted">{copy.subtitle}</p>
        </div>
      </header>

      <form className="panel" onSubmit={(event) => void create(event)}>
        <div className="panel__head">
          <h2>{copy.createLabel}</h2>
        </div>
        <div className="form-row">
          <label className="field field--grow">
            <span>Название</span>
            <input
              value={name}
              maxLength={200}
              placeholder={kind === "location" ? "Например, Кухня" : "Например, Красный мяч"}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <button type="submit" className="button button--ok" disabled={busy}>
            {busy ? "…" : "Создать"}
          </button>
        </div>
        <label className="field">
          <span>Описание</span>
          <textarea
            value={description}
            rows={2}
            maxLength={2000}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        {error !== null && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
      </form>

      {state.status === "loading" && <StateView kind="loading" title={`Загрузка: ${copy.title}`} />}

      {state.status === "error" && (
        <StateView
          kind="error"
          title={`Не удалось загрузить: ${copy.title}`}
          message={state.error.message}
          onRetry={reload}
        />
      )}

      {state.status === "ready" && state.data.length === 0 && (
        <StateView kind="empty" title={copy.emptyTitle} message={copy.emptyMessage} />
      )}

      {state.status === "ready" && state.data.length > 0 && (
        <div className="cards">
          {state.data.map((entity) => (
            <a
              key={entity.id}
              className="card"
              href={`${BASE_HASH[kind]}/${entity.id}`}
            >
              <div className="card__head">
                <h2>{entity.name}</h2>
                <StatusBadge status={entity.status} />
              </div>
              <p className="muted">{entity.slug}</p>
              {entity.description !== null && <p>{entity.description}</p>}
              <dl className="stats">
                <div>
                  <dt>Референсы</dt>
                  <dd>{entity.reference_count}</dd>
                </div>
              </dl>
            </a>
          ))}
        </div>
      )}
    </section>
  );
}

export function LibraryDetailPage({
  kind,
  entityId,
}: {
  kind: LibraryKind;
  entityId: string;
}) {
  const copy = COPY[kind];
  const client = libraryApi[kind];
  const detail = useAsync(() => client.get(entityId), [kind, entityId]);

  const [snapshot, setSnapshot] = useState<LibraryEntityDetail | null>(null);
  const [preview, setPreview] = useState<ReferenceAsset | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { pendingId, actionError, review } = useReferenceReview();

  useEffect(() => {
    if (detail.state.status === "ready") setSnapshot(detail.state.data);
  }, [detail.state]);

  if (snapshot === null) {
    if (detail.state.status === "error") {
      return (
        <StateView
          kind="error"
          title="Не удалось загрузить карточку"
          message={detail.state.error.message}
          onRetry={detail.reload}
        />
      );
    }
    return <StateView kind="loading" title="Загрузка карточки" />;
  }

  const entity = snapshot;
  const references = [...entity.references].sort(
    (left, right) => Number(right.role === "primary") - Number(left.role === "primary"),
  );
  const approvedWithoutAlpha =
    kind === "prop" &&
    references.some((asset) => asset.status === "approved" && asset.has_alpha === false);
  const approvedPrimary = references.find(
    (asset) => asset.status === "approved" && asset.role === "primary",
  );

  async function run(key: string, action: () => Promise<unknown>, success: string): Promise<void> {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(success);
      detail.reload();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(null);
    }
  }

  async function handleReview(
    asset: ReferenceAsset,
    action: "approve" | "reject",
  ): Promise<void> {
    const updated = await review(asset, action);
    if (updated === null) return;
    setPreview((current) => (current !== null && current.id === updated.id ? updated : current));
    detail.reload();
  }

  async function save(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const name = String(data.get("name") ?? "").trim();
    if (name === "") {
      setError("Укажите название.");
      return;
    }
    const description = String(data.get("description") ?? "").trim();
    await run(
      "save",
      () => client.update(entity.id, { name, description: description === "" ? null : description }),
      "Изменения сохранены.",
    );
  }

  async function upload(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (files.length === 0) {
      setError("Выберите один или несколько файлов PNG/JPEG.");
      return;
    }
    const form = event.currentTarget;
    const params: ReferenceUploadParams = { kind: client.kind };
    params[client.ownerParam] = entity.id;
    setBusy("upload");
    setError(null);
    setNotice(null);
    try {
      const uploaded = await api.uploadReferences(entity.project_id, params, files);
      form.reset();
      setFiles([]);
      detail.reload();
      setNotice(
        uploaded.some((asset) => asset.status === "approved")
          ? "Часть файлов уже была в проекте — референс переиспользован."
          : `Загружено файлов: ${uploaded.length}. Утвердите нужные вручную.`,
      );
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="page">
      <a className="back" href={BASE_HASH[kind]}>
        ← К списку
      </a>

      <header className="page__head">
        <div>
          <h1>{snapshot.name}</h1>
          <p className="muted">{snapshot.slug}</p>
        </div>
        <StatusBadge status={snapshot.status} />
      </header>

      {snapshot.description !== null && <p>{snapshot.description}</p>}

      <dl className="stats">
        <div>
          <dt>Референсы</dt>
          <dd>{snapshot.reference_count}</dd>
        </div>
        <div>
          <dt>Утверждено</dt>
          <dd>{snapshot.references.filter((asset) => asset.status === "approved").length}</dd>
        </div>
      </dl>

      <form className="panel" key={snapshot.id} onSubmit={(event) => void save(event)}>
        <div className="panel__head">
          <h2>Карточка</h2>
        </div>
        <div className="form-row">
          <label className="field field--grow">
            <span>Название</span>
            <input name="name" defaultValue={snapshot.name} maxLength={200} />
          </label>
          <button type="submit" className="button" disabled={busy !== null}>
            {busy === "save" ? "…" : "Сохранить"}
          </button>
        </div>
        <label className="field">
          <span>Описание</span>
          <textarea name="description" defaultValue={snapshot.description ?? ""} rows={3} maxLength={2000} />
        </label>
      </form>

      <section className="panel">
        <div className="panel__head">
          <h2>Изображения</h2>
          <span className="muted">{snapshot.references.length}</span>
        </div>

        <form className="form-row" onSubmit={(event) => void upload(event)}>
          <label className="field field--grow">
            <span>Файлы PNG/JPEG</span>
            <input
              type="file"
              multiple
              accept="image/png,image/jpeg"
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
          </label>
          <button type="submit" className="button button--ok" disabled={busy !== null}>
            {busy === "upload" ? "…" : "Загрузить"}
          </button>
        </form>
        <p className="muted">{copy.uploadHint}</p>

        {error !== null && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        {actionError !== null && (
          <p className="alert" role="alert">
            {actionError}
          </p>
        )}
        {notice !== null && <p className="notice">{notice}</p>}
        {approvedWithoutAlpha && (
          <p className="warn" role="status">
            У предмета есть утверждённый референс без альфа-канала: при использовании в композиции
            появится предупреждение.
          </p>
        )}
        {approvedPrimary !== undefined && (
          <p className="muted">
            Основной референс уже утверждён; утверждённые данные неизменяемы, поэтому выбрать
            другой основной нельзя.
          </p>
        )}

        {references.length === 0 ? (
          <StateView
            kind="empty"
            title="Изображений нет"
            message="Загрузите один или несколько файлов PNG/JPEG, затем утвердите нужные."
          />
        ) : (
          <div className="grid">
            {references.map((asset) => (
              <ReferenceCard
                key={asset.id}
                asset={asset}
                pending={pendingId === asset.id || busy === `primary-${asset.id}`}
                onOpen={setPreview}
                onApprove={(item) => void handleReview(item, "approve")}
                onReject={(item) => void handleReview(item, "reject")}
                extraAction={
                  approvedPrimary === undefined &&
                  asset.role !== "primary" &&
                  canApproveReference(asset.status)
                    ? {
                        label: "Сделать основным",
                        onSelect: (item) =>
                          void run(
                            `primary-${item.id}`,
                            () => api.relabel(item.id, { role: "primary" }),
                            "Референс выбран основным.",
                          ),
                      }
                    : undefined
                }
              />
            ))}
          </div>
        )}
      </section>

      {preview !== null && (
        <ReferenceLightbox
          asset={preview}
          pending={pendingId === preview.id}
          onClose={() => setPreview(null)}
          onApprove={(item) => void handleReview(item, "approve")}
          onReject={(item) => void handleReview(item, "reject")}
        />
      )}
    </section>
  );
}

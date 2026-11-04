import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type {
  BibleVersion,
  CharacterDetail,
  ReferenceAsset,
  ReferenceFilters,
} from "../api/types";
import { FilterBar } from "../components/FilterBar";
import { ReferenceCard } from "../components/ReferenceCard";
import { ReferenceLightbox } from "../components/ReferenceLightbox";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";
import { useAsync } from "../hooks/useAsync";
import { useReferenceReview } from "../hooks/useReferenceReview";
import {
  canApproveReference,
  canRejectReference,
  kindLabel,
} from "../labels";

const SOURCE_LABELS: Record<string, string> = {
  manual: "вручную",
  import: "импорт",
};

type LibraryData = [CharacterDetail, BibleVersion[]];

export function CharacterDetailPage({ characterId }: { characterId: string }) {
  const [filters, setFilters] = useState<ReferenceFilters>({ status: "", view: "", pose: "" });
  const [snapshot, setSnapshot] = useState<LibraryData | null>(null);
  const [preview, setPreview] = useState<ReferenceAsset | null>(null);
  const [voiceFile, setVoiceFile] = useState<File | null>(null);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [voiceNotice, setVoiceNotice] = useState<string | null>(null);
  const voiceInput = useRef<HTMLInputElement>(null);
  const { pendingId, actionError, review } = useReferenceReview();

  const library = useAsync(
    () => Promise.all([api.character(characterId), api.bible(characterId)]),
    [characterId],
  );
  const references = useAsync(
    () => api.references(characterId, filters),
    [characterId, filters.status, filters.view, filters.pose],
  );

  useEffect(() => {
    if (library.state.status === "ready") {
      setSnapshot(library.state.data);
    }
  }, [library.state]);

  async function handleReview(
    asset: ReferenceAsset,
    action: "approve" | "reject",
  ): Promise<void> {
    const updated = await review(asset, action);
    if (updated === null) return;
    setPreview((current) => (current !== null && current.id === updated.id ? updated : current));
    references.reload();
    library.reload();
  }

  async function handleMultiView(asset: ReferenceAsset, value: boolean): Promise<void> {
    const updated = await api.relabel(asset.id, { multi_view: value });
    setPreview((current) => (current !== null && current.id === updated.id ? updated : current));
    references.reload();
  }

  async function handleVoiceUpload(): Promise<void> {
    if (voiceFile === null) return;
    setVoiceBusy(true);
    setVoiceError(null);
    setVoiceNotice(null);
    try {
      await api.uploadVoice(characterId, voiceFile);
      setVoiceFile(null);
      if (voiceInput.current !== null) voiceInput.current.value = "";
      setVoiceNotice("Голосовой образец загружен");
      references.reload();
      library.reload();
    } catch (error) {
      setVoiceError(error instanceof Error ? error.message : String(error));
    } finally {
      setVoiceBusy(false);
    }
  }

  if (snapshot === null) {
    if (library.state.status === "error") {
      return (
        <StateView
          kind="error"
          title="Не удалось загрузить персонажа"
          message={library.state.error.message}
          onRetry={library.reload}
        />
      );
    }
    return <StateView kind="loading" title="Загрузка персонажа" />;
  }

  const [character, bible] = snapshot;
  const latestBible = bible[0] ?? null;
  const allReferences = references.state.status === "ready" ? references.state.data : [];
  const voiceReferences = allReferences.filter((asset) => asset.role === "voice");
  const imageReferences = allReferences.filter((asset) => asset.role !== "voice");

  return (
    <section className="page">
      <a className="back" href="#/characters">
        ← К персонажам
      </a>

      <header className="page__head">
        <div>
          <h1>{character.name}</h1>
          <p className="muted">
            {kindLabel(character.kind)} · {character.slug}
          </p>
        </div>
        <StatusBadge status={character.status} />
      </header>

      {character.description !== null && <p>{character.description}</p>}

      <dl className="stats stats--wide">
        <div>
          <dt>Референсы</dt>
          <dd>{character.reference_count}</dd>
        </div>
        <div>
          <dt>Утверждено</dt>
          <dd>{character.approved_reference_count}</dd>
        </div>
        <div>
          <dt>Версий bible</dt>
          <dd>{character.bible_version_count}</dd>
        </div>
        <div>
          <dt>Последняя bible</dt>
          <dd>
            {character.latest_bible_version === null ? "—" : `v${character.latest_bible_version}`}
          </dd>
        </div>
      </dl>

      <section className="panel">
        <h2>Bible</h2>
        {latestBible === null ? (
          <p className="muted">Bible ещё не загружена.</p>
        ) : (
          <>
            <div className="bible__meta">
              <strong>Версия {latestBible.version}</strong>
              <StatusBadge status={latestBible.status} />
              <span className="muted">
                источник: {SOURCE_LABELS[latestBible.source] ?? latestBible.source}
              </span>
            </div>
            <pre className="bible">{latestBible.body}</pre>
          </>
        )}
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2>Референсы</h2>
          <span className="muted">
            {references.state.status === "ready"
              ? `${imageReferences.length} из ${character.reference_count}`
              : "…"}
          </span>
        </div>

        <FilterBar value={filters} onChange={setFilters} />

        {actionError !== null && (
          <p className="alert" role="alert">
            {actionError}
          </p>
        )}

        {references.state.status === "loading" && (
          <StateView kind="loading" title="Загрузка референсов" />
        )}

        {references.state.status === "error" && (
          <StateView
            kind="error"
            title="Не удалось загрузить референсы"
            message={references.state.error.message}
            onRetry={references.reload}
          />
        )}

        {references.state.status === "ready" &&
          (imageReferences.length === 0 ? (
            <StateView
              kind="empty"
              title="Референсов нет"
              message="Измените фильтры или добавьте файлы в библиотеку."
            />
          ) : (
            <div className="grid">
              {imageReferences.map((asset) => (
                <ReferenceCard
                  key={asset.id}
                  asset={asset}
                  pending={pendingId === asset.id}
                  onOpen={setPreview}
                  onApprove={(item) => void handleReview(item, "approve")}
                  onReject={(item) => void handleReview(item, "reject")}
                />
              ))}
            </div>
          ))}
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2>Голос</h2>
          <span className="muted">
            {voiceReferences.length === 0 ? "нет образца" : `${voiceReferences.length} шт.`}
          </span>
        </div>
        <p className="muted">
          Образец тембра до 30 секунд (mp3, wav, m4a, aac). Синтез речи не выполняется:
          файл хранится как референс и в рендере не участвует.
        </p>

        <div className="voice__upload">
          <input
            ref={voiceInput}
            type="file"
            accept="audio/*"
            disabled={voiceBusy}
            onChange={(event) => {
              setVoiceFile(event.currentTarget.files?.[0] ?? null);
              setVoiceError(null);
              setVoiceNotice(null);
            }}
          />
          <button
            type="button"
            className="button"
            disabled={voiceBusy || voiceFile === null}
            onClick={() => void handleVoiceUpload()}
          >
            {voiceBusy ? "Загрузка…" : "Загрузить голос"}
          </button>
        </div>

        {voiceNotice !== null && <p className="notice">{voiceNotice}</p>}
        {voiceError !== null && (
          <p className="alert" role="alert">
            {voiceError}
          </p>
        )}

        {voiceReferences.length === 0 ? (
          <p className="muted">Голосовой образец не загружен.</p>
        ) : (
          <ul className="voice__list">
            {voiceReferences.map((asset) => (
              <li key={asset.id} className="voice">
                <div className="reference__meta">
                  <StatusBadge status={asset.status} />
                  <span className="muted">
                    {asset.duration_s === null
                      ? "длительность неизвестна"
                      : `${asset.duration_s.toFixed(2)} с`}
                  </span>
                  <span className="mono muted">{asset.sha256.slice(0, 12)}</span>
                </div>
                <audio className="voice__player" controls preload="none" src={asset.content_url}>
                  <track kind="captions" />
                </audio>
                <div className="reference__actions">
                  {canApproveReference(asset.status) && (
                    <button
                      type="button"
                      className="button button--small button--ok"
                      disabled={pendingId === asset.id}
                      onClick={() => void handleReview(asset, "approve")}
                    >
                      {pendingId === asset.id ? "…" : "Утвердить"}
                    </button>
                  )}
                  {canRejectReference(asset.status) && (
                    <button
                      type="button"
                      className="button button--small button--danger"
                      disabled={pendingId === asset.id}
                      onClick={() => void handleReview(asset, "reject")}
                    >
                      Отклонить
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {preview !== null && (
        <ReferenceLightbox
          asset={preview}
          pending={pendingId === preview.id}
          onClose={() => setPreview(null)}
          onApprove={(asset) => void handleReview(asset, "approve")}
          onReject={(asset) => void handleReview(asset, "reject")}
          onMultiViewChange={handleMultiView}
        />
      )}
    </section>
  );
}

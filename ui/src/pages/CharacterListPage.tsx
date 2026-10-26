import { api } from "../api/client";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";
import { useAsync } from "../hooks/useAsync";
import { kindLabel } from "../labels";

export function CharacterListPage({ projectId }: { projectId: string }) {
  const { state, reload } = useAsync(() => api.characters(projectId), [projectId]);

  return (
    <section className="page">
      <header className="page__head">
        <div>
          <h1>Персонажи</h1>
          <p className="muted">Bible, референсы и статусы утверждения.</p>
        </div>
      </header>

      {state.status === "loading" && <StateView kind="loading" title="Загрузка персонажей" />}

      {state.status === "error" && (
        <StateView
          kind="error"
          title="Не удалось загрузить персонажей"
          message={state.error.message}
          onRetry={reload}
        />
      )}

      {state.status === "ready" && state.data.length === 0 && (
        <StateView
          kind="empty"
          title="Персонажей нет"
          message="В этом проекте пока нет записей библиотеки."
        />
      )}

      {state.status === "ready" && state.data.length > 0 && (
        <div className="cards">
          {state.data.map((character) => (
            <a key={character.id} className="card" href={`#/characters/${character.id}`}>
              <div className="card__head">
                <h2>{character.name}</h2>
                <StatusBadge status={character.status} />
              </div>
              <p className="muted">
                {kindLabel(character.kind)} · {character.slug}
              </p>
              {character.description !== null && <p>{character.description}</p>}
              <dl className="stats">
                <div>
                  <dt>Референсы</dt>
                  <dd>
                    {character.approved_reference_count} / {character.reference_count}
                  </dd>
                </div>
                <div>
                  <dt>Bible</dt>
                  <dd>
                    {character.latest_bible_version === null
                      ? "—"
                      : `v${character.latest_bible_version}`}
                  </dd>
                </div>
              </dl>
            </a>
          ))}
        </div>
      )}
    </section>
  );
}

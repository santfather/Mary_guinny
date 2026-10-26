import { api } from "../api/client";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";
import { useAsync } from "../hooks/useAsync";

export function LocationsPage({ projectId }: { projectId: string }) {
  const { state, reload } = useAsync(() => api.locations(projectId), [projectId]);

  return (
    <section className="page">
      <header className="page__head">
        <div>
          <h1>Локации</h1>
          <p className="muted">Каталог мест проекта и количество привязанных референсов.</p>
        </div>
      </header>

      {state.status === "loading" && <StateView kind="loading" title="Загрузка локаций" />}

      {state.status === "error" && (
        <StateView
          kind="error"
          title="Не удалось загрузить локации"
          message={state.error.message}
          onRetry={reload}
        />
      )}

      {state.status === "ready" && state.data.length === 0 && (
        <StateView
          kind="empty"
          title="Локаций нет"
          message="Локации появятся после импорта или ручного добавления."
        />
      )}

      {state.status === "ready" && state.data.length > 0 && (
        <ul className="list">
          {state.data.map((location) => (
            <li className="list__item" key={location.id}>
              <div className="list__main">
                <strong>{location.name}</strong>
                <span className="muted">
                  {location.slug}
                  {location.description !== null ? ` · ${location.description}` : ""}
                </span>
              </div>
              <div className="list__meta">
                <span className="badge badge--muted">{location.reference_count} реф.</span>
                <StatusBadge status={location.status} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

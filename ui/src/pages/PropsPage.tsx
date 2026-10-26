import { api } from "../api/client";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";
import { useAsync } from "../hooks/useAsync";

export function PropsPage({ projectId }: { projectId: string }) {
  const { state, reload } = useAsync(() => api.props(projectId), [projectId]);

  return (
    <section className="page">
      <header className="page__head">
        <div>
          <h1>Предметы</h1>
          <p className="muted">Каталог предметов проекта и количество привязанных референсов.</p>
        </div>
      </header>

      {state.status === "loading" && <StateView kind="loading" title="Загрузка предметов" />}

      {state.status === "error" && (
        <StateView
          kind="error"
          title="Не удалось загрузить предметы"
          message={state.error.message}
          onRetry={reload}
        />
      )}

      {state.status === "ready" && state.data.length === 0 && (
        <StateView
          kind="empty"
          title="Предметов нет"
          message="Предметы появятся после импорта или ручного добавления."
        />
      )}

      {state.status === "ready" && state.data.length > 0 && (
        <ul className="list">
          {state.data.map((prop) => (
            <li className="list__item" key={prop.id}>
              <div className="list__main">
                <strong>{prop.name}</strong>
                <span className="muted">
                  {prop.slug}
                  {prop.description !== null ? ` · ${prop.description}` : ""}
                </span>
              </div>
              <div className="list__meta">
                <span className="badge badge--muted">{prop.reference_count} реф.</span>
                <StatusBadge status={prop.status} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

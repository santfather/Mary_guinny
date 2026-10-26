import { useState } from "react";
import type { ChangeEvent } from "react";

import { api } from "./api/client";
import type { Project } from "./api/types";
import { StateView } from "./components/StateView";
import { useAsync } from "./hooks/useAsync";
import { useHashRoute } from "./hooks/useHashRoute";
import { CharacterDetailPage } from "./pages/CharacterDetailPage";
import { CharacterListPage } from "./pages/CharacterListPage";
import { LocationsPage } from "./pages/LocationsPage";
import { PropsPage } from "./pages/PropsPage";
import { ShotDetailPage } from "./pages/ShotDetailPage";
import { ShotsPage } from "./pages/ShotsPage";

function preferredProject(projects: Project[]): Project | null {
  return projects.find((project) => project.title === "Mary Studio") ?? projects[0] ?? null;
}

export function App() {
  const route = useHashRoute();
  const projects = useAsync(() => api.projects(), []);
  const [selectedId, setSelectedId] = useState("");

  const list = projects.state.status === "ready" ? projects.state.data : [];
  const active = list.find((project) => project.id === selectedId) ?? preferredProject(list);
  const inCharacters = route.name === "characters" || route.name === "character";
  const inShots = route.name === "shots" || route.name === "shot";

  function renderContent() {
    if (route.name === "character") {
      return <CharacterDetailPage characterId={route.id} />;
    }
    if (route.name === "shot") {
      return <ShotDetailPage shotId={route.id} />;
    }
    if (projects.state.status === "loading") {
      return <StateView kind="loading" title="Загрузка проектов" />;
    }
    if (projects.state.status === "error") {
      return (
        <StateView
          kind="error"
          title="Не удалось загрузить проекты"
          message={projects.state.error.message}
          onRetry={projects.reload}
        />
      );
    }
    if (active === null) {
      return (
        <StateView
          kind="empty"
          title="Проектов нет"
          message="Создайте проект в базе, чтобы наполнить библиотеку."
        />
      );
    }
    if (route.name === "locations") {
      return <LocationsPage projectId={active.id} />;
    }
    if (route.name === "props") {
      return <PropsPage projectId={active.id} />;
    }
    if (route.name === "shots") {
      return <ShotsPage projectId={active.id} />;
    }
    return <CharacterListPage projectId={active.id} />;
  }

  const showProjectPicker = !inCharacters && !inShots;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand__name">Mary Studio</span>
          <span className="brand__tag">библиотека</span>
        </div>
        <nav className="nav" aria-label="Разделы">
          <a
            href="#/characters"
            className={inCharacters ? "nav__link nav__link--active" : "nav__link"}
          >
            Персонажи
          </a>
          <a
            href="#/locations"
            className={route.name === "locations" ? "nav__link nav__link--active" : "nav__link"}
          >
            Локации
          </a>
          <a
            href="#/props"
            className={route.name === "props" ? "nav__link nav__link--active" : "nav__link"}
          >
            Предметы
          </a>
          <a
            href="#/shots"
            className={inShots ? "nav__link nav__link--active" : "nav__link"}
          >
            Шоты
          </a>
        </nav>
        {showProjectPicker && list.length > 1 && active !== null && (
          <label className="field field--inline">
            <span>Проект</span>
            <select
              value={active.id}
              onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                setSelectedId(event.target.value)
              }
            >
              {list.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.title}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>
      <main className="main">{renderContent()}</main>
    </div>
  );
}

import type {
  Attempt,
  BibleVersion,
  CharacterDetail,
  CharacterSummary,
  Composition,
  CompositionLayerInput,
  CompositionRender,
  CompositionSummary,
  KeyframeResult,
  LocationSummary,
  Project,
  PropSummary,
  ReferenceAsset,
  ReferenceFilters,
  RenderQueued,
  SceneSummary,
  ShotDetail,
  ShotReference,
  ShotSummary,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const DETAIL_MESSAGES: Record<string, string> = {
  render_already_active: "Рендер уже запущен",
};

function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail !== null && typeof detail === "object" && "error" in detail) {
    const error = (detail as { error: unknown }).error;
    if (typeof error === "string") {
      const text = DETAIL_MESSAGES[error] ?? error;
      const jobId = (detail as { job_id?: unknown }).job_id;
      return typeof jobId === "string" ? `${text} (job ${jobId.slice(0, 8)})` : text;
    }
  }
  return JSON.stringify(detail);
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload: unknown = await response.json();
      if (payload !== null && typeof payload === "object" && "detail" in payload) {
        message = describeDetail((payload as { detail: unknown }).detail);
      }
    } catch {
      // тело ошибки не JSON — оставляем код статуса
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function request<T>(path: string, init?: RequestInit): Promise<T> {
  return fetch(path, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  }).then(parse<T>);
}

function send<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function referenceQuery(filters: ReferenceFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.view) params.set("view", filters.view);
  if (filters.pose) params.set("pose", filters.pose);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export interface CompositionWrite {
  width: number;
  height: number;
  layers: CompositionLayerInput[];
}

export const api = {
  projects: () => request<Project[]>("/api/projects"),

  characters: (projectId: string) =>
    request<CharacterSummary[]>(`/api/projects/${projectId}/characters`),

  character: (characterId: string) =>
    request<CharacterDetail>(`/api/characters/${characterId}`),

  bible: (characterId: string) =>
    request<BibleVersion[]>(`/api/characters/${characterId}/bible`),

  references: (characterId: string, filters: ReferenceFilters) =>
    request<ReferenceAsset[]>(
      `/api/characters/${characterId}/references${referenceQuery(filters)}`,
    ),

  locations: (projectId: string) =>
    request<LocationSummary[]>(`/api/projects/${projectId}/locations`),

  props: (projectId: string) =>
    request<PropSummary[]>(`/api/projects/${projectId}/props`),

  projectReferences: (projectId: string) =>
    request<ReferenceAsset[]>(`/api/projects/${projectId}/references`),

  approve: (referenceId: string) =>
    request<ReferenceAsset>(`/api/reference-assets/${referenceId}/approve`, {
      method: "POST",
    }),

  reject: (referenceId: string) =>
    request<ReferenceAsset>(`/api/reference-assets/${referenceId}/reject`, {
      method: "POST",
    }),

  scenes: (projectId: string) =>
    request<SceneSummary[]>(`/api/projects/${projectId}/scenes`),

  createScene: (projectId: string, body: { title: string | null }) =>
    send<SceneSummary>(`/api/projects/${projectId}/scenes`, "POST", body),

  createShot: (sceneId: string, body: { target_duration_frames?: number | null }) =>
    send<ShotSummary>(`/api/scenes/${sceneId}/shots`, "POST", body),

  shot: (shotId: string) => request<ShotDetail>(`/api/shots/${shotId}`),

  attempts: (shotId: string) => request<Attempt[]>(`/api/shots/${shotId}/attempts`),

  attachReference: (
    shotId: string,
    body: { reference_asset_id: string; purpose: string },
  ) => send<ShotReference>(`/api/shots/${shotId}/references`, "POST", body),

  detachReference: (shotId: string, linkId: string) =>
    request<void>(`/api/shots/${shotId}/references/${linkId}`, { method: "DELETE" }),

  compositions: (shotId: string) =>
    request<CompositionSummary[]>(`/api/shots/${shotId}/compositions`),

  composition: (shotId: string, revision: number) =>
    request<Composition>(`/api/shots/${shotId}/compositions/${revision}`),

  createComposition: (shotId: string, body: CompositionWrite) =>
    send<Composition>(`/api/shots/${shotId}/compositions`, "POST", body),

  updateComposition: (shotId: string, revision: number, body: CompositionWrite) =>
    send<Composition>(`/api/shots/${shotId}/compositions/${revision}`, "PUT", body),

  renderComposition: (shotId: string, revision: number) =>
    request<CompositionRender>(
      `/api/shots/${shotId}/compositions/${revision}/render`,
      { method: "POST" },
    ),

  approveComposition: (shotId: string, revision: number) =>
    request<Composition>(`/api/shots/${shotId}/compositions/${revision}/approve`, {
      method: "POST",
    }),

  supersedeComposition: (shotId: string, revision: number) =>
    request<Composition>(`/api/shots/${shotId}/compositions/${revision}/supersede`, {
      method: "POST",
    }),

  keyframe: (shotId: string, compositionRevision: number | null) =>
    send<KeyframeResult>(`/api/shots/${shotId}/keyframe`, "POST", {
      composition_revision: compositionRevision,
    }),

  promoteKeyframe: (shotId: string, attemptId: string) =>
    request<ShotSummary>(
      `/api/shots/${shotId}/attempts/${attemptId}/promote-keyframe`,
      { method: "POST" },
    ),

  renderShot: (shotId: string) =>
    request<RenderQueued>(`/api/shots/${shotId}/render`, { method: "POST" }),
};

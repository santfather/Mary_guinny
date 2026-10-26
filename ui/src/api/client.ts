import type {
  BibleVersion,
  CharacterDetail,
  CharacterSummary,
  LocationSummary,
  Project,
  PropSummary,
  ReferenceAsset,
  ReferenceFilters,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload: unknown = await response.json();
      if (payload !== null && typeof payload === "object" && "detail" in payload) {
        const detail = (payload as { detail: unknown }).detail;
        message = typeof detail === "string" ? detail : JSON.stringify(detail);
      }
    } catch {
      // тело ошибки не JSON — оставляем код статуса
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

function referenceQuery(filters: ReferenceFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.view) params.set("view", filters.view);
  if (filters.pose) params.set("pose", filters.pose);
  const query = params.toString();
  return query ? `?${query}` : "";
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

  approve: (referenceId: string) =>
    request<ReferenceAsset>(`/api/reference-assets/${referenceId}/approve`, {
      method: "POST",
    }),

  reject: (referenceId: string) =>
    request<ReferenceAsset>(`/api/reference-assets/${referenceId}/reject`, {
      method: "POST",
    }),
};

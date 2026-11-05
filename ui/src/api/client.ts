import type {
  Attempt,
  AttemptFilters,
  AttemptPage,
  BibleVersion,
  CharacterDetail,
  CharacterSummary,
  Composition,
  CompositionLayerInput,
  CompositionRender,
  CompositionSummary,
  ExportCreate,
  ExportResult,
  JobDetail,
  JobEvent,
  KeyframeResult,
  LayoutExport,
  LibraryEntity,
  LibraryEntityDetail,
  LibraryKind,
  MouthAnimationRequest,
  MouthAnimationResult,
  MouthCalibration,
  MouthCalibrationInput,
  PlanGenerateRequest,
  ProductionPlan,
  Project,
  ProjectAudio,
  ReferenceAsset,
  ReferenceFilters,
  RenderAgentStatus,
  RenderQueued,
  ScenePlan,
  ScenePlanCandidate,
  ScenePlanGenerateRequest,
  ScenePlanWrite,
  SceneSummary,
  SeriesRun,
  SeriesRunCreate,
  SeriesRunSummary,
  ShotAudio,
  ShotAudioWaveform,
  ShotDetail,
  ShotReference,
  ShotSummary,
  Timeline,
  VisemeSetReport,
  VisemeVariant,
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
  duplicate_reference: "Такой файл уже загружен в проект",
  // WP-VOICE-02: импорт и подготовка аудио.
  unsupported_audio_type: "Неподдерживаемый формат: нужен WAV, MP3, M4A или AAC",
  empty_body: "Файл пустой",
  sha256_mismatch: "Контрольная сумма файла не совпала с заявленной",
  ffprobe_failed: "ffprobe не смог прочитать файл",
  missing_audio_stream: "В файле нет аудиодорожки",
  invalid_audio: "Файл не является корректной аудиозаписью",
  audio_too_long: "Запись длиннее допустимого предела",
  audio_work_copy_missing: "Рабочая PCM-копия записи отсутствует",
  audio_work_copy_invalid: "Рабочая PCM-копия записи повреждена",
  envelope_missing: "У записи нет огибающей",
  work_audio_missing: "Рабочая копия записи потеряна в storage",
  // WP-VOICE-02: блокировки Talking Preview.
  audio_required: "Нужна утверждённая запись: импортируйте и утвердите аудио",
  audio_not_approved: "Запись ещё не утверждена человеком",
  source_image_required: "Нужен approved-референс или утверждённый стартовый кадр",
  source_reference_not_approved: "Референс не утверждён человеком",
  source_file_missing: "Файл источника не найден в storage",
  source_image_invalid: "Источник не декодируется как изображение",
  reference_not_linked: "Референс не привязан к шоту",
  video_talking_not_supported:
    "Video Talking не поддерживается: нет надёжного tracking морды. Используйте image-режим",
  calibration_required: "Сначала сохраните калибровку области рта",
  calibration_source_mismatch: "Калибровка относится к другому источнику изображения",
  calibration_conflict: "Калибровка уже сохраняется, повторите запрос",
  mouth_region_out_of_bounds: "Область рта выходит за кадр",
  ffmpeg_missing: "ffmpeg не найден в PATH",
  ffmpeg_failed: "FFmpeg не смог собрать MP4",
  invalid_preview: "Результат не прошёл проверку MP4 и аудиодорожки",
  // WP-VOICE-06: viseme-набор и новый движок.
  viseme_state_invalid: "Неизвестная форма рта",
  viseme_image_invalid: "Кадр морды не читается как PNG или JPEG",
  viseme_set_incomplete: "Набор viseme-кадров неполный",
  viseme_set_not_approved: "Не все viseme-кадры утверждены человеком",
  viseme_set_blocked:
    "Набор viseme-кадров не прошёл проверку совместимости — генерация заблокирована",
  viseme_resolution_mismatch: "Кадры набора разного разрешения",
  viseme_head_shift: "Голова в кадрах набора сдвинута",
  viseme_outside_mouth_changes: "Кадры отличаются вне области морды",
  viseme_closed_mismatch: "Кадр closed не совпадает с источником",
  viseme_no_articulation: "Форма рта в кадре не отличается от закрытой",
  viseme_flicker_risk: "При переключении кадров будет мерцание",
  viseme_file_missing: "Файл viseme-кадра потерян в storage",
  viseme_timing_required: "Нужен viseme timing JSON или проверенный Rhubarb",
  viseme_timing_invalid: "Viseme timing JSON невалиден",
  viseme_pause_not_closed: "В паузе рот не закрыт",
  rhubarb_not_installed: "Rhubarb не установлен",
  rhubarb_not_executable: "Файл Rhubarb не исполняемый",
  rhubarb_arch_unknown: "Не удалось определить архитектуру Rhubarb",
  rhubarb_arch_unsupported: "Бинарник Rhubarb не для этой архитектуры",
  rhubarb_res_missing: "Рядом с бинарником Rhubarb нет каталога res/",
  rhubarb_input_unsupported: "Rhubarb принимает только .wav и .ogg",
  rhubarb_runs_under_rosetta: "Rhubarb работает через Rosetta 2 (сборка x86_64)",
  rhubarb_sha256_not_pinned: "SHA-256 Rhubarb не закреплён в настройках",
  rhubarb_sha256_mismatch: "SHA-256 бинарника Rhubarb не совпал с закреплённым",
  rhubarb_output_invalid: "Rhubarb вернул неожиданный JSON",
  rhubarb_failed: "Rhubarb не смог разобрать запись",
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

function attemptQuery(filters: AttemptFilters): string {
  const params = new URLSearchParams();
  if (filters.scene_id) params.set("scene_id", filters.scene_id);
  if (filters.shot_id) params.set("shot_id", filters.shot_id);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.status) params.set("status", filters.status);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export interface CompositionWrite {
  width: number;
  height: number;
  layers: CompositionLayerInput[];
}

export interface ReferenceUploadParams {
  kind: string;
  character_id?: string;
  location_id?: string;
  prop_id?: string;
  view?: string;
  pose?: string;
  role?: string;
}

export interface ReferenceMeta {
  view?: string;
  pose?: string;
  expression?: string;
  role?: string;
  multi_view?: boolean;
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string" && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

function uploadReference(
  projectId: string,
  params: ReferenceUploadParams,
  file: File,
): Promise<ReferenceAsset> {
  return fetch(
    `/api/projects/${projectId}/references${query({
      kind: params.kind,
      character_id: params.character_id,
      location_id: params.location_id,
      prop_id: params.prop_id,
      view: params.view,
      pose: params.pose,
      role: params.role,
    })}`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": file.type || "application/octet-stream",
      },
      body: file,
    },
  ).then(parse<ReferenceAsset>);
}

async function uploadReferences(
  projectId: string,
  params: ReferenceUploadParams,
  files: File[],
): Promise<ReferenceAsset[]> {
  const uploaded: ReferenceAsset[] = [];
  for (const file of files) {
    uploaded.push(await uploadReference(projectId, params, file));
  }
  return uploaded;
}

/** Голосовой образец персонажа: `reference_assets(role='voice')`, до 30 секунд. */
function uploadVoice(characterId: string, file: File): Promise<ReferenceAsset> {
  return fetch(`/api/characters/${characterId}/voice`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": file.type || "application/octet-stream",
    },
    body: file,
  }).then(parse<ReferenceAsset>);
}

async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/** Универсальная загрузка артефакта (звук для сборки): сервер сверяет sha256. */
async function uploadArtifact(file: File, kind: string): Promise<{ id: string }> {
  const digest = await sha256Hex(file);
  return parse<{ id: string }>(
    await fetch(`/api/artifacts?kind=${encodeURIComponent(kind)}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": file.type || "application/octet-stream",
        "X-Content-SHA256": digest,
      },
      body: file,
    }),
  );
}

const AUDIO_MIME_BY_EXTENSION: Record<string, string> = {
  wav: "audio/wav",
  mp3: "audio/mpeg",
  m4a: "audio/mp4",
  aac: "audio/aac",
};

function audioMime(file: File): string {
  const declared = (file.type || "").split(";")[0].trim().toLowerCase();
  if (declared !== "") return declared;
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return AUDIO_MIME_BY_EXTENSION[extension] ?? "application/octet-stream";
}

/** Импорт готовой записи: оригинал сохраняется на сервере без изменений. */
async function uploadShotAudio(shotId: string, file: File): Promise<ShotAudio> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": audioMime(file),
    "X-Content-SHA256": await sha256Hex(file),
  };
  // HTTP-заголовки не переносят не-ASCII: имя с кириллицей просто не передаём.
  if (/^[\x20-\x7e]+$/.test(file.name)) headers["X-Original-Name"] = file.name;
  return parse<ShotAudio>(
    await fetch(`/api/shots/${shotId}/audio`, { method: "POST", headers, body: file }),
  );
}

/** PNG предпросмотра рта: blob URL, вызывающий код обязан его освободить. */
async function mouthCalibrationPreview(
  shotId: string,
  body: MouthCalibrationInput,
  state: "closed" | "open",
): Promise<string> {
  const response = await fetch(
    `/api/shots/${shotId}/mouth-calibrations/preview?state=${state}`,
    {
      method: "POST",
      headers: { Accept: "image/png", "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
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
  return URL.createObjectURL(await response.blob());
}

/** WP-VOICE-06: отчёт совместимости viseme-набора шота. */
function visemeSet(
  shotId: string,
  referenceAssetId?: string,
  calibrationId?: string,
): Promise<VisemeSetReport> {
  const params = new URLSearchParams();
  if (referenceAssetId) params.set("reference_asset_id", referenceAssetId);
  if (calibrationId) params.set("calibration_id", calibrationId);
  const suffix = params.toString();
  return request<VisemeSetReport>(
    `/api/shots/${shotId}/viseme-set${suffix ? `?${suffix}` : ""}`,
  );
}

/** Импорт одного кадра морды: файл сохраняется черновиком, исходник не меняется. */
function uploadViseme(
  shotId: string,
  state: string,
  file: File,
): Promise<VisemeVariant> {
  return fetch(`/api/shots/${shotId}/viseme-set/${encodeURIComponent(state)}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": file.type || "image/png",
    },
    body: file,
  }).then(parse<VisemeVariant>);
}

export interface LibraryApi {
  list: (projectId: string) => Promise<LibraryEntity[]>;
  get: (id: string) => Promise<LibraryEntityDetail>;
  create: (projectId: string, body: { name: string; description?: string }) => Promise<LibraryEntity>;
  update: (id: string, body: { name?: string; description?: string | null }) => Promise<LibraryEntity>;
}

export interface LibraryUploadTarget {
  kind: string;
  ownerParam: "location_id" | "prop_id";
}

/** Локации и предметы отличаются только путём API и полем-владельцем референса. */
export const libraryApi: Record<LibraryKind, LibraryApi & LibraryUploadTarget> = {
  location: {
    list: (projectId) =>
      request<LibraryEntity[]>(`/api/projects/${projectId}/locations`),
    get: (id) => request<LibraryEntityDetail>(`/api/locations/${id}`),
    create: (projectId, body) =>
      send<LibraryEntity>(`/api/projects/${projectId}/locations`, "POST", body),
    update: (id, body) => send<LibraryEntity>(`/api/locations/${id}`, "PATCH", body),
    kind: "location_reference",
    ownerParam: "location_id",
  },
  prop: {
    list: (projectId) => request<LibraryEntity[]>(`/api/projects/${projectId}/props`),
    get: (id) => request<LibraryEntityDetail>(`/api/props/${id}`),
    create: (projectId, body) =>
      send<LibraryEntity>(`/api/projects/${projectId}/props`, "POST", body),
    update: (id, body) => send<LibraryEntity>(`/api/props/${id}`, "PATCH", body),
    kind: "prop_reference",
    ownerParam: "prop_id",
  },
};

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

  relabel: (referenceId: string, body: ReferenceMeta) =>
    send<ReferenceAsset>(`/api/reference-assets/${referenceId}`, "PATCH", body),

  uploadReference,

  uploadReferences,

  uploadVoice,

  scenes: (projectId: string) =>
    request<SceneSummary[]>(`/api/projects/${projectId}/scenes`),

  createScene: (projectId: string, body: { title: string | null }) =>
    send<SceneSummary>(`/api/projects/${projectId}/scenes`, "POST", body),

  createShot: (sceneId: string, body: { target_duration_frames?: number | null }) =>
    send<ShotSummary>(`/api/scenes/${sceneId}/shots`, "POST", body),

  shot: (shotId: string) => request<ShotDetail>(`/api/shots/${shotId}`),

  // WP-VOICE-02: готовые записи шота, калибровка рта и Talking Preview.
  shotAudio: (shotId: string) => request<ShotAudio[]>(`/api/shots/${shotId}/audio`),

  uploadShotAudio,

  shotAudioWaveform: (shotId: string, assetId: string, buckets = 400) =>
    request<ShotAudioWaveform>(
      `/api/shots/${shotId}/audio/${assetId}/waveform?buckets=${buckets}`,
    ),

  mouthCalibrations: (shotId: string) =>
    request<MouthCalibration[]>(`/api/shots/${shotId}/mouth-calibrations`),

  saveMouthCalibration: (shotId: string, body: MouthCalibrationInput) =>
    send<MouthCalibration>(
      `/api/shots/${shotId}/mouth-calibrations`,
      "POST",
      body,
    ),

  mouthCalibrationPreview,

  // WP-VOICE-06: набор кадров морды и проверка совместимости.
  visemeSet,

  uploadViseme,

  createMouthAnimation: (shotId: string, body: MouthAnimationRequest) =>
    send<MouthAnimationResult>(
      `/api/shots/${shotId}/mouth-animation`,
      "POST",
      body,
    ),

  attempts: (shotId: string) => request<Attempt[]>(`/api/shots/${shotId}/attempts`),

  projectAttempts: (projectId: string, filters: AttemptFilters = {}) =>
    request<AttemptPage>(`/api/projects/${projectId}/attempts${attemptQuery(filters)}`),

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

  exportLayout: (shotId: string, revision: number, size: number, mode: string) =>
    send<LayoutExport>(
      `/api/shots/${shotId}/compositions/${revision}/export`,
      "POST",
      { size, mode },
    ),

  scenePlans: (shotId: string) =>
    request<ScenePlan[]>(`/api/shots/${shotId}/scene-plans`),

  generateScenePlan: (shotId: string, body: ScenePlanGenerateRequest) =>
    send<ScenePlanCandidate>(`/api/shots/${shotId}/scene-plans/generate`, "POST", body),

  createScenePlan: (
    shotId: string,
    body: {
      plan: ScenePlanWrite;
      source: string;
      warnings: { code: string; message: string }[];
    },
  ) => send<ScenePlan>(`/api/shots/${shotId}/scene-plans`, "POST", body),

  updateScenePlan: (shotId: string, revision: number, plan: ScenePlanWrite) =>
    send<ScenePlan>(`/api/shots/${shotId}/scene-plans/${revision}`, "PUT", plan),

  approveScenePlan: (shotId: string, revision: number) =>
    request<ScenePlan>(`/api/shots/${shotId}/scene-plans/${revision}/approve`, {
      method: "POST",
    }),

  supersedeScenePlan: (shotId: string, revision: number) =>
    request<ScenePlan>(`/api/shots/${shotId}/scene-plans/${revision}/supersede`, {
      method: "POST",
    }),

  compositionFromPlan: (shotId: string, revision: number) =>
    request<Composition>(
      `/api/shots/${shotId}/scene-plans/${revision}/composition`,
      { method: "POST" },
    ),

  promoteKeyframe: (shotId: string, attemptId: string) =>
    request<ShotSummary>(
      `/api/shots/${shotId}/attempts/${attemptId}/promote-keyframe`,
      { method: "POST" },
    ),

  approveAttempt: (shotId: string, attemptId: string) =>
    request<ShotSummary>(`/api/shots/${shotId}/attempts/${attemptId}/approve`, {
      method: "POST",
    }),

  rejectAttempt: (shotId: string, attemptId: string) =>
    request<ShotSummary>(`/api/shots/${shotId}/attempts/${attemptId}/reject`, {
      method: "POST",
    }),

  job: (jobId: string) => request<JobDetail>(`/api/jobs/${jobId}`),

  jobEvents: (jobId: string) =>
    request<JobEvent[]>(`/api/jobs/${jobId}/events`),

  renderShot: (shotId: string, preview = false) =>
    send<RenderQueued>(`/api/shots/${shotId}/render`, "POST", { preview }),

  seriesRuns: (projectId: string) =>
    request<SeriesRunSummary[]>(`/api/projects/${projectId}/series/runs`),

  seriesRun: (runId: string) => request<SeriesRun>(`/api/series/${runId}`),

  createSeriesRun: (projectId: string, body: SeriesRunCreate) =>
    send<SeriesRun>(`/api/projects/${projectId}/series/runs`, "POST", body),

  seriesAction: (runId: string, action: string) =>
    request<SeriesRun>(`/api/series/${runId}/${action}`, { method: "POST" }),

  renderAgentStatus: () => request<RenderAgentStatus>("/api/render-agent/status"),

  exports: (projectId: string) =>
    request<ExportResult[]>(`/api/projects/${projectId}/exports`),

  createExport: (projectId: string, body: ExportCreate) =>
    send<ExportResult>(`/api/projects/${projectId}/exports`, "POST", body),

  uploadArtifact,

  projectAudio: (projectId: string) =>
    request<ProjectAudio>(`/api/projects/${projectId}/audio`),

  attachProjectAudio: (projectId: string, artifactId: string) =>
    send<ProjectAudio>(`/api/projects/${projectId}/audio`, "POST", {
      artifact_id: artifactId,
    }),

  projectTimeline: (projectId: string) =>
    request<Timeline>(`/api/projects/${projectId}/timeline`),

  productionPlans: (projectId: string) =>
    request<ProductionPlan[]>(`/api/projects/${projectId}/production-plans`),

  productionPlan: (planId: string) =>
    request<ProductionPlan>(`/api/production-plans/${planId}`),

  generateProductionPlan: (projectId: string, body: PlanGenerateRequest) =>
    send<ProductionPlan>(
      `/api/projects/${projectId}/production-plans/generate`,
      "POST",
      body,
    ),
};

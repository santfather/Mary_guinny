export interface Project {
  id: string;
  title: string;
  status: string;
}

export interface BibleVersionSummary {
  version: number;
  status: string;
  source: string;
  sha256: string;
  created_at: string;
  approved_at: string | null;
}

export interface BibleVersion extends BibleVersionSummary {
  body: string;
}

export interface ReferenceAsset {
  id: string;
  kind: string;
  status: string;
  role: string | null;
  character_id: string | null;
  location_id: string | null;
  prop_id: string | null;
  view: string | null;
  pose: string | null;
  expression: string | null;
  width: number | null;
  height: number | null;
  mime_type: string | null;
  sha256: string;
  has_alpha: boolean | null;
  duration_s: number | null;
  multi_view: boolean;
  approved_at: string | null;
  created_at: string;
  content_url: string;
}

export interface CharacterSummary {
  id: string;
  slug: string;
  name: string;
  kind: string;
  status: string;
  description: string | null;
  reference_count: number;
  approved_reference_count: number;
  bible_version_count: number;
  latest_bible_version: number | null;
  latest_bible_status: string | null;
}

export interface CharacterDetail extends CharacterSummary {
  bible_versions: BibleVersionSummary[];
}

export type LibraryKind = "location" | "prop";

export interface LibraryEntity {
  id: string;
  project_id: string;
  slug: string;
  name: string;
  description: string | null;
  status: string;
  reference_count: number;
}

export interface LibraryEntityDetail extends LibraryEntity {
  references: ReferenceAsset[];
}

export interface ReferenceFilters {
  status: string;
  view: string;
  pose: string;
}

export interface ShotSummary {
  id: string;
  scene_id: string;
  project_id: string;
  sequence_no: number;
  status: string;
  target_duration_frames: number | null;
  timeline_fps: number | null;
  start_keyframe_artifact_id: string | null;
  start_keyframe_attempt_id: string | null;
  start_keyframe_content_url: string | null;
  approved_attempt_id: string | null;
}

export interface SceneSummary {
  id: string;
  project_id: string;
  episode_id: string | null;
  sequence_no: number;
  title: string | null;
  shots: ShotSummary[];
}

export interface ShotReference {
  id: string;
  purpose: string;
  reference: ReferenceAsset;
}

export interface CompositionLayerInput {
  reference_asset_id: string;
  z_index: number;
  x: number;
  y: number;
  scale: number;
  rotation: number;
  opacity: number;
}

export interface CompositionLayer extends CompositionLayerInput {
  reference: ReferenceAsset;
}

export interface CompositionSummary {
  revision: number;
  width: number;
  height: number;
  status: string;
  layer_count: number;
  preview_artifact_id: string | null;
  preview_content_url: string | null;
  source_plan_id: string | null;
  layout_mockup: boolean;
  created_at: string;
  approved_at: string | null;
}

export interface Composition extends CompositionSummary {
  layers: CompositionLayer[];
}

export interface CompositionWarning {
  code: string;
  message: string;
  z_index: number;
  reference_asset_id: string;
}

export interface CompositionRender {
  artifact_id: string;
  content_url: string;
  width: number;
  height: number;
  preview_artifact_id: string | null;
  warnings: CompositionWarning[];
  is_layout_mockup: boolean;
}

export interface Attempt {
  id: string;
  kind: string;
  status: string;
  job_id: string | null;
  created_at: string;
  artifact_id: string | null;
  artifact_content_url: string | null;
  composition_revision: number | null;
  visual_plan_revision: number | null;
  workflow_version: string | null;
  model_hash: string | null;
  seed: number | null;
  duration_s: number | null;
  render_parameters: Record<string, unknown> | null;
}

export interface AttemptListItem extends Attempt {
  shot_id: string;
  shot_sequence_no: number;
  scene_id: string;
  scene_title: string | null;
  shot_status: string;
  approved: boolean;
}

export interface AttemptPage {
  items: AttemptListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AttemptFilters {
  scene_id?: string;
  shot_id?: string;
  kind?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export interface JobEvent {
  sequence: number;
  event: string;
  stage: string | null;
  progress: number | null;
  attempt_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface JobDetail {
  id: string;
  kind: string;
  status: string;
  shot_id: string | null;
  scene_id: string | null;
  attempts: number;
  max_attempts: number;
  error_code: string | null;
  lease_owner: string | null;
  lease_until: string | null;
  run_after: string | null;
  created_at: string;
  updated_at: string;
  last_event: JobEvent | null;
}

export interface KeyframeResult {
  attempt_id: string;
  artifact_id: string;
  artifact_content_url: string;
  composition_revision: number;
  status: string;
}

export interface RenderQueued {
  job_id: string;
  status: string;
  shot_id: string;
  start_keyframe_artifact_id: string;
}

export interface ShotDetail extends ShotSummary {
  references: ShotReference[];
  composition_revisions: CompositionSummary[];
  attempts: Attempt[];
}

export type PlanRole = "character" | "location" | "prop" | "style" | "storyboard";
export type CameraFraming = "wide" | "medium" | "close_up" | "other";
export type CameraMovement =
  | "static"
  | "pan"
  | "tilt"
  | "dolly"
  | "zoom"
  | "handheld"
  | "other";

export interface PlanReference {
  asset_id: string;
  role: PlanRole;
  entity_id: string | null;
  alias: string;
}

export interface PlanInitialState {
  subject: string;
  position: string;
  action: string;
}

export interface PlanActionBeat {
  order: number;
  subject: string;
  action: string;
  target: string | null;
}

export interface ScenePlanWrite {
  canvas: { width: number; height: number };
  references: PlanReference[];
  camera: { framing: CameraFraming; movement: CameraMovement };
  initial_state: PlanInitialState[];
  action_beats: PlanActionBeat[];
  constraints: {
    preserve_character_identity: boolean;
    preserve_location_layout: boolean;
    no_unreferenced_characters: boolean;
  };
  motion_prompt: string;
  needs_review: boolean;
}

export interface ScenePlanWarning {
  code: string;
  message: string;
}

export interface ScenePlan {
  id: string;
  project_id: string;
  shot_id: string;
  revision: number;
  schema_version: number;
  status: string;
  source: string;
  plan: ScenePlanWrite;
  warnings: ScenePlanWarning[];
  created_at: string;
  approved_at: string | null;
}

export interface ScenePlanCandidate {
  plan: ScenePlanWrite;
  warnings: ScenePlanWarning[];
  source: string;
}

export interface ScenePlanGenerateRequest {
  action: string;
  references: PlanReference[];
  camera: { framing: CameraFraming; movement: CameraMovement };
  canvas: { width: number; height: number };
  use_vision: boolean;
}

export interface LayoutExport {
  artifact_id: string;
  content_url: string;
  size: number;
  mode: string;
  source_composition_revision: number;
  source_artifact_id: string;
  is_layout_mockup: boolean;
}

export interface SeriesRunSummary {
  run_id: string;
  title: string | null;
  status: string;
  total_items: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface SeriesItem {
  order: number;
  shot_id: string;
  shot_sequence_no: number;
  status: string;
  job_id: string | null;
  job_status: string | null;
  progress: number | null;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface SeriesRun {
  run_id: string;
  project_id: string;
  title: string | null;
  status: string;
  stop_on_error: boolean;
  manifest_sha256: string | null;
  total_items: number;
  counts: Record<string, number>;
  started_at: string | null;
  finished_at: string | null;
  items: SeriesItem[];
}

export interface SeriesRunCreate {
  title?: string;
  shot_orders?: number[];
  stop_on_error: boolean;
}

/** WP-THERMAL-02 (Q-29): read-only состояние render-agent. */
export interface RenderAgentStatus {
  worker_online: boolean;
  stale: boolean;
  updated_at: string | null;
  age_seconds: number | null;
  worker: string | null;
  profile: string | null;
  rendering: boolean;
  current_job_id: string | null;
  thermal: { state: string; source: string };
  power: { source: string | null; battery_percent: number | null };
  memory: { pressure: string | null; pressure_level: number | null; available_mb: number | null };
  admission: { allowed: boolean | null; reason: string | null; wait_seconds: number | null };
  cooldown: { next_allowed_at: string | null; remaining_seconds: number | null };
  pause: { active: boolean; reason: string | null; since: string | null; waited_seconds: number | null };
  batch: { index: number | null; size: number | null };
  queue: {
    active_render_jobs: number;
    pending_render_jobs: number;
    current_run_id: string | null;
    current_run_status: string | null;
  };
  last_events: {
    ts: string | null;
    event: string | null;
    reason: string | null;
    thermal: string | null;
    job_id: string | null;
  }[];
}

export interface ExportClipInput {
  shot_id: string;
  attempt_id: string;
  trim_start_s?: number;
  trim_end_s?: number;
}

export interface ExportCreate {
  clips: ExportClipInput[];
  audio_artifact_id?: string;
}

export interface ExportResult {
  artifact_id: string;
  content_url: string;
  sha256: string;
  bytes: number;
  width: number;
  height: number;
  fps: number;
  duration_s: number;
  clip_count: number;
  audio_artifact_id: string | null;
  created_at: string;
}

export interface PlanWarning {
  code: string;
  message: string;
}

export interface ProjectAudio {
  artifact_id: string;
  content_url: string;
  mime_type: string;
  bytes: number;
  duration_s: number;
}

export type EnergyTier = "low" | "mid" | "high";

export interface TimelineSection {
  start_s: number;
  end_s: number;
  rms: number;
  energy_tier: EnergyTier;
}

export interface Timeline {
  duration_s: number;
  bpm: number | null;
  bpm_confidence: number;
  meter: string;
  beats: number[];
  downbeats: number[];
  sections: TimelineSection[];
  method: string;
  analysis_rate_hz: number;
  warnings: PlanWarning[];
}

export interface PlanShot {
  order: number;
  start_s: number;
  end_s: number;
  action: string;
  prompt: string;
  framing: CameraFraming;
  camera_movement: CameraMovement;
}

export interface PlanScene {
  order: number;
  section_index: number;
  title: string;
  intent: string;
  energy_tier: EnergyTier;
  start_s: number;
  end_s: number;
  shots: PlanShot[];
}

export interface ProductionPlanBody {
  schema_version: number;
  logline: string;
  scenes: PlanScene[];
  notes: string[];
  needs_review: boolean;
}

export interface ProductionPlan {
  id: string;
  project_id: string;
  revision: number;
  schema_version: number;
  status: string;
  source: string;
  audio_artifact_id: string | null;
  timeline: Timeline;
  plan: ProductionPlanBody;
  warnings: PlanWarning[];
  created_at: string;
}

export interface PlanGenerateRequest {
  brief?: string;
  use_llm: boolean;
}

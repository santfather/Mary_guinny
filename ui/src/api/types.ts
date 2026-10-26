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
  view: string | null;
  pose: string | null;
  expression: string | null;
  width: number | null;
  height: number | null;
  mime_type: string | null;
  sha256: string;
  has_alpha: boolean | null;
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

export interface LocationSummary {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  status: string;
  reference_count: number;
}

export interface PropSummary {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  status: string;
  reference_count: number;
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

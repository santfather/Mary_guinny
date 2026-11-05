import type { Attempt } from "./api/types";

// Порядок ключей `render_parameters`, которые пишет воркер (WP-N3).
export const PARAMETER_KEYS = [
  "width",
  "height",
  "num_frames",
  "frame_rate",
  "fps",
  "cfg_scale",
  "aspect_ratio",
  "long_side",
  "shot_key",
];

// WP-THERMAL-03 (T-07): preview-попытка — не финальный ролик.
export function isPreviewAttempt(attempt: Attempt): boolean {
  return attempt.render_parameters?.preview === true;
}

export function attemptMeta(attempt: Attempt): { summary: string[]; parameters: string[] } {
  const summary: string[] = [];
  if (isPreviewAttempt(attempt)) summary.push("preview");
  if (attempt.seed !== null) summary.push(`seed ${attempt.seed}`);
  if (attempt.duration_s !== null) summary.push(`${attempt.duration_s.toFixed(2)} с`);
  if (attempt.workflow_version !== null) {
    summary.push(`wf ${attempt.workflow_version.slice(0, 8)}`);
  }
  if (attempt.model_hash !== null) summary.push(`model ${attempt.model_hash.slice(0, 8)}`);
  const values = attempt.render_parameters;
  const parameters =
    values === null
      ? []
      : PARAMETER_KEYS.filter((key) => values[key] !== undefined).map(
          (key) => `${key}=${String(values[key])}`,
        );
  return { summary, parameters };
}

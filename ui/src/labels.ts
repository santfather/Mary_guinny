const STATUS_LABELS: Record<string, string> = {
  draft: "Черновик",
  approved: "Утверждён",
  rejected: "Отклонён",
  superseded: "Заменён",
  active: "Активен",
  archived: "В архиве",
};

const VIEW_LABELS: Record<string, string> = {
  front: "спереди",
  side: "сбоку",
  three_quarter: "три четверти",
  back: "сзади",
  other: "другой ракурс",
};

const POSE_LABELS: Record<string, string> = {
  stand: "стоит",
  sit: "сидит",
  walk: "идёт",
  lie: "лежит",
  sleep: "спит",
  custom: "другая поза",
};

const KIND_LABELS: Record<string, string> = {
  cat: "Кот",
  human: "Человек",
  other: "Другое",
};

const PURPOSE_LABELS: Record<string, string> = {
  character: "персонаж",
  location: "локация",
  prop: "предмет",
  style: "стиль",
  other: "другое",
};

const REFERENCE_KIND_LABELS: Record<string, string> = {
  character_reference: "персонаж",
  location_reference: "локация",
  prop_reference: "предмет",
  uploaded: "загружен",
};

const PLAN_ROLE_LABELS: Record<string, string> = {
  character: "персонаж",
  location: "локация",
  prop: "предмет",
  style: "стиль",
  storyboard: "раскадровка",
};

const FRAMING_LABELS: Record<string, string> = {
  wide: "общий",
  medium: "средний",
  close_up: "крупный",
  other: "другой",
};

const MOVEMENT_LABELS: Record<string, string> = {
  static: "статичная",
  pan: "панорама",
  tilt: "наклон",
  dolly: "тележка",
  zoom: "зум",
  handheld: "ручная",
  other: "другая",
};

const PLAN_SOURCE_LABELS: Record<string, string> = {
  manual: "вручную",
  llm: "vision-предложение",
  fallback: "fallback",
};

export function planRoleLabel(role: string): string {
  return PLAN_ROLE_LABELS[role] ?? role;
}

export function framingLabel(framing: string): string {
  return FRAMING_LABELS[framing] ?? framing;
}

export function movementLabel(movement: string): string {
  return MOVEMENT_LABELS[movement] ?? movement;
}

export function planSourceLabel(source: string): string {
  return PLAN_SOURCE_LABELS[source] ?? source;
}

export function purposeLabel(purpose: string): string {
  return PURPOSE_LABELS[purpose] ?? purpose;
}

export function referenceKindLabel(kind: string): string {
  return REFERENCE_KIND_LABELS[kind] ?? kind;
}

export function canApproveReference(status: string): boolean {
  return status === "draft" || status === "rejected";
}

export function canRejectReference(status: string): boolean {
  return status === "draft" || status === "approved";
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function statusTone(status: string): "ok" | "danger" | "warn" | "muted" {
  if (status === "approved" || status === "active") return "ok";
  if (status === "rejected") return "danger";
  if (status === "superseded") return "warn";
  return "muted";
}

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

export function viewLabel(view: string | null): string | null {
  if (view === null) return null;
  return VIEW_LABELS[view] ?? view;
}

export function poseLabel(pose: string | null): string | null {
  if (pose === null) return null;
  return POSE_LABELS[pose] ?? pose;
}

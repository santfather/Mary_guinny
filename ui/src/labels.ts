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

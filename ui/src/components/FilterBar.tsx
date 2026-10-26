import type { ChangeEvent } from "react";

import type { ReferenceFilters } from "../api/types";

interface FilterBarProps {
  value: ReferenceFilters;
  onChange: (next: ReferenceFilters) => void;
}

const STATUS_OPTIONS = [
  ["", "Все статусы"],
  ["draft", "Черновик"],
  ["approved", "Утверждён"],
  ["rejected", "Отклонён"],
  ["superseded", "Заменён"],
] as const;

const VIEW_OPTIONS = [
  ["", "Все ракурсы"],
  ["front", "Спереди"],
  ["side", "Сбоку"],
  ["three_quarter", "Три четверти"],
  ["back", "Сзади"],
  ["other", "Другой"],
] as const;

const POSE_OPTIONS = [
  ["", "Все позы"],
  ["stand", "Стоит"],
  ["sit", "Сидит"],
  ["walk", "Идёт"],
  ["lie", "Лежит"],
  ["sleep", "Спит"],
  ["custom", "Другая"],
] as const;

export function FilterBar({ value, onChange }: FilterBarProps) {
  const update =
    (key: keyof ReferenceFilters) => (event: ChangeEvent<HTMLSelectElement>) => {
      onChange({ ...value, [key]: event.target.value });
    };

  return (
    <div className="filters">
      <label className="field">
        <span>Статус</span>
        <select value={value.status} onChange={update("status")}>
          {STATUS_OPTIONS.map(([option, label]) => (
            <option key={option} value={option}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Ракурс</span>
        <select value={value.view} onChange={update("view")}>
          {VIEW_OPTIONS.map(([option, label]) => (
            <option key={option} value={option}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Поза</span>
        <select value={value.pose} onChange={update("pose")}>
          {POSE_OPTIONS.map(([option, label]) => (
            <option key={option} value={option}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="button button--ghost"
        onClick={() => onChange({ status: "", view: "", pose: "" })}
      >
        Сбросить
      </button>
    </div>
  );
}

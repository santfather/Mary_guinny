interface StateViewProps {
  kind: "loading" | "empty" | "error";
  title: string;
  message?: string;
  onRetry?: () => void;
}

export function StateView({ kind, title, message, onRetry }: StateViewProps) {
  return (
    <div className={`state state--${kind}`} role={kind === "error" ? "alert" : "status"}>
      {kind === "loading" && <span className="spinner" aria-hidden="true" />}
      <h2 className="state__title">{title}</h2>
      {message !== undefined && <p className="state__message">{message}</p>}
      {onRetry !== undefined && (
        <button type="button" className="button" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

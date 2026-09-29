import type { ReactNode } from "react";
import type { ApiErrorBody, Job, ProjectStatus, Stage } from "../types";

export function Page({ title, subtitle, actions, children }: { title: string; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          {subtitle && <p className="muted">{subtitle}</p>}
        </div>
        {actions && <div className="row gap">{actions}</div>}
      </header>
      {children}
    </div>
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={"card " + (className ?? "")}>
      {(title || actions) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="row gap">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function Button({
  children,
  onClick,
  busy,
  disabled,
  kind = "default",
  title,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  busy?: boolean;
  disabled?: boolean;
  kind?: "default" | "primary" | "danger" | "ghost";
  title?: string;
  type?: "button" | "submit";
}) {
  return (
    <button type={type} className={`btn btn-${kind}`} onClick={onClick} disabled={disabled || busy} title={title}>
      {busy ? <span className="spinner" aria-hidden /> : null}
      {children}
    </button>
  );
}

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: "neutral" | "good" | "bad" | "warn" | "info" | "accent"; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<ProjectStatus, "neutral" | "good" | "bad" | "warn" | "info" | "accent"> = {
  DRAFT: "neutral",
  REVIEW: "warn",
  APPROVED: "good",
  REJECTED: "bad",
  EXPORTED: "info",
  POSTED: "accent",
  SUBMITTED: "accent",
};

export function StatusBadge({ status }: { status: ProjectStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{status}</Badge>;
}

export function ErrorBanner({ error, onClose }: { error: ApiErrorBody | null; onClose?: () => void }) {
  if (!error) return null;
  return (
    <div className="banner banner-error" role="alert">
      <div>
        <strong>{error.message}</strong>
        {error.hint && <div>{error.hint}</div>}
        {error.errors && error.errors.length > 0 && (
          <ul>
            {error.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}
        {error.detail && (
          <details>
            <summary>Technical details</summary>
            <pre>{error.detail}</pre>
          </details>
        )}
      </div>
      {onClose && (
        <button className="btn btn-ghost" onClick={onClose} aria-label="Dismiss">
          ×
        </button>
      )}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" | "good" }) {
  return <div className={`banner banner-${tone}`}>{children}</div>;
}

export function JobBar({ job }: { job: Job | null }) {
  if (!job || job.status === "succeeded") return null;
  return (
    <div className="jobbar">
      <div className="jobbar-text">
        <span className="spinner" aria-hidden /> {job.message}
      </div>
      <div className="progress">
        <div className="progress-fill" style={{ width: `${Math.round(job.progress * 100)}%` }} />
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function StageStepper({ stages }: { stages: Stage[] }) {
  return (
    <ol className="stepper">
      {stages.map((s, i) => (
        <li key={s.name} className={`step step-${s.state}`}>
          <span className="step-dot">{s.state === "done" ? "✓" : i + 1}</span>
          <span className="step-name">{s.name}</span>
        </li>
      ))}
    </ol>
  );
}

export function Score({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100);
  const tone = pct >= 75 ? "good" : pct >= 50 ? "warn" : "bad";
  return (
    <span className={`score score-${tone}`} title={`${label}: ${pct}%`}>
      {label} {pct}%
    </span>
  );
}

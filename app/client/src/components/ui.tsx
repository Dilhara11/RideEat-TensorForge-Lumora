// Small, consistent component vocabulary. Status is always text + icon, never colour alone.

import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type Variant = "default" | "primary" | "ghost" | "danger" | "danger-ghost";
type Size = "md" | "sm" | "icon";

const VARIANT: Record<Variant, string> = {
  default: "border-border-strong bg-surface text-text hover:bg-surface-2",
  primary: "border-accent bg-accent text-on-accent hover:border-accent-hover hover:bg-accent-hover",
  ghost: "border-transparent bg-transparent text-text hover:bg-surface-2",
  danger: "border-danger bg-danger text-on-danger hover:opacity-90",
  "danger-ghost": "border-transparent bg-transparent text-danger hover:bg-danger-soft",
};
const SIZE: Record<Size, string> = {
  md: "min-h-10 px-4 py-2",
  sm: "min-h-8 px-2.5 py-1 text-[13px]",
  icon: "h-10 w-10 p-0 text-lg",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  busy?: boolean;
  busyLabel?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "md", busy = false, busyLabel, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md border font-semibold no-underline transition-colors disabled:cursor-not-allowed disabled:opacity-55",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {busy ? (
        <>
          <Spinner /> {busyLabel ?? children}
        </>
      ) : (
        children
      )}
    </button>
  );
});

export function Spinner() {
  return <span aria-hidden="true" className="inline-block size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" />;
}

type Tone = "urgent" | "review" | "ok" | "neutral" | "info" | "danger";
const TONE: Record<Tone, string> = {
  urgent: "border-danger bg-danger-soft text-danger",
  danger: "border-transparent bg-danger-soft text-danger",
  review: "border-warning-fill bg-warning-soft text-warning",
  ok: "border-transparent bg-success-soft text-success",
  neutral: "border-border bg-surface-2 text-text-2",
  info: "border-transparent bg-accent-soft text-accent",
};

export function Badge({ tone = "neutral", icon, children, className }: { tone?: Tone; icon?: string; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[13px] font-semibold", TONE[tone], className)}>
      {icon && <span aria-hidden="true">{icon}</span>}
      {children}
    </span>
  );
}

export const UrgentBadge = () => <Badge tone="urgent" icon="▲">Urgent</Badge>;
export const ReviewBadge = ({ short = false }: { short?: boolean }) => <Badge tone="review" icon="●">{short ? "Review" : "Needs review"}</Badge>;

const NOTE: Record<"warning" | "danger" | "ok" | "info", string> = {
  warning: "border-warning-fill bg-warning-soft",
  danger: "border-danger bg-danger-soft",
  ok: "border-success bg-success-soft",
  info: "border-accent bg-accent-soft",
};

export function Note({ tone, children, role }: { tone: keyof typeof NOTE; children: ReactNode; role?: "alert" | "status" }) {
  return (
    <div role={role} className={cx("my-3 rounded-md border-l-4 px-4 py-3 text-[14.5px]", NOTE[tone])}>
      {children}
    </div>
  );
}

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function Card({ className, children, ...rest }, ref) {
  return (
    <div ref={ref} className={cx("mb-6 rounded-card border border-border bg-surface p-4 shadow-card sm:p-6", className)} {...rest}>
      {children}
    </div>
  );
});

export function Eyebrow({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <p id={id} className="mb-0.5 text-xs font-semibold uppercase tracking-wide text-muted">
      {children}
    </p>
  );
}

export function FieldError({ id, children }: { id?: string; children?: ReactNode }) {
  if (!children) return null;
  return (
    <p id={id} className="mt-1 text-sm text-danger">
      <span aria-hidden="true">⚠ </span>
      {children}
    </p>
  );
}

export function StatTile({ label, value, sub, icon }: { label: string; value: string; sub?: string | null; icon?: string }) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3">
      <div className="text-[13px] text-muted">
        {icon && <span aria-hidden="true" className="mr-1">{icon}</span>}
        {label}
      </div>
      <div className="text-2xl font-semibold leading-tight">{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function PanelHead({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-6 max-w-3xl">
      <h1 className="mb-2 text-2xl font-semibold leading-tight">{title}</h1>
      <p className="text-muted">{children}</p>
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: string; title: string; children: ReactNode }) {
  return (
    <div className="px-4 py-12 text-center">
      <span aria-hidden="true" className="mb-2 block text-3xl text-muted">{icon}</span>
      <p className="mb-1 font-semibold">{title}</p>
      <p className="text-muted">{children}</p>
    </div>
  );
}

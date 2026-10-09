// Small, consistent component vocabulary. Status is always text + icon, never colour alone.

import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from "react";
import { Icon, type IconName } from "./icons";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type Variant = "default" | "primary" | "ghost" | "danger" | "danger-ghost";
type Size = "md" | "sm" | "icon";

const VARIANT: Record<Variant, string> = {
  default: "border-border-strong bg-surface text-text shadow-card hover:border-accent/40 hover:bg-surface-2",
  primary: "border-transparent bg-accent text-on-accent shadow-[0_1px_2px_rgb(0_0_0/0.12),inset_0_1px_0_rgb(255_255_255/0.12)] hover:bg-accent-hover",
  ghost: "border-transparent bg-transparent text-text-2 hover:bg-surface-3 hover:text-text",
  danger: "border-transparent bg-danger text-on-danger hover:opacity-90",
  "danger-ghost": "border-transparent bg-transparent text-danger hover:bg-danger-soft",
};
const SIZE: Record<Size, string> = {
  md: "min-h-10 px-4 py-2 text-[14.5px]",
  sm: "min-h-8 px-3 py-1 text-[13px]",
  icon: "size-10 p-0",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  busy?: boolean;
  busyLabel?: string;
  icon?: IconName;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "md", busy = false, busyLabel, icon, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex cursor-pointer select-none items-center justify-center gap-2 whitespace-nowrap rounded-lg border font-semibold no-underline transition-[background-color,border-color,color,transform] duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100",
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
        <>
          {icon && <Icon name={icon} size={size === "sm" ? 15 : 17} />}
          {children}
        </>
      )}
    </button>
  );
});

export function Spinner() {
  return <span aria-hidden="true" className="inline-block size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" />;
}

type Tone = "urgent" | "review" | "ok" | "neutral" | "info" | "danger";
const TONE: Record<Tone, string> = {
  urgent: "border-danger/30 bg-danger-soft text-danger",
  danger: "border-transparent bg-danger-soft text-danger",
  review: "border-warning-fill/40 bg-warning-soft text-warning",
  ok: "border-success/25 bg-success-soft text-success",
  neutral: "border-border bg-surface-2 text-text-2",
  info: "border-accent/25 bg-accent-soft text-accent",
};

export function Badge({ tone = "neutral", icon, small = false, children, className }: { tone?: Tone; icon?: IconName; small?: boolean; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border font-semibold",
        small ? "px-2 py-px text-[11.5px]" : "px-2.5 py-0.5 text-[12.5px]",
        TONE[tone],
        className,
      )}
    >
      {icon && <Icon name={icon} size={small ? 12 : 13} />}
      {children}
    </span>
  );
}

export const UrgentBadge = () => <Badge tone="urgent" icon="zap">Urgent</Badge>;
export const ReviewBadge = ({ short = false }: { short?: boolean }) => <Badge tone="review" icon="userCheck">{short ? "Review" : "Needs review"}</Badge>;

const NOTE: Record<"warning" | "danger" | "ok" | "info", { box: string; icon: IconName; ink: string }> = {
  warning: { box: "border-warning-fill/40 bg-warning-soft", icon: "alert", ink: "text-warning" },
  danger: { box: "border-danger/30 bg-danger-soft", icon: "alert", ink: "text-danger" },
  ok: { box: "border-success/30 bg-success-soft", icon: "checkCircle", ink: "text-success" },
  info: { box: "border-accent/25 bg-accent-soft", icon: "inbox", ink: "text-accent" },
};

export function Note({ tone, children, role }: { tone: keyof typeof NOTE; children: ReactNode; role?: "alert" | "status" }) {
  const n = NOTE[tone];
  return (
    <div role={role} className={cx("my-3 flex gap-3 rounded-lg border px-4 py-3 text-[14.5px]", n.box)}>
      <Icon name={n.icon} size={18} className={cx("mt-0.5", n.ink)} />
      <div className="min-w-0 flex-1">{children}</div>
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

export function CardHead({ icon, title, sub, children }: { icon?: IconName; title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-start gap-3">
      {icon && (
        <span aria-hidden="true" className="grid size-9 place-items-center rounded-lg bg-accent-soft text-accent">
          <Icon name={icon} size={18} />
        </span>
      )}
      <div className="mr-auto min-w-0">
        <h2 className="font-semibold leading-tight">{title}</h2>
        {sub && <p className="mt-0.5 text-sm text-muted">{sub}</p>}
      </div>
      {children}
    </div>
  );
}

export function Eyebrow({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <p id={id} className="mb-0.5 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-muted">
      {children}
    </p>
  );
}

export function FieldError({ id, children }: { id?: string; children?: ReactNode }) {
  if (!children) return null;
  return (
    <p id={id} className="mt-1.5 flex items-center gap-1.5 text-sm text-danger">
      <Icon name="alert" size={14} />
      {children}
    </p>
  );
}

export function StatTile({ label, value, sub, icon, tone = "info" }: { label: string; value: string; sub?: string | null; icon?: IconName; tone?: "info" | "urgent" | "review" | "ok" }) {
  const chip = { info: "bg-accent-soft text-accent", urgent: "bg-danger-soft text-danger", review: "bg-warning-soft text-warning", ok: "bg-success-soft text-success" }[tone];
  return (
    <div className="rounded-card border border-border bg-surface p-4 shadow-card">
      <div className="flex items-center gap-2 text-[13px] font-medium text-muted">
        {icon && (
          <span aria-hidden="true" className={cx("grid size-7 place-items-center rounded-md", chip)}>
            <Icon name={icon} size={15} />
          </span>
        )}
        {label}
      </div>
      <div className="mt-2 text-[26px] font-semibold leading-none tracking-tight tabular-nums">{value}</div>
      {sub && <div className="mt-1.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function PanelHead({ title, eyebrow, children, actions }: { title: string; eyebrow?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end gap-4">
      <div className="mr-auto max-w-3xl">
        {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
        <h1 className="mb-1.5 text-[26px] font-semibold leading-tight tracking-tight">{title}</h1>
        <p className="text-muted">{children}</p>
      </div>
      {actions}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: IconName; title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-4 py-12 text-center">
      <span aria-hidden="true" className="mb-3 grid size-12 place-items-center rounded-full bg-surface-2 text-muted ring-8 ring-surface-2/50">
        <Icon name={icon} size={22} />
      </span>
      <p className="mb-1 font-semibold">{title}</p>
      <p className="max-w-sm text-sm text-muted">{children}</p>
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-b-2 border-border-strong bg-surface px-1.5 py-px text-[12px] text-text-2">{children}</kbd>;
}

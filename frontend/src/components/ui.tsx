import {
  forwardRef,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import type { Confidence, EnrichmentStatus } from "../api/types";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

/* ---------- Buttons ---------- */

type Variant = "primary" | "secondary" | "danger" | "ghost";

const base =
  "inline-flex items-center justify-center gap-2 min-h-11 px-5 rounded-[12px] text-body font-semibold select-none " +
  "transition-colors disabled:cursor-not-allowed disabled:opacity-60";
const variants: Record<Variant, string> = {
  primary: "bg-navy-900 text-white hover:bg-navy-700 active:bg-navy-700",
  secondary: "bg-white text-navy-900 border border-line hover:bg-navy-50 active:bg-navy-100",
  danger: "bg-danger text-white hover:bg-[#9a3030] active:bg-[#9a3030]",
  ghost: "bg-transparent text-navy-900 hover:bg-navy-100 active:bg-navy-100",
};

export function buttonClass(variant: Variant = "primary", extra?: string) {
  return cx(base, variants[variant], extra);
}

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean; loadingText?: string }
>(function Button({ variant = "primary", loading, loadingText, className, children, disabled, type, ...rest }, ref) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={buttonClass(variant, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <>
          <Spinner />
          <span>{loadingText ?? children}</span>
        </>
      ) : (
        children
      )}
    </button>
  );
});

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("size-4 animate-spin motion-reduce:animate-none", className)} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/* ---------- Layout ---------- */

export function Card({ children, className, as: As = "section", padded = true, ...rest }: { children: ReactNode; className?: string; as?: "section" | "div" | "article"; padded?: boolean; "aria-labelledby"?: string }) {
  return (
    <As className={cx("bg-white border border-line rounded-card shadow-card", padded && "p-5", className)} {...rest}>
      {children}
    </As>
  );
}

export function SectionHeader({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <h2 id={id} className="label-caps text-navy-500 mb-2">
      {children}
    </h2>
  );
}

export function Chip({ children, onRemove, removeLabel }: { children: ReactNode; onRemove?: () => void; removeLabel?: string }) {
  return (
    <span className={cx("inline-flex items-center max-w-full rounded-full bg-navy-100 text-navy-900 text-label font-medium pl-3 py-1 min-h-8", onRemove ? "pr-0" : "pr-3")}>
      <span className="truncate">{children}</span>
      {onRemove && (
        // 44×44 hit area overlapping the chip edge; the visible circle stays 28 px.
        <button
          type="button"
          onClick={onRemove}
          aria-label={removeLabel ?? "Remove"}
          className="group -my-1.5 inline-flex size-11 shrink-0 items-center justify-center rounded-full text-navy-500"
        >
          <span className="inline-flex size-7 items-center justify-center rounded-full group-hover:bg-white/70">
            <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </span>
        </button>
      )}
    </span>
  );
}

/* ---------- Inferred marker ---------- */

export const INFERRED_TOOLTIP = "Rolo's reading of your notes, not something you said.";
export const MAYBE_TOOLTIP = "You weren't sure about this.";

/**
 * Tap-to-explain marker. The button is a 44×44 hit area; negative margins keep the
 * line height and the visual small (DESIGN.md: inferred = gold dot, maybe = gold-outline chip).
 */
function Marker({ kind }: { kind: "inferred" | "maybe" }) {
  const [open, setOpen] = useState(false);
  const tipId = useId();
  const tip = kind === "maybe" ? MAYBE_TOOLTIP : INFERRED_TOOLTIP;
  return (
    <>
      <button
        type="button"
        title={tip}
        aria-describedby={tipId}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="group -my-2.5 inline-flex h-11 min-w-11 items-center justify-center rounded-full px-1 align-middle"
      >
        {kind === "maybe" ? (
          <span className="inline-flex h-5 items-center rounded-full border border-gold bg-transparent px-2 text-tiny font-medium text-navy-700 group-hover:bg-navy-50">
            maybe
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-tiny font-medium text-navy-500 group-hover:text-navy-900">
            <span className="size-1.5 rounded-full bg-gold" aria-hidden="true" />
            inferred
          </span>
        )}
      </button>
      <span id={tipId} role="tooltip" className={open ? "mt-1 block text-meta text-navy-500" : "sr-only"}>
        {tip}
      </span>
    </>
  );
}

export function InferredMarker() {
  return <Marker kind="inferred" />;
}

export function MaybeMarker() {
  return <Marker kind="maybe" />;
}

export function ConfidenceMarker({ confidence }: { confidence: Confidence | undefined | null }) {
  if (confidence === "maybe") return <MaybeMarker />;
  if (confidence === "inferred") return <InferredMarker />;
  return null;
}

export function ConfidenceText({ value, confidence }: { value: string; confidence: Confidence }) {
  return (
    <span>
      {value}
      {(confidence === "inferred" || confidence === "maybe") && (
        <>
          {" "}
          <ConfidenceMarker confidence={confidence} />
        </>
      )}
    </span>
  );
}

/* ---------- Status dot ---------- */

const STATUS: Record<EnrichmentStatus, { cls: string; label: string }> = {
  none: { cls: "bg-white border border-navy-500", label: "Not enriched" },
  pending: { cls: "bg-navy-500 animate-pulse motion-reduce:animate-none", label: "Enriching" },
  done: { cls: "bg-success", label: "Enriched" },
  failed: { cls: "bg-danger", label: "Enrichment failed" },
};

export function StatusDot({ status }: { status: EnrichmentStatus }) {
  const s = STATUS[status] ?? STATUS.none;
  return (
    <span className="inline-flex items-center" title={s.label}>
      <span className={cx("size-2.5 rounded-full", s.cls)} aria-hidden="true" />
      <span className="sr-only">{s.label}</span>
    </span>
  );
}

/* ---------- Skeleton ---------- */

export function SkeletonLines({ lines = 3, className }: { lines?: number; className?: string }) {
  const widths = ["w-11/12", "w-4/5", "w-2/3", "w-3/4", "w-1/2"];
  return (
    <div className={cx("space-y-3", className)} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className={cx("skeleton h-3.5", widths[i % widths.length])} />
      ))}
    </div>
  );
}

/* ---------- Alerts ---------- */

export function ErrorBox({ title, children, action }: { title?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div role="alert" className="rounded-card border border-danger/40 bg-[#FBF1F1] p-4 text-navy-900">
      {title && <p className="font-semibold text-danger">{title}</p>}
      <div className="text-body">{children}</div>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function EmptyState({ text, action }: { text: string; action?: ReactNode }) {
  return (
    <div className="py-12 text-center">
      <p className="text-body text-navy-500">{text}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

/* ---------- Auto-sizing textarea ---------- */

export const AutoTextarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { minRows?: number }>(
  function AutoTextarea({ minRows = 6, className, value, onChange, ...rest }, ref) {
    const inner = useRef<HTMLTextAreaElement | null>(null);
    const resize = () => {
      const el = inner.current;
      if (!el) return;
      el.style.height = "auto";
      const max = Math.max(240, Math.round(window.innerHeight * 0.6));
      const h = el.scrollHeight + 2;
      el.style.height = `${Math.min(h, max)}px`;
      el.style.overflowY = h > max ? "auto" : "hidden";
    };
    useLayoutEffect(resize, [value]);
    useEffect(() => {
      window.addEventListener("resize", resize);
      return () => window.removeEventListener("resize", resize);
    }, []);
    return (
      <textarea
        ref={(el) => {
          inner.current = el;
          if (typeof ref === "function") ref(el);
          else if (ref) ref.current = el;
        }}
        rows={minRows}
        value={value}
        onChange={onChange}
        className={cx(inputClass, "resize-none leading-6", className)}
        {...rest}
      />
    );
  },
);

export const inputClass =
  "block w-full rounded-[12px] border border-line bg-white px-4 py-3 text-body text-navy-900 placeholder:text-navy-500 " +
  "focus-visible:border-navy-900 aria-[invalid=true]:border-danger";

export function FieldLabel({ htmlFor, children, hint }: { htmlFor: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-3">
      <label htmlFor={htmlFor} className="label-caps text-navy-500">
        {children}
      </label>
      {hint}
    </div>
  );
}

export function FieldError({ id, children }: { id: string; children: ReactNode }) {
  if (!children) return null;
  return (
    <p id={id} className="mt-2 text-label text-danger" role="alert">
      {children}
    </p>
  );
}

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { addDays, formatLongDate, parseYmd, toYmd, todayYmd } from "../lib/dates";
import { cx } from "./ui";

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/**
 * Compact month calendar (DESIGN.md v2). Monday-first, 7 columns.
 * Each day is a ≥44 px button with a 32 px visual circle: selected = navy-900 fill, today = navy-500 ring.
 * Days before `minDate` are disabled. Arrow keys move between days (roving tabindex).
 */
export function MiniCalendar({
  value,
  onSelect,
  minDate,
  disabled,
  label = "Choose a date",
}: {
  value: string | null;
  onSelect?: (ymd: string) => void;
  minDate?: string;
  disabled?: boolean;
  label?: string;
}) {
  const today = todayYmd();
  const initial = parseYmd(value) ?? parseYmd(today)!;
  const [view, setView] = useState({ y: initial.getFullYear(), m: initial.getMonth() });
  const [focusYmd, setFocusYmd] = useState(value ?? today);
  const gridRef = useRef<HTMLDivElement>(null);
  const wantFocus = useRef(false);

  useEffect(() => {
    const d = parseYmd(value);
    if (d) {
      setView({ y: d.getFullYear(), m: d.getMonth() });
      setFocusYmd(value!);
    }
  }, [value]);

  const cells = useMemo(() => {
    const first = new Date(view.y, view.m, 1);
    const lead = (first.getDay() + 6) % 7; // Monday-first
    const days = new Date(view.y, view.m + 1, 0).getDate();
    const out: (string | null)[] = Array.from({ length: lead }, () => null);
    for (let d = 1; d <= days; d++) out.push(toYmd(new Date(view.y, view.m, d)));
    while (out.length % 7) out.push(null);
    return out;
  }, [view]);

  const monthLabel = new Date(view.y, view.m, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const min = minDate ? parseYmd(minDate) : null;
  const prevDisabled = !!min && new Date(view.y, view.m, 1) <= new Date(min.getFullYear(), min.getMonth(), 1);
  const isDisabled = (ymd: string) => disabled || (!!minDate && ymd < minDate);

  // Keep the roving focus target inside the visible month.
  const inView = cells.includes(focusYmd);
  const tabTarget = inView ? focusYmd : (cells.find((c) => c && !isDisabled(c)) ?? null);

  useEffect(() => {
    if (!wantFocus.current) return;
    wantFocus.current = false;
    gridRef.current?.querySelector<HTMLButtonElement>(`[data-ymd="${focusYmd}"]`)?.focus();
  }, [focusYmd, view]);

  const moveFocus = (ymd: string) => {
    const d = parseYmd(ymd)!;
    wantFocus.current = true;
    setFocusYmd(ymd);
    if (d.getFullYear() !== view.y || d.getMonth() !== view.m) setView({ y: d.getFullYear(), m: d.getMonth() });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, ymd: string) => {
    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (delta !== undefined) {
      e.preventDefault();
      const next = addDays(ymd, delta);
      if (!minDate || next >= minDate) moveFocus(next);
    }
  };

  const shift = (n: number) => {
    const d = new Date(view.y, view.m + n, 1);
    setView({ y: d.getFullYear(), m: d.getMonth() });
  };

  return (
    <div className="-mx-3" role="group" aria-label={label}>
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => shift(-1)}
          disabled={prevDisabled || disabled}
          aria-label="Previous month"
          className="inline-flex size-11 items-center justify-center rounded-full text-navy-900 hover:bg-navy-50 disabled:opacity-40"
        >
          <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
            <path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <p className="text-body font-semibold" aria-live="polite">
          {monthLabel}
        </p>
        <button
          type="button"
          onClick={() => shift(1)}
          disabled={disabled}
          aria-label="Next month"
          className="inline-flex size-11 items-center justify-center rounded-full text-navy-900 hover:bg-navy-50 disabled:opacity-40"
        >
          <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
            <path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
      <div className="grid grid-cols-7" aria-hidden="true">
        {WEEKDAYS.map((w, i) => (
          <abbr key={w} title={WEEKDAY_NAMES[i]} className="py-1 text-center text-tiny font-medium text-navy-500 no-underline">
            {w}
          </abbr>
        ))}
      </div>
      <div ref={gridRef} className="grid grid-cols-7">
        {cells.map((ymd, i) =>
          ymd ? (
            <button
              key={ymd}
              type="button"
              data-ymd={ymd}
              tabIndex={ymd === tabTarget ? 0 : -1}
              disabled={isDisabled(ymd)}
              aria-pressed={ymd === value}
              aria-current={ymd === today ? "date" : undefined}
              aria-label={`${formatLongDate(ymd)}${ymd === today ? ", today" : ""}`}
              onClick={() => {
                setFocusYmd(ymd);
                onSelect?.(ymd);
              }}
              onKeyDown={(e) => onKeyDown(e, ymd)}
              className="group flex h-11 min-w-0 items-center justify-center disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span
                className={cx(
                  "inline-flex size-8 items-center justify-center rounded-full text-label",
                  ymd === value
                    ? "bg-navy-900 font-semibold text-white"
                    : ymd === today
                      ? "text-navy-900 ring-1 ring-navy-500 ring-inset group-hover:bg-navy-100"
                      : "text-navy-900 group-hover:bg-navy-100",
                  isDisabled(ymd) && "group-hover:bg-transparent",
                )}
              >
                {Number(ymd.slice(8))}
              </span>
            </button>
          ) : (
            <span key={`pad-${i}`} aria-hidden="true" />
          ),
        )}
      </div>
    </div>
  );
}

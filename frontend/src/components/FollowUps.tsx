import { useEffect, useId, useRef, useState } from "react";
import { api, ApiError, USE_MOCK, errorMessage, followUpIcsUrl, type Contact, type FollowUp } from "../api/client";
import { addDays, addMonths, formatShortDate, nextMonday, todayYmd } from "../lib/dates";
import { MiniCalendar } from "./MiniCalendar";
import { useToast } from "./Toast";
import { Card, ConfidenceMarker, SectionHeader, buttonClass, cx } from "./ui";

/** The date a follow-up is scheduled for, if any: the user's pick, else an exact suggestion. */
export function effectiveDate(f: FollowUp): string | null {
  if (f.dismissed) return null;
  if (f.confirmed_date) return f.confirmed_date;
  if (f.date_status === "exact" && f.suggested_date) return f.suggested_date;
  return null;
}

/** "Follow-ups" card section (DESIGN.md v2): calendar, date question, Add to Calendar. */
export function FollowUpsSection({
  contact,
  followUps,
  onChange,
}: {
  contact: Contact;
  followUps: FollowUp[];
  onChange: (c: Contact) => void;
}) {
  const id = useId();
  const pending = contact.enrichment_status === "pending";
  return (
    <Card aria-labelledby={id}>
      <SectionHeader id={id}>Follow-ups</SectionHeader>
      {pending && (
        <p className="mb-3 text-meta text-navy-500">Dates can be changed once Rolo finishes organising.</p>
      )}
      <ul className="divide-y divide-line">
        {followUps.map((f, i) => (
          <li key={`${i}-${f.action}`} className="py-4 first:pt-1 last:pb-0">
            <FollowUpRow contact={contact} f={f} index={i} disabled={pending} onChange={onChange} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

type Mode = "idle" | "chips" | "pick";

function FollowUpRow({
  contact,
  f,
  index,
  disabled,
  onChange,
}: {
  contact: Contact;
  f: FollowUp;
  index: number;
  disabled: boolean;
  onChange: (c: Contact) => void;
}) {
  const toast = useToast();
  const date = effectiveDate(f);
  const [mode, setMode] = useState<Mode>("idle");
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const calId = useId();
  const today = todayYmd();
  const isPast = f.date_status === "past";
  const askDate = !isPast && !date && !f.dismissed && f.date_status === "needs_date";

  useEffect(() => {
    if (disabled) setMode("idle");
  }, [disabled]);

  const patch = async (body: { confirmed_date?: string | null; dismissed?: boolean }, message: string, undo: { confirmed_date: string | null; dismissed: boolean } | null) => {
    if (busy || disabled) return;
    setBusy(true);
    setErr(null);
    try {
      const c = await api.patchFollowUp(contact.id, index, body);
      onChange(c);
      setMode("idle");
      toast(message, "success", undo ? { action: { label: "Undo", onClick: () => void revert(undo) } } : undefined);
    } catch (e) {
      setErr(
        e instanceof ApiError && e.code === "enrichment_in_progress"
          ? "Rolo is still organising this card. Try again in a moment."
          : errorMessage(e),
      );
    } finally {
      setBusy(false);
    }
  };

  const revert = async (prev: { confirmed_date: string | null; dismissed: boolean }) => {
    try {
      onChange(await api.patchFollowUp(contact.id, index, prev));
      toast("Undone.");
    } catch (e) {
      toast(`Couldn't undo. ${errorMessage(e)}`, "error");
    }
  };

  const prev = { confirmed_date: f.confirmed_date, dismissed: f.dismissed };
  const pick = (ymd: string) => void patch({ confirmed_date: ymd, dismissed: false }, `Follow-up set for ${formatShortDate(ymd)}`, prev);
  const noDate = () => void patch({ confirmed_date: null, dismissed: true }, "No date for this follow-up.", prev);

  return (
    <div>
      <p className="text-body">
        {f.action}
        {f.confidence !== "stated" && (
          <>
            {" "}
            <ConfidenceMarker confidence={f.confidence} />
          </>
        )}
      </p>
      {f.when_text && <p className="text-meta text-navy-500">“{f.when_text}”</p>}

      {isPast && <p className="mt-1 text-meta text-navy-500">(already happened)</p>}

      {/* exact / confirmed: date row (44 px) that expands into the calendar */}
      {!isPast && date && mode === "idle" && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setExpanded((x) => !x)}
            aria-expanded={expanded}
            aria-controls={calId}
            className="-mx-3 flex min-h-11 w-[calc(100%+24px)] items-center gap-3 rounded-[10px] px-3 text-left hover:bg-navy-50"
          >
            <CalendarIcon />
            <span className="flex-1 text-body font-medium">
              {formatShortDate(date)}
              {date < today && <span className="ml-2 text-meta font-normal text-navy-500">overdue</span>}
            </span>
            <svg viewBox="0 0 24 24" className={cx("size-5 text-navy-500 transition-transform", expanded && "rotate-180")} aria-hidden="true">
              <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="sr-only">{expanded ? "Hide calendar" : "Show calendar"}</span>
          </button>
          {expanded && (
            <div id={calId} className="mt-2">
              <MiniCalendar value={date} onSelect={(d) => d !== date && pick(d)} minDate={today} disabled={disabled || busy} label={`Follow-up date for: ${f.action}`} />
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
            <AddToCalendar contactId={contact.id} index={index} contactName={contact.name} />
            <button
              type="button"
              onClick={() => setMode("chips")}
              disabled={disabled}
              className="inline-flex min-h-11 items-center rounded-md px-1 text-label font-medium text-navy-700 underline underline-offset-4 disabled:opacity-60"
            >
              Change date
            </button>
          </div>
        </div>
      )}

      {/* needs_date: the question is shown straight away */}
      {(askDate || mode !== "idle") && !isPast && (
        <DateQuestion
          whenText={f.when_text}
          mode={mode === "pick" ? "pick" : "chips"}
          busy={busy}
          disabled={disabled}
          current={date}
          onChip={(ymd) => pick(ymd)}
          onPick={() => setMode("pick")}
          onNoDate={noDate}
          onCancel={mode !== "idle" ? () => setMode("idle") : undefined}
          label={f.action}
        />
      )}

      {/* none, or dismissed: a text link opens the chips */}
      {!isPast && !date && !askDate && mode === "idle" && (
        <div className="mt-1 flex flex-wrap items-center gap-x-3">
          {f.dismissed && <span className="text-meta text-navy-500">No date</span>}
          <button
            type="button"
            onClick={() => setMode("chips")}
            disabled={disabled}
            className="inline-flex min-h-11 items-center rounded-md px-1 text-label font-medium text-navy-700 underline underline-offset-4 disabled:opacity-60"
          >
            Add a date
          </button>
        </div>
      )}

      {err && (
        <p role="alert" className="mt-2 text-label text-danger">
          {err}
        </p>
      )}
    </div>
  );
}

function DateQuestion({
  whenText,
  mode,
  busy,
  disabled,
  current,
  onChip,
  onPick,
  onNoDate,
  onCancel,
  label,
}: {
  whenText: string | null;
  mode: "chips" | "pick";
  busy: boolean;
  disabled: boolean;
  current: string | null;
  onChip: (ymd: string) => void;
  onPick: () => void;
  onNoDate: () => void;
  onCancel?: () => void;
  label: string;
}) {
  const today = todayYmd();
  const chips: [string, string][] = [
    ["Next week", nextMonday(today)], // backend rule: next Monday
    ["In 2 weeks", addDays(today, 14)],
    ["Next month", addMonths(today, 1)],
  ];
  const off = busy || disabled;
  const chipCls =
    "inline-flex min-h-11 items-center rounded-full border border-line bg-white px-4 text-label font-medium text-navy-900 hover:bg-navy-100 disabled:opacity-60";
  return (
    <div className="mt-3">
      <div className="rounded-[12px] bg-navy-50 p-4">
        <p className="text-body">
          When should you follow up?
          {whenText ? ` You said “${whenText}”.` : ""}
        </p>
        <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label={`Quick dates for: ${label}`}>
          {chips.map(([text, ymd]) => (
            <button key={text} type="button" className={chipCls} disabled={off} onClick={() => onChip(ymd)} title={formatShortDate(ymd)}>
              {text}
            </button>
          ))}
          <button type="button" className={cx(chipCls, mode === "pick" && "border-navy-900")} disabled={off} onClick={onPick} aria-expanded={mode === "pick"}>
            Pick a date
          </button>
          <button type="button" className={chipCls} disabled={off} onClick={onNoDate}>
            No date
          </button>
        </div>
      </div>
      {mode === "pick" && (
        <div className="mt-3">
          <MiniCalendar value={current} onSelect={onChip} minDate={today} disabled={off} label={`Pick a follow-up date for: ${label}`} />
        </div>
      )}
      {onCancel && (
        <button
          type="button"
          onClick={onCancel}
          className="mt-1 inline-flex min-h-11 items-center rounded-md px-1 text-label font-medium text-navy-700 underline underline-offset-4"
        >
          Cancel
        </button>
      )}
    </div>
  );
}

function AddToCalendar({ contactId, index, contactName }: { contactId: string; index: number; contactName: string }) {
  const href = followUpIcsUrl(contactId, index);
  const toast = useToast();
  const linkRef = useRef<HTMLAnchorElement>(null);
  return (
    <a
      ref={linkRef}
      href={href}
      download="rolo-followup.ics"
      onClick={async (e) => {
        if (!USE_MOCK) return; // real backend serves the file
        e.preventDefault();
        const { mockIcs } = await import("../api/mock");
        const ics = mockIcs(contactId, index);
        if (!ics) {
          toast("Pick a date first.", "error");
          return;
        }
        const url = URL.createObjectURL(new Blob([ics], { type: "text/calendar" }));
        const a = document.createElement("a");
        a.href = url;
        a.download = "rolo-followup.ics";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }}
      aria-label={`Add to Calendar: follow up with ${contactName}`}
      className={buttonClass("primary", "w-full sm:w-auto")}
    >
      <CalendarIcon />
      Add to Calendar
    </a>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5 shrink-0" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </svg>
  );
}

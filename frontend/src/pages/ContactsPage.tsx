import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { api, errorMessage, type ContactSummary, type ServiceStatus, type UpcomingItem } from "../api/client";
import { formatShortDate } from "../lib/dates";
import { voiceSupportProblem } from "../voice/recorder";
import { AppBar, Page, SettingsLink } from "../components/AppBar";
import { Button, Chip, EmptyState, ErrorBox, SkeletonLines, Spinner, StatusDot, buttonClass, inputClass } from "../components/ui";
import { useToast } from "../components/Toast";
import { POLL_TIMEOUT_MS, useDebounced } from "../lib/hooks";
import { relativeTime } from "../lib/format";

type State =
  | { kind: "loading" }
  | { kind: "ready"; contacts: ContactSummary[] }
  | { kind: "error"; message: string };

export default function ContactsPage() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const debouncedQ = useDebounced(q, 250);
  const [state, setState] = useState<State>({ kind: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const flashShown = useRef(false);

  // One-shot message passed via navigation state (e.g. after delete).
  useEffect(() => {
    const flash = (location.state as { flash?: string } | null)?.flash;
    if (flash && !flashShown.current) {
      flashShown.current = true;
      toast(flash, "success");
      navigate(location.pathname + location.search, { replace: true, state: null });
    }
  }, [location, navigate, toast]);

  // Keep ?q= in the URL so Back returns to the same search.
  useEffect(() => {
    const trimmed = debouncedQ.trim();
    if ((params.get("q") ?? "") !== trimmed) {
      setParams(trimmed ? { q: trimmed } : {}, { replace: true });
    }
  }, [debouncedQ, params, setParams]);

  useEffect(() => {
    const ctrl = new AbortController();
    setRefreshing(true);
    api
      .listContacts(debouncedQ, { signal: ctrl.signal })
      .then((r) => setState({ kind: "ready", contacts: r.contacts }))
      .catch((e) => {
        if (!ctrl.signal.aborted) setState({ kind: "error", message: errorMessage(e) });
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setRefreshing(false);
      });
    return () => ctrl.abort();
  }, [debouncedQ, attempt]);

  // Refresh while any listed contact is still enriching, so status dots update.
  const anyPending = state.kind === "ready" && state.contacts.some((c) => c.enrichment_status === "pending");
  useEffect(() => {
    if (!anyPending) return;
    const ctrl = new AbortController();
    const t = setInterval(() => {
      api
        .listContacts(debouncedQ, { signal: ctrl.signal })
        .then((r) => setState({ kind: "ready", contacts: r.contacts }))
        .catch(() => {});
    }, 3000);
    const stop = setTimeout(() => clearInterval(t), POLL_TIMEOUT_MS);
    return () => {
      ctrl.abort();
      clearInterval(t);
      clearTimeout(stop);
    };
  }, [anyPending, debouncedQ]);

  const searching = debouncedQ.trim().length > 0;

  return (
    <>
      <AppBar title="Contacts" actions={<SettingsLink />} />
      <Page>
        <h1 className="text-title font-semibold">Contacts</h1>

        <form role="search" className="mt-5" onSubmit={(e) => e.preventDefault()}>
          <label htmlFor="search" className="sr-only">
            Search contacts
          </label>
          <div className="relative">
            <svg viewBox="0 0 24 24" className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-navy-500" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.5-3.5" />
            </svg>
            <input
              id="search"
              type="search"
              inputMode="search"
              autoComplete="off"
              enterKeyHint="search"
              placeholder="Search contacts"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className={`${inputClass} pl-12 pr-12`}
            />
            {refreshing && state.kind === "ready" && (
              <span className="absolute right-4 top-1/2 -translate-y-1/2 text-navy-500">
                <Spinner />
                <span className="sr-only">Searching…</span>
              </span>
            )}
          </div>
        </form>

        <SpeakButton />

        {!searching && <UpcomingStrip refreshKey={attempt} />}

        <div className="mt-6">
          {state.kind === "loading" && (
            <div aria-busy="true" aria-label="Loading contacts" className="space-y-4">
              {[0, 1, 2].map((i) => (
                <div key={i} className="rounded-card border border-line bg-white p-5">
                  <SkeletonLines lines={2} />
                </div>
              ))}
            </div>
          )}

          {state.kind === "error" && (
            <ErrorBox
              title="Couldn't load contacts"
              action={
                <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
                  Try again
                </Button>
              }
            >
              {state.message}
            </ErrorBox>
          )}

          {state.kind === "ready" && state.contacts.length === 0 &&
            (searching ? (
              <EmptyState
                text={`No contacts match “${debouncedQ.trim()}”.`}
                action={
                  <Button variant="secondary" onClick={() => setQ("")}>
                    Clear search
                  </Button>
                }
              />
            ) : (
              <EmptyState
                text="No contacts yet."
                action={
                  <Link to="/new" className={buttonClass("primary")}>
                    Add your first contact
                  </Link>
                }
              />
            ))}

          {state.kind === "ready" && state.contacts.length > 0 && (
            <>
              <p className="sr-only" aria-live="polite">
                {state.contacts.length} {state.contacts.length === 1 ? "contact" : "contacts"}
                {searching ? ` matching ${debouncedQ.trim()}` : ""}
              </p>
              <ul className="space-y-4">
                {state.contacts.map((c) => (
                  <li key={c.id}>
                    <ContactRow c={c} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </Page>

      <Link
        to="/new"
        aria-label="New contact"
        className="fixed bottom-[calc(20px+env(safe-area-inset-bottom))] right-5 z-30 inline-flex size-14 items-center justify-center rounded-full bg-navy-900 text-white shadow-card hover:bg-navy-700 md:right-[max(20px,calc(50%-300px))]"
      >
        <svg viewBox="0 0 24 24" className="size-7" aria-hidden="true">
          <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </Link>
    </>
  );
}

function ContactRow({ c }: { c: ContactSummary }) {
  const subtitle = c.headline ?? c.company ?? (c.enrichment_status === "pending" ? "Organising notes…" : null);
  return (
    <Link
      to={`/c/${c.id}`}
      className="block rounded-card border border-line bg-white p-5 shadow-card hover:border-navy-500"
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-name font-semibold">{c.name}</h2>
          {subtitle && <p className="mt-0.5 line-clamp-2 text-body text-navy-500">{subtitle}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-2">
          <span className="text-meta text-navy-500">{relativeTime(c.updated_at)}</span>
          <StatusDot status={c.enrichment_status} />
        </div>
      </div>
      {c.tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {c.tags.slice(0, 2).map((t) => (
            <Chip key={t}>{t}</Chip>
          ))}
          {c.tags.length > 2 && <span className="self-center text-meta text-navy-500">+{c.tags.length - 2}</span>}
        </div>
      )}
    </Link>
  );
}

/** "🎤 Speak" under the search field (DESIGN v2). Disabled with a short reason if voice can't work. */
function SpeakButton() {
  const [asr, setAsr] = useState<ServiceStatus | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .health({ signal: ctrl.signal, timeoutMs: 8000 })
      .then((h) => setAsr(h.asr ?? null))
      .catch(() => {});
    return () => ctrl.abort();
  }, []);
  const support = voiceSupportProblem();
  const reason = support
    ? support.kind === "insecure"
      ? "Voice needs the secure (https) address."
      : support.message
    : asr && !asr.available
      ? asr.detail ?? "Voice isn't set up yet."
      : null;

  return (
    <div className="mt-3">
      {reason ? (
        <>
          <button type="button" disabled aria-describedby="speak-reason" className={buttonClass("secondary", "w-full")}>
            <span aria-hidden="true">🎤</span> Speak
          </button>
          <p id="speak-reason" className="mt-1 text-meta text-navy-500">
            {reason}{" "}
            <Link to={support?.kind === "insecure" ? "/speak" : "/settings"} className="inline-flex min-h-11 items-center font-medium text-navy-700 underline underline-offset-4">
              {support?.kind === "insecure" ? "Details" : "Settings"}
            </Link>
          </p>
        </>
      ) : (
        <Link to="/speak" className={buttonClass("secondary", "w-full")}>
          <span aria-hidden="true">🎤</span> Speak
        </Link>
      )}
    </div>
  );
}

/** Upcoming follow-ups (next 14 days), up to 3 rows. Hidden when empty or on error. */
function UpcomingStrip({ refreshKey }: { refreshKey: number }) {
  const [items, setItems] = useState<UpcomingItem[]>([]);
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .upcomingFollowUps(14, { signal: ctrl.signal })
      .then((r) => setItems(r.items ?? []))
      .catch(() => {
        if (!ctrl.signal.aborted) setItems([]);
      });
    return () => ctrl.abort();
  }, [refreshKey]);
  if (!items.length) return null;
  return (
    <section aria-labelledby="upcoming-h" className="mt-6">
      <h2 id="upcoming-h" className="label-caps text-navy-500">
        Upcoming
      </h2>
      <ul className="mt-2 overflow-hidden rounded-card border border-line bg-white shadow-card">
        {items.slice(0, 3).map((it) => (
          <li key={`${it.contact_id}-${it.index}`} className="border-b border-line last:border-b-0">
            <Link to={`/c/${it.contact_id}`} className="flex min-h-11 items-baseline gap-2 px-4 py-3 hover:bg-navy-50">
              <span className="shrink-0 text-label font-semibold">{formatShortDate(it.date)}</span>
              <span className="min-w-0 line-clamp-2 text-body">
                <span aria-hidden="true">· </span>
                {it.contact_name} — {it.action}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

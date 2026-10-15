import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import {
  api,
  ApiError,
  errorField,
  errorMessage,
  NOTES_MAX,
  type ConfidentItem,
  type ConfidentValue,
  type Contact,
  type Enrichment,
} from "../api/client";
import { AppBar, Page } from "../components/AppBar";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { OverflowMenu } from "../components/OverflowMenu";
import { useToast } from "../components/Toast";
import {
  AutoTextarea,
  Button,
  Card,
  Chip,
  ConfidenceText,
  EmptyState,
  ErrorBox,
  FieldError,
  FieldLabel,
  SectionHeader,
  SkeletonLines,
  buttonClass,
  inputClass,
} from "../components/ui";
import { copyText } from "../lib/clipboard";
import { formatDateTime, normaliseTag } from "../lib/format";
import { FollowUpsSection } from "../components/FollowUps";
import { useContact } from "../lib/hooks";
import { charCount, validateName, validateNotes } from "../lib/validation";

export default function ContactPage() {
  const { id = "" } = useParams();
  const { contact, state, error, timedOut, pollError, reload, replace, resumePolling } = useContact(id);
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [enriching, setEnriching] = useState(false); // request in flight
  const [notesChanged, setNotesChanged] = useState(false);

  const createdToastShown = useRef(false);
  useEffect(() => {
    if ((location.state as { justCreated?: boolean } | null)?.justCreated && !createdToastShown.current) {
      createdToastShown.current = true;
      toast("Saved.", "success");
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pending = contact?.enrichment_status === "pending";
  const notesBlank = !contact?.raw_notes.trim();

  const startEnrich = async () => {
    if (!contact || enriching) return;
    if (!contact.raw_notes.trim()) {
      toast("Add some notes before enriching.", "error");
      return;
    }
    setEnriching(true);
    try {
      const c = await api.enrich(contact.id);
      replace(c);
      setNotesChanged(false);
    } catch (e) {
      if (e instanceof ApiError && e.code === "enrichment_in_progress") {
        toast("Already organising this contact. Hang on a moment.");
        resumePolling();
        void reload();
      } else {
        // e.g. 400 "raw_notes: add some notes before enriching" → "Add some notes before enriching"
        toast(errorMessage(e), "error");
      }
    } finally {
      setEnriching(false);
    }
  };

  const doDelete = async () => {
    if (!contact) return;
    setDeleting(true);
    try {
      await api.deleteContact(contact.id);
      navigate("/", { replace: true, state: { flash: `Deleted ${contact.name}.` } });
    } catch (e) {
      setDeleting(false);
      if (e instanceof ApiError && e.status === 404) {
        navigate("/", { replace: true, state: { flash: "That contact was already deleted." } });
        return;
      }
      setConfirmDelete(false);
      toast(errorMessage(e), "error");
    }
  };

  const menu =
    contact && state === "ready" ? (
      <OverflowMenu
        items={[
          { label: "Edit", onSelect: () => setEditing(true), disabled: editing },
          {
            label: pending ? "Enriching…" : notesBlank ? "Re-enrich (add notes first)" : "Re-enrich",
            onSelect: () => void startEnrich(),
            disabled: pending || enriching || notesBlank,
          },
          { label: "Delete", onSelect: () => setConfirmDelete(true), danger: true },
        ]}
      />
    ) : null;

  return (
    <>
      <AppBar title={contact?.name ?? "Contact"} back="/" actions={menu} />
      <Page>
        {state === "loading" && (
          <div aria-busy="true" aria-label="Loading contact" className="space-y-4">
            <div className="skeleton h-8 w-2/3" />
            <div className="skeleton h-4 w-1/2" />
            <Card as="div">
              <SkeletonLines lines={4} />
            </Card>
          </div>
        )}

        {state === "not_found" && (
          <EmptyState
            text="This contact doesn't exist. It may have been deleted."
            action={
              <Link to="/" className={buttonClass("secondary")}>
                Back to contacts
              </Link>
            }
          />
        )}

        {state === "error" && (
          <ErrorBox
            title="Couldn't load this contact"
            action={
              <Button variant="secondary" onClick={() => void reload()}>
                Try again
              </Button>
            }
          >
            {error}
          </ErrorBox>
        )}

        {state === "ready" && contact && (
          <div className="space-y-4">
            {editing ? (
              <EditForm
                contact={contact}
                onCancel={() => setEditing(false)}
                onSaved={(c, notesDiffer) => {
                  replace(c);
                  setEditing(false);
                  toast("Changes saved.", "success");
                  if (notesDiffer && c.enrichment) setNotesChanged(true);
                }}
              />
            ) : (
              <Header contact={contact} onAddName={() => setEditing(true)} />
            )}

            {!editing && (
              <>
                <StatusPanel
                  contact={contact}
                  timedOut={timedOut}
                  pollError={pollError}
                  enriching={enriching}
                  onEnrich={() => void startEnrich()}
                />

                {notesChanged && !pending && !notesBlank && contact.enrichment_status !== "failed" && (
                  <div className="flex flex-col gap-3 rounded-card border border-line bg-navy-100 p-4 sm:flex-row sm:items-center">
                    <p className="flex-1 text-body">Notes changed. Re-enrich to update the card.</p>
                    <Button variant="primary" onClick={() => void startEnrich()} loading={enriching} loadingText="Starting…">
                      Re-enrich
                    </Button>
                  </div>
                )}

                {contact.enrichment && (
                  <EnrichmentSections e={contact.enrichment} stale={pending} contact={contact} onChange={replace} />
                )}

                <TagsCard contact={contact} onSaved={replace} />

                <OriginalNotes notes={contact.raw_notes} />

                <AddNote contact={contact} onAdded={(c) => {
                  replace(c);
                  setNotesChanged(c.enrichment_status !== "pending" && !!c.enrichment);
                }} />

                <p className="pt-2 text-center text-meta text-navy-500">
                  Created {formatDateTime(contact.created_at)} · Updated {formatDateTime(contact.updated_at)}
                </p>
              </>
            )}
          </div>
        )}
      </Page>

      <ConfirmDialog
        open={confirmDelete}
        title={`Delete ${contact?.name ?? "contact"}?`}
        confirmLabel="Delete"
        danger
        busy={deleting}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void doDelete()}
      >
        This removes the contact and all notes. It can't be undone.
      </ConfirmDialog>
    </>
  );
}

/* ---------------- Header ---------------- */

function Header({ contact, onAddName }: { contact: Contact; onAddName: () => void }) {
  const e = contact.enrichment;
  return (
    <div className="pb-2">
      <h1 className="text-title font-semibold break-words">{contact.needs_name ? "New contact" : contact.name}</h1>
      {contact.needs_name && (
        <div className="mt-3 flex flex-col gap-3 rounded-card border border-line bg-white p-4 sm:flex-row sm:items-center">
          <p className="flex-1 text-body">
            {contact.enrichment_status === "pending"
              ? "No name yet. Rolo will use it if you said it — or add it now."
              : "No name was heard. Add one so you can find this contact later."}
          </p>
          <Button variant="secondary" onClick={onAddName}>
            Add a name
          </Button>
        </div>
      )}
      {contact.source === "voice" && (
        <p className="mt-1 text-meta text-navy-500">
          <span aria-hidden="true">🎤 </span>Captured by voice
        </p>
      )}
      {e?.headline && <p className="mt-1 text-body text-navy-500">{e.headline}</p>}
      {e?.summary && <p className="mt-4 text-body">{e.summary}</p>}
      {contact.enriched_at && (
        <p className="mt-3 text-meta text-navy-500">
          Organised on this device{contact.model_name ? ` by ${contact.model_name}` : ""} · {formatDateTime(contact.enriched_at)}
        </p>
      )}
    </div>
  );
}

/* ---------------- Status (pending / failed / timeout / none) ---------------- */

function StatusPanel({
  contact,
  timedOut,
  pollError,
  enriching,
  onEnrich,
}: {
  contact: Contact;
  timedOut: boolean;
  pollError: string | null;
  enriching: boolean;
  onEnrich: () => void;
}) {
  const s = contact.enrichment_status;

  if (s === "pending" && timedOut) {
    return (
      <ErrorBox
        title="Still organising"
        action={
          <Button variant="secondary" onClick={onEnrich} loading={enriching} loadingText="Retrying…">
            Retry
          </Button>
        }
      >
        This is taking longer than expected. The local model may be busy or stopped. Your notes are saved.
      </ErrorBox>
    );
  }

  if (s === "pending") {
    return (
      <Card as="div" className="space-y-4">
        <p className="text-body font-medium" role="status" aria-live="polite">
          Organising your notes on this device…
        </p>
        <SkeletonLines lines={4} />
        {pollError && <p className="text-meta text-navy-500">Connection hiccup — still trying.</p>}
      </Card>
    );
  }

  const blank = !contact.raw_notes.trim();

  if (s === "failed") {
    return (
      <ErrorBox
        title="Couldn't organise these notes"
        action={
          blank ? (
            <p className="text-label text-navy-500">Add some notes below, then enrich again.</p>
          ) : (
            <Button variant="secondary" onClick={onEnrich} loading={enriching} loadingText="Retrying…">
              Retry
            </Button>
          )
        }
      >
        {contact.enrichment_error ?? "The local model couldn't process these notes. Your notes are saved."}
      </ErrorBox>
    );
  }

  if (s === "none" && !contact.enrichment) {
    if (blank) {
      return (
        <Card as="div">
          <p className="text-body text-navy-500">No notes yet. Add a note below and Rolo will build the card from it.</p>
        </Card>
      );
    }
    return (
      <Card as="div">
        <p className="text-body text-navy-500">These notes haven't been organised yet.</p>
        <Button className="mt-4 w-full sm:w-auto" onClick={onEnrich} loading={enriching} loadingText="Starting…">
          Enrich
        </Button>
      </Card>
    );
  }
  return null;
}

/* ---------------- Enrichment sections ---------------- */

function has(v: ConfidentValue | null | undefined): v is ConfidentValue & { value: string } {
  return !!v && typeof v.value === "string" && v.value.trim() !== "";
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <Card aria-labelledby={id}>
      <SectionHeader id={id}>{title}</SectionHeader>
      {children}
    </Card>
  );
}

function ItemList({ items }: { items: ConfidentItem[] }) {
  return (
    <ul className="space-y-2">
      {items.map((it, i) => (
        <li key={i} className="flex gap-3 text-body">
          <span className="mt-[10px] size-1.5 shrink-0 rounded-full bg-navy-500" aria-hidden="true" />
          <ConfidenceText value={it.value} confidence={it.confidence} />
        </li>
      ))}
    </ul>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_1fr] gap-3 py-1.5">
      <dt className="text-label text-navy-500">{label}</dt>
      <dd className="min-w-0 break-words text-body">{children}</dd>
    </div>
  );
}

function EnrichmentSections({
  e,
  stale,
  contact,
  onChange,
}: {
  e: Enrichment;
  stale: boolean;
  contact: Contact;
  onChange: (c: Contact) => void;
}) {
  const list = <T,>(x: T[] | null | undefined): T[] => (Array.isArray(x) ? x : []);
  const followUps = list(e.follow_ups);
  const wants = list(e.what_they_want);
  const help = list(e.how_i_can_help);
  const interests = list(e.interests);
  const personal = list(e.personal_details);
  const gaps = list(e.gaps);
  const questions = list(e.questions_to_ask);
  const ci = e.contact_info ?? { email: null, phone: null, linkedin: null };
  const hasRole = has(e.role) || has(e.company) || has(e.location) || ci.email || ci.phone || ci.linkedin;

  return (
    <div className={stale ? "space-y-4 opacity-60" : "space-y-4"} aria-busy={stale || undefined}>
      {followUps.length > 0 && <FollowUpsSection contact={contact} followUps={followUps} onChange={onChange} />}

      {wants.length > 0 && (
        <Section title="What they want">
          <ItemList items={wants} />
        </Section>
      )}

      {help.length > 0 && (
        <Section title="How I can help">
          <ItemList items={help} />
        </Section>
      )}

      {hasRole && (
        <Section title="Role & company">
          <dl>
            {has(e.role) && (
              <Row label="Role">
                <ConfidenceText value={e.role.value} confidence={e.role.confidence} />
              </Row>
            )}
            {has(e.company) && (
              <Row label="Company">
                <ConfidenceText value={e.company.value} confidence={e.company.confidence} />
              </Row>
            )}
            {has(e.location) && (
              <Row label="Location">
                <ConfidenceText value={e.location.value} confidence={e.location.confidence} />
              </Row>
            )}
            {ci.email && (
              <Row label="Email">
                <a className="-my-2.5 inline-flex min-h-11 items-center break-all underline underline-offset-4" href={`mailto:${ci.email}`}>
                  {ci.email}
                </a>
              </Row>
            )}
            {ci.phone && (
              <Row label="Phone">
                <a className="-my-2.5 inline-flex min-h-11 items-center underline underline-offset-4" href={`tel:${ci.phone.replace(/[^\d+]/g, "")}`}>
                  {ci.phone}
                </a>
              </Row>
            )}
            {ci.linkedin && <Row label="LinkedIn">{ci.linkedin}</Row>}
          </dl>
        </Section>
      )}

      {has(e.how_we_met) && (
        <Section title="How we met">
          <p className="text-body">
            <ConfidenceText value={e.how_we_met.value} confidence={e.how_we_met.confidence} />
          </p>
        </Section>
      )}

      {interests.length > 0 && (
        <Section title="Interests">
          <ItemList items={interests} />
        </Section>
      )}

      {personal.length > 0 && (
        <Section title="Personal">
          <ItemList items={personal} />
        </Section>
      )}

      {(gaps.length > 0 || questions.length > 0) && (
        <Section title="Gaps & questions to ask">
          {gaps.length > 0 && (
            <>
              <h3 className="text-label font-medium text-navy-700">Not in your notes yet</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-body marker:text-navy-500">
                {gaps.map((g, i) => (
                  <li key={i}>{g}</li>
                ))}
              </ul>
            </>
          )}
          {questions.length > 0 && (
            <>
              <h3 className={`text-label font-medium text-navy-700 ${gaps.length ? "mt-4" : ""}`}>Questions to ask</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-body marker:text-navy-500">
                {questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </>
          )}
        </Section>
      )}

      {e.suggested_opener?.trim() && <Opener text={e.suggested_opener} />}
    </div>
  );
}

function Opener({ text }: { text: string }) {
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const onCopy = async () => {
    const ok = await copyText(text);
    setStatus(ok ? "copied" : "failed");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setStatus("idle"), 2500);
  };
  return (
    <Section title="Suggested opener">
      <blockquote className="border-l-2 border-line pl-4 text-body">{text}</blockquote>
      <div className="mt-4 flex items-center gap-3">
        <Button variant="secondary" onClick={() => void onCopy()} aria-describedby="copy-status">
          {status === "copied" ? "Copied" : "Copy"}
        </Button>
        <span id="copy-status" role="status" aria-live="polite" className="text-meta text-navy-500">
          {status === "copied" ? "Copied to clipboard." : status === "failed" ? "Couldn't copy. Select the text and copy it manually." : ""}
        </span>
      </div>
    </Section>
  );
}

/* ---------------- Tags ---------------- */

function TagsCard({ contact, onSaved }: { contact: Contact; onSaved: (c: Contact) => void }) {
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const inputId = useId();
  const tags = contact.tags ?? [];
  const suggestions = (contact.enrichment?.suggested_tags ?? [])
    .map(normaliseTag)
    .filter((t) => t && !tags.includes(t));

  const save = async (next: string[]) => {
    setSaving(true);
    setErr(null);
    try {
      onSaved(await api.updateContact(contact.id, { tags: next }));
      return true;
    } catch (e) {
      setErr(errorMessage(e));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const add = async (e?: FormEvent) => {
    e?.preventDefault();
    const t = normaliseTag(input);
    if (!t) return;
    if (tags.includes(t)) {
      setInput("");
      return;
    }
    if (await save([...tags, t])) setInput("");
  };

  return (
    <Section title="Tags">
      {tags.length > 0 ? (
        <ul className="flex flex-wrap gap-x-2 gap-y-3" aria-label="Tags">
          {tags.map((t) => (
            <li key={t}>
              <Chip onRemove={saving ? undefined : () => void save(tags.filter((x) => x !== t))} removeLabel={`Remove tag ${t}`}>
                {t}
              </Chip>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-body text-navy-500">No tags yet.</p>
      )}

      {suggestions.length > 0 && (
        <div className="mt-4">
          <p className="text-meta text-navy-500">Suggested from your notes</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {suggestions.map((t) => (
              <button
                key={t}
                type="button"
                disabled={saving}
                onClick={() => void save([...tags, t])}
                aria-label={`Add tag ${t}`}
                className="inline-flex min-h-11 items-center rounded-full border border-dashed border-navy-500 px-3 text-label font-medium text-navy-700 hover:bg-navy-50 disabled:opacity-60"
              >
                + {t}
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={(e) => void add(e)} className="mt-4 flex gap-2">
        <label htmlFor={inputId} className="sr-only">
          Add a tag
        </label>
        <input
          id={inputId}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Add a tag"
          autoComplete="off"
          enterKeyHint="done"
          className={`${inputClass} flex-1`}
        />
        <Button type="submit" variant="secondary" loading={saving} loadingText="Saving" disabled={!input.trim()}>
          Add
        </Button>
      </form>
      {err && <p className="mt-2 text-label text-danger" role="alert">{err}</p>}
    </Section>
  );
}

/* ---------------- Original notes ---------------- */

function OriginalNotes({ notes }: { notes: string }) {
  return (
    <Card as="div" padded={false}>
      <details className="group">
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between rounded-card p-5 [&::-webkit-details-marker]:hidden">
          <h2 className="label-caps text-navy-500">Original notes</h2>
          <svg viewBox="0 0 24 24" className="size-5 text-navy-500 transition-transform group-open:rotate-180" aria-hidden="true">
            <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </summary>
        <div className="border-t border-line px-5 pb-5 pt-4">
          {notes.trim() ? (
            <p className="whitespace-pre-wrap break-words text-body">{notes}</p>
          ) : (
            <p className="text-body text-navy-500">No notes yet.</p>
          )}
        </div>
      </details>
    </Card>
  );
}

/* ---------------- Add a note ---------------- */

function AddNote({ contact, onAdded }: { contact: Contact; onAdded: (c: Contact) => void }) {
  const [text, setText] = useState("");
  const [reEnrich, setReEnrich] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();
  const busy = useRef(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy.current) return;
    if (!text.trim()) {
      setErr("Write something to add.");
      return;
    }
    busy.current = true;
    setSaving(true);
    setErr(null);
    try {
      const enrich = reEnrich;
      const c = await api.addNote(contact.id, { text: text.trim(), enrich });
      setText("");
      onAdded(c);
      toast(enrich ? "Note added. Updating the card…" : "Note added.", "success");
    } catch (e2) {
      const field = errorField(e2);
      // "text" / "raw_notes" problems belong under this input; anything else gets the keep-your-note hint.
      setErr(field === "text" || field === "raw_notes" ? errorMessage(e2) : `${errorMessage(e2)} Your note is still here.`);
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  return (
    <Card>
      <form onSubmit={(e) => void submit(e)} noValidate>
        <FieldLabel htmlFor="add-note">Add a note</FieldLabel>
        <AutoTextarea
          id="add-note"
          minRows={3}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            if (err) setErr(null);
          }}
          placeholder="Anything new — what you talked about, what they asked for, next steps."
          aria-invalid={!!err}
          aria-describedby={err ? "add-note-error" : undefined}
        />
        <FieldError id="add-note-error">{err}</FieldError>
        <label className="mt-3 flex min-h-11 cursor-pointer items-center gap-3 text-body">
          <input
            type="checkbox"
            checked={reEnrich}
            onChange={(e) => setReEnrich(e.target.checked)}
            className="size-5 accent-navy-900"
          />
          Update the card after adding
        </label>
        <Button type="submit" className="mt-3 w-full" loading={saving} loadingText="Adding…">
          Add note
        </Button>
      </form>
    </Card>
  );
}

/* ---------------- Edit ---------------- */

function EditForm({
  contact,
  onCancel,
  onSaved,
}: {
  contact: Contact;
  onCancel: () => void;
  onSaved: (c: Contact, notesChanged: boolean) => void;
}) {
  const [name, setName] = useState(contact.needs_name ? "" : contact.name);
  const [notes, setNotes] = useState(contact.raw_notes);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [serverField, setServerField] = useState<{ name?: string; notes?: string }>({});
  const nameErr = serverField.name ?? validateName(name);
  const notesErr = serverField.notes ?? validateNotes(notes);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (nameErr || notesErr || saving) return;
    setSaving(true);
    setErr(null);
    const body: { name?: string; raw_notes?: string } = {};
    if (name.trim() !== contact.name || contact.needs_name) body.name = name.trim();
    if (notes !== contact.raw_notes) body.raw_notes = notes;
    if (!body.name && body.raw_notes === undefined) {
      onCancel();
      return;
    }
    try {
      const c = await api.updateContact(contact.id, body);
      onSaved(c, body.raw_notes !== undefined);
    } catch (e2) {
      const field = errorField(e2);
      if (field === "name") setServerField({ name: errorMessage(e2) });
      else if (field === "raw_notes") setServerField({ notes: errorMessage(e2) });
      else setErr(errorMessage(e2));
      setSaving(false);
    }
  };

  return (
    <Card>
      <h1 className="text-name font-semibold">Edit contact</h1>
      <form onSubmit={(e) => void submit(e)} noValidate className="mt-4 space-y-5">
        <div>
          <FieldLabel htmlFor="edit-name">Name</FieldLabel>
          <input
            id="edit-name"
            autoFocus
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setServerField((f) => ({ ...f, name: undefined }));
            }}
            aria-invalid={!!nameErr}
            aria-describedby={nameErr ? "edit-name-error" : undefined}
            className={inputClass}
            autoComplete="off"
          />
          <FieldError id="edit-name-error">{nameErr}</FieldError>
        </div>
        <div>
          <FieldLabel htmlFor="edit-notes" hint={
              <span className={charCount(notes) > NOTES_MAX ? "text-meta font-semibold text-danger" : "text-meta text-navy-500"}>
                {charCount(notes).toLocaleString()} / {NOTES_MAX.toLocaleString()}
              </span>
            }>
            Notes
          </FieldLabel>
          <AutoTextarea
            id="edit-notes"
            minRows={8}
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value);
              setServerField((f) => ({ ...f, notes: undefined }));
            }}
            aria-invalid={!!notesErr}
            aria-describedby={notesErr ? "edit-notes-error" : undefined}
          />
          <FieldError id="edit-notes-error">{notesErr}</FieldError>
        </div>
        {err && <ErrorBox title="Not saved">{err}</ErrorBox>}
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" loading={saving} loadingText="Saving…" disabled={!!nameErr || !!notesErr}>
            Save changes
          </Button>
        </div>
      </form>
    </Card>
  );
}

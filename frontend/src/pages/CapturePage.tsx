import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api, ApiError, NOTES_MAX, errorField, errorMessage } from "../api/client";
import { charCount, validateName, validateNotes } from "../lib/validation";
import { AppBar, Page } from "../components/AppBar";
import { AutoTextarea, Button, ErrorBox, FieldError, FieldLabel, cx, inputClass } from "../components/ui";

const DRAFT_KEY = "rolo-capture-draft";
const PLACEHOLDER =
  "Everything you remember — where you met, what they do, what they want, personal details, follow-ups.";

type Draft = { name: string; notes: string };

function loadDraft(): Draft {
  try {
    const d = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null") as Draft | null;
    if (d && typeof d.name === "string" && typeof d.notes === "string") return d;
  } catch {
    /* ignore */
  }
  return { name: "", notes: "" };
}

export default function CapturePage() {
  const navigate = useNavigate();
  const initial = useRef(loadDraft()).current;
  const [name, setName] = useState(initial.name);
  const [notes, setNotes] = useState(initial.notes);
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState<null | "enrich" | "plain">(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ name?: string; notes?: string }>({});
  const nameRef = useRef<HTMLInputElement>(null);
  const notesRef = useRef<HTMLTextAreaElement>(null);
  const inFlight = useRef(false);

  // Keep a local draft so nothing is lost if the user navigates away or saving fails.
  useEffect(() => {
    const t = setTimeout(() => {
      if (name || notes) localStorage.setItem(DRAFT_KEY, JSON.stringify({ name, notes }));
      else localStorage.removeItem(DRAFT_KEY);
    }, 300);
    return () => clearTimeout(t);
  }, [name, notes]);

  const nameError = fieldErrors.name ?? (touched ? validateName(name) : null);
  const notesError = fieldErrors.notes ?? validateNotes(notes);

  const save = async (enrich: boolean) => {
    if (inFlight.current) return; // prevent double-tap
    setTouched(true);
    setServerError(null);
    setFieldErrors({});
    const nErr = validateName(name);
    const tErr = validateNotes(notes);
    if (nErr) {
      nameRef.current?.focus();
      return;
    }
    if (tErr) {
      notesRef.current?.focus();
      return;
    }
    inFlight.current = true;
    setSaving(enrich ? "enrich" : "plain");
    try {
      const c = await api.createContact({ name: name.trim(), raw_notes: notes, enrich });
      localStorage.removeItem(DRAFT_KEY);
      navigate(`/c/${c.id}`, { replace: true, state: { justCreated: true } });
    } catch (e) {
      inFlight.current = false;
      setSaving(null);
      if (e instanceof ApiError && e.code === "validation_error") {
        const field = errorField(e);
        const msg = errorMessage(e);
        if (field === "raw_notes") {
          setFieldErrors({ notes: msg });
          notesRef.current?.focus();
        } else if (field === "name") {
          setFieldErrors({ name: msg });
          nameRef.current?.focus();
        } else setServerError(msg);
      } else {
        setServerError(
          `${e instanceof ApiError ? e.message : "Couldn't save."} Your notes are kept on this screen.`,
        );
      }
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void save(true);
  };

  const count = charCount(notes);

  return (
    <>
      <AppBar title="New contact" back />
      <Page>
        <h1 className="text-title font-semibold">Quick capture</h1>
        <form id="capture" onSubmit={onSubmit} noValidate className="mt-6 space-y-6">
          <div>
            <FieldLabel htmlFor="name">Name</FieldLabel>
            <input
              ref={nameRef}
              id="name"
              name="name"
              type="text"
              autoComplete="off"
              autoCapitalize="words"
              enterKeyHint="next"
              autoFocus
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (fieldErrors.name) setFieldErrors((f) => ({ ...f, name: undefined }));
              }}
              onBlur={() => name && setTouched(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  notesRef.current?.focus();
                }
              }}
              aria-invalid={!!nameError}
              aria-describedby={nameError ? "name-error" : undefined}
              aria-required="true"
              className={inputClass}
              placeholder="e.g. Priya Shah"
            />
            <FieldError id="name-error">{nameError}</FieldError>
          </div>

          <div>
            <FieldLabel
              htmlFor="notes"
              hint={
                <span
                  id="notes-count"
                  className={cx("text-meta", count > NOTES_MAX ? "font-semibold text-danger" : "text-navy-500")}
                >
                  {count.toLocaleString()} / {NOTES_MAX.toLocaleString()}
                </span>
              }
            >
              Notes
            </FieldLabel>
            <AutoTextarea
              ref={notesRef}
              id="notes"
              name="notes"
              minRows={8}
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
                if (fieldErrors.notes) setFieldErrors((f) => ({ ...f, notes: undefined }));
              }}
              placeholder={PLACEHOLDER}
              aria-invalid={!!notesError}
              aria-describedby={cx("notes-count", notesError && "notes-error") || undefined}
            />
            <FieldError id="notes-error">{notesError}</FieldError>
          </div>

          {serverError && <ErrorBox title="Not saved">{serverError}</ErrorBox>}
        </form>
      </Page>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-white/95 pb-[calc(12px+env(safe-area-inset-bottom))] pt-3 backdrop-blur">
        <div className="mx-auto flex max-w-[640px] flex-col items-stretch gap-1 px-5 md:px-8">
          <Button
            type="submit"
            form="capture"
            className="w-full"
            loading={saving === "enrich"}
            loadingText="Saving…"
            disabled={saving !== null}
          >
            Save &amp; Enrich
          </Button>
          <button
            type="button"
            onClick={() => void save(false)}
            disabled={saving !== null}
            className="mx-auto inline-flex min-h-11 items-center gap-2 rounded-md px-3 text-label font-medium text-navy-700 underline underline-offset-4 disabled:opacity-60"
          >
            {saving === "plain" ? "Saving…" : "Save without enriching"}
          </button>
        </div>
      </div>
    </>
  );
}

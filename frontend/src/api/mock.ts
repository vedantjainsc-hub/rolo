// In-browser mock of the Rolo API (contract v2.0), used only when VITE_USE_MOCK=1.
// Data lives in localStorage. Enrichment is simulated with a short delay and a naive,
// notes-only extractor (it never adds outside facts, same as the real thing).
//
// Test hooks:
//   notes containing [mock:fail]  → enrichment fails with a friendly error
//   notes containing [mock:slow]  → enrichment stays pending forever (120 s polling timeout)
//   localStorage["rolo-mock-asr"] = "down"  → voice unavailable (health + 503 on transcribe)

import type { RawResponse } from "./client";
import type {
  ConfidentItem,
  Contact,
  ContactSummary,
  DateStatus,
  Enrichment,
  FollowUp,
  UpcomingItem,
} from "./types";
import { NAME_MAX, NOTES_MAX } from "./types";
import { addDays, nextMonday, parseYmd, toYmd, todayYmd } from "../lib/dates";

const KEY = "rolo-mock-db-v2";
const MODEL = "mock-model";
const ASR = "mock-asr";
const ENRICH_MS = 3000;

type Choice = { confirmed_date: string | null; dismissed: boolean };
type MockContact = Contact & { _choices?: Record<string, Choice> };
type DB = { contacts: MockContact[] };

const cp = (s: string) => [...s].length;

function load(): DB {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const db = JSON.parse(raw) as DB;
      for (const c of db.contacts) c.source ??= "typed"; // pre-v2.1 mock data
      return db;
    }
  } catch {
    /* fall through */
  }
  const db: DB = { contacts: [] };
  const now = new Date().toISOString();
  const priya: MockContact = {
    id: crypto.randomUUID(),
    name: "Priya Shah",
    needs_name: false,
    source: "typed",
    raw_notes:
      "Met at Fintech Forward. Runs partnerships at a payments startup, I think Stripe-adjacent. Wants intros to bank CTOs. Has a dog named Biscuit. Said to follow up after Diwali. Send her the deck by Friday. We had a recap call last Monday.",
    tags: ["fintech", "partnerships"],
    enrichment: null,
    enrichment_status: "done",
    enrichment_error: null,
    enriched_at: now,
    model_name: MODEL,
    created_at: now,
    updated_at: now,
  };
  priya.enrichment = fakeEnrich(priya);
  db.contacts.push(priya);
  save(db);
  return db;
}

function save(db: DB) {
  localStorage.setItem(KEY, JSON.stringify(db));
}

const timers = new Map<string, number>();

function sentences(notes: string): string[] {
  return notes
    .replace(/\[mock:\w+\]/g, "")
    .replace(/\[\d{4}-\d{2}-\d{2}\]/g, "")
    .split(/(?<=[.!?])\s+|\n+/)
    .map((s) => s.trim().replace(/[.!?]$/, ""))
    .filter(Boolean);
}

const HEDGE = /\b(i think|maybe|not sure|probably|might|possibly|i guess)\b/i;

function item(s: string): ConfidentItem {
  return { value: s, confidence: HEDGE.test(s) ? "maybe" : "stated" };
}

const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];

/** Backend-style follow-up classification (simplified). */
function classify(when: string | null): { date_status: DateStatus; suggested_date: string | null } {
  if (!when) return { date_status: "none", suggested_date: null };
  const w = when.toLowerCase();
  const today = todayYmd();
  if (/\b(last|since|ago|yesterday|recap|was|did)\b/.test(w)) return { date_status: "past", suggested_date: null };
  if (/\btomorrow\b/.test(w)) return { date_status: "exact", suggested_date: addDays(today, 1) };
  if (/\bnext week\b/.test(w)) return { date_status: "exact", suggested_date: nextMonday(today) };
  const inDays = /\bin (\d+) days?\b/.exec(w);
  if (inDays) return { date_status: "exact", suggested_date: addDays(today, Number(inDays[1])) };
  const wd = WEEKDAYS.findIndex((d) => w.includes(d));
  if (wd >= 0) {
    const now = parseYmd(today)!;
    const delta = ((wd - now.getDay() + 7) % 7) || 7;
    return { date_status: "exact", suggested_date: addDays(today, delta) };
  }
  return { date_status: "needs_date", suggested_date: null };
}

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

function fakeEnrich(c: MockContact): Enrichment {
  const notes = c.raw_notes;
  const ss = sentences(notes);
  const find = (re: RegExp) => ss.filter((s) => re.test(s));
  const first = (re: RegExp) => find(re)[0] ?? null;
  const email = notes.match(/[\w.+-]+@[\w-]+\.[\w.]+/)?.[0] ?? null;
  const phone = notes.match(/\+?\d[\d\s-]{7,}\d/)?.[0] ?? null;
  const linkedin = notes.match(/linkedin\.com\/[\w/-]+/i)?.[0] ?? null;
  const roleS = first(/\b(runs|works|lead|head|founder|ceo|cto|engineer|manager|director|partner)\b/i);
  const metS = first(/\b(met|introduced)\b/i);
  const wants = find(/\b(wants|looking for|needs|hoping)\b/i);
  const personal = find(/\b(has a|kids?|dog|cat|married|wife|husband|loves|birthday)\b/i);
  const interests = find(/\b(into|enjoys|likes|interested in|plays)\b/i);
  const follow = find(/\b(follow up|follow-up|call|email|send|catch up|ping|coffee)\b/i).slice(0, 5);
  const personName =
    /\b(?:[Tt]his is|[Mm]et|[Nn]ame is|called)\s+([A-Z][\p{L}'-]+(?:\s+[A-Z][\p{L}'-]+)?)/u.exec(notes)?.[1] ?? null;
  const gaps: string[] = [];
  if (!email) gaps.push("Email or other contact details");
  if (!roleS) gaps.push("Job title");
  gaps.push("Exact company name");
  const words = notes.toLowerCase().match(/[a-z]{5,}/g) ?? [];
  const tags = [
    ...new Set(words.filter((w) => ["fintech", "payments", "startup", "partnerships", "design", "investor", "climate", "health"].includes(w))),
  ].slice(0, 5);
  const choices = c._choices ?? {};
  const follow_ups: FollowUp[] = follow.map((s) => {
    const when =
      s.match(/\b(after|next|before|by|in|on|tomorrow|last|since)\b.*$/i)?.[0] ?? null;
    const cls = classify(when);
    const ch = choices[norm(s)];
    return {
      action: s,
      when_text: when,
      ...cls,
      confidence: HEDGE.test(s) ? "maybe" : "stated",
      confirmed_date: ch?.confirmed_date ?? null,
      dismissed: ch?.dismissed ?? false,
    };
  });
  const first_name = (c.needs_name ? personName : c.name)?.split(" ")[0];
  return {
    person_name: personName,
    headline: (roleS ?? ss[0] ?? c.name).slice(0, 80),
    summary: ss.slice(0, 2).join(". ") + (ss.length ? "." : ""),
    role: { value: roleS, confidence: roleS && HEDGE.test(roleS) ? "maybe" : "stated" },
    company: { value: roleS && HEDGE.test(roleS) ? "A startup, possibly as described" : null, confidence: "maybe" },
    location: { value: null, confidence: "stated" },
    how_we_met: { value: metS, confidence: "stated" },
    interests: interests.map(item),
    what_they_want: wants.map(item),
    how_i_can_help: wants.length ? [{ value: "Make the introductions they asked for", confidence: "inferred" }] : [],
    personal_details: personal.map(item),
    follow_ups,
    gaps,
    questions_to_ask: ["What are you focused on this quarter?"],
    suggested_opener: `Hi${first_name ? ` ${first_name}` : ""}, great meeting you. Would love to continue our conversation.`,
    suggested_tags: tags,
    contact_info: { email, phone, linkedin },
  };
}

function summary(c: Contact): ContactSummary {
  return {
    id: c.id,
    name: c.name,
    headline: c.enrichment?.headline ?? null,
    company: c.enrichment?.company.value ?? null,
    tags: c.tags,
    enrichment_status: c.enrichment_status,
    updated_at: c.updated_at,
  };
}

function strip(c: MockContact | undefined): Contact | undefined {
  if (!c) return c;
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { _choices, ...rest } = c;
  return rest;
}

function startEnrichment(id: string) {
  const db = load();
  const c = db.contacts.find((x) => x.id === id);
  if (!c) return;
  const old = timers.get(id);
  if (old) clearTimeout(old);
  timers.delete(id);
  c.enrichment_status = "pending";
  c.enrichment_error = null;
  save(db);
  if (c.raw_notes.includes("[mock:slow]")) return;
  const t = window.setTimeout(() => {
    timers.delete(id);
    const db2 = load();
    const c2 = db2.contacts.find((x) => x.id === id);
    if (!c2) return;
    if (c2.raw_notes.includes("[mock:fail]")) {
      c2.enrichment_status = "failed";
      c2.enrichment_error = "The local model isn't running. Start Ollama and tap Retry.";
    } else {
      c2.enrichment = fakeEnrich(c2);
      c2.enrichment_status = "done";
      c2.enriched_at = new Date().toISOString();
      c2.model_name = MODEL;
      const pn = c2.enrichment.person_name;
      if (c2.needs_name && pn && c2.raw_notes.toLowerCase().includes(pn.toLowerCase())) {
        c2.name = pn;
        c2.needs_name = false;
      }
      if (c2.tags.length === 0) c2.tags = [...c2.enrichment.suggested_tags];
    }
    c2.updated_at = new Date().toISOString();
    save(db2);
  }, ENRICH_MS);
  timers.set(id, t);
}

const err = (status: number, code: string, message: string): RawResponse => ({
  status,
  body: { error: { code, message } },
});

function validateName(name: unknown): string | RawResponse {
  if (typeof name !== "string" || !name.trim()) return err(400, "validation_error", "name: is required");
  if (cp(name.trim()) > NAME_MAX) return err(400, "validation_error", `name: must be at most ${NAME_MAX} characters`);
  return name.trim();
}

function validateNotes(notes: unknown): string | RawResponse {
  if (notes === undefined || notes === null) return "";
  if (typeof notes !== "string") return err(400, "validation_error", "raw_notes: must be a string");
  if (cp(notes) > NOTES_MAX)
    return err(400, "validation_error", `raw_notes: must be at most ${NOTES_MAX.toLocaleString()} characters`);
  return notes;
}

function asrDown() {
  return localStorage.getItem("rolo-mock-asr") === "down";
}

// Canned speech returned progressively as the recording grows (~2.5 words per second).
const CANNED =
  "This is Priya Shah. We met at Fintech Forward. She runs partnerships at a payments startup, I think Stripe adjacent. She wants intros to bank CTOs. She has a dog named Biscuit. Send her the deck by Friday and follow up after Diwali.";

async function transcribe(body: unknown): Promise<RawResponse> {
  if (asrDown()) return err(503, "asr_unavailable", "Voice isn't set up. Run ./run.sh once on the laptop.");
  if (!(body instanceof Blob)) return err(400, "validation_error", "audio: must be a WAV file");
  const head = new DataView(await body.slice(0, 44).arrayBuffer());
  if (body.size < 44 || head.getUint32(0, false) !== 0x52494646 /* RIFF */)
    return err(400, "validation_error", "audio: must be a WAV file");
  const rate = head.getUint32(24, true);
  const channels = head.getUint16(22, true);
  const bits = head.getUint16(34, true);
  if (rate !== 16000 || channels !== 1 || bits !== 16)
    return err(400, "validation_error", "audio: must be 16 kHz mono PCM16");
  const duration_s = (body.size - 44) / 32000;
  if (duration_s > 300) return err(400, "validation_error", "audio: must be at most 5 minutes");
  await new Promise((r) => setTimeout(r, 250)); // pretend to think
  const words = CANNED.split(" ");
  const n = Math.min(words.length, Math.floor(duration_s * 2.5));
  return { status: 200, body: { text: words.slice(0, n).join(" "), duration_s } };
}

function effective(f: FollowUp): string | null {
  if (f.dismissed) return null;
  if (f.confirmed_date) return f.confirmed_date;
  return f.date_status === "exact" ? f.suggested_date : null;
}

/** Builds the .ics body for the mock "Add to Calendar" link; null when there is no date. */
export function mockIcs(id: string, index: number): string | null {
  const c = load().contacts.find((x) => x.id === id);
  const f = c?.enrichment?.follow_ups?.[index];
  if (!c || !f) return null;
  const date = f.confirmed_date ?? f.suggested_date;
  if (!date) return null;
  const d = date.replace(/-/g, "");
  const end = addDays(date, 1).replace(/-/g, "");
  const esc = (s: string) => s.replace(/[\;,]/g, (m) => `\\${m}`).replace(/\n/g, "\\n");
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Rolo//Mock//EN",
    "BEGIN:VEVENT",
    `UID:${id}-${index}@rolo.local`,
    `DTSTAMP:${stamp}`,
    `DTSTART;VALUE=DATE:${d}`,
    `DTEND;VALUE=DATE:${end}`,
    `SUMMARY:${esc(`Follow up: ${c.name} — ${f.action}`)}`,
    `DESCRIPTION:${esc([f.when_text, c.enrichment?.headline].filter(Boolean).join("\n"))}`,
    "END:VEVENT",
    "END:VCALENDAR",
    "",
  ].join("\r\n");
}

export async function handleMockRequest(
  method: string,
  path: string,
  body: unknown,
  signal: AbortSignal,
): Promise<RawResponse> {
  await new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, 180);
    signal.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

  const url = new URL(path, "http://mock");
  const parts = url.pathname.replace(/^\/api\/?/, "").split("/").filter(Boolean);
  const b = (body instanceof Blob ? {} : (body ?? {})) as Record<string, unknown>;
  const db = load();

  if (method === "GET" && parts[0] === "health") {
    return {
      status: 200,
      body: {
        status: "ok",
        model: { name: MODEL, available: true, detail: null },
        asr: asrDown()
          ? { name: ASR, available: false, detail: "Run ./run.sh once to set up voice" }
          : { name: ASR, available: true, detail: null },
      },
    };
  }

  if (method === "POST" && parts[0] === "transcribe") return transcribe(body);

  if (method === "GET" && parts[0] === "export") {
    return { status: 200, body: { exported_at: new Date().toISOString(), contacts: db.contacts.map(strip) } };
  }

  if (method === "GET" && parts[0] === "follow-ups" && parts[1] === "upcoming") {
    const days = Math.min(60, Math.max(0, Number(url.searchParams.get("days") ?? 14) || 14));
    const today = todayYmd();
    const until = addDays(today, days);
    const items: UpcomingItem[] = [];
    for (const c of db.contacts) {
      (c.enrichment?.follow_ups ?? []).forEach((f, index) => {
        const date = effective(f);
        if (date && date >= today && date <= until && f.date_status !== "past")
          items.push({ contact_id: c.id, contact_name: c.name, index, action: f.action, date });
      });
    }
    items.sort((a, z) => a.date.localeCompare(z.date));
    return { status: 200, body: { items } };
  }

  if (parts[0] !== "contacts") return err(404, "not_found", "Not found.");

  if (parts.length === 1) {
    if (method === "GET") {
      const q = (url.searchParams.get("q") ?? "").trim().toLowerCase();
      const list = db.contacts
        .filter((c) => {
          if (!q) return true;
          const hay = [c.name, c.raw_notes, c.tags.join(" "), c.enrichment?.company.value ?? "", c.enrichment?.headline ?? ""]
            .join(" ")
            .toLowerCase();
          return hay.includes(q);
        })
        .sort((a, z) => z.updated_at.localeCompare(a.updated_at))
        .map(summary);
      return { status: 200, body: { contacts: list } };
    }
    if (method === "POST") {
      const voice = b.source === "voice";
      let name = "New contact";
      let needs_name = false;
      if (voice && (typeof b.name !== "string" || !b.name.trim())) {
        needs_name = true;
      } else {
        const n = validateName(b.name);
        if (typeof n !== "string") return n;
        name = n;
      }
      const notes = validateNotes(b.raw_notes);
      if (typeof notes !== "string") return notes;
      if (voice && !notes.trim()) return err(400, "validation_error", "raw_notes: nothing was heard");
      const now = new Date().toISOString();
      const c: MockContact = {
        id: crypto.randomUUID(),
        name,
        needs_name,
        source: voice ? "voice" : "typed",
        raw_notes: notes,
        tags: Array.isArray(b.tags) ? (b.tags as string[]) : [],
        enrichment: null,
        enrichment_status: "none",
        enrichment_error: null,
        enriched_at: null,
        model_name: null,
        created_at: now,
        updated_at: now,
      };
      db.contacts.push(c);
      save(db);
      if (b.enrich !== false && notes.trim()) startEnrichment(c.id);
      return { status: 201, body: strip(load().contacts.find((x) => x.id === c.id)) };
    }
  }

  const id = parts[1];
  const c = db.contacts.find((x) => x.id === id);
  if (!c) return err(404, "not_found", "Contact not found.");

  if (parts.length === 2) {
    if (method === "GET") {
      // Resume simulated enrichment after a page reload dropped the timer.
      if (c.enrichment_status === "pending" && !timers.has(id) && !c.raw_notes.includes("[mock:slow]")) {
        startEnrichment(id);
      }
      return { status: 200, body: strip(load().contacts.find((x) => x.id === id)) };
    }
    if (method === "DELETE") {
      db.contacts = db.contacts.filter((x) => x.id !== id);
      save(db);
      const t = timers.get(id);
      if (t) clearTimeout(t);
      return { status: 204, body: null };
    }
    if (method === "PATCH") {
      if (b.name !== undefined) {
        const name = validateName(b.name);
        if (typeof name !== "string") return name;
        c.name = name;
        c.needs_name = false;
      }
      if (b.raw_notes !== undefined) {
        const notes = validateNotes(b.raw_notes);
        if (typeof notes !== "string") return notes;
        c.raw_notes = notes;
      }
      if (Array.isArray(b.tags)) c.tags = b.tags as string[];
      c.updated_at = new Date().toISOString();
      save(db);
      return { status: 200, body: strip(c) };
    }
  }

  if (parts[2] === "follow-ups" && parts[3] !== undefined) {
    const icsMatch = /^(\d+)\.ics$/.exec(parts[3]);
    const index = Number(icsMatch ? icsMatch[1] : parts[3]);
    const f = c.enrichment?.follow_ups?.[index];
    if (!Number.isInteger(index) || !f) return err(404, "not_found", "Follow-up not found.");
    if (icsMatch && method === "GET") {
      const ics = mockIcs(id, index);
      return ics ? { status: 200, body: ics } : err(400, "validation_error", "date: pick a date first");
    }
    if (method === "PATCH") {
      if (c.enrichment_status === "pending")
        return err(409, "enrichment_in_progress", "This contact is being enriched. Try again when it finishes.");
      if (b.confirmed_date !== undefined) {
        if (b.confirmed_date !== null && (typeof b.confirmed_date !== "string" || !parseYmd(b.confirmed_date)))
          return err(400, "validation_error", "confirmed_date: must be a date (YYYY-MM-DD)");
        f.confirmed_date = (b.confirmed_date as string | null) ?? null;
        if (f.confirmed_date) f.dismissed = false;
      }
      if (typeof b.dismissed === "boolean") {
        f.dismissed = b.dismissed;
        if (b.dismissed) f.confirmed_date = null;
      }
      c._choices = { ...(c._choices ?? {}), [norm(f.action)]: { confirmed_date: f.confirmed_date, dismissed: f.dismissed } };
      c.updated_at = new Date().toISOString();
      save(db);
      return { status: 200, body: strip(c) };
    }
  }

  if (parts[2] === "notes" && method === "POST") {
    const text = typeof b.text === "string" ? b.text.trim() : "";
    if (!text) return err(400, "validation_error", "text: is required");
    const stamp = `[${toYmd(new Date())}] ${text}`;
    const next = c.raw_notes ? `${c.raw_notes}\n\n${stamp}` : stamp;
    if (cp(next) > NOTES_MAX)
      return err(400, "validation_error", `text: notes would exceed ${NOTES_MAX.toLocaleString()} characters`);
    c.raw_notes = next;
    c.updated_at = new Date().toISOString();
    save(db);
    if (b.enrich !== false) startEnrichment(c.id); // allowed while pending: supersedes
    return { status: 200, body: strip(load().contacts.find((x) => x.id === id)) };
  }

  if (parts[2] === "enrich" && method === "POST") {
    if (!c.raw_notes.trim()) return err(400, "validation_error", "raw_notes: add some notes before enriching");
    if (c.enrichment_status === "pending" && !c.raw_notes.includes("[mock:slow]"))
      return err(409, "enrichment_in_progress", "This contact is already being enriched.");
    startEnrichment(c.id);
    return { status: 202, body: strip(load().contacts.find((x) => x.id === id)) };
  }

  return err(404, "not_found", "Not found.");
}

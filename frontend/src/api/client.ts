// Typed client for every endpoint in docs/API_CONTRACT.md.
// All requests go to relative /api/... (Vite proxies to the backend on :8000).
// With VITE_USE_MOCK=1 requests are answered by an in-browser mock instead.

import type {
  AddNoteBody,
  ApiErrorBody,
  Contact,
  ContactListResponse,
  CreateContactBody,
  ExportResponse,
  HealthResponse,
  PatchFollowUpBody,
  TranscribeResponse,
  UpcomingResponse,
  UpdateContactBody,
} from "./types";

export * from "./types";

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "1";

const DEFAULT_TIMEOUT_MS = 15_000;

/** Every failed request becomes an ApiError with a message that is safe to show. */
export class ApiError extends Error {
  readonly status: number; // 0 for network / timeout
  readonly code: string; // contract code, or "network_error" | "timeout" | "bad_response"

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export interface RawResponse {
  status: number;
  body: unknown;
}

async function send(
  method: Method,
  path: string,
  body: unknown,
  signal: AbortSignal,
): Promise<RawResponse> {
  if (USE_MOCK) {
    const { handleMockRequest } = await import("./mock");
    return handleMockRequest(method, path, body, signal);
  }
  const isBlob = body instanceof Blob;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (isBlob) headers["Content-Type"] = body.type || "application/octet-stream";
  else if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : isBlob ? body : JSON.stringify(body),
    signal,
  });
  let parsed: unknown = null;
  if (res.status !== 204) {
    const text = await res.text();
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = null;
      }
    }
  }
  return { status: res.status, body: parsed };
}

function isApiErrorBody(x: unknown): x is ApiErrorBody {
  return (
    typeof x === "object" &&
    x !== null &&
    "error" in x &&
    typeof (x as ApiErrorBody).error?.message === "string"
  );
}

function fallbackMessage(status: number): string {
  if (status === 404) return "That contact couldn't be found. It may have been deleted.";
  if (status === 409) return "Rolo is already organising this contact. Hang on a moment.";
  if (status === 400 || status === 422) return "Some details weren't accepted. Check the form and try again.";
  if (status === 503) return "Voice isn't available right now. Try again in a minute.";
  if (status === 502 || status === 504)
    return "Can't reach the Rolo server. Make sure it's running, then try again.";
  return "Something went wrong on the Rolo server. Try again in a moment.";
}

function normaliseCode(status: number, code: string | undefined): string {
  if (code) return code;
  if (status === 404) return "not_found";
  if (status === 409) return "enrichment_in_progress";
  if (status === 400 || status === 422) return "validation_error";
  return "internal_error";
}

async function request<T>(
  method: Method,
  path: string,
  body?: unknown,
  opts: { timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<T> {
  const ctrl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    ctrl.abort();
  }, opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const onOuterAbort = () => ctrl.abort();
  opts.signal?.addEventListener("abort", onOuterAbort);

  let res: RawResponse;
  try {
    res = await send(method, path, body, ctrl.signal);
  } catch (e) {
    if (timedOut) {
      throw new ApiError(0, "timeout", "The Rolo server took too long to respond. Check it's running and try again.");
    }
    if (opts.signal?.aborted) throw e; // caller cancelled; let them ignore it
    throw new ApiError(0, "network_error", "Can't reach the Rolo server. Check it's running and you're on the same network.");
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onOuterAbort);
  }

  if (res.status >= 200 && res.status < 300) return res.body as T;

  // A dev proxy with no backend behind it typically answers 500/502/504 with no JSON body.
  if (!isApiErrorBody(res.body) && res.status >= 500 && res.status !== 503) {
    throw new ApiError(res.status, "network_error", fallbackMessage(502));
  }
  const err = isApiErrorBody(res.body) ? res.body.error : undefined;
  throw new ApiError(res.status, normaliseCode(res.status, err?.code), err?.message || fallbackMessage(res.status));
}

type Opts = { signal?: AbortSignal; timeoutMs?: number };

export const api = {
  /** GET /api/health */
  health: (o?: Opts) => request<HealthResponse>("GET", "/api/health", undefined, o),

  /** GET /api/contacts?q= */
  listContacts: (q?: string, o?: Opts) => {
    const query = q && q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
    return request<ContactListResponse>("GET", `/api/contacts${query}`, undefined, o);
  },

  /** POST /api/contacts → 201 Contact */
  createContact: (body: CreateContactBody, o?: Opts) => request<Contact>("POST", "/api/contacts", body, o),

  /** GET /api/contacts/{id} */
  getContact: (id: string, o?: Opts) => request<Contact>("GET", `/api/contacts/${encodeURIComponent(id)}`, undefined, o),

  /** PATCH /api/contacts/{id} */
  updateContact: (id: string, body: UpdateContactBody, o?: Opts) =>
    request<Contact>("PATCH", `/api/contacts/${encodeURIComponent(id)}`, body, o),

  /** POST /api/contacts/{id}/notes */
  addNote: (id: string, body: AddNoteBody, o?: Opts) =>
    request<Contact>("POST", `/api/contacts/${encodeURIComponent(id)}/notes`, body, o),

  /** POST /api/contacts/{id}/enrich → 202 Contact (409 if already pending) */
  enrich: (id: string, o?: Opts) =>
    request<Contact>("POST", `/api/contacts/${encodeURIComponent(id)}/enrich`, undefined, o),

  /** DELETE /api/contacts/{id} → 204 */
  deleteContact: (id: string, o?: Opts) =>
    request<null>("DELETE", `/api/contacts/${encodeURIComponent(id)}`, undefined, o),

  /** PATCH /api/contacts/{id}/follow-ups/{index} (v2) */
  patchFollowUp: (id: string, index: number, body: PatchFollowUpBody, o?: Opts) =>
    request<Contact>("PATCH", `/api/contacts/${encodeURIComponent(id)}/follow-ups/${index}`, body, o),

  /** GET /api/follow-ups/upcoming?days= (v2) */
  upcomingFollowUps: (days = 14, o?: Opts) =>
    request<UpcomingResponse>("GET", `/api/follow-ups/upcoming?days=${days}`, undefined, o),

  /** POST /api/transcribe (v2). Body is a 16 kHz mono PCM16 WAV. */
  transcribe: (wav: Blob, o?: Opts) =>
    request<TranscribeResponse>(
      "POST",
      "/api/transcribe",
      wav.type === "audio/wav" ? wav : new Blob([wav], { type: "audio/wav" }),
      { timeoutMs: 25_000, ...o },
    ),

  /** GET /api/export */
  exportAll: (o?: Opts) => request<ExportResponse>("GET", "/api/export", undefined, { timeoutMs: 30_000, ...o }),
};

/**
 * Validation messages start with the field name, e.g. "name: is required" (contract v1.1).
 * Returns the field and a display message with the prefix removed.
 */
const FIELD_LABELS: Record<string, string> = {
  name: "Name",
  audio: "Audio",
  date: "Date",
  confirmed_date: "Date",
  raw_notes: "Notes",
  text: "Note",
  tags: "Tags",
  body: "Request",
};

// Predicates that read naturally after the field label: "Name is required", "Notes must be at most …".
const PREDICATE = /^(is|are|must|can|cannot|can't|should|has|have|may|was|were|exceeds?|would)\b/i;

export function splitFieldMessage(message: string): { field: string | null; text: string } {
  const m = /^([a-z_][a-z0-9_.]*):\s*(.+)$/is.exec(message.trim());
  if (!m) return { field: null, text: message };
  const field = m[1].toLowerCase().split(".")[0];
  const rest = m[2].trim();
  const label = FIELD_LABELS[field];
  const text = label && PREDICATE.test(rest) ? `${label} ${rest}` : rest.charAt(0).toUpperCase() + rest.slice(1);
  return { field, text: /[.!?]$/.test(text) ? text : `${text}.` };
}

/** For validation errors, the field the server complained about (e.g. "name", "raw_notes", "text"). */
export function errorField(e: unknown): string | null {
  if (e instanceof ApiError && e.code === "validation_error") return splitFieldMessage(e.message).field;
  return null;
}

/** URL of the .ics download for one follow-up (v2). Use as an <a download> href. */
export function followUpIcsUrl(id: string, index: number): string {
  return `/api/contacts/${encodeURIComponent(id)}/follow-ups/${index}.ics`;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.code === "validation_error" ? splitFieldMessage(e.message).text : e.message;
  return "Something went wrong. Try again.";
}

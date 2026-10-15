// Types copied from docs/API_CONTRACT.md (v2.0) and docs/ENRICHMENT.md (v2).
// Do not change these without a contract change from the lead.

export type EnrichmentStatus = "none" | "pending" | "done" | "failed";

export type Confidence = "stated" | "maybe" | "inferred"; // v2: "maybe" added

export type DateStatus = "exact" | "needs_date" | "none" | "past";

export interface ConfidentValue {
  value: string | null;
  confidence: Confidence;
}

export interface ConfidentItem {
  value: string;
  confidence: Confidence;
}

// Shape of each item in enrichment.follow_ups as returned by the API (backend adds the
// last four fields; the model only produces action/when_text).
export interface FollowUp {
  action: string;
  when_text: string | null;
  suggested_date: string | null; // YYYY-MM-DD, computed by backend; null unless exact
  date_status: DateStatus;
  confidence: Confidence;
  confirmed_date: string | null; // YYYY-MM-DD the user picked; survives re-enrichment
  dismissed: boolean; // user chose "No date"
}

export interface ContactInfo {
  email: string | null;
  phone: string | null;
  linkedin: string | null;
}

export interface Enrichment {
  person_name?: string | null; // v2: the person's name only if said in the notes
  headline: string;
  summary: string;
  role: ConfidentValue;
  company: ConfidentValue;
  location: ConfidentValue;
  how_we_met: ConfidentValue;
  interests: ConfidentItem[];
  what_they_want: ConfidentItem[];
  how_i_can_help: ConfidentItem[];
  personal_details: ConfidentItem[];
  follow_ups: FollowUp[];
  gaps: string[];
  questions_to_ask: string[];
  suggested_opener: string;
  suggested_tags: string[];
  contact_info: ContactInfo;
}

export interface Contact {
  id: string;
  name: string;
  needs_name: boolean; // v2: true when created by voice without a name
  source: ContactSource; // v2.1
  raw_notes: string;
  tags: string[];
  enrichment: Enrichment | null; // schema in ENRICHMENT.md
  enrichment_status: EnrichmentStatus;
  enrichment_error: string | null; // human-readable, safe to show the user
  enriched_at: string | null;
  model_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContactSummary {
  // used in the list view
  id: string;
  name: string;
  headline: string | null; // enrichment.headline, if any
  company: string | null; // enrichment.company.value, if any
  tags: string[];
  enrichment_status: EnrichmentStatus;
  updated_at: string;
}

export interface ApiErrorBody {
  error: { code: string; message: string };
}

export interface ServiceStatus {
  name: string;
  available: boolean;
  detail: string | null;
}

export interface HealthResponse {
  status: "ok";
  model: ServiceStatus;
  asr: ServiceStatus; // v2
}

export interface ContactListResponse {
  contacts: ContactSummary[];
}

export type ContactSource = "typed" | "voice";

export interface CreateContactBody {
  name?: string; // required unless source is "voice"
  raw_notes: string;
  tags?: string[];
  enrich?: boolean;
  source?: ContactSource;
}

export interface PatchFollowUpBody {
  confirmed_date?: string | null; // YYYY-MM-DD
  dismissed?: boolean;
}

export interface UpcomingItem {
  contact_id: string;
  contact_name: string;
  index: number;
  action: string;
  date: string; // YYYY-MM-DD
}

export interface UpcomingResponse {
  items: UpcomingItem[];
}

export interface TranscribeResponse {
  text: string;
  duration_s: number;
}

export interface UpdateContactBody {
  name?: string;
  raw_notes?: string;
  tags?: string[];
}

export interface AddNoteBody {
  text: string;
  enrich?: boolean;
}

export interface ExportResponse {
  exported_at: string;
  contacts: Contact[];
}

// Limits from the contract.
export const NAME_MAX = 120;
export const NOTES_MAX = 10_000;

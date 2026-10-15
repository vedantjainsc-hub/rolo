# Rolo — Design System

Clean, corporate, calm. Navy and white, lots of space. It should feel like a
well-made private-banking or consulting tool — never playful, never cluttered.

## Color tokens (Tailwind theme + CSS variables)
| Token | Hex | Use |
|---|---|---|
| navy-900 | `#0B1F3A` | primary text, app bar, primary buttons |
| navy-700 | `#1E3A5F` | pressed states, headings accent |
| navy-500 | `#3D5A80` | secondary text, icons |
| navy-100 | `#E6ECF3` | chips, subtle fills |
| navy-50  | `#F5F7FA` | page background |
| white    | `#FFFFFF` | cards, inputs |
| line     | `#D9E0E8` | borders, dividers |
| gold     | `#B8925A` | one accent only: "inferred" markers, focus ring detail |
| success  | `#2F7D5B` | done states |
| danger   | `#B23A3A` | delete, errors |

Contrast: all text meets WCAG AA. No gradients, no heavy shadows (max `0 1px 2px rgba(11,31,58,.06)`).

## Type
- Font: Inter (self-hosted or system fallback `-apple-system, Segoe UI, Roboto`).
  No external font CDN at runtime.
- Scale: 28/34 semibold (page title), 20/28 semibold (card name), 16/24 regular (body),
  14/20 medium (labels, uppercase tracking 0.04em), 13/18 (meta).
- Body copy never below 16px on inputs (prevents iOS zoom).

## Space & layout
- 8px grid. Page padding 20px mobile, 32px ≥ 768px. Max content width 640px, centered.
- Cards: white, 12px radius, 1px `line` border, 20px padding, 16px gap between.
- Touch targets ≥ 44×44px. Primary actions in the thumb zone (bottom).

## Components
- **App bar:** navy-900, white title, 56px.
- **Primary button:** navy-900 fill, white text, 12px radius, full width on mobile.
- **Secondary button:** white fill, navy-900 text, `line` border.
- **FAB (+):** 56px navy-900 circle, bottom-right, 20px from edges.
- **Chips (tags):** navy-100 fill, navy-900 text, 999px radius.
- **Inferred marker:** small gold dot + "inferred" label in 12px; tooltip "Based on your notes, not confirmed."
- **Section header on card:** 14px uppercase label in navy-500, then content.
- **Empty states:** one line of copy + one action. No illustrations needed.
- **Loading (enriching):** skeleton lines on the card + text "Organising your notes on this device…"

## Screens
1. **Contacts** — search field at top, list of cards (name, headline, 2 tags, status dot), FAB.
2. **Quick Capture** — name input, large autosizing notes textarea (placeholder:
   "Everything you remember — where you met, what they do, what they want, personal details, follow-ups."),
   sticky bottom "Save & Enrich" + text link "Save without enriching".
3. **Contact Card** — name + headline, summary, then sections in order: Follow-ups,
   What they want, How I can help, Role & company, How we met, Interests, Personal,
   Gaps & questions to ask, Suggested opener (with Copy), Tags, Original notes (collapsible),
   "Add a note" input, overflow menu (Edit, Re-enrich, Delete).
4. **Settings** — model status pill (green "<model name> running locally", using `model.name` from /api/health / red with fix steps),
   Export JSON, app version, privacy line: "Your notes never leave this device's network."

## Voice
Short, plain, professional. "Save & Enrich", not "Magic!" Errors say what happened and
what to do next.

## v2 additions

### Confidence markers (three levels)
- **stated** — no marker.
- **maybe** — small chip with a 1px gold border and transparent fill, the text "maybe" in
  12px navy-700. Tooltip/tap: "You weren't sure about this."
- **inferred** — the existing gold dot plus "inferred" label. Tooltip: "Rolo's reading of your notes,
  not something you said."
- Both are ≥ 44×44 tap targets (as in v1).

### Speak (voice capture)
- **Contacts screen:** a full-width secondary-style "🎤 Speak" button directly under the search field
  (top of the screen, as the user asked). The FAB (+) still opens Quick Capture.
- **Speak screen (`/speak`):**
  - App bar "New contact".
  - Hint copy: "Say their name, where you met, what they do, and anything to follow up on."
  - A 96px navy-900 circular mic button in the thumb zone, with a pulsing 2px navy-100 ring
    while recording.
  - mm:ss timer.
  - Live transcript in a white card. Words not yet final are shown in navy-500.
  - While recording, the mic becomes a square Stop button.
  - Under it: text link "Cancel" (discards everything after a confirm if > 5 s recorded).
  - Language note in 13px meta: "Works in English and major European languages."
- **After stop:** "Saving…" then navigate to the card.

### Follow-ups with a calendar (card section "Follow-ups")
Each follow-up is a row: the action (16px), then `when_text` in 13px navy-500 quotes. What
comes next depends on `date_status`:
- **exact / confirmed:** a compact month calendar.
  - 7 columns, 32px cells. The visible area is the 44px row, which expands on tap.
  - The selected day is a navy-900 filled circle with white text; today has a navy-500 ring.
  - Prev/next month buttons are 44px.
  - Below the calendar: primary "Add to Calendar" (downloads the .ics) and text link "Change date".
- **needs_date:** a question in a navy-50 box: "When should you follow up? You said 'after
  Diwali'."
  - Chips (secondary style, 44px tall): Next week · In 2 weeks · Next month · Pick a date ·
    No date.
    Chip dates use the backend's date rules: Next week = next Monday, In 2 weeks = today+14,
    Next month = same day next month (clamped).
  - "Pick a date" opens the same mini calendar.
- **none:** a text link "Add a date" opens the same chips.
- **past:** no calendar. The row shows "(already happened)" in meta style.
- After you choose, a toast confirms "Follow-up set for Fri 16 Oct" with Undo.

### Upcoming strip (Contacts screen)
Shown above the list when there are items: label "UPCOMING" (14px uppercase navy-500), then
up to 3 rows of "Fri 16 Oct · Priya Shah — send the deck". Tapping a row opens the card.
The strip is hidden when empty.

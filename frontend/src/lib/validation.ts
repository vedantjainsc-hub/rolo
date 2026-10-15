import { NAME_MAX, NOTES_MAX } from "../api/types";

/**
 * Length in Unicode code points, matching the API (Python `len`, contract v1.2).
 * An emoji like "😀" counts as 1, not 2 UTF-16 units.
 */
export function charCount(s: string): number {
  let n = 0;
  for (const _ of s) n++;
  return n;
}

export function validateName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "Enter a name.";
  if (charCount(trimmed) > NAME_MAX) return `Name must be at most ${NAME_MAX} characters.`;
  return null;
}

export function validateNotes(notes: string): string | null {
  const n = charCount(notes);
  if (n > NOTES_MAX)
    return `Notes are ${n.toLocaleString()} characters. The limit is ${NOTES_MAX.toLocaleString()} — shorten them to save.`;
  return null;
}

// Plain-date (YYYY-MM-DD) helpers in the user's local time zone.

export function toYmd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function parseYmd(ymd: string | null | undefined): Date | null {
  if (!ymd || !/^\d{4}-\d{2}-\d{2}$/.test(ymd)) return null;
  const [y, m, d] = ymd.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function todayYmd(): string {
  return toYmd(new Date());
}

export function addDays(ymd: string, n: number): string {
  const d = parseYmd(ymd) ?? new Date();
  d.setDate(d.getDate() + n);
  return toYmd(d);
}

/** Backend rule for "next week": the next Monday after today (Monday → today + 7). */
export function nextMonday(ymd: string): string {
  const d = parseYmd(ymd) ?? new Date();
  const delta = ((1 - d.getDay() + 7) % 7) || 7;
  return addDays(toYmd(d), delta);
}

/** Same day next month, clamped to the month's last day (31 Jan → 28/29 Feb). */
export function addMonths(ymd: string, n: number): string {
  const d = parseYmd(ymd) ?? new Date();
  const target = new Date(d.getFullYear(), d.getMonth() + n, 1);
  const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(d.getDate(), last));
  return toYmd(target);
}

/** "Fri 16 Oct" (adds the year when it isn't this year). */
export function formatShortDate(ymd: string | null | undefined): string {
  const d = parseYmd(ymd);
  if (!d) return "";
  const sameYear = d.getFullYear() === new Date().getFullYear();
  const wd = d.toLocaleDateString("en-GB", { weekday: "short" });
  const dm = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
  return `${wd} ${dm}`;
}

export function formatLongDate(ymd: string): string {
  const d = parseYmd(ymd);
  if (!d) return ymd;
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

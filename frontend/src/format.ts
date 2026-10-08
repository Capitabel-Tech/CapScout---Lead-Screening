// Dates as the prototype shows them: "Mon 05 Oct", "Today", "2 days overdue".

const pad = (n: number) => String(n).padStart(2, '0')

// 1234567 -> "12,34,567" (Indian grouping). Amounts are stored as plain digits (rupees) and shown with commas.
export function formatINR(value: string | number | null | undefined): string {
  const digits = String(value ?? '').replace(/[^\d]/g, '')
  return digits ? Number(digits).toLocaleString('en-IN') : ''
}

export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function addDays(d: Date, n: number): Date {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

export function shortDate(iso: string | Date): string {
  const d = typeof iso === 'string' ? new Date(iso.length === 10 ? `${iso}T00:00:00` : iso) : iso
  const wd = d.toLocaleDateString('en-GB', { weekday: 'short' })
  const dm = d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
  return `${wd} ${dm}`
}

export function dayMonth(d: Date = new Date()): string {
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
}

/** Days from today to an ISO date (negative = in the past). */
export function daysFromToday(iso: string): number {
  const target = new Date(`${iso}T00:00:00`).getTime()
  const today = new Date(`${isoDate(new Date())}T00:00:00`).getTime()
  return Math.round((target - today) / 86_400_000)
}

export function nextActionWhen(iso: string): { text: string; late: boolean } {
  const n = daysFromToday(iso)
  if (n === 0) return { text: 'Today', late: false }
  if (n === 1) return { text: 'Tomorrow', late: false }
  if (n < 0) return { text: `${-n} day${n === -1 ? '' : 's'} overdue`, late: true }
  return { text: shortDate(iso), late: false }
}

export function relativeDay(iso: string | null): string {
  if (!iso) return 'No meetings yet'
  const n = daysFromToday(isoDate(new Date(iso)))
  if (n === 0) return 'Today'
  if (n === -1) return 'Yesterday'
  return shortDate(iso)
}

export function displayName(c: { business_name: string | null; promoter: string | null; lead_ref: string }) {
  return c.business_name || c.promoter || c.lead_ref
}

export function shortStaffName(full: string | undefined): string {
  if (!full) return ''
  const parts = full.trim().split(/\s+/)
  return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : parts[0]
}

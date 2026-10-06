import type { GpsPoint } from './api'

// The in-progress meeting lives on the phone until "Save meeting", so a closed
// tab or a crash loses nothing. (Phase 4 moves this to IndexedDB with an
// upload queue for offline use.)

export type MeetingDraft = {
  id: string // generated here; the server uses it to ignore duplicate submissions
  customerId: string
  startedAt: string
  gpsStart: GpsPoint | null
  gpsUnavailableReason: string | null
  // Only fields touched in this meeting. "" means "clear this field".
  values: Record<string, string>
}

const key = (customerId: string) => `meeting-draft:${customerId}`

export function loadDraft(customerId: string): MeetingDraft | null {
  try {
    const raw = localStorage.getItem(key(customerId))
    return raw ? (JSON.parse(raw) as MeetingDraft) : null
  } catch {
    return null
  }
}

export function saveDraft(draft: MeetingDraft): void {
  try {
    localStorage.setItem(key(draft.customerId), JSON.stringify(draft))
  } catch {
    // Storage full or blocked: the meeting still works for this session.
  }
}

export function clearDraft(customerId: string): void {
  try {
    localStorage.removeItem(key(customerId))
  } catch {
    // ignore
  }
}

// randomUUID needs a secure (https) page; getRandomValues works everywhere.
function uuid4(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

export function newDraft(customerId: string): MeetingDraft {
  return {
    id: uuid4(),
    customerId,
    startedAt: new Date().toISOString(),
    gpsStart: null,
    gpsUnavailableReason: null,
    values: {},
  }
}

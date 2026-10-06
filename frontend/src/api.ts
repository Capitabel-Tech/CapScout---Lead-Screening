// Thin wrapper over fetch for the FastAPI backend. The session lives in an
// httpOnly cookie, so there is no token handling here.

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `Request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...init.headers },
    })
  } catch {
    throw new ApiError(0, 'No connection. Check your network and try again.')
  }
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, body?.detail ?? null)
  return body as T
}

export const post = <T>(path: string, data?: unknown) =>
  api<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) })

// --- types returned by the backend ------------------------------------------

export type Staff = {
  id: string
  employee_code: string
  full_name: string
  role: 'FIELD_STAFF' | 'SUPERVISOR' | 'ADMIN'
}

export type Progress = { filled: number; total: number; percent: number }

export type ConversionStatus = 'NOT_CONVERTED' | 'CONVERTING' | 'CONVERTED' | 'CONVERSION_FAILED'

export type CustomerCard = {
  id: string
  lead_ref: string
  business_name: string | null
  promoter: string | null
  mobile: string | null
  location: string | null
  loan_required: string | null
  purpose: string | null
  opportunity_grade: string | null
  status: string | null
  next_action: string | null
  next_action_date: string | null
  conversion_status: ConversionStatus
  zoho_lead_id: string | null
  progress: Progress
  meeting_count: number
  last_meeting_at: string | null
}

export type SectionProgress = { key: string; label: string; filled: number; total: number }

export type CustomerDetail = CustomerCard & {
  owner: { id: string; full_name: string }
  converted_at: string | null
  lead_sync_status: 'NOT_QUEUED' | 'PENDING' | 'SYNCING' | 'SYNCED' | 'FAILED'
  lead_sync_error: string | null
  lead_sync_attempts: number
  sections: SectionProgress[]
  values: Record<string, string>
}

export type CustomerList = { total: number; items: CustomerCard[] }

export type DuplicateMatch = {
  id: string
  lead_ref: string
  conversion_status: ConversionStatus
  last_meeting_at: string | null
  business_name: string | null
  promoter: string | null
  mobile: string | null
  loan_required: string | null
  purpose: string | null
  likely_product: string | null
}

export type FieldType = 'system' | 'text' | 'long_text' | 'phone' | 'number' | 'date' | 'single_select'

export type FieldDef = {
  key: string
  label: string
  field_type: FieldType
  options: string[] | null
  unit: string | null
  section: string
  display_order: number
  counts_toward_progress: boolean
  system_source: 'application_ref' | 'meeting_date' | 'staff_name' | null
}

export type Section = { key: string; label: string; display_order: number }

export type FieldCatalog = { version: number; progress_total: number; sections: Section[]; fields: FieldDef[] }

export type GpsPoint = { latitude: number; longitude: number; accuracy_m: number; captured_at: string }

export type FieldChange = {
  field: string
  old: string | null
  new: string | null
  type: 'NEW' | 'UPDATED' | 'CLEARED'
}

export type SyncStatus = 'NOT_QUEUED' | 'PENDING' | 'SYNCING' | 'SYNCED' | 'FAILED'

export type Meeting = {
  id: string
  customer_id: string
  sequence_no: number
  staff: { id: string; full_name: string | null }
  started_at: string
  ended_at: string | null
  changes: FieldChange[]
  gps_status: 'PENDING' | 'CAPTURED' | 'UNAVAILABLE'
  gps_unavailable_reason: string | null
  place: string | null
  gps_start: GpsPoint | null
  gps_end: GpsPoint | null
  zoho_sync_status: SyncStatus
  zoho_meeting_id: string | null
  zoho_last_error: string | null
}

export type HomeSummary = { not_converted: number; converted: number; sync_pending: number; sync_failed: number }

// --- the "Convert to Lead" form: Zoho's own Lead fields -----------------------------------

export type ZohoFieldKind =
  | 'text'
  | 'textarea'
  | 'select'
  | 'email'
  | 'phone'
  | 'url'
  | 'integer'
  | 'decimal'
  | 'boolean'
  | 'date'

export type ZohoFormField = {
  api_name: string
  label: string
  kind: ZohoFieldKind
  required: boolean
  options: string[] | null
  max_length: number | null
  custom: boolean
  value: string | number | boolean | null
  prefilled_from: string | null
}

export type ConvertForm = {
  customer: { id: string; lead_ref: string; name: string | null }
  fields: ZohoFormField[]
}

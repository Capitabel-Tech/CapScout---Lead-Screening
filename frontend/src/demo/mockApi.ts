// DEMO MODE: a stand-in for the backend that runs entirely in the browser.
//
// It answers the same requests as the real API, with sample leads kept in this browser's
// localStorage, so the app can be shown (screens, navigation and the main rules) with NO server.
// Nothing here ever reaches Zoho or a database. Switched on only by VITE_DEMO=true (see .env.demo).
// Add ?reset=1 to the address to go back to the original sample data.

import type {
  ConversionStatus,
  ConvertForm,
  CustomerCard,
  CustomerDetail,
  CustomerList,
  FieldCatalog,
  FieldChange,
  GpsPoint,
  HomeSummary,
  Meeting,
  Staff,
  ZohoFormField,
} from '../api'
import { addDays, isoDate } from '../format'
import catalogJson from './fields_v1.json'
import { demoPlace } from './places'
import { ZOHO_LEAD_FIELDS } from './zohoLeadFields'

export class DemoHttpError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `Request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

// --- catalogue ------------------------------------------------------------------------------

const FIELDS = catalogJson.fields
const BY_KEY = new Map(FIELDS.map((f) => [f.key, f]))
const PROGRESS_KEYS = new Set(FIELDS.filter((f) => f.counts_toward_progress).map((f) => f.key))

const CATALOG: FieldCatalog = {
  version: catalogJson.version,
  progress_total: PROGRESS_KEYS.size,
  sections: catalogJson.sections,
  fields: FIELDS.map((f) => ({
    key: f.key,
    label: f.label,
    field_type: f.field_type as FieldCatalog['fields'][number]['field_type'],
    options: f.options,
    unit: f.unit,
    section: f.section,
    display_order: f.display_order,
    counts_toward_progress: f.counts_toward_progress,
    system_source: f.system_source as FieldCatalog['fields'][number]['system_source'],
  })),
}

const STAFF: Staff = { id: 'demo-staff-ravi', employee_code: 'DEV001', full_name: 'Ravi Kumar', role: 'FIELD_STAFF' }
const CONVERT_SECONDS = 4
const SYNC_SECONDS = 3
const PLACE_SECONDS = 2.5

// --- the demo "database" ------------------------------------------------------------------------

type DMeeting = {
  id: string
  seq: number
  started_at: string
  ended_at: string
  created_ms: number
  changes: FieldChange[]
  gps: GpsPoint | null
  reason: string | null
  place: string | null
  failed: boolean
}

type DCustomer = {
  id: string
  ref_no: number
  values: Record<string, string>
  status: ConversionStatus
  zoho_lead_id: string | null
  convert_requested_ms: number | null
  converted_at: string | null
  created_ms: number
  meetings: DMeeting[]
}

type Db = { v: 1; next_ref: number; signed_in: boolean; customers: DCustomer[] }

const KEY = 'capscout-demo-db-v1'
let db: Db | null = null

const uid = () =>
  typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0
        return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
      })

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000)

function normMobile(raw: string | undefined): string {
  const digits = (raw ?? '').replace(/\D/g, '')
  return digits.length > 10 ? digits.slice(-10) : digits
}

/** Apply typed values to a customer's current values. Returns what changed (the meeting's history). */
function applyValues(c: DCustomer, raw: Record<string, unknown>): FieldChange[] {
  const changes: FieldChange[] = []
  for (const [key, value] of Object.entries(raw)) {
    const spec = BY_KEY.get(key)
    if (!spec || spec.field_type === 'system' || key === 'location') continue // Location comes from GPS only
    let next = String(value ?? '').trim()
    if (spec.field_type === 'phone') next = normMobile(next)
    const old = c.values[key]
    if (!next) {
      if (old !== undefined) {
        delete c.values[key]
        changes.push({ field: key, old, new: null, type: 'CLEARED' })
      }
      continue
    }
    if (old === next) continue
    c.values[key] = next
    changes.push({ field: key, old: old ?? null, new: next, type: old === undefined ? 'NEW' : 'UPDATED' })
  }
  return changes
}

type MeetingInput = {
  id?: string
  started_at: string
  ended_at?: string
  gps_start?: GpsPoint | null
  gps_unavailable_reason?: string | null
  values?: Record<string, unknown>
}

function addMeeting(c: DCustomer, input: MeetingInput, opts: { createdMs?: number; failed?: boolean } = {}): DMeeting {
  const changes = applyValues(c, input.values ?? {})
  const gps = input.gps_start ?? null
  const place = gps ? demoPlace(gps.latitude, gps.longitude) : null
  // The lead's address is set ONCE, from the first meeting that has a GPS place, and then stays fixed.
  if (place && !c.values.location) {
    c.values.location = place.area
    changes.push({ field: 'location', old: null, new: place.area, type: 'NEW' })
  }
  const meeting: DMeeting = {
    id: input.id ?? uid(),
    seq: c.meetings.length + 1,
    started_at: input.started_at,
    ended_at: input.ended_at ?? input.started_at,
    created_ms: opts.createdMs ?? Date.now(),
    changes,
    gps,
    reason: gps ? null : (input.gps_unavailable_reason ?? 'No GPS'),
    place: place?.place ?? null,
    failed: opts.failed ?? false,
  }
  c.meetings.push(meeting)
  // "Proceed" sends the prospect to Leads (the phone asked the user to confirm first).
  if (c.values.sm_recommendation === 'Proceed' && c.status === 'NOT_CONVERTED') {
    c.status = 'CONVERTING'
    c.convert_requested_ms = Date.now()
  }
  return meeting
}

function newCustomer(refNo?: number): DCustomer {
  const d = load()
  return {
    id: uid(),
    ref_no: refNo ?? d.next_ref++,
    values: {},
    status: 'NOT_CONVERTED',
    zoho_lead_id: null,
    convert_requested_ms: null,
    converted_at: null,
    created_ms: Date.now(),
    meetings: [],
  }
}

// --- sample data ----------------------------------------------------------------------------------

function seed(): Db {
  const now = Date.now()
  const today = new Date()
  const customers: DCustomer[] = []
  const make = (
    ref: number,
    meetings: { at: Date; gps: [number, number, number] | null; reason?: string; values: Record<string, string>; failed?: boolean }[],
  ) => {
    const c: DCustomer = { ...newCustomerShell(ref), created_ms: meetings[0].at.getTime() }
    for (const m of meetings) {
      addMeeting(
        c,
        {
          started_at: m.at.toISOString(),
          ended_at: new Date(m.at.getTime() + 20 * 60_000).toISOString(),
          gps_start: m.gps
            ? { latitude: m.gps[0], longitude: m.gps[1], accuracy_m: m.gps[2], captured_at: m.at.toISOString() }
            : null,
          gps_unavailable_reason: m.reason ?? null,
          values: m.values,
        },
        { createdMs: m.at.getTime(), failed: m.failed },
      )
    }
    customers.push(c)
    return c
  }
  const date = (offset: number) => isoDate(addDays(today, offset))

  const charan = make(5, [
    {
      at: hoursAgo(72),
      gps: null,
      reason: 'Location permission denied',
      values: {
        source_type: 'DSA', source_name: 'Dhanvik Reddy', source_contact: '7894561231',
        business_name: 'Sri Charan Enterprises', promoter: 'Charan Reddy', mobile: '9875435211',
        constitution: 'Proprietorship', industry: 'Automobiles', vintage_years: '12', loan_required: '5000000',
        purpose: 'Expansion', urgency: '<30 days', secured_unsecured: 'Secured',
        annual_turnover: '1200000', monthly_banking: '3000000', existing_debt: '1200000', monthly_emi: '100000',
        gst_available: 'Yes', itr_financials: 'Yes', bank_statements: 'Yes',
        property_available: 'Yes', property_type: 'Commercial', property_documents: 'Yes',
        overdue: 'No', bounces: 'No', settlement_write_off: 'No',
        documents_readiness: 'Ready', business_quality: 'Strong', banking_quality: 'Strong', credit_risk: 'Manageable',
        opportunity_grade: 'A – Priority', likely_product: 'LAP', sm_recommendation: 'Proceed',
        next_action: 'New', next_action_date: date(3),
      },
    },
    { at: hoursAgo(48), gps: [13.085, 80.2101, 14], values: { next_action: 'Sanction', loan_required: '6000000' } },
    { at: hoursAgo(20), gps: [13.0852, 80.2099, 11], values: { loan_required: '7000000' } },
  ])
  charan.status = 'CONVERTED'
  charan.zoho_lead_id = '1236291000001094004'
  charan.converted_at = hoursAgo(47).toISOString()

  make(8, [
    {
      at: hoursAgo(2),
      gps: [17.4948, 78.399, 22],
      values: {
        source_type: 'Direct', business_name: "Pragya's Sales and Retails", promoter: 'Pragya', mobile: '9000000011',
        industry: 'Retail', constitution: 'Partnership', vintage_years: '4', loan_required: '1500000',
        purpose: 'Working Capital', urgency: 'Immediate', secured_unsecured: 'Unsecured',
        annual_turnover: '700000', monthly_banking: '900000', gst_available: 'Yes', itr_financials: 'Unknown',
        bank_statements: 'Yes', business_quality: 'Average', next_action: 'Qualified', next_action_date: date(0),
      },
    },
  ])

  make(10, [
    {
      at: hoursAgo(96),
      gps: [17.4967, 78.3556, 17],
      values: {
        source_type: 'DSA', source_name: 'Raghav', source_contact: '9811122233',
        business_name: "Vishwath's tech solutions", promoter: 'Vishwath', mobile: '9000000010',
        industry: 'IT services', constitution: 'Pvt Ltd', vintage_years: '7', loan_required: '4000000',
        purpose: 'Capex', urgency: '30-60 days', secured_unsecured: 'Open to both',
        annual_turnover: '1700000', monthly_banking: '2800000', existing_debt: '2500000', monthly_emi: '250000',
        gst_available: 'Yes', itr_financials: 'Yes', bank_statements: 'No',
        documents_readiness: 'Partial', business_quality: 'Strong', banking_quality: 'Average', credit_risk: 'Manageable',
        opportunity_grade: 'B – Develop', likely_product: 'Business Loan', sm_recommendation: 'Hold',
        next_action: 'Documents Pending', next_action_date: date(-2),
      },
    },
    {
      at: hoursAgo(24), gps: null, reason: 'GPS switched off', failed: true,
      values: { bank_statements: 'Yes', documents_readiness: 'Ready' },
    },
  ])

  make(11, [
    {
      at: hoursAgo(26),
      gps: [17.4399, 78.4983, 19],
      values: {
        source_type: 'Auditor/CA', source_name: 'CA Ramesh Babu', source_contact: '9988776655',
        business_name: 'Sri Maruthi Automobiles', promoter: 'Maruthi Rao', mobile: '9000000012',
        industry: 'Auto dealership', constitution: 'Proprietorship', vintage_years: '9', loan_required: '6000000',
        purpose: 'Expansion', urgency: '<30 days', secured_unsecured: 'Secured',
        property_available: 'Yes', property_type: 'Residential', property_documents: 'Yes', overdue: 'No', bounces: 'No',
        business_quality: 'Strong', credit_risk: 'None known', opportunity_grade: 'B – Develop',
        likely_product: 'LAP', sm_recommendation: 'Hold', next_action: 'Lender Matching', next_action_date: date(1),
      },
    },
  ])

  const annapurna = make(9, [
    {
      at: hoursAgo(140),
      gps: [12.9716, 77.5946, 25],
      values: {
        source_type: 'Connector', source_name: 'Prasad', source_contact: '9123456780',
        business_name: 'Annapurna Foods LLP', promoter: 'Lakshmi Devi', mobile: '9000000009',
        industry: 'Food processing', constitution: 'LLP', vintage_years: '8', loan_required: '1500000',
        purpose: 'Working Capital', urgency: 'Flexible', secured_unsecured: 'Unsecured',
        annual_turnover: '800000', monthly_banking: '1100000', gst_available: 'Yes', itr_financials: 'Yes', bank_statements: 'Yes',
        documents_readiness: 'Partial', business_quality: 'Average', banking_quality: 'Average',
        opportunity_grade: 'B – Develop', likely_product: 'Working Capital', sm_recommendation: 'Proceed',
        next_action: 'Documents Pending', next_action_date: date(-3),
      },
    },
    { at: hoursAgo(50), gps: [12.9719, 77.5949, 21], values: { documents_readiness: 'Ready', next_action: 'Login', next_action_date: date(1) } },
  ])
  annapurna.status = 'CONVERTED'
  annapurna.zoho_lead_id = '1236291000001101009'
  annapurna.converted_at = hoursAgo(49).toISOString()

  return { v: 1, next_ref: 12, signed_in: false, customers: customers.map((c) => ({ ...c, created_ms: Math.min(c.created_ms, now) })) }
}

function newCustomerShell(ref: number): DCustomer {
  return {
    id: uid(), ref_no: ref, values: {}, status: 'NOT_CONVERTED', zoho_lead_id: null,
    convert_requested_ms: null, converted_at: null, created_ms: Date.now(), meetings: [],
  }
}

function load(): Db {
  if (db) return db
  try {
    if (new URLSearchParams(location.search).has('reset')) localStorage.removeItem(KEY)
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Db
      if (parsed.v === 1) return (db = parsed)
    }
  } catch {
    // unreadable storage: start from the sample data
  }
  db = seed()
  save()
  return db
}

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(db))
  } catch {
    // private window or full storage: the demo still works until the page is closed
  }
}

// --- derived state (time-based: a conversion takes seconds, a sync takes seconds) ------------------

function refresh(c: DCustomer) {
  if (c.status === 'CONVERTING' && c.convert_requested_ms && Date.now() - c.convert_requested_ms >= CONVERT_SECONDS * 1000) {
    c.status = 'CONVERTED'
    c.zoho_lead_id = `12362910000011${String(c.ref_no).padStart(5, '0')}`
    c.converted_at = new Date().toISOString()
    save()
  }
}

const syncOf = (m: DMeeting): 'PENDING' | 'SYNCED' | 'FAILED' =>
  m.failed ? 'FAILED' : Date.now() - m.created_ms < SYNC_SECONDS * 1000 ? 'PENDING' : 'SYNCED'

const refOf = (c: DCustomer) => `MSME-${String(c.ref_no).padStart(4, '0')}`

// Direct customers are not asked for a source name or contact, so those two do not count for them.
const applicableKeys = (c: DCustomer) =>
  [...PROGRESS_KEYS].filter(
    (k) =>
      !(['source_name', 'source_contact'].includes(k) && c.values.source_type === 'Direct') &&
      !(['property_type', 'property_documents'].includes(k) && c.values.property_available === 'No') &&
      !(['property_available', 'property_type', 'property_documents'].includes(k) && c.values.secured_unsecured === 'Unsecured'),
  )

function progress(c: DCustomer) {
  const keys = applicableKeys(c)
  const filled = keys.filter((k) => k in c.values).length
  const total = keys.length
  return { filled, total, percent: Math.round((filled * 100) / total) }
}

function lastMeetingAt(c: DCustomer): string | null {
  return c.meetings.length ? c.meetings.map((m) => m.started_at).sort().at(-1)! : null
}

function card(c: DCustomer): CustomerCard {
  refresh(c)
  const v = c.values
  return {
    id: c.id,
    lead_ref: refOf(c),
    business_name: v.business_name ?? null,
    promoter: v.promoter ?? null,
    mobile: v.mobile ?? null,
    location: v.location ?? null,
    loan_required: v.loan_required ?? null,
    purpose: v.purpose ?? null,
    opportunity_grade: v.opportunity_grade ?? null,
    status: v.status ?? null,
    next_action: v.next_action ?? null,
    next_action_date: v.next_action_date ?? null,
    conversion_status: c.status,
    zoho_lead_id: c.zoho_lead_id,
    progress: progress(c),
    meeting_count: c.meetings.length,
    last_meeting_at: lastMeetingAt(c),
  }
}

function detail(c: DCustomer): CustomerDetail {
  const base = card(c)
  return {
    ...base,
    owner: { id: STAFF.id, full_name: STAFF.full_name },
    converted_at: c.converted_at,
    lead_sync_status: c.status === 'CONVERTING' ? 'PENDING' : c.status === 'CONVERTED' ? 'SYNCED' : 'NOT_QUEUED',
    lead_sync_error: null,
    lead_sync_attempts: 0,
    sections: CATALOG.sections.map((s) => {
      const keys = applicableKeys(c).filter((k) => BY_KEY.get(k)?.section === s.key)
      return { key: s.key, label: s.label, filled: keys.filter((k) => k in c.values).length, total: keys.length }
    }),
    values: { ...c.values },
  }
}

function meetingOut(c: DCustomer, m: DMeeting): Meeting {
  const sync = syncOf(m)
  const placeReady = Date.now() - m.created_ms >= PLACE_SECONDS * 1000
  return {
    id: m.id,
    customer_id: c.id,
    sequence_no: m.seq,
    staff: { id: STAFF.id, full_name: STAFF.full_name },
    started_at: m.started_at,
    ended_at: m.ended_at,
    changes: m.changes,
    gps_status: m.gps ? 'CAPTURED' : 'UNAVAILABLE',
    gps_unavailable_reason: m.gps ? null : m.reason,
    place: m.gps && placeReady ? m.place : null,
    gps_start: m.gps,
    gps_end: null,
    zoho_sync_status: sync,
    zoho_meeting_id: sync === 'SYNCED' ? `12362910000009${String(c.ref_no).padStart(2, '0')}${m.seq}` : null,
    zoho_last_error: sync === 'FAILED' ? 'OAUTH_SCOPE_MISMATCH invalid oauth scope to access this URL' : null,
  }
}

// --- the Convert to Lead form ----------------------------------------------------------------------

function convertForm(c: DCustomer): ConvertForm {
  const v = c.values
  const standard: Record<string, [string | undefined, string]> = {
    Last_Name: [v.promoter ?? v.business_name, 'Promoter'],
    Company: [v.business_name, 'Business Name'],
    Mobile: [v.mobile, 'Mobile'],
    City: [v.location, 'Location'],
  }
  const loanType = [v.likely_product, v.purpose].find((x) => x && ['LAP', 'Business Loan', 'Working Capital'].includes(x))
  const description = [
    'CapScout details (updated automatically)',
    refOf(c),
    '',
    ...FIELDS.filter((f) => f.field_type !== 'system' && v[f.key] !== undefined).map((f) => `${f.label}: ${v[f.key]}`),
  ].join('\n')

  const fields: ZohoFormField[] = ZOHO_LEAD_FIELDS.map((f) => {
    let value: string | null = null
    let from: string | null = null
    if (standard[f.api_name]?.[0]) [value, from] = [standard[f.api_name][0]!, standard[f.api_name][1]]
    else if (f.api_name === 'Loan_Type' && loanType) [value, from] = [loanType, 'Likely Product']
    else if (f.api_name === 'Description') [value, from] = [description, 'everything collected in the app']
    return {
      api_name: f.api_name,
      label: f.label,
      kind: f.kind,
      required: !!f.required,
      options: f.options ?? null,
      max_length: ['text', 'textarea', 'phone', 'email', 'url'].includes(f.kind) ? 255 : null,
      custom: !!f.custom,
      value,
      prefilled_from: from,
    }
  })
  return {
    customer: { id: c.id, lead_ref: refOf(c), name: v.business_name ?? v.promoter ?? null },
    fields,
  }
}

function validateLead(values: Record<string, unknown>): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const f of ZOHO_LEAD_FIELDS) {
    const raw = values[f.api_name]
    const text = raw === undefined || raw === null ? '' : String(raw).trim()
    if (!text) {
      if (f.required) errors[f.api_name] = 'required'
      continue
    }
    if (f.kind === 'email' && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(text)) errors[f.api_name] = 'enter a valid email address'
    else if ((f.kind === 'integer' || f.kind === 'decimal') && Number.isNaN(Number(text))) errors[f.api_name] = 'enter a valid number'
    else if (f.kind === 'select' && !f.options?.some((o) => o.toLowerCase() === text.toLowerCase()))
      errors[f.api_name] = 'choose one of the options'
  }
  return errors
}

// --- routing ------------------------------------------------------------------------------------------

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const find = (id: string): DCustomer => {
  const c = load().customers.find((x) => x.id === id)
  if (!c) throw new DemoHttpError(404, 'Not found')
  return c
}
const matchPath = (path: string, re: RegExp) => path.match(re)

export async function demoApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  await sleep(90 + Math.random() * 140) // feels like a real network call
  const method = (init.method ?? 'GET').toUpperCase()
  const url = new URL(path, 'http://demo.local')
  const p = url.pathname
  const q = url.searchParams
  const body = init.body ? (JSON.parse(String(init.body)) as Record<string, any>) : {} // eslint-disable-line @typescript-eslint/no-explicit-any
  const d = load()
  const out = (value: unknown) => value as T

  // ---- sign in (any employee code and password work in the demo) ----
  if (p === '/auth/login' && method === 'POST') {
    if (!String(body.employee_code ?? '').trim() || !String(body.password ?? '')) throw new DemoHttpError(422, 'Enter your employee code and password')
    d.signed_in = true
    save()
    return out({ ...STAFF, employee_code: String(body.employee_code).trim().toUpperCase() })
  }
  if (p === '/auth/logout') {
    d.signed_in = false
    save()
    return out(undefined)
  }
  if (!d.signed_in) throw new DemoHttpError(401, 'Not signed in')

  if (p === '/me') return out(STAFF)
  if (p === '/fields') return out(CATALOG)

  if (p === '/geo/reverse') {
    const near = demoPlace(Number(q.get('lat')), Number(q.get('lng')))
    return out({ place: near.place, area: near.area })
  }

  if (p === '/customers/-/summary') {
    d.customers.forEach(refresh)
    const meetings = d.customers.flatMap((c) => c.meetings.map(syncOf))
    const summary: HomeSummary = {
      not_converted: d.customers.filter((c) => c.status !== 'CONVERTED').length,
      converted: d.customers.filter((c) => c.status === 'CONVERTED').length,
      sync_pending: meetings.filter((s) => s === 'PENDING').length,
      sync_failed: meetings.filter((s) => s === 'FAILED').length,
    }
    return out(summary)
  }

  if (p === '/customers' && method === 'GET') {
    const converted = q.get('tab') === 'converted'
    const needle = (q.get('q') ?? '').trim().toLowerCase()
    d.customers.forEach(refresh)
    const rows = d.customers
      .filter((c) => (converted ? c.status === 'CONVERTED' : c.status !== 'CONVERTED'))
      .filter((c) => !needle || ['business_name', 'promoter', 'mobile'].some((k) => (c.values[k] ?? '').toLowerCase().includes(needle)))
      .sort((a, b) => (lastMeetingAt(b) ?? '').localeCompare(lastMeetingAt(a) ?? '') || b.created_ms - a.created_ms)
    const limit = Number(q.get('limit') ?? 50)
    const list: CustomerList = { total: rows.length, items: rows.slice(0, limit).map(card) }
    return out(list)
  }

  // ---- "New lead": a prospect and its Meeting #1 in one step ----
  if (p === '/leads/new' && method === 'POST') {
    const m = body.meeting as MeetingInput
    const existing = d.customers.flatMap((c) => c.meetings.map((x) => ({ c, x }))).find((e) => e.x.id === m.id)
    if (existing) return out({ customer_id: existing.c.id, meeting: meetingOut(existing.c, existing.x) })

    const typed = Object.fromEntries(Object.entries(m.values ?? {}).filter(([k]) => k !== 'location'))
    if (!['business_name', 'promoter', 'mobile'].some((k) => String(typed[k] ?? '').trim())) {
      const message = 'enter at least Business Name, POC or Mobile'
      throw new DemoHttpError(422, { code: 'INVALID_VALUES', errors: { business_name: message, promoter: message, mobile: message } })
    }
    const mobile = normMobile(String(typed.mobile ?? ''))
    if (typed.mobile && mobile.length !== 10)
      throw new DemoHttpError(422, { code: 'INVALID_VALUES', errors: { mobile: 'must be a 10-digit mobile number' } })

    const matches = mobile ? d.customers.filter((c) => c.values.mobile === mobile) : []
    let target: DCustomer | undefined
    const choice = (body.on_duplicate as string | undefined) ?? 'ask'
    if (matches.length && choice === 'ask') {
      throw new DemoHttpError(409, {
        code: 'DUPLICATE_OWN',
        message: 'A customer with this mobile number already exists.',
        choices: ['overwrite', 'create_new', 'cancel'],
        matches: matches.map((c) => ({
          id: c.id, lead_ref: refOf(c), conversion_status: c.status, last_meeting_at: lastMeetingAt(c),
          business_name: c.values.business_name ?? null, promoter: c.values.promoter ?? null, mobile: c.values.mobile ?? null,
          loan_required: c.values.loan_required ?? null, purpose: c.values.purpose ?? null, likely_product: c.values.likely_product ?? null,
        })),
      })
    }
    if (matches.length && choice === 'overwrite') {
      target = matches.find((c) => c.id === body.overwrite_customer_id)
      if (!target) throw new DemoHttpError(422, { code: 'INVALID_VALUES', errors: { overwrite_customer_id: 'choose one of the matching records' } })
    }
    const customer = target ?? newCustomer()
    if (!target) d.customers.push(customer)
    const meeting = addMeeting(customer, { ...m, values: typed })
    save()
    return out({ customer_id: customer.id, meeting: meetingOut(customer, meeting) })
  }

  // ---- "New lead": the blank Zoho Lead form; saving creates the customer and the Lead together ----
  if (p === '/customers/-/lead-form') {
    const blank = convertForm(newCustomerShell(0)).fields.map((f) => ({ ...f, value: null, prefilled_from: null }))
    return out({ customer: null, fields: blank })
  }
  if (p === '/customers/-/new-lead' && method === 'POST') {
    const lv = (body.lead_values ?? {}) as Record<string, unknown>
    const errors = validateLead(lv)
    if (Object.keys(errors).length) throw new DemoHttpError(422, { code: 'INVALID_VALUES', errors })
    const mobile = normMobile(String(lv.Mobile ?? lv.Phone ?? ''))
    if (mobile && d.customers.some((c) => c.values.mobile === mobile))
      throw new DemoHttpError(409, { code: 'DUPLICATE_OWN', message: 'A customer with this mobile number already exists.' })
    const customer = newCustomer()
    customer.values = {
      promoter: [lv.First_Name, lv.Last_Name].filter(Boolean).join(' '),
      ...(lv.Company ? { business_name: String(lv.Company) } : {}),
      ...(mobile ? { mobile } : {}),
    }
    customer.status = 'CONVERTING'
    customer.convert_requested_ms = Date.now()
    d.customers.push(customer)
    save()
    return out(detail(customer))
  }

  // ---- one customer ----
  let hit = matchPath(p, /^\/customers\/([^/]+)\/meetings\/([^/]+)\/retry-sync$/)
  if (hit && method === 'POST') {
    const c = find(hit[1])
    const m = c.meetings.find((x) => x.id === hit![2])
    if (!m) throw new DemoHttpError(404, 'Not found')
    if (syncOf(m) === 'FAILED') [m.failed, m.created_ms] = [false, Date.now()]
    save()
    return out(meetingOut(c, m))
  }

  hit = matchPath(p, /^\/customers\/([^/]+)\/meetings$/)
  if (hit) {
    const c = find(hit[1])
    if (method === 'GET') return out({ items: [...c.meetings].reverse().map((m) => meetingOut(c, m)) })
    if (method === 'POST') {
      const input = body as unknown as MeetingInput
      const again = c.meetings.find((x) => x.id === input.id)
      const meeting = again ?? addMeeting(c, input)
      save()
      return out(meetingOut(c, meeting))
    }
  }

  hit = matchPath(p, /^\/customers\/([^/]+)\/convert-form$/)
  if (hit) return out(convertForm(find(hit[1])))

  hit = matchPath(p, /^\/customers\/([^/]+)\/convert$/)
  if (hit && method === 'POST') {
    const c = find(hit[1])
    refresh(c)
    if (body.lead_values) {
      const errors = validateLead(body.lead_values as Record<string, unknown>)
      if (Object.keys(errors).length) throw new DemoHttpError(422, { code: 'INVALID_VALUES', errors })
    }
    if (c.status === 'NOT_CONVERTED' || c.status === 'CONVERSION_FAILED') {
      c.status = 'CONVERTING'
      c.convert_requested_ms = Date.now()
      save()
    }
    return out(detail(c))
  }

  hit = matchPath(p, /^\/customers\/([^/]+)$/)
  if (hit && method === 'GET') return out(detail(find(hit[1])))

  throw new DemoHttpError(404, 'Not found')
}

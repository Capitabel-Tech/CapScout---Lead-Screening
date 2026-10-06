// The meeting form, laid out exactly like the client's prototype: 6 step tabs
// (Lead · Business · Money · Property · Assess · Decide), Back / Next footer,
// and a summary screen after saving. Every option list comes from the Excel;
// fields the Excel gives no dropdown (Status, Litigation/Dispute, …) are typed.
//
// "New lead" (/new) creates the prospect and its Meeting #1 together;
// /customers/:id/meeting records the next meeting for an existing customer.

import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  api,
  ApiError,
  post,
  type CustomerDetail,
  type DuplicateMatch,
  type FieldCatalog,
  type GpsPoint,
  type Meeting,
} from '../api'
import { useAuth } from '../auth'
import { IconArrow, IconCheck, IconGps, IconMic, IconX } from '../components/icons'
import { Choice, cleanNumber, MoneyBox, MoneyField, TextField, TriRow } from '../components/widgets'
import { useFieldCatalog } from '../fields'
import { addDays, dayMonth, isoDate, relativeDay, shortDate, shortStaffName } from '../format'
import { captureLocation, GPS_ERROR_TEXT, GpsError, type GpsErrorCode } from '../gps'
import { clearDraft, loadDraft, newDraft, saveDraft, type MeetingDraft } from '../meetingDraft'

const STEPS = ['lead', 'business', 'money', 'property', 'assess', 'decide'] as const
const TABS = ['Lead', 'Business', 'Money', 'Property', 'Assess', 'Decide']
const NEW = 'new'

type Saved = { customerId: string; meeting: Meeting; leadRef: string }

export default function MeetingPage() {
  const params = useParams()
  const customerId = params.id ?? NEW
  const isNew = customerId === NEW
  const navigate = useNavigate()
  const { staff } = useAuth()
  const catalog = useFieldCatalog()
  const [customer, setCustomer] = useState<CustomerDetail | null>(null)
  const [draft, setDraft] = useState<MeetingDraft>(() => loadDraft(customerId) ?? newDraft(customerId))
  const [stepIdx, setStepIdx] = useState(0)
  const [saved, setSaved] = useState<Saved | null>(null)
  const gps = useMeetingGps(draft, update)

  useEffect(() => {
    if (!isNew) api<CustomerDetail>(`/customers/${customerId}`).then(setCustomer).catch(() => undefined)
  }, [customerId, isNew])

  function update(next: MeetingDraft) {
    setDraft(next)
    saveDraft(next)
  }

  if (!catalog || (!isNew && !customer)) return <div className="splash">Loading…</div>
  if (saved) return <DoneScreen saved={saved} values={{ ...(customer?.values ?? {}), ...draft.values }} />

  const current = customer?.values ?? {}
  const v = (key: string) => draft.values[key] ?? current[key] ?? ''
  const set = (key: string) => (value: string) => {
    const values = { ...draft.values }
    if (value === (current[key] ?? '')) delete values[key]
    else values[key] = value
    update({ ...draft, values })
  }
  const field = (key: string) => {
    const f = catalog.fields.find((x) => x.key === key)!
    return { label: f.label, options: f.options ?? [], value: v(key), onChange: set(key) }
  }

  const leaveTo = isNew ? '/' : `/customers/${customerId}`
  const title = isNew ? 'New lead' : `Meeting #${(customer?.meeting_count ?? 0) + 1}`
  const ref = customer?.lead_ref ?? 'New'
  const step = STEPS[stepIdx]
  const caption = catalog.sections.find((s) => s.key === step)?.label ?? ''
  const go = (i: number) => {
    setStepIdx(i)
    document.querySelector('.scroll')?.scrollTo(0, 0)
  }

  return (
    <>
      <div className="hdr" style={{ padding: '10px 12px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button className="icon-btn" aria-label="Close (the meeting stays as a draft)" onClick={() => navigate(leaveTo)}>
            <IconX />
          </button>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 17, fontWeight: 700 }}>{title}</div>
            <div className="mono" style={{ fontSize: 12, color: '#B9C6D3' }}>
              {ref} · {dayMonth(new Date(draft.startedAt))} · {shortStaffName(staff?.full_name)}
            </div>
          </div>
          <button
            style={{
              flex: 'none',
              height: 36,
              padding: '0 12px',
              borderRadius: 18,
              border: '1.5px solid #4A6178',
              background: 'transparent',
              color: '#fff',
              fontSize: 13,
              fontWeight: 600,
            }}
            onClick={() => {
              saveDraft(draft)
              navigate(leaveTo)
            }}
          >
            Save draft
          </button>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map((t, i) => (
            <button
              key={t}
              className={`tab${i === stepIdx ? ' cur' : i < stepIdx ? ' done' : ''}`}
              aria-label={`Go to step ${i + 1}, ${t}`}
              onClick={() => go(i)}
            >
              <span className="c">{i < stepIdx ? <IconCheck size={12} width={3.2} /> : i + 1}</span>
              <span>{t}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="scroll">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--muted)' }}>
            Step {stepIdx + 1} of 6 · {caption}
          </div>
          <GpsStatus gps={gps} />
        </div>
        {step === 'lead' && <LeadStep field={field} gps={gps} leadLocation={isNew ? '' : (current.location ?? '')} />}
        {step === 'business' && <BusinessStep field={field} />}
        {step === 'money' && <MoneyStep field={field} />}
        {step === 'property' && <PropertyStep field={field} />}
        {step === 'assess' && <AssessStep field={field} />}
        {step === 'decide' && <DecideStep field={field} />}
      </div>

      <SaveFooter
        stepIdx={stepIdx}
        go={go}
        leave={() => navigate(leaveTo)}
        draft={draft}
        isNew={isNew}
        gps={gps}
        update={update}
        catalog={catalog}
        onSaved={(s) => {
          clearDraft(customerId)
          setSaved(s)
        }}
        fallbackRef={ref}
      />
    </>
  )
}

type FieldProps = { label: string; options: string[]; value: string; onChange: (v: string) => void }
type F = (key: string) => FieldProps

// --- the six steps (prototype layout, Excel labels and options) ---------------------------

// The place shown in the Location box: worked out from the meeting's GPS. Display only: nothing typed
// here is ever saved. The server works the place out again from the saved GPS (see app/services/places.py).
function useShownPlace(point: GpsPoint | null): { state: 'idle' | 'loading' | 'ok' | 'none'; area: string | null } {
  const [shown, setShown] = useState<{ key: string; area: string | null } | null>(null)
  const lat = point?.latitude
  const lng = point?.longitude
  const key = lat === undefined ? '' : `${lat},${lng}`
  useEffect(() => {
    if (lat === undefined) return
    let cancelled = false
    api<{ area: string | null }>(`/geo/reverse?lat=${lat}&lng=${lng}`)
      .then((r) => !cancelled && setShown({ key, area: r.area }))
      .catch(() => !cancelled && setShown({ key, area: null }))
    return () => {
      cancelled = true
    }
  }, [lat, lng, key])
  if (lat === undefined) return { state: 'idle', area: null }
  if (shown?.key !== key) return { state: 'loading', area: null }
  return shown.area ? { state: 'ok', area: shown.area } : { state: 'none', area: null }
}

function LeadStep({ field, gps, leadLocation }: { field: F; gps: MeetingGps; leadLocation: string }) {
  const mobile = field('mobile')
  const loc = field('location')
  const place = useShownPlace(gps.point)
  const shownText =
    place.state === 'ok'
      ? (place.area ?? '')
      : place.state === 'loading'
        ? 'Finding the address…'
        : place.state === 'none'
          ? 'Address not found (your GPS position is saved)'
          : gps.state === 'locating'
            ? 'Getting your GPS…'
            : 'Not available (no GPS)'
  return (
    <>
      <Choice {...field('source_type')} />
      <div className="g2">
        <TextField id="f-srcname" {...field('source_name')} placeholder="CA / DSA name" />
        <TextField id="f-srccontact" {...field('source_contact')} placeholder="Mobile" type="tel" inputMode="tel" />
      </div>
      <TextField id="f-biz" {...field('business_name')} placeholder="Registered business name" />
      <div className="g2">
        <TextField id="f-prom" {...field('promoter')} placeholder="Full name" />
        <div>
          <label className="lbl" htmlFor="f-mob">
            {mobile.label}
          </label>
          <div className="box">
            <span className="mono" style={{ fontSize: 15, color: 'var(--muted)' }}>
              +91
            </span>
            <input
              id="f-mob"
              type="tel"
              inputMode="numeric"
              placeholder="10 digits"
              style={{ fontWeight: 500 }}
              value={mobile.value}
              onChange={(e) => mobile.onChange(e.target.value.replace(/[^\d+ ]/g, ''))}
            />
          </div>
        </div>
      </div>
      <div>
        <label className="lbl" htmlFor="f-loc" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>{loc.label}</span>
          <span className="tag good">from GPS</span>
        </label>
        <div style={{ display: 'flex', gap: 8 }}>
          {/* Read-only on purpose: the location always comes from the GPS and is never typed. */}
          <input
            className="fld"
            id="f-loc"
            readOnly
            value={shownText}
            aria-readonly="true"
            style={{
              flex: 1,
              minWidth: 0,
              background: '#EEF1F4',
              color: place.state === 'ok' ? 'var(--navy)' : 'var(--muted)',
              fontWeight: place.state === 'ok' ? 600 : 500,
            }}
          />
          <button
            type="button"
            aria-label="Get this meeting's GPS location again"
            onClick={gps.retry}
            style={{
              flex: 'none',
              height: 48,
              padding: '0 14px',
              borderRadius: 10,
              border: '1.5px solid var(--navy)',
              background: gps.point ? 'var(--navy)' : '#fff',
              color: gps.point ? '#fff' : 'var(--navy)',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 14,
              fontWeight: 700,
            }}
          >
            <IconGps /> GPS
          </button>
        </div>
        {leadLocation && (
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>
            Lead&apos;s location: <strong style={{ color: 'var(--ink)' }}>{leadLocation}</strong> (set from the first meeting)
          </div>
        )}
      </div>
    </>
  )
}

function BusinessStep({ field }: { field: F }) {
  const vintage = field('vintage_years')
  const loan = field('loan_required')
  const years = Number(vintage.value || 0)
  const stepBtn = {
    flex: 'none',
    width: 44,
    height: '100%',
    border: 'none',
    background: '#EEF1F4',
    color: 'var(--navy)',
    fontSize: 22,
    fontWeight: 600,
  } as const
  return (
    <>
      <Choice {...field('constitution')} />
      <TextField id="f-ind" {...field('industry')} placeholder="e.g. Food processing, Auto parts" />
      <div className="g2">
        <div>
          <label className="lbl" htmlFor="f-vint">
            {vintage.label}
          </label>
          <div className="box" style={{ padding: 0, overflow: 'hidden' }}>
            <button
              type="button"
              aria-label="Fewer years"
              style={stepBtn}
              onClick={() => vintage.onChange(String(Math.max(0, years - 1)))}
            >
              −
            </button>
            <input
              id="f-vint"
              className="mono"
              inputMode="decimal"
              placeholder="0"
              value={vintage.value}
              onChange={(e) => vintage.onChange(cleanNumber(e.target.value))}
              style={{ textAlign: 'center', fontWeight: 700 }}
            />
            <span className="unit" style={{ paddingRight: 6 }}>
              yrs
            </span>
            <button type="button" aria-label="More years" style={stepBtn} onClick={() => vintage.onChange(String(years + 1))}>
              +
            </button>
          </div>
        </div>
        <div>
          <label className="lbl" htmlFor="f-loan">
            {loan.label}
          </label>
          <MoneyBox id="f-loan" value={loan.value} onChange={loan.onChange} unit="Lakh" placeholder="0" />
        </div>
      </div>
      <Choice {...field('purpose')} />
      <Choice {...field('urgency')} kind="seg" />
      <Choice {...field('secured_unsecured')} kind="seg" />
    </>
  )
}

function MoneyStep({ field }: { field: F }) {
  const money = (key: string, id: string) => {
    const f = field(key)
    return <MoneyField id={id} label={f.label} value={f.value} onChange={f.onChange} />
  }
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div className="h">Financials</div>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)' }}>All amounts in ₹ lakh</div>
      </div>
      <div className="g2">
        {money('annual_turnover', 'm-turn')}
        {money('monthly_banking', 'm-bank')}
        {money('monthly_surplus', 'm-surp')}
        {money('existing_debt', 'm-debt')}
        {money('monthly_emi', 'm-emi')}
      </div>
      <div className="h" style={{ marginTop: 6 }}>
        Documents available
      </div>
      <div className="card">
        <TriRow {...field('gst_available')} />
        <TriRow {...field('itr_financials')} />
        <TriRow {...field('bank_statements')} />
      </div>
    </>
  )
}

function PropertyStep({ field }: { field: F }) {
  const prop = field('property_available')
  const value = field('property_value')
  const flags = ['overdue', 'bounces', 'settlement_write_off'].map(field)
  const n = flags.filter((f) => f.value === 'Yes').length
  return (
    <>
      <div className="h">Property</div>
      <div className="card">
        <TriRow {...prop} />
        {prop.value === 'Yes' && (
          <>
            <div className="row" style={{ borderBottom: '1px solid #EDF0F2' }}>
              <label className="t" htmlFor="f-propval" style={{ fontSize: 14, fontWeight: 600, color: '#3D4B59' }}>
                {value.label}
              </label>
              <MoneyBox
                id="f-propval"
                value={value.value}
                onChange={value.onChange}
                style={{ width: 200, height: 44, flex: 'none' }}
              />
            </div>
            <TriRow {...field('existing_mortgage')} />
          </>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 6 }}>
        <div className="h">Credit red flags</div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            padding: '4px 10px',
            borderRadius: 12,
            background: n ? '#FBE7DB' : '#E3F1E9',
            color: n ? 'var(--warn)' : 'var(--good)',
          }}
        >
          {n ? `${n} flag${n > 1 ? 's' : ''} marked` : 'No flags marked'}
        </div>
      </div>
      <div className="card">
        {flags.map((f) => (
          <TriRow key={f.label} {...f} risk />
        ))}
      </div>
      {/* No dropdown for Litigation/Dispute in the Excel, so it is typed. */}
      <TextField id="f-litig" {...field('litigation_dispute')} placeholder="Type details, or leave blank" />
    </>
  )
}

const SCORE: Record<string, number> = {
  Ready: 2,
  Partial: 1,
  Weak: 0,
  Strong: 2,
  Average: 1,
  Unknown: 0,
  'None known': 2,
  Manageable: 1,
  Significant: 0,
}

function AssessStep({ field }: { field: F }) {
  const docs = field('documents_readiness')
  const biz = field('business_quality')
  const bank = field('banking_quality')
  const risk = field('credit_risk')
  const grade = field('opportunity_grade')
  // The prototype's suggestion; shown only once all four inputs are chosen,
  // and the staff member still picks the grade.
  const inputs = [docs.value, biz.value, bank.value, risk.value]
  const total = inputs.every((x) => x in SCORE) ? inputs.reduce((a, x) => a + SCORE[x], 0) : null
  const suggested =
    total === null ? null : grade.options[total >= 7 ? 0 : total >= 5 ? 1 : total >= 3 ? 2 : 3] ?? null
  return (
    <>
      <Choice {...docs} kind="seg" />
      <Choice {...biz} kind="seg" />
      <Choice {...bank} kind="seg" />
      <Choice {...risk} kind="seg" />
      <div>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
          <div className="lbl" style={{ margin: 0 }}>
            {grade.label}
          </div>
          {suggested && (
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--good)' }}>Suggested: {suggested}</div>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 6 }}>
          {grade.options.map((o) => {
            const [letter, word] = o.split(/\s+–\s+/)
            return (
              <button
                key={o}
                type="button"
                className={`sg${grade.value === o ? ' on' : ''}`}
                aria-pressed={grade.value === o}
                onClick={() => grade.onChange(grade.value === o ? '' : o)}
                style={{
                  height: 62,
                  borderRadius: 12,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 1,
                }}
              >
                <span className="mono" style={{ fontSize: 22, fontWeight: 600 }}>
                  {letter}
                </span>
                <span style={{ fontSize: 12 }}>{word ?? ''}</span>
              </button>
            )
          })}
        </div>
      </div>
      <Choice {...field('likely_product')} kind="hs" />
      <TextField id="f-lender" {...field('potential_lender')} placeholder="Type or pick from lender list" />
    </>
  )
}

const REC_COLOR: Record<string, string> = { Proceed: '#1F6F4A', Hold: '#9A5B00', Reject: '#9F1D1D' }

function DecideStep({ field }: { field: F }) {
  const rec = field('sm_recommendation')
  const date = field('next_action_date')
  const comments = field('reason_comments')
  const today = new Date()
  const quick: [string, string][] = [
    ['Today', isoDate(today)],
    ['Tomorrow', isoDate(addDays(today, 1))],
    ['In 3 days', isoDate(addDays(today, 3))],
  ]
  const isQuick = quick.some(([, d]) => d === date.value)
  const [picking, setPicking] = useState(!!date.value && !isQuick)
  return (
    <>
      <div>
        <div className="lbl">{rec.label}</div>
        <div className="seg" style={{ gap: 8 }}>
          {rec.options.map((o) => {
            const on = rec.value === o
            const c = REC_COLOR[o] ?? 'var(--navy)'
            return (
              <button
                key={o}
                type="button"
                className="sg"
                aria-pressed={on}
                onClick={() => rec.onChange(on ? '' : o)}
                style={{
                  height: 54,
                  borderRadius: 12,
                  border: `2px solid ${on ? c : 'var(--line)'}`,
                  background: on ? c : '#fff',
                  color: on ? '#fff' : c,
                  fontSize: 16,
                  fontWeight: 700,
                }}
              >
                {o}
              </button>
            )
          })}
        </div>
      </div>
      {/* No dropdown for Status in the Excel, so it is typed. */}
      <TextField id="f-status" {...field('status')} placeholder="Type the status" />
      <Choice {...field('next_action')} kind="hs" />
      <div>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
          <div className="lbl" style={{ margin: 0 }}>
            {date.label}
          </div>
          <div className="mono" style={{ fontSize: 13, fontWeight: 600, color: 'var(--navy)' }}>
            {date.value ? shortDate(date.value) : picking ? 'Choose…' : ''}
          </div>
        </div>
        <div className="seg">
          {quick.map(([label, d]) => (
            <button
              key={label}
              type="button"
              className={`sg${date.value === d && !picking ? ' on' : ''}`}
              style={{ fontSize: 13, height: 42 }}
              onClick={() => {
                setPicking(false)
                date.onChange(date.value === d ? '' : d)
              }}
            >
              {label}
            </button>
          ))}
          <button
            type="button"
            className={`sg${picking ? ' on' : ''}`}
            style={{ fontSize: 13, height: 42 }}
            onClick={() => setPicking(true)}
          >
            Pick date
          </button>
        </div>
        {picking && (
          <input
            className="fld"
            type="date"
            aria-label={date.label}
            value={date.value}
            onChange={(e) => date.onChange(e.target.value)}
            style={{ marginTop: 8 }}
          />
        )}
      </div>
      <CommentsField {...comments} />
    </>
  )
}

// Voice typing via the browser's speech recognition where it exists (Chrome on
// Android). Note: Chrome sends the audio to Google's speech service.
type SpeechRec = {
  lang: string
  interimResults: boolean
  onresult: (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void
  onend: () => void
  onerror: () => void
  start: () => void
  stop: () => void
}

function CommentsField({ label, value, onChange }: FieldProps) {
  const [listening, setListening] = useState<SpeechRec | null>(null)
  const Rec = (window as unknown as { SpeechRecognition?: new () => SpeechRec; webkitSpeechRecognition?: new () => SpeechRec })
  const Ctor = Rec.SpeechRecognition ?? Rec.webkitSpeechRecognition

  function dictate() {
    if (!Ctor) return
    if (listening) return listening.stop()
    const r = new Ctor()
    r.lang = 'en-IN'
    r.interimResults = false
    r.onresult = (e) => {
      const text = Array.from(e.results)
        .map((res) => res[0].transcript)
        .join(' ')
      onChange([value, text].filter(Boolean).join(value ? ' ' : ''))
    }
    r.onend = () => setListening(null)
    r.onerror = () => setListening(null)
    r.start()
    setListening(r)
  }

  return (
    <div>
      <label className="lbl" htmlFor="f-comments">
        {label}
      </label>
      <div style={{ position: 'relative' }}>
        <textarea
          className="fld"
          id="f-comments"
          placeholder={Ctor ? 'Why this grade and recommendation? Tap the mic to speak.' : 'Why this grade and recommendation?'}
          style={{ height: 96, resize: 'none', padding: Ctor ? '12px 60px 12px 14px' : '12px 14px' }}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        {Ctor && (
          <button
            type="button"
            aria-label={listening ? 'Stop dictation' : 'Dictate comments'}
            onClick={dictate}
            style={{
              position: 'absolute',
              right: 8,
              bottom: 10,
              width: 44,
              height: 44,
              borderRadius: 22,
              border: 'none',
              background: listening ? 'var(--amber)' : 'var(--navy)',
              color: listening ? 'var(--navy)' : '#fff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <IconMic />
          </button>
        )}
      </div>
    </div>
  )
}

// --- GPS ------------------------------------------------------------------------------------

type MeetingGps = {
  state: 'locating' | 'ok' | 'error' | 'skipped'
  point: GpsPoint | null
  error: GpsErrorCode | null
  retry: () => void
}

// Captured automatically when the meeting opens; the form never waits for it.
function useMeetingGps(draft: MeetingDraft, update: (d: MeetingDraft) => void): MeetingGps {
  const [attempt, setAttempt] = useState(draft.gpsStart || draft.gpsUnavailableReason ? -1 : 0)
  const [state, setState] = useState<MeetingGps['state']>(
    draft.gpsStart ? 'ok' : draft.gpsUnavailableReason ? 'skipped' : 'locating',
  )
  const [error, setError] = useState<GpsErrorCode | null>(null)

  useEffect(() => {
    if (attempt < 0) return
    let cancelled = false
    setState('locating')
    captureLocation()
      .then((p) => {
        if (cancelled) return
        setState('ok')
        update({ ...draftRef.current, gpsStart: p, gpsUnavailableReason: null })
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof GpsError ? e.code : 'unavailable')
        setState('error')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])

  draftRef.current = draft
  return { state, point: draft.gpsStart, error, retry: () => setAttempt((a) => Math.max(1, a + 1)) }
}
// Latest draft for async GPS callbacks (avoids overwriting edits made while locating).
const draftRef: { current: MeetingDraft } = { current: null as unknown as MeetingDraft }

function GpsStatus({ gps }: { gps: MeetingGps }) {
  const base = { flex: 'none', whiteSpace: 'nowrap', fontSize: 12, fontWeight: 700, padding: '4px 10px', borderRadius: 12, border: 'none' } as const
  if (gps.state === 'ok' && gps.point)
    return (
      <span style={{ ...base, background: '#E3F1E9', color: 'var(--good)' }}>GPS ✓ ±{Math.round(gps.point.accuracy_m)} m</span>
    )
  if (gps.state === 'locating') return <span style={{ ...base, background: '#E7ECF1', color: 'var(--navy)' }}>Locating…</span>
  return (
    <button style={{ ...base, background: '#FBE7DB', color: 'var(--warn)' }} onClick={gps.retry}>
      No GPS · Retry
    </button>
  )
}

// --- footer: Back / Next / Save, with GPS-reason and duplicate sheets --------------------------

const NO_GPS_REASONS = ['Location permission denied', 'GPS switched off', 'No GPS signal at this place', 'Other']
const REASON_FOR_ERROR: Partial<Record<GpsErrorCode, string>> = {
  denied: 'Location permission denied',
  unavailable: 'GPS switched off',
  timeout: 'No GPS signal at this place',
}

function SaveFooter({
  stepIdx,
  go,
  leave,
  draft,
  isNew,
  gps,
  update,
  catalog,
  onSaved,
  fallbackRef,
}: {
  stepIdx: number
  go: (i: number) => void
  leave: () => void
  draft: MeetingDraft
  isNew: boolean
  gps: MeetingGps
  update: (d: MeetingDraft) => void
  catalog: FieldCatalog
  onSaved: (s: Saved) => void
  fallbackRef: string
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [askReason, setAskReason] = useState(false)
  const [matches, setMatches] = useState<DuplicateMatch[] | null>(null)
  const last = stepIdx === STEPS.length - 1

  async function save(dup?: { choice: 'overwrite' | 'create_new'; id?: string }, reasonOverride?: string) {
    const reason = reasonOverride ?? draft.gpsUnavailableReason
    if (!draft.gpsStart && !reason) {
      if (gps.state === 'locating') {
        setError('Still getting the GPS location. Wait a few seconds and tap Save again.')
        return
      }
      setAskReason(true)
      return
    }
    setError(null)
    setBusy('Saving…')
    const gpsEnd = draft.gpsStart ? await captureLocation(6_000).catch(() => null) : null
    const meeting = {
      id: draft.id,
      started_at: draft.startedAt,
      ended_at: new Date().toISOString(),
      gps_start: draft.gpsStart,
      gps_end: gpsEnd,
      gps_unavailable_reason: draft.gpsStart ? null : reason,
      values: draft.values,
    }
    try {
      if (isNew) {
        const r = await post<{ customer_id: string; meeting: Meeting }>('/leads/new', {
          meeting,
          on_duplicate: dup?.choice ?? 'ask',
          overwrite_customer_id: dup?.id,
        })
        const c = await api<CustomerDetail>(`/customers/${r.customer_id}`).catch(() => null)
        onSaved({ customerId: r.customer_id, meeting: r.meeting, leadRef: c?.lead_ref ?? '' })
      } else {
        const m = await post<Meeting>(`/customers/${draft.customerId}/meetings`, meeting)
        onSaved({ customerId: draft.customerId, meeting: m, leadRef: fallbackRef })
      }
    } catch (e) {
      if (!(e instanceof ApiError)) throw e
      const d = e.detail as
        | { code?: string; message?: string; errors?: Record<string, string>; matches?: DuplicateMatch[] }
        | { msg: string }[]
        | null
      if (e.status === 0) setError('No connection. The meeting is kept on this phone — tap Save again when you have signal.')
      else if (Array.isArray(d)) setError(d[0]?.msg?.replace(/^Value error, /, '') ?? 'Could not save')
      else if (d?.code === 'DUPLICATE_OWN' && d.matches) setMatches(d.matches)
      else if (d?.code === 'INVALID_VALUES' && d.errors) {
        const label = (k: string) => catalog.fields.find((f) => f.key === k)?.label ?? k
        setError(Object.entries(d.errors).map(([k, msg]) => `${label(k)}: ${msg}`).join(' · '))
      } else setError(d?.message ?? e.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      {error && (
        <div style={{ padding: '0 16px 10px', background: 'var(--ground)' }}>
          <div className="err" role="alert">
            {error}
          </div>
        </div>
      )}
      <div className="foot">
        <div className="inner" style={{ flexDirection: 'column', gap: 8 }}>
          {/* Nothing more to enter? Save from any step; no need to walk through the remaining ones. */}
          {!last && (
            <button type="button" className="save-now" disabled={!!busy} onClick={() => save()}>
              {busy ?? 'Nothing more to add? Save meeting now'}
            </button>
          )}
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn ghost" style={{ flex: 'none', width: 104 }} onClick={() => (stepIdx > 0 ? go(stepIdx - 1) : leave())}>
              {stepIdx > 0 ? 'Back' : 'Cancel'}
            </button>
            <button
              className="btn primary"
              style={{ flex: 1 }}
              disabled={!!busy}
              onClick={() => (last ? save() : go(stepIdx + 1))}
            >
              {busy && last ? busy : last ? 'Save meeting' : `Next · ${TABS[stepIdx + 1]}`} {!busy && <IconArrow />}
            </button>
          </div>
        </div>
      </div>

      {askReason && (
        <ReasonSheet
          initial={gps.error ? (REASON_FOR_ERROR[gps.error] ?? '') : ''}
          errorText={gps.error ? GPS_ERROR_TEXT[gps.error] : null}
          onRetry={() => {
            setAskReason(false)
            gps.retry()
          }}
          onCancel={() => setAskReason(false)}
          onConfirm={(reason) => {
            setAskReason(false)
            update({ ...draft, gpsUnavailableReason: reason })
            void save(undefined, reason)
          }}
        />
      )}

      {matches && (
        <DuplicateSheet
          matches={matches}
          busy={!!busy}
          onChoose={(choice, id) => {
            setMatches(null)
            void save({ choice, id })
          }}
          onCancel={() => setMatches(null)}
        />
      )}
    </>
  )
}

function ReasonSheet({
  initial,
  errorText,
  onRetry,
  onCancel,
  onConfirm,
}: {
  initial: string
  errorText: string | null
  onRetry: () => void
  onCancel: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState(initial)
  const [other, setOther] = useState('')
  const final = reason === 'Other' ? other.trim() : reason
  return (
    <div className="sheet-bg" role="dialog" aria-modal="true" aria-labelledby="gps-title">
      <div className="sheet">
        <div className="sheet-title" id="gps-title">
          GPS location not captured
        </div>
        {errorText && <div className="muted" style={{ fontSize: 14 }}>{errorText}</div>}
        <div className="lbl" style={{ margin: 0 }}>
          Why is GPS not available? The meeting will be marked “No GPS”.
        </div>
        <div className="wrap">
          {NO_GPS_REASONS.map((r) => (
            <button key={r} type="button" className={`chip${reason === r ? ' on' : ''}`} onClick={() => setReason(r)}>
              {r}
            </button>
          ))}
        </div>
        {reason === 'Other' && (
          <input className="fld" placeholder="Type the reason" maxLength={300} value={other} onChange={(e) => setOther(e.target.value)} />
        )}
        <button className="btn primary" disabled={!final} onClick={() => onConfirm(final)}>
          Save without GPS
        </button>
        <button className="btn ghost" onClick={onRetry}>
          Try GPS again
        </button>
        <button className="btn ghost" style={{ border: 'none' }} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}

function DuplicateSheet({
  matches,
  busy,
  onChoose,
  onCancel,
}: {
  matches: DuplicateMatch[]
  busy: boolean
  onChoose: (choice: 'overwrite' | 'create_new', id?: string) => void
  onCancel: () => void
}) {
  return (
    <div className="sheet-bg" role="dialog" aria-modal="true" aria-labelledby="dup-title">
      <div className="sheet">
        <div className="sheet-title" id="dup-title">
          This customer already exists
        </div>
        <div className="muted" style={{ fontSize: 14 }}>
          You already have a customer with this mobile number.
        </div>
        {matches.map((m) => (
          <div key={m.id} className="card" style={{ padding: '4px 14px 14px' }}>
            {[
              ['Business', m.business_name],
              ['Promoter', m.promoter],
              ['Loan type', m.purpose || m.likely_product],
              ['Loan required', m.loan_required ? `₹${m.loan_required} L` : null],
              ['Mobile', m.mobile],
              ['Last meeting', relativeDay(m.last_meeting_at)],
            ].map(([k, val]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '10px 0', borderBottom: '1px solid #EDF0F2' }}>
                <div style={{ fontSize: 14, color: 'var(--muted)', fontWeight: 500 }}>{k}</div>
                <div style={{ fontSize: 14, color: 'var(--navy)', fontWeight: 700, textAlign: 'right' }}>{val || '—'}</div>
              </div>
            ))}
            <button className="btn ghost" style={{ width: '100%', marginTop: 12 }} disabled={busy} onClick={() => onChoose('overwrite', m.id)}>
              Overwrite existing
            </button>
          </div>
        ))}
        <button className="btn primary" disabled={busy} onClick={() => onChoose('create_new')}>
          Create new
        </button>
        <button className="btn ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}

// --- after saving (prototype's "Lead submitted" screen) ---------------------------------------

function DoneScreen({ saved, values }: { saved: Saved; values: Record<string, string> }) {
  const navigate = useNavigate()
  const { meeting } = saved
  const rows = useMemo(
    () =>
      [
        ['Business', values.business_name || values.promoter],
        ['Need', [values.purpose, values.secured_unsecured].filter(Boolean).join(' · ')],
        ['Grade', values.opportunity_grade],
        ['Recommendation', [values.sm_recommendation, values.status].filter(Boolean).join(' · ')],
        [
          'Next action',
          [values.next_action, values.next_action_date ? shortDate(values.next_action_date) : null].filter(Boolean).join(' · '),
        ],
        ['GPS', meeting.gps_start ? `Captured ±${Math.round(meeting.gps_start.accuracy_m)} m` : `No GPS — ${meeting.gps_unavailable_reason}`],
      ] as [string, string | undefined][],
    [values, meeting],
  )
  return (
    <div style={{ flex: '1 1 auto', minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', padding: '56px 20px 20px', gap: 22 }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, textAlign: 'center' }}>
        <div
          style={{
            width: 76,
            height: 76,
            borderRadius: 38,
            background: 'var(--good)',
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <IconCheck size={40} width={2.6} />
        </div>
        <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--navy)' }}>
          {meeting.sequence_no === 1 ? 'Lead saved' : 'Meeting saved'}
        </div>
        <div className="mono" style={{ fontSize: 14, color: 'var(--muted)' }}>
          {saved.leadRef} · Meeting #{meeting.sequence_no} · Zoho sync pending
        </div>
      </div>
      <div className="card" style={{ padding: '4px 16px' }}>
        {rows.map(([k, val]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '12px 0', borderBottom: '1px solid #EDF0F2' }}>
            <div style={{ fontSize: 14, color: 'var(--muted)', fontWeight: 500 }}>{k}</div>
            <div style={{ fontSize: 14, color: 'var(--navy)', fontWeight: 700, textAlign: 'right' }}>{val || '—'}</div>
          </div>
        ))}
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <button className="btn primary" style={{ height: 56, fontSize: 17 }} onClick={() => navigate(`/customers/${saved.customerId}`)}>
          Open lead
        </button>
        <button className="btn ghost" onClick={() => navigate('/')}>
          Back to my leads
        </button>
      </div>
    </div>
  )
}

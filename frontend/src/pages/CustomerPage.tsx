// Customer / lead overview: current progress by step and full meeting history.
// Not in the prototype, so it is built from the prototype's components.

import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError, post, type CustomerDetail } from '../api'
import { IconArrow, IconBack, IconCheck } from '../components/icons'
import MeetingHistory from '../components/MeetingHistory'
import { displayName, relativeDay } from '../format'
import { friendlyZohoError } from '../zohoErrors'
import { loadDraft } from '../meetingDraft'

const STATUS_LABEL: Record<CustomerDetail['conversion_status'], string> = {
  NOT_CONVERTED: 'Not Converted',
  CONVERTING: 'Converting…',
  CONVERTED: 'Converted Lead',
  CONVERSION_FAILED: 'Conversion failed',
}
const SLOW_AFTER_MS = 20_000 // a normal conversion finishes in a few seconds
const TABS = ['Lead', 'Business', 'Money', 'Property', 'Assess', 'Decide']

export default function CustomerPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [c, setC] = useState<CustomerDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showCount, setShowCount] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [convertError, setConvertError] = useState<string | null>(null)

  // "Retry conversion" after a failure: no new form, the details confirmed earlier are kept.
  async function retryConversion() {
    setRetrying(true)
    setConvertError(null)
    try {
      setC(await post<CustomerDetail>(`/customers/${id}/convert`))
    } catch (e) {
      setConvertError(
        e instanceof ApiError && e.status === 0
          ? 'No connection. Converting to a Lead needs the internet. Try again when you have signal.'
          : 'Could not start the conversion. Try again.',
      )
    } finally {
      setRetrying(false)
    }
  }

  useEffect(() => {
    api<CustomerDetail>(`/customers/${id}`)
      .then(setC)
      .catch((e) => setError(e instanceof ApiError && e.status === 404 ? 'Lead not found.' : 'Could not load this lead.'))
  }, [id])

  // While Zoho is creating the Lead, check again every few seconds so the screen updates by itself.
  const converting_ = c?.conversion_status === 'CONVERTING'
  // A normal conversion takes seconds. After SLOW_AFTER_MS we tell the user it is taking longer.
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    if (!converting_) return
    const t = setTimeout(() => setSlow(true), SLOW_AFTER_MS)
    return () => {
      clearTimeout(t)
      setSlow(false)
    }
  }, [converting_])
  useEffect(() => {
    if (!converting_) return
    const t = setInterval(() => {
      api<CustomerDetail>(`/customers/${id}?quiet=true`).then(setC).catch(() => undefined)
    }, 3000)
    return () => clearInterval(t)
  }, [converting_, id])

  const converted = c?.conversion_status === 'CONVERTED'
  const back = () => navigate(converted ? '/?tab=converted' : '/')
  const hasDraft = loadDraft(id) !== null

  return (
    <>
      <div className="hdr" style={{ padding: '10px 12px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button className="icon-btn" aria-label="Back to my leads" onClick={back}>
            <IconBack />
          </button>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 17, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {c ? displayName(c) : 'Lead'}
            </div>
            <div className="mono" style={{ fontSize: 12, color: '#B9C6D3' }}>
              {c ? `${c.lead_ref} · ${STATUS_LABEL[c.conversion_status]}` : ''}
            </div>
          </div>
        </div>
      </div>

      <div className="scroll">
        {error && <div className="err">{error}</div>}
        {!c && !error && <div className="empty">Loading…</div>}
        {c && (
          <>
            <div className="card" style={{ padding: '14px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              {(c.promoter || c.mobile) && (
                <div style={{ fontSize: 14, color: 'var(--muted)' }}>
                  {[c.business_name ? c.promoter : null, c.mobile ? `+91 ${c.mobile}` : null].filter(Boolean).join(' · ')}
                </div>
              )}
              {c.zoho_lead_id && (
                <div className="mono" style={{ fontSize: 13, color: 'var(--good)', fontWeight: 600 }}>
                  Zoho Lead ID: {c.zoho_lead_id}
                </div>
              )}
              {/* Percentage by default; tap for "32 / 41 completed". */}
              <button className="progress-btn" onClick={() => setShowCount((s) => !s)} aria-label={`${c.progress.filled} of ${c.progress.total} fields completed`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, fontWeight: 600 }}>
                  <span>Fields collected</span>
                  <span className="mono" style={{ color: 'var(--navy)' }}>
                    {showCount ? `${c.progress.filled} / ${c.progress.total} completed` : `${c.progress.percent}%`}
                  </span>
                </div>
                <div className="bar">
                  <span style={{ width: `${c.progress.percent}%` }} />
                </div>
              </button>
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                {c.meeting_count} meeting{c.meeting_count === 1 ? '' : 's'} · Last: {relativeDay(c.last_meeting_at)}
              </div>
            </div>

            {convertError && <div className="err">{convertError}</div>}
            <ConversionPanel
              c={c}
              slow={slow}
              retrying={retrying}
              onConvert={() => navigate(`/customers/${id}/convert`)}
              onRetry={retryConversion}
            />

            <div className="card">
              {c.sections.map((s, i) => {
                const done = s.filled === s.total
                return (
                  <div key={s.key} className="row">
                    <span
                      style={{
                        flex: 'none',
                        width: 22,
                        height: 22,
                        borderRadius: 11,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 11,
                        fontWeight: 700,
                        background: done ? '#2F8F62' : '#E7ECF1',
                        color: done ? '#fff' : 'var(--navy)',
                      }}
                    >
                      {done ? <IconCheck size={12} width={3.2} /> : i + 1}
                    </span>
                    <div className="t">
                      {TABS[i]} <span className="muted" style={{ fontSize: 13 }}>· {s.label}</span>
                    </div>
                    <div className="mono" style={{ fontSize: 14, fontWeight: 600, color: done ? 'var(--good)' : 'var(--muted)' }}>
                      {s.filled}/{s.total}
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="h" style={{ marginTop: 4 }}>
              Meeting history
            </div>
            <MeetingHistory customerId={id} reloadKey={`${c.meeting_count}:${c.conversion_status}`} />
          </>
        )}
      </div>

      <div className="foot">
        <div className="inner">
          <button className="btn ghost" style={{ flex: 'none', width: 104 }} onClick={back}>
            Back
          </button>
          <button
            className="btn primary"
            style={{ flex: 1 }}
            disabled={!c}
            onClick={() => navigate(`/customers/${id}/meeting`)}
          >
            {hasDraft ? 'Continue meeting' : converted ? 'New meeting' : 'Start meeting'} <IconArrow />
          </button>
        </div>
      </div>
    </>
  )
}

// Conversion state on the lead screen: the action, or where the conversion is.
function ConversionPanel({
  c,
  slow: slowLocal,
  retrying,
  onConvert,
  onRetry,
}: {
  c: CustomerDetail
  slow: boolean
  retrying: boolean
  onConvert: () => void
  onRetry: () => void
}) {
  if (c.conversion_status === 'NOT_CONVERTED')
    return (
      <button className="btn ghost" style={{ width: '100%' }} onClick={onConvert}>
        Convert to Lead
      </button>
    )
  if (c.conversion_status === 'CONVERTING') {
    // Normally a few seconds. If it is taking longer (or Zoho already failed once and is retrying),
    // say so, and tell the user it is safe to close the app and check back later.
    const slow = c.lead_sync_attempts > 0 || slowLocal
    return (
      <div className="card" style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: 8 }} role="status">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="spinner-ring" aria-hidden />
          <div style={{ fontSize: 15, fontWeight: 700, color: slow ? 'var(--warn)' : '#8a5a00' }}>
            {slow ? 'Still converting to Lead…' : 'Converting to Lead…'}
          </div>
        </div>
        {slow ? (
          <div style={{ fontSize: 13, color: 'var(--ink)' }}>
            This is taking longer than usual and may take <strong>up to 5 minutes</strong>. You can safely{' '}
            <strong>close the app and check again after 5 minutes</strong>. It will finish on its own and the lead will
            then move to Converted Leads.
          </div>
        ) : (
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>Sending to Zoho CRM. This usually takes a few seconds.</div>
        )}
        {c.lead_sync_status === 'FAILED' && c.lead_sync_error && (
          <div style={{ fontSize: 12, color: 'var(--warn)', fontWeight: 600 }}>
            {friendlyZohoError(c.lead_sync_error)}
          </div>
        )}
      </div>
    )
  }
  if (c.conversion_status === 'CONVERSION_FAILED')
    return (
      <div className="card" style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--warn)' }}>Conversion failed</div>
        {c.lead_sync_error && <div style={{ fontSize: 13, color: 'var(--muted)' }}>{friendlyZohoError(c.lead_sync_error)}</div>}
        <button className="btn ghost" style={{ width: '100%' }} disabled={retrying} onClick={onRetry}>
          {retrying ? 'Retrying…' : 'Retry conversion'}
        </button>
      </div>
    )
  return null
}

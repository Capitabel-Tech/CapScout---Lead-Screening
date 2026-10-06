import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type CustomerCard, type CustomerList, type HomeSummary } from '../api'
import { useAuth } from '../auth'
import { IconCal, IconCloud, IconPlus, IconPower, IconSearch } from '../components/icons'
import { useFieldCatalog } from '../fields'
import { daysFromToday, displayName, nextActionWhen } from '../format'

const ROLE: Record<string, string> = { FIELD_STAFF: 'Sales Manager', SUPERVISOR: 'Supervisor', ADMIN: 'Admin' }
const GRADE_COLORS: Record<string, [string, string]> = {
  A: ['#1F6F4A', '#fff'],
  B: ['#12263A', '#fff'],
  C: ['#E7ECF1', '#12263A'],
  D: ['#9F1D1D', '#fff'],
}

type Tab = 'not_converted' | 'converted'

export default function Home() {
  const { staff, logout } = useAuth()
  const navigate = useNavigate()
  const catalog = useFieldCatalog()
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'converted' ? 'converted' : 'not_converted'
  const [filter, setFilter] = useState('All')
  const [query, setQuery] = useState('')
  const [list, setList] = useState<CustomerList | null>(null)
  const [summary, setSummary] = useState<HomeSummary | null>(null)
  const [tick, setTick] = useState(0) // bumped to re-check while Zoho is still working

  useEffect(() => {
    api<HomeSummary>('/customers/-/summary').then(setSummary).catch(() => undefined)
  }, [tick])

  useEffect(() => {
    let cancelled = false
    const t = setTimeout(() => {
      const q = new URLSearchParams({ tab, limit: '200' })
      if (query.trim()) q.set('q', query.trim())
      api<CustomerList>(`/customers?${q}`)
        .then((d) => !cancelled && setList(d))
        .catch(() => undefined)
    }, 200)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [tab, query, tick])

  // While a lead is "Converting…" or a meeting is still going to Zoho, re-check every few seconds.
  const busy =
    (list?.items.some((c) => c.conversion_status === 'CONVERTING') ?? false) || (summary?.sync_pending ?? 0) > 0
  useEffect(() => {
    if (!busy) return
    const t = setInterval(() => setTick((n) => n + 1), 4000)
    return () => clearInterval(t)
  }, [busy])

  // One chip per Next Action option in the Excel (all 8), after "All".
  const filters = useMemo(
    () => ['All', ...(catalog?.fields.find((f) => f.key === 'next_action')?.options ?? [])],
    [catalog],
  )

  const items = list?.items ?? []
  const dated = items.filter((c) => c.next_action_date)
  const followUpsToday = dated.filter((c) => daysFromToday(c.next_action_date!) === 0).length
  const overdue = dated.filter((c) => daysFromToday(c.next_action_date!) < 0).length
  const shown = items.filter((c) => filter === 'All' || c.next_action === filter)

  const syncPill =
    summary && summary.sync_failed > 0
      ? { cls: 'failed', text: `${summary.sync_failed} failed` }
      : summary && summary.sync_pending > 0
        ? { cls: 'pending', text: `${summary.sync_pending} pending` }
        : { cls: '', text: 'Synced' }

  const tile = (n: number | string, label: string, hi = false) => (
    <div
      style={{
        background: hi ? 'var(--amber)' : '#1D3A52',
        color: hi ? 'var(--navy)' : '#fff',
        borderRadius: 12,
        padding: '10px 12px',
      }}
    >
      <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>
        {n}
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: hi ? undefined : '#CAD5E0' }}>{label}</div>
    </div>
  )

  return (
    <>
      <div className="hdr" style={{ padding: '14px 16px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div className="brand">CapScout - Lead Screening</div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div className="hdr-sub">
              {staff?.full_name} · {ROLE[staff?.role ?? ''] ?? ''}
            </div>
            <div style={{ fontSize: 24, fontWeight: 700, marginTop: 2 }}>My leads</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div className={`hdr-pill ${syncPill.cls}`} title="Zoho sync">
              <IconCloud /> {syncPill.text}
            </div>
            <button
              className="icon-btn"
              style={{ width: 36, height: 36, color: '#B9C6D3' }}
              aria-label="Sign out"
              onClick={() => confirm('Sign out?') && logout()}
            >
              <IconPower />
            </button>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 8 }}>
          {tile(followUpsToday, 'Follow-ups today', true)}
          {tile(list?.total ?? '–', tab === 'converted' ? 'Converted leads' : 'Open leads')}
          {tile(overdue, 'Overdue')}
        </div>
      </div>

      <div style={{ padding: '14px 16px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className="box" style={{ color: 'var(--muted)' }}>
          <IconSearch />
          <label className="sr" htmlFor="h-search">
            Search leads
          </label>
          <input
            id="h-search"
            type="search"
            placeholder="Business, promoter or mobile"
            style={{ fontWeight: 500 }}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="seg" role="tablist" aria-label="Lead status">
          <button
            role="tab"
            aria-selected={tab === 'not_converted'}
            className={`sg${tab === 'not_converted' ? ' on' : ''}`}
            onClick={() => setParams({})}
          >
            Not Converted ({summary?.not_converted ?? '–'})
          </button>
          <button
            role="tab"
            aria-selected={tab === 'converted'}
            className={`sg${tab === 'converted' ? ' on' : ''}`}
            onClick={() => setParams({ tab: 'converted' })}
          >
            Converted Leads ({summary?.converted ?? '–'})
          </button>
        </div>
        <div className="hs">
          {filters.map((f) => (
            <button key={f} className={`chip${filter === f ? ' on' : ''}`} aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="scroll" style={{ paddingTop: 12, gap: 10 }}>
        {list === null ? (
          <div className="empty">Loading…</div>
        ) : shown.length === 0 ? (
          <div className="empty">{items.length === 0 ? 'No leads yet' : 'No leads in this filter'}</div>
        ) : (
          <div className="lead-grid">
            {shown.map((c) => (
              <LeadCard key={c.id} c={c} />
            ))}
          </div>
        )}
      </div>

      <div className="foot">
        <div className="inner">
          <button
            className="btn primary"
            style={{ width: '100%', height: 56, fontSize: 17 }}
            onClick={() => navigate('/new')}
          >
            <IconPlus /> New lead
          </button>
        </div>
      </div>
    </>
  )
}

function LeadCard({ c }: { c: CustomerCard }) {
  const grade = c.opportunity_grade?.[0]
  const sub = [c.business_name ? c.promoter : null, c.location].filter(Boolean).join(' · ')
  const need = [c.loan_required ? `₹${c.loan_required} L` : null, c.purpose].filter(Boolean)
  const when = c.next_action_date ? nextActionWhen(c.next_action_date) : null
  const next = [c.next_action, when?.text].filter(Boolean).join(' · ')
  return (
    <Link to={`/customers/${c.id}`} className="lead">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--navy)' }}>{displayName(c)}</div>
          {sub && <div style={{ fontSize: 13, color: 'var(--muted)' }}>{sub}</div>}
        </div>
        {grade && GRADE_COLORS[grade] && (
          <div className="mono grade" style={{ background: GRADE_COLORS[grade][0], color: GRADE_COLORS[grade][1] }}>
            {grade}
          </div>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', gap: 8 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>
          {need.length ? (
            <>
              {c.loan_required && <span className="mono">₹{c.loan_required} L</span>}
              {c.loan_required && c.purpose && ' · '}
              {c.purpose}
            </>
          ) : (
            <span className="muted" style={{ fontWeight: 500 }}>
              {c.lead_ref}
            </span>
          )}
        </div>
        {c.conversion_status === 'CONVERTING' ? (
          <div className="status-pill" style={{ background: '#FDF1DC', color: '#8a5a00' }}>
            <span className="spinner-ring sm" aria-hidden />
            Converting…
          </div>
        ) : c.conversion_status === 'CONVERSION_FAILED' ? (
          <div className="status-pill" style={{ background: '#FBE7DB', color: 'var(--warn)' }}>Conversion failed</div>
        ) : (
          c.status && <div className="status-pill">{c.status}</div>
        )}
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 13,
          fontWeight: 600,
          color: !next ? 'var(--muted)' : when?.late ? 'var(--warn)' : 'var(--good)',
        }}
      >
        <IconCal /> {next || 'No next action set'}
      </div>
    </Link>
  )
}

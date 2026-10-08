import { formatINR } from '../format'
import { useEffect, useState } from 'react'
import { api, post, type Meeting, type SyncStatus } from '../api'
import { fieldLabel, useFieldCatalog } from '../fields'
import { shortDate } from '../format'
import { mapsUrl } from '../gps'
import { friendlyZohoError } from '../zohoErrors'

const SYNC: Record<SyncStatus, { label: string; cls: string }> = {
  NOT_QUEUED: { label: 'Not sent', cls: '' },
  PENDING: { label: 'Sending…', cls: 'warn' },
  SYNCING: { label: 'Sending…', cls: 'warn' },
  SYNCED: { label: 'Synced ✓', cls: 'good' },
  FAILED: { label: 'Not sent ✕', cls: 'bad' },
}

export default function MeetingHistory({ customerId, reloadKey }: { customerId: string; reloadKey?: unknown }) {
  const catalog = useFieldCatalog()
  // Rupee amounts are shown with commas (12,34,567).
  const show = (key: string, value: string) => (catalog?.fields.find((f) => f.key === key)?.unit === '₹' ? `₹${formatINR(value)}` : value)
  const [items, setItems] = useState<Meeting[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [retrying, setRetrying] = useState<string | null>(null)

  async function retry(m: Meeting) {
    setRetrying(m.id)
    try {
      const updated = await post<Meeting>(`/customers/${customerId}/meetings/${m.id}/retry-sync`)
      setItems((list) => list?.map((x) => (x.id === m.id ? updated : x)) ?? list)
    } catch {
      // the status line keeps showing the last known state
    } finally {
      setRetrying(null)
    }
  }

  useEffect(() => {
    api<{ items: Meeting[] }>(`/customers/${customerId}/meetings`)
      .then((d) => {
        setItems(d.items)
        setOpen(d.items[0]?.id ?? null)
      })
      .catch(() => setItems([]))
  }, [customerId, reloadKey])

  // Keep the "Zoho: pending" tags fresh until every meeting has been sent.
  const syncingNow = items?.some((m) => m.zoho_sync_status === 'PENDING' || m.zoho_sync_status === 'SYNCING') ?? false
  useEffect(() => {
    if (!syncingNow) return
    const t = setInterval(() => {
      api<{ items: Meeting[] }>(`/customers/${customerId}/meetings`)
        .then((d) => setItems(d.items))
        .catch(() => undefined)
    }, 3000)
    return () => clearInterval(t)
  }, [syncingNow, customerId])

  if (!items) return <div className="empty">Loading…</div>
  if (items.length === 0) return <div className="empty">No meetings yet</div>

  const showsPlace = items.some((m) => m.place)
  return (
    <>
      {items.map((m) => {
        const added = m.changes.filter((c) => c.type === 'NEW').length
        const updated = m.changes.filter((c) => c.type === 'UPDATED').length
        const cleared = m.changes.filter((c) => c.type === 'CLEARED').length
        const isOpen = open === m.id
        const time = new Date(m.started_at).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })
        return (
          <div key={m.id} className="card mtg">
            <button className="mtg-head" onClick={() => setOpen(isOpen ? null : m.id)} aria-expanded={isOpen}>
              <span style={{ fontSize: 15, fontWeight: 700 }}>
                Meeting #{m.sequence_no}{' '}
                <span className="mono" style={{ fontSize: 13, fontWeight: 500, color: 'var(--muted)' }}>
                  · {shortDate(m.started_at)}, {time}
                </span>
              </span>
              <span aria-hidden style={{ color: 'var(--muted)' }}>
                {isOpen ? '▾' : '▸'}
              </span>
            </button>
            <div className="tags">
              <span className={`tag ${m.gps_start ? 'good' : 'bad'}`}>{m.gps_start ? 'GPS ✓' : 'No GPS'}</span>
              <span className={`tag ${SYNC[m.zoho_sync_status].cls}`}>{SYNC[m.zoho_sync_status].label}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)' }}>
                {added} new · {updated} updated{cleared ? ` · ${cleared} cleared` : ''}
              </span>
            </div>
            {m.zoho_sync_status === 'FAILED' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ fontSize: 13, color: 'var(--warn)', fontWeight: 600 }}>
                  {friendlyZohoError(m.zoho_last_error) || 'Zoho sync failed.'}
                </div>
                <button
                  className="btn ghost"
                  style={{ height: 44, fontSize: 15 }}
                  disabled={retrying === m.id}
                  onClick={() => retry(m)}
                >
                  {retrying === m.id ? 'Retrying…' : 'Retry sync'}
                </button>
              </div>
            )}
            {isOpen && (
              <>
                <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                  By {m.staff.full_name} ·{' '}
                  {m.gps_start ? (
                    <a href={mapsUrl(m.gps_start)} target="_blank" rel="noreferrer" style={{ color: 'var(--navy)', fontWeight: 600 }}>
                      Location ±{Math.round(m.gps_start.accuracy_m)} m ↗
                    </a>
                  ) : (
                    <span style={{ color: 'var(--warn)', fontWeight: 600 }}>No GPS: {m.gps_unavailable_reason}</span>
                  )}
                </div>
                {m.place && (
                  <div style={{ fontSize: 13, color: 'var(--navy)', fontWeight: 600 }}>📍 {m.place}</div>
                )}
                {m.changes.length > 0 ? (
                  <ul className="changes">
                    {m.changes.map((c) => (
                      <li key={c.field}>
                        <span className="k">{fieldLabel(catalog, c.field)}</span>
                        <span className="v">
                          {c.old && (
                            <>
                              <s style={{ color: 'var(--muted)', fontWeight: 500 }}>{show(c.field, c.old)}</s> →{' '}
                            </>
                          )}
                          {c.new ? show(c.field, c.new) : <em style={{ color: 'var(--muted)' }}>cleared</em>}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div style={{ fontSize: 13, color: 'var(--muted)' }}>No fields changed in this meeting.</div>
                )}
              </>
            )}
          </div>
        )
      })}
      {showsPlace && (
        <div style={{ fontSize: 11, color: 'var(--muted)', textAlign: 'center', padding: '2px 0 6px' }}>
          Place names ©{' '}
          <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" style={{ textDecoration: 'underline' }}>
            OpenStreetMap contributors
          </a>
        </div>
      )}
    </>
  )
}

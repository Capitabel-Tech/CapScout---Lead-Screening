// "New meeting": first choose who the meeting is with. Customer opens the existing meeting form;
// Banker and Connector will have their own forms (not set up yet).

import { useNavigate, useParams } from 'react-router-dom'
import { IconBack } from '../components/icons'

const TYPES = [
  { key: 'customer', label: 'Customer', hint: 'A business we may lend to. Saved as a prospect, can be converted to a Lead.' },
  { key: 'banker', label: 'Banker', hint: 'A meeting with a banker.' },
  { key: 'connector', label: 'Connector', hint: 'A meeting with a connector who brings us customers.' },
]

export default function MeetingType() {
  const navigate = useNavigate()
  const { kind } = useParams()
  const picked = TYPES.find((t) => t.key === kind && t.key !== 'customer')

  return (
    <>
      <div className="hdr" style={{ padding: '10px 12px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
        <button className="icon-btn" aria-label="Back" onClick={() => navigate(picked ? '/new-meeting' : '/')}>
          <IconBack />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 17, fontWeight: 700 }}>{picked ? `${picked.label} meeting` : 'New meeting'}</div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>{picked ? 'Coming soon' : 'Who is the meeting with?'}</div>
        </div>
      </div>

      <div className="scroll">
        {picked ? (
          <div className="card" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--navy)' }}>The {picked.label.toLowerCase()} form is not set up yet</div>
            <div style={{ fontSize: 13, color: 'var(--muted)' }}>It will have its own fields, different from a customer meeting.</div>
          </div>
        ) : (
          <>
            <div className="lbl">Type of meeting</div>
            {TYPES.map((t) => (
              <button
                key={t.key}
                className="lead"
                onClick={() => navigate(t.key === 'customer' ? '/new' : `/new-meeting/${t.key}`, { state: { title: 'New meeting' } })}
              >
                <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--navy)' }}>{t.label}</div>
                <div style={{ fontSize: 13, color: 'var(--muted)' }}>{t.hint}</div>
              </button>
            ))}
          </>
        )}
      </div>
    </>
  )
}

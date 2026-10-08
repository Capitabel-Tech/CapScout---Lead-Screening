// "New meeting": first choose who the meeting is with. Customer opens the existing meeting form;
// Banker and Connector will have their own forms (not set up yet).

import type { ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { IconBack } from '../components/icons'

const BLUE = '#2F6DB5'

// Simple line icons (48 x 48), one per type of meeting.
const Svg = ({ children }: { children: ReactNode }) => (
  <svg width="46" height="46" viewBox="0 0 48 48" fill="none" stroke={BLUE} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
)

const ICONS: Record<string, ReactNode> = {
  // an ID card above a handshake
  customer: (
    <Svg>
      <rect x="12" y="4" width="24" height="16" rx="2.5" />
      <circle cx="19" cy="10.5" r="2.4" />
      <path d="M16 16.5c.8-2 4.2-2 5 0M25 9.5h7M25 13.5h7" />
      <rect x="3" y="27" width="7" height="13" rx="1.6" />
      <rect x="38" y="27" width="7" height="13" rx="1.6" />
      <path d="M10 29.5l7-3 7 3 7-3 7 3M10 37.5l6 3.5 8-3.5 8 3.5 6-3.5M24 29.5v8" />
    </Svg>
  ),
  // a bank building
  banker: (
    <Svg>
      <path d="M24 5L5 15.5h38L24 5z" />
      <circle cx="24" cy="12" r="2.2" />
      <path d="M10 20v16M19 20v16M29 20v16M38 20v16M6 40h36M4 44h40" />
    </Svg>
  ),
  // two chain links and a small person
  connector: (
    <Svg>
      <rect x="4" y="14" width="22" height="12" rx="6" transform="rotate(-40 15 20)" />
      <rect x="20" y="22" width="22" height="12" rx="6" transform="rotate(-40 31 28)" />
      <circle cx="37" cy="38" r="3" />
      <path d="M31 46c.5-4 2.5-5.5 6-5.5s5.5 1.5 6 5.5" />
    </Svg>
  ),
}

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
                className="mtype"
                onClick={() => navigate(t.key === 'customer' ? '/new' : `/new-meeting/${t.key}`, { state: { title: 'New meeting' } })}
              >
                <span className="mtype-icon">{ICONS[t.key]}</span>
                <span className="mtype-text">
                  <span className="mtype-title">{t.label}</span>
                  <span className="mtype-hint">{t.hint}</span>
                </span>
              </button>
            ))}
          </>
        )}
      </div>
    </>
  )
}

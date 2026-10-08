// The CapScout logo: a magnifying glass drawn as a "C" with a tick, "Cap" in gold and "Scout" in navy, and
// "Lead generation" underneath. Drawn as SVG + text so it stays sharp on every screen.

export function Logo({ size = 'small' }: { size?: 'small' | 'big' }) {
  return (
    <div className={`logo ${size}`} role="img" aria-label="CapScout, lead generation">
      <svg viewBox="0 0 66 66" aria-hidden="true">
        {/* a "C": the ring is open on the right, and the handle starts just beyond its lower end */}
        <path d="M42.1 42.1A20 20 0 1 1 44.4 16.5" fill="none" stroke="#F28F0C" strokeWidth="8" strokeLinecap="round" />
        <path d="M20 29l7 7 12-14" fill="none" stroke="#12263A" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M49 49l11 11" fill="none" stroke="#12263A" strokeWidth="8" strokeLinecap="round" />
      </svg>
      <div className="logo-text">
        <div className="logo-name">
          <i>Cap</i>Scout
        </div>
        <div className="logo-sub">Lead generation</div>
      </div>
    </div>
  )
}

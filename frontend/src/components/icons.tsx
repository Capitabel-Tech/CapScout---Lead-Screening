// Icons copied from the client's prototype.

const stroke = { fill: 'none', stroke: 'currentColor', strokeLinecap: 'round' } as const

export const IconX = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" {...stroke} strokeWidth="2">
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
)

export const IconCheck = ({ size, width }: { size: number; width: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...stroke} strokeWidth={width} strokeLinejoin="round">
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
)

export const IconArrow = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} strokeWidth="2.4" strokeLinejoin="round">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
)

export const IconBack = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" {...stroke} strokeWidth="2.4" strokeLinejoin="round">
    <path d="M19 12H5M11 6l-6 6 6 6" />
  </svg>
)

export const IconGps = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} strokeWidth="2">
    <circle cx="12" cy="12" r="3" />
    <circle cx="12" cy="12" r="7" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
  </svg>
)

export const IconMic = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} strokeWidth="2">
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </svg>
)

export const IconCal = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...stroke} strokeWidth="2">
    <rect x="4" y="5" width="16" height="15" rx="2" />
    <path d="M4 10h16M9 3v4M15 3v4" />
  </svg>
)

export const IconPlus = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" {...stroke} strokeWidth="2.4">
    <path d="M12 5v14M5 12h14" />
  </svg>
)

export const IconSearch = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} strokeWidth="2">
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4 4" />
  </svg>
)

export const IconCloud = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...stroke} strokeWidth="2" strokeLinejoin="round">
    <path d="M7 18a4.5 4.5 0 0 1-.5-9 6 6 0 0 1 11.5 1.5A3.75 3.75 0 0 1 17.5 18z" />
    <path d="M9.5 13.5l2 2 3.5-3.5" />
  </svg>
)

export const IconPower = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} strokeWidth="2">
    <path d="M12 3v8M6.5 6.5a8 8 0 1 0 11 0" />
  </svg>
)

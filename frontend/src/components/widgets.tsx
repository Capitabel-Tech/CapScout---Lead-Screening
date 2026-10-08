// Form controls from the client's prototype. Options always come from the
// Excel (via the field catalogue); fields without an Excel dropdown are typed.

import { formatINR } from '../format'
import type { ReactNode } from 'react'

type ChoiceProps = {
  label: string
  options: string[]
  value: string
  onChange: (v: string) => void
  kind?: 'wrap' | 'seg' | 'hs'
  disabled?: boolean // greyed out and cannot be changed
}

// Tapping the selected option again clears it, so a wrong tap can be undone.
export function Choice({ label, options, value, onChange, kind = 'wrap', disabled = false }: ChoiceProps) {
  const cls = kind === 'seg' ? 'sg' : 'chip'
  return (
    <div>
      <div className="lbl">{label}</div>
      <div className={kind === 'seg' ? 'seg' : kind === 'hs' ? 'hs' : 'wrap'} role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o}
            type="button"
            className={`${cls}${value === o ? ' on' : ''}`}
            aria-pressed={value === o}
            disabled={disabled}
            onClick={() => onChange(value === o ? '' : o)}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  )
}

export function TriRow({
  label,
  options,
  value,
  onChange,
  risk = false,
  disabled = false,
}: {
  label: string
  options: string[]
  value: string
  onChange: (v: string) => void
  risk?: boolean
  disabled?: boolean
}) {
  return (
    <div className="row">
      <div className="t">{label}</div>
      <div style={{ display: 'flex', gap: 4, flex: 'none' }} role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o}
            type="button"
            className={`tri${value === o ? ' on' + (risk && o === 'Yes' ? ' risk' : '') : ''}`}
            aria-pressed={value === o}
            disabled={disabled}
            onClick={() => onChange(value === o ? '' : o)}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  )
}

export function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
  inputMode,
  after,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  inputMode?: 'text' | 'tel' | 'numeric' | 'decimal'
  after?: ReactNode
}) {
  const input = (
    <input
      className="fld"
      id={id}
      type={type}
      inputMode={inputMode}
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={after ? { flex: 1, minWidth: 0 } : undefined}
    />
  )
  return (
    <div>
      <label className="lbl" htmlFor={id}>
        {label}
      </label>
      {after ? (
        <div style={{ display: 'flex', gap: 8 }}>
          {input}
          {after}
        </div>
      ) : (
        input
      )}
    </div>
  )
}

// ₹ amount box: type the full amount in rupees; commas are added as you type (12,34,567).
export function MoneyField({
  id,
  label,
  value,
  onChange,
  unit = '',
  placeholder = '0',
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  unit?: string
  placeholder?: string
}) {
  return (
    <div>
      <label className="lbl" htmlFor={id}>
        {label}
      </label>
      <MoneyBox id={id} value={value} onChange={onChange} unit={unit} placeholder={placeholder} />
    </div>
  )
}

export function MoneyBox({
  id,
  value,
  onChange,
  unit = '',
  placeholder = '0',
  style,
}: {
  id: string
  value: string
  onChange: (v: string) => void
  unit?: string
  placeholder?: string
  style?: React.CSSProperties
}) {
  return (
    <div className="box" style={style}>
      <span style={{ color: 'var(--muted)' }}>₹</span>
      <input
        className="mono"
        id={id}
        inputMode="numeric"
        placeholder={placeholder}
        value={formatINR(value)}
        onChange={(e) => onChange(e.target.value.replace(/[^\d]/g, '').slice(0, 13))}
      />
      {unit && <span className="unit">{unit}</span>}
    </div>
  )
}

export function cleanNumber(raw: string): string {
  const digits = raw.replace(/[^\d.]/g, '')
  const [whole, ...rest] = digits.split('.')
  return rest.length ? `${whole}.${rest.join('')}` : whole
}

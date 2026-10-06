// "Convert to Lead": one form showing the same fields as the Lead form in the client's Zoho CRM,
// with the same names, pre-filled from what the app already collected. The fields are read live
// from Zoho, so any field the Zoho admin adds later shows up here without changing the app.

import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError, post, type ConvertForm, type ZohoFormField } from '../api'
import { IconArrow, IconBack } from '../components/icons'

type Values = Record<string, string>

const CHIP_MAX = 6 // short lists are shown as one-tap buttons, longer ones as a dropdown

export default function ConvertPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [form, setForm] = useState<ConvertForm | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [values, setValues] = useState<Values>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const load = useCallback(() => {
    api<ConvertForm>(`/customers/${id}/convert-form`)
      .then((f) => {
        setForm(f)
        const initial: Values = {}
        for (const field of f.fields) initial[field.api_name] = field.value === null ? '' : String(field.value)
        setValues(initial)
      })
      .catch((e) =>
        setLoadError(
          e instanceof ApiError && typeof e.detail === 'string'
            ? e.detail
            : e instanceof ApiError && e.status === 404
              ? 'Lead not found.'
              : 'Could not load the Zoho Lead form.',
        ),
      )
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const reload = () => {
    setLoadError(null)
    setForm(null)
    load()
  }

  const set = (api_name: string, v: string) => {
    setValues((cur) => ({ ...cur, [api_name]: v }))
    setErrors((cur) => {
      if (!(api_name in cur)) return cur
      const next = { ...cur }
      delete next[api_name]
      return next
    })
  }

  async function submit(withForm: boolean) {
    setBusy(true)
    setSubmitError(null)
    setErrors({})
    try {
      let body: { lead_values: Record<string, string> } | undefined
      if (withForm && form) {
        const lead_values: Record<string, string> = {}
        for (const f of form.fields) if ((values[f.api_name] ?? '').trim() !== '') lead_values[f.api_name] = values[f.api_name]
        const missing = form.fields.filter((f) => f.required && !lead_values[f.api_name])
        if (missing.length) {
          setErrors(Object.fromEntries(missing.map((f) => [f.api_name, 'required'])))
          setSubmitError(`Please fill in: ${missing.map((f) => f.label).join(', ')}`)
          document.getElementById(`z-${missing[0].api_name}`)?.scrollIntoView({ block: 'center' })
          return
        }
        body = { lead_values }
      }
      await post(`/customers/${id}/convert`, body)
      navigate(`/customers/${id}`, { replace: true })
    } catch (e) {
      if (!(e instanceof ApiError)) throw e
      const d = e.detail as { code?: string; errors?: Record<string, string> } | string | null
      if (typeof d === 'object' && d?.code === 'INVALID_VALUES' && d.errors) {
        setErrors(d.errors)
        const labels = Object.fromEntries((form?.fields ?? []).map((f) => [f.api_name, f.label]))
        setSubmitError(
          Object.entries(d.errors)
            .map(([k, msg]) => `${labels[k] ?? k}: ${msg}`)
            .join(' · '),
        )
        document.getElementById(`z-${Object.keys(d.errors)[0]}`)?.scrollIntoView({ block: 'center' })
      } else if (e.status === 0) {
        setSubmitError('No connection. Converting to a Lead needs the internet. Try again when you have signal.')
      } else {
        setSubmitError(typeof d === 'string' ? d : 'Could not start the conversion. Try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  const back = () => navigate(`/customers/${id}`)

  return (
    <>
      <div className="hdr" style={{ padding: '10px 12px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
        <button className="icon-btn" aria-label="Back to the lead" onClick={back}>
          <IconBack />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 17, fontWeight: 700 }}>Convert to Lead</div>
          <div className="mono" style={{ fontSize: 12, color: '#B9C6D3' }}>
            {form ? `${form.customer.lead_ref} · ${form.customer.name ?? ''}` : 'Zoho Lead form'}
          </div>
        </div>
      </div>

      <div className="scroll">
        {!form && !loadError && <div className="empty">Loading your Zoho Lead form…</div>}

        {loadError && (
          <div className="card" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--warn)' }}>Could not load the Zoho Lead form</div>
            <div style={{ fontSize: 13, color: 'var(--muted)' }}>{loadError}</div>
            <button className="btn ghost" style={{ height: 46 }} onClick={reload}>
              Try again
            </button>
            <button className="btn ghost" style={{ height: 46 }} disabled={busy} onClick={() => submit(false)}>
              {busy ? 'Converting…' : 'Convert with the default details instead'}
            </button>
          </div>
        )}

        {form && (
          <>
            <div className="card" style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--navy)' }}>
                Convert {form.customer.name ?? form.customer.lead_ref} to Lead?
              </div>
              <div style={{ fontSize: 13, color: 'var(--ink)' }}>
                This will create the Lead in Zoho CRM with the details below. They are the fields of your Zoho Lead form.
                Check them and change anything that is wrong. All meetings stay with this lead.
              </div>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                <span className="tag good">from the app</span> marks details filled in from what you already collected.
              </div>
            </div>

            <div className="card" style={{ padding: '4px 14px' }}>
              {form.fields.map((f) => (
                <Field
                  key={f.api_name}
                  field={f}
                  value={values[f.api_name] ?? ''}
                  error={errors[f.api_name]}
                  onChange={(v) => set(f.api_name, v)}
                />
              ))}
            </div>

            {submitError && (
              <div className="err" role="alert">
                {submitError}
              </div>
            )}
          </>
        )}
      </div>

      {form && (
        <div className="foot">
          <div className="inner">
            <button className="btn ghost" style={{ flex: 'none', width: 104 }} disabled={busy} onClick={back}>
              Cancel
            </button>
            <button className="btn primary" style={{ flex: 1 }} disabled={busy} onClick={() => submit(true)}>
              {busy ? 'Converting…' : 'Convert to Lead'} {!busy && <IconArrow />}
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// One Zoho field, shown with Zoho's own label.
function Field({
  field,
  value,
  error,
  onChange,
}: {
  field: ZohoFormField
  value: string
  error?: string
  onChange: (v: string) => void
}) {
  const id = `z-${field.api_name}`
  return (
    <div id={id} style={{ padding: '12px 0', borderBottom: '1px solid #EDF0F2' }}>
      <label className="lbl" htmlFor={`${id}-input`} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span>
          {field.label}
          {field.required && <span style={{ color: 'var(--warn)' }}> *</span>}
        </span>
        {field.prefilled_from && <span className="tag good">from the app</span>}
        {field.custom && <span className="tag">custom</span>}
      </label>
      <Control field={field} id={`${id}-input`} value={value} onChange={onChange} invalid={!!error} />
      {error && (
        <div style={{ color: 'var(--warn)', fontSize: 13, fontWeight: 600, marginTop: 4 }}>{error === 'required' ? 'Required' : error}</div>
      )}
    </div>
  )
}

function Control({
  field,
  id,
  value,
  onChange,
  invalid,
}: {
  field: ZohoFormField
  id: string
  value: string
  onChange: (v: string) => void
  invalid: boolean
}) {
  const style = invalid ? { borderColor: 'var(--warn)' } : undefined
  switch (field.kind) {
    case 'textarea':
      return (
        <textarea
          id={id}
          className="fld"
          style={{ height: 110, resize: 'none', padding: '12px 14px', ...style }}
          value={value}
          maxLength={field.max_length ?? undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      )
    case 'select': {
      const options = field.options ?? []
      if (options.length <= CHIP_MAX)
        return (
          <div className="wrap" role="radiogroup" aria-label={field.label}>
            {options.map((o) => (
              <button
                key={o}
                type="button"
                className={`chip${value === o ? ' on' : ''}`}
                aria-pressed={value === o}
                onClick={() => onChange(value === o ? '' : o)}
              >
                {o}
              </button>
            ))}
          </div>
        )
      return (
        <select id={id} className="fld" style={style} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">None</option>
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      )
    }
    case 'boolean':
      return (
        <div className="wrap" role="radiogroup" aria-label={field.label}>
          {['Yes', 'No'].map((o) => {
            const v = o === 'Yes' ? 'true' : 'false'
            return (
              <button key={o} type="button" className={`chip${value === v ? ' on' : ''}`} aria-pressed={value === v} onClick={() => onChange(value === v ? '' : v)}>
                {o}
              </button>
            )
          })}
        </div>
      )
    default: {
      const type = { email: 'email', phone: 'tel', url: 'url', date: 'date' }[field.kind as 'email' | 'phone' | 'url' | 'date'] ?? 'text'
      const inputMode = field.kind === 'integer' ? 'numeric' : field.kind === 'decimal' ? 'decimal' : undefined
      return (
        <input
          id={id}
          className="fld"
          style={style}
          type={type}
          inputMode={inputMode}
          value={value}
          maxLength={field.max_length ?? undefined}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
        />
      )
    }
  }
}

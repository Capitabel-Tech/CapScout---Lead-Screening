import { useEffect, useState } from 'react'
import { api, type FieldCatalog } from './api'

// The field catalogue rarely changes, so it is fetched once per app load.
let cached: Promise<FieldCatalog> | null = null

function loadCatalog(): Promise<FieldCatalog> {
  cached ??= api<FieldCatalog>('/fields').catch((e) => {
    cached = null
    throw e
  })
  return cached
}

export function useFieldCatalog(): FieldCatalog | null {
  const [catalog, setCatalog] = useState<FieldCatalog | null>(null)
  useEffect(() => {
    loadCatalog().then(setCatalog).catch(() => undefined)
  }, [])
  return catalog
}

export function fieldLabel(catalog: FieldCatalog | null, key: string): string {
  return catalog?.fields.find((f) => f.key === key)?.label ?? REMOVED_LABELS[key] ?? key
}

// Fields shown only for some answers: {field: [the field it depends on, whether to show it for that field's value]}.
// When the answer changes so that a field is hidden, whatever was typed in it is cleared.
export const DEPENDENT_FIELDS: Record<string, [string, (parentValue: string) => boolean][]> = {
  source_name: [['source_type', (v) => v !== 'Direct']],
  source_contact: [['source_type', (v) => v !== 'Direct']],
  constitution_other: [['constitution', (v) => v === 'Other']],
  source_type_other: [['source_type', (v) => v === 'Other']],
  purpose_other: [['purpose', (v) => v === 'Other']],
  likely_product_other: [['likely_product', (v) => v === 'Other']],
  property_type_other: [['property_type', (v) => v === 'Other']],
  // Property questions do not apply to an unsecured loan, or when there is no property.
  property_available: [['secured_unsecured', (v) => v !== 'Unsecured']],
  property_type: [
    ['property_available', (v) => v !== 'No'],
    ['secured_unsecured', (v) => v !== 'Unsecured'],
  ],
  property_documents: [
    ['property_available', (v) => v !== 'No'],
    ['secured_unsecured', (v) => v !== 'Unsecured'],
  ],
}

// Fields removed from the form but still in older meetings' history.
const REMOVED_LABELS: Record<string, string> = {
  monthly_surplus: 'Monthly Surplus (₹L)',
  property_value: 'Property Value (₹L)',
  existing_mortgage: 'Existing Mortgage',
}

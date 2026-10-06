import { useEffect, useState } from 'react'
import { api, type FieldCatalog } from './api'

// The 44-field catalogue rarely changes, so it is fetched once per app load.
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
  return catalog?.fields.find((f) => f.key === key)?.label ?? key
}

// Staff should never see raw Zoho error codes. Turn the common ones into plain sentences.

export function friendlyZohoError(raw: string | null | undefined): string {
  const e = (raw ?? '').toLowerCase()
  if (!e) return ''
  if (e.includes('oauth_scope_mismatch') || e.includes('invalid oauth scope') || e.includes('no_permission'))
    return 'Zoho has not given this app permission to save. Please tell your admin.'
  if (e.includes('not authori'))
    return 'The connection to Zoho needs to be authorized again. Please tell your admin.'
  if (e.includes('invalid_token') || e.includes('authentication required') || e.includes('401'))
    return 'The connection to Zoho needs to be renewed. Please tell your admin.'
  if (e.includes('cannot connect') || e.includes('did not answer') || e.includes('timeout') || e.includes('network'))
    return 'Could not reach Zoho right now. It will try again by itself.'
  if (e.includes('mandatory') || e.includes('invalid_data') || e.includes('invalid data'))
    return 'Zoho did not accept some of the details. Please tell your admin.'
  if (e.includes('too_many_requests') || e.includes('limit'))
    return 'Zoho is busy right now. It will try again by itself.'
  return 'Zoho could not save this yet. It will try again by itself.'
}

// Staff should never see raw error codes or the word Zoho. Turn the common ones into plain sentences.

export function friendlyZohoError(raw: string | null | undefined): string {
  const e = (raw ?? '').toLowerCase()
  if (!e) return ''
  if (e.includes('oauth_scope_mismatch') || e.includes('invalid oauth scope') || e.includes('no_permission'))
    return 'This app is not allowed to save this right now. Please tell your admin.'
  if (e.includes('not authori'))
    return 'The connection needs to be authorized again. Please tell your admin.'
  if (e.includes('invalid_token') || e.includes('authentication required') || e.includes('401'))
    return 'The connection needs to be renewed. Please tell your admin.'
  if (e.includes('cannot connect') || e.includes('did not answer') || e.includes('timeout') || e.includes('network'))
    return 'Could not connect right now. It will try again by itself.'
  if (e.includes('mandatory') || e.includes('invalid_data') || e.includes('invalid data'))
    return 'Some of the details were not accepted. Please tell your admin.'
  if (e.includes('too_many_requests') || e.includes('limit'))
    return 'The system is busy right now. It will try again by itself.'
  return 'Could not save this yet. It will try again by itself.'
}

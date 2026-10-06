import type { GpsPoint } from './api'

// Meeting-based GPS: one reading when the meeting starts, one (best effort)
// when it finishes. Readings come only from the device; nothing is ever
// filled in, cached from an earlier visit, or guessed.

export type GpsErrorCode = 'denied' | 'unavailable' | 'timeout' | 'unsupported' | 'insecure'

export class GpsError extends Error {
  code: GpsErrorCode
  constructor(code: GpsErrorCode) {
    super(code)
    this.code = code
  }
}

export const GPS_ERROR_TEXT: Record<GpsErrorCode, string> = {
  denied: 'Location permission is blocked. Allow location for this app in the phone settings, then try again.',
  unavailable: 'Location is not available. Check that GPS/Location is switched on.',
  timeout: 'Could not get a GPS fix in time. Move near a window or outdoors and try again.',
  unsupported: 'This browser cannot read the location.',
  insecure: 'Location only works over a secure (https) connection.',
}

export function captureLocation(timeoutMs = 20_000): Promise<GpsPoint> {
  return new Promise((resolve, reject) => {
    if (!window.isSecureContext) return reject(new GpsError('insecure'))
    if (!('geolocation' in navigator)) return reject(new GpsError('unsupported'))
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        resolve({
          latitude: Number(pos.coords.latitude.toFixed(6)),
          longitude: Number(pos.coords.longitude.toFixed(6)),
          accuracy_m: Math.max(0.1, Number(pos.coords.accuracy.toFixed(1))),
          captured_at: new Date(pos.timestamp).toISOString(),
        }),
      (err) =>
        reject(
          new GpsError(
            err.code === err.PERMISSION_DENIED ? 'denied' : err.code === err.TIMEOUT ? 'timeout' : 'unavailable',
          ),
        ),
      // maximumAge 0: never reuse a stale position from an earlier place.
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
    )
  })
}

export type GpsQuality = 'good' | 'fair' | 'poor'

export function gpsQuality(accuracyM: number): GpsQuality {
  if (accuracyM <= 100) return 'good'
  if (accuracyM <= 500) return 'fair'
  return 'poor'
}

export function mapsUrl(p: { latitude: number; longitude: number }): string {
  return `https://www.google.com/maps?q=${p.latitude},${p.longitude}`
}

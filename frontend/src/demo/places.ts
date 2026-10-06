// Demo-mode stand-in for the GPS -> address lookup: the nearest well-known area within ~40 km.

type Spot = { lat: number; lng: number; area: string; place: string }

const SPOTS: Spot[] = [
  { lat: 13.085, lng: 80.2101, area: 'Anna Nagar West, Chennai', place: '2nd Avenue, Anna Nagar West, Chennai, Tamil Nadu' },
  { lat: 17.4948, lng: 78.399, area: 'Kukatpally, Hyderabad', place: 'KPHB Colony, Kukatpally, Hyderabad, Telangana' },
  { lat: 17.4967, lng: 78.3556, area: 'Miyapur, Hyderabad', place: 'Miyapur, Hyderabad, Telangana' },
  { lat: 17.4399, lng: 78.4983, area: 'Secunderabad', place: 'Paradise Circle, Secunderabad, Telangana' },
  { lat: 12.9716, lng: 77.5946, area: 'MG Road, Bengaluru', place: 'MG Road, Bengaluru, Karnataka' },
  { lat: 19.076, lng: 72.8777, area: 'Andheri, Mumbai', place: 'Andheri East, Mumbai, Maharashtra' },
  { lat: 28.6139, lng: 77.209, area: 'Connaught Place, New Delhi', place: 'Connaught Place, New Delhi, Delhi' },
]

function km(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2
  return 6371 * 2 * Math.asin(Math.sqrt(h))
}

export function demoPlace(lat: number, lng: number): { area: string; place: string } {
  let best: Spot | null = null
  let bestKm = Infinity
  for (const s of SPOTS) {
    const d = km({ lat, lng }, s)
    if (d < bestKm) [best, bestKm] = [s, d]
  }
  if (best && bestKm <= 40) return { area: best.area, place: best.place }
  return { area: 'Your current area', place: 'Your current area, India' }
}

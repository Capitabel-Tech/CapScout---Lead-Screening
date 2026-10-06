from fastapi import APIRouter, Query

from app.auth import CurrentStaff
from app.config import get_settings
from app.services import places

router = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/reverse")
def reverse(
    _: CurrentStaff,
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
) -> dict:
    """Readable place for GPS numbers, SHOWN (read-only) in the Location box of the meeting form.

    Nothing is saved here: the place that is stored is worked out again by the server from the
    meeting's own GPS. Only the two numbers go to the map service. Always answers 200: if the
    lookup fails the values are null and the box simply shows that no place is available.
    """
    cfg = get_settings()
    if not cfg.geocoding_enabled:
        return {"place": None, "area": None}
    return places.names_for(cfg, lat, lng)

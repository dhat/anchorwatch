"""Workaround for a gpsd-py3 bug: satellite counts silently read as 0.

gpsd-py3's GpsResponse.from_json only derives sats/sats_valid by counting
entries in the SKY report's "satellites" array. Some receiver/driver
combinations (confirmed here with gpsd 3.25 + the NMEA0183 read-only driver)
never send that array -- they emit GSA sentences (giving gpsd's summary
"uSat" field, the used-satellite count) but not GSV sentences (which is what
would let gpsd build the full array and the "nSat" seen-satellite count).
In that case gpsd-py3 reports sats=sats_valid=0 even though gpsd itself is
tracking real satellite counts -- confirmed by querying gpsd directly and
seeing uSat populated while the "satellites" key was absent every poll.

This patches GpsResponse.from_json to fall back to the summary uSat/nSat
fields when the satellite array isn't present, and leaves the original
per-satellite counting untouched when the array *is* present.
"""
import gpsd

_original_from_json = gpsd.GpsResponse.from_json.__func__


def _from_json_with_sat_fallback(cls, packet):
    result = _original_from_json(cls, packet)
    last_sky = packet['sky'][-1]
    if 'satellites' not in last_sky:
        result.sats_valid = last_sky.get('uSat', 0)
        result.sats = last_sky.get('nSat', result.sats_valid)
    return result


def patch_satellite_counts():
    """Apply the fallback once. Safe to call more than once."""
    gpsd.GpsResponse.from_json = classmethod(_from_json_with_sat_fallback)

"""Pure geographic calculations used by the anchor watch alarm logic.

No I/O here on purpose -- these are the functions the alarm decision depends
on, so they need to be trivially unit-testable.
"""
import math

from haversine import haversine, Unit


def calc_distance(lat1, lon1, lat2, lon2):
    return haversine((lat1, lon1), (lat2, lon2), unit=Unit.FEET)


def calc_bearing(lat1, lon1, lat2, lon2):
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
        math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360


def decdeg2dms(dd):
    is_positive = dd >= 0
    dd = abs(dd)
    fminutes, fseconds = divmod(dd * 3600, 60)
    fdegrees, fminutes = divmod(fminutes, 60)
    fdegrees = fdegrees if is_positive else -fdegrees
    return fdegrees, fminutes, fseconds

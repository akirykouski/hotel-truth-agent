"""Положение солнца: азимут заката по месяцам (середина месяца, без рефракции)."""
import math

from app import region

LAT = region.META["sun_lat"]
MID_DAY = {1: 15, 2: 46, 3: 74, 4: 105, 5: 135, 6: 166, 7: 196, 8: 227, 9: 258, 10: 288, 11: 319, 12: 349}
MONTHS_RU = {1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь", 7: "июль", 8: "август",
             9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь"}


def declination(day):
    return 23.44 * math.sin(math.radians(360 / 365 * (284 + day)))


def sunset_azimuth(month, lat=LAT):
    d = math.radians(declination(MID_DAY[month]))
    a = math.degrees(math.acos(max(-1, min(1, math.sin(d) / math.cos(math.radians(lat))))))
    return 360 - a


def sunrise_azimuth(month, lat=LAT):
    return 360 - sunset_azimuth(month, lat)


def sun_position(month, minutes_before_sunset, lat=LAT):
    """Азимут (от севера по часовой) и высота солнца в середине месяца за N минут до заката; высота 0 — закат."""
    phi = math.radians(lat)
    d = math.radians(declination(MID_DAY[month]))
    h0 = math.acos(max(-1, min(1, -math.tan(phi) * math.tan(d))))
    h = h0 - math.radians(0.25 * minutes_before_sunset)   # 15° часового угла в час
    alt = math.asin(math.sin(phi) * math.sin(d) + math.cos(phi) * math.cos(d) * math.cos(h))
    az = math.degrees(math.atan2(math.sin(h), math.cos(h) * math.sin(phi) - math.tan(d) * math.cos(phi))) + 180
    return az % 360, math.degrees(alt)


def sun_path(month, span_min=90, step_min=5, lat=LAT):
    """Путь солнца в последние span_min минут до заката: [(минут до заката, азимут, высота)]."""
    return [(m, *sun_position(month, m, lat)) for m in range(span_min, -1, -step_min)]

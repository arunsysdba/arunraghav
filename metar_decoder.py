"""
metar_decoder.py
----------------
Parses and decodes raw METAR strings into structured, human-readable fields.

A METAR (Meteorological Aerodrome Report) is a fixed-format weather observation
issued by airports. This module walks through the token-by-token structure defined
in ICAO Annex 3 / WMO No. 49 and converts each group into plain English.

Typical METAR token order:
  [METAR|SPECI] ICAO DDHHmmZ [AUTO] wind [wind-variation] visibility
  [RVR] [weather] sky temp/dew altimeter [RMK ...]
"""

import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

# ICAO weather phenomenon codes -> English descriptions
WEATHER_CODES = {
    "RA": "Rain", "SN": "Snow", "DZ": "Drizzle", "GR": "Hail", "GS": "Small Hail",
    "TS": "Thunderstorm", "FG": "Fog", "BR": "Mist", "HZ": "Haze", "FU": "Smoke",
    "DU": "Dust", "SA": "Sand", "SQ": "Squall", "FC": "Funnel Cloud / Tornado",
    "SS": "Sandstorm", "DS": "Duststorm", "PL": "Ice Pellets", "IC": "Ice Crystals",
    "SG": "Snow Grains", "UP": "Unknown Precipitation", "VA": "Volcanic Ash",
    "PY": "Spray", "PO": "Dust Whirls", "RASN": "Rain and Snow",
}

# Precipitation intensity prefix: '-' light, '+' heavy, '' moderate, 'VC' vicinity
INTENSITY_MAP = {"-": "Light", "+": "Heavy", "": "Moderate", "VC": "In the Vicinity"}

# Two-letter descriptor prefixes that modify weather phenomena
DESCRIPTOR_MAP = {
    "MI": "Shallow", "BC": "Patches", "PR": "Partial", "DR": "Low Drifting",
    "BL": "Blowing", "SH": "Showers", "TS": "Thunderstorm", "FZ": "Freezing",
}

# Cloud coverage abbreviations
CLOUD_MAP = {
    "FEW": "Few", "SCT": "Scattered", "BKN": "Broken",
    "OVC": "Overcast", "SKC": "Sky Clear", "CLR": "Clear",
}

# 16-point compass rose used for wind direction conversion
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def deg_to_compass(deg):
    """Convert a degree heading (0-360) to the nearest 16-point compass label."""
    idx = round(deg / 22.5) % 16
    return COMPASS[idx]


# ---------------------------------------------------------------------------
# Individual field decoders
# ---------------------------------------------------------------------------

def decode_wind(token):
    """
    Decode a wind group token (e.g. '27015G25KT', 'VRB05KT') into English.
    Handles variable direction, gusts, and KT / MPS / KMH units.
    Returns a plain-English string or None if the token doesn't match.
    """
    # Variable wind direction (speed still reported)
    if token.startswith("VRB"):
        m = re.match(r"VRB(\d{2})(G(\d{2,3}))?(KT|MPS|KMH)", token)
        if m:
            speed = int(m.group(1))
            gust = int(m.group(3)) if m.group(3) else None
            unit = m.group(4)
            conv = 1 if unit == "KT" else (1.944 if unit == "MPS" else 0.5399)
            speed_kt = round(speed * conv)
            result = f"Variable winds at {speed_kt} knots"
            if gust:
                result += f", gusting to {round(gust * conv)} knots"
            return result

    # Standard directional wind: dddffGggUU
    m = re.match(r"(\d{3})(\d{2,3})(G(\d{2,3}))?(KT|MPS|KMH)", token)
    if not m:
        return None
    direction = int(m.group(1))
    speed = int(m.group(2))
    gust = int(m.group(4)) if m.group(4) else None
    unit = m.group(5)
    # Conversion factors to knots
    conv = 1 if unit == "KT" else (1.944 if unit == "MPS" else 0.5399)
    speed_kt = round(speed * conv)
    if direction == 0 and speed_kt == 0:
        return "Calm winds"
    compass = deg_to_compass(direction)
    result = f"From {compass} ({direction}°) at {speed_kt} knots"
    if gust:
        result += f", gusting to {round(gust * conv)} knots"
    return result


def decode_visibility(token, next_token=None):
    """
    Decode a visibility token into plain English.
    Handles metric (9999, 4-digit meters), statute miles (SM), and CAVOK.
    """
    if token == "9999":
        return "Visibility greater than 10 km (6+ miles)"
    if token == "CAVOK":
        return "CAVOK — Ceiling and Visibility OK (visibility > 10 km, no significant cloud, no weather)"
    # 4-digit metric value in meters (e.g. '0800', '3000')
    m = re.match(r"^(\d{4})$", token)
    if m:
        meters = int(m.group(1))
        miles = meters / 1609.34
        return f"{meters} meters ({miles:.1f} miles)"
    # Whole statute miles (e.g. '10SM')
    m = re.match(r"^(\d+)SM$", token)
    if m:
        return f"{m.group(1)} statute miles"
    # Fractional statute miles without leading whole number (e.g. '1/2SM')
    m = re.match(r"^(\d+)/(\d+)SM$", token)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        return f"{num}/{den} statute miles ({num/den*1609:.0f} meters)"
    # Mixed fraction statute miles (e.g. '1 1/2SM' pre-joined by caller)
    m = re.match(r"^(\d+)\s+(\d+)/(\d+)SM$", token)
    if m:
        whole, num, den = int(m.group(1)), int(m.group(2)), int(m.group(3))
        total = whole + num / den
        return f"{whole} {num}/{den} statute miles (~{total*1609:.0f} meters)"
    return None


def decode_weather(token):
    """
    Decode a present-weather token (e.g. '-RA', '+TSRA', 'FZFG', 'VCSH').
    Returns an English description string, or None if not a weather token.
    """
    m = re.match(
        r"^(\+|-|VC)?(MI|BC|PR|DR|BL|SH|TS|FZ)?"
        r"(RA|SN|DZ|GR|GS|FG|BR|HZ|FU|DU|SA|SQ|FC|SS|DS|PL|IC|SG|UP|VA|PY|PO|RASN)(.*)$",
        token
    )
    if not m:
        return None
    intensity = INTENSITY_MAP.get(m.group(1) or "", "")
    descriptor = DESCRIPTOR_MAP.get(m.group(2) or "", "")
    phenomenon = WEATHER_CODES.get(m.group(3) or "", m.group(3) or "")
    parts = [p for p in [intensity, descriptor, phenomenon] if p]
    return " ".join(parts)


def decode_sky(token):
    """
    Decode a sky condition group (e.g. 'BKN025', 'OVC010CB', 'SKC').
    Returns English coverage + height string, or None if not a sky token.
    """
    m = re.match(r"(FEW|SCT|BKN|OVC|SKC|CLR)(\d{3})?(CB|TCU)?", token)
    if not m:
        return None
    coverage = CLOUD_MAP.get(m.group(1), m.group(1))
    height_str = m.group(2)
    cb = m.group(3)
    if m.group(1) in ("SKC", "CLR"):
        return f"{coverage} (no clouds)"
    if height_str:
        height_ft = int(height_str) * 100          # coded in hundreds of feet
        height_m = round(height_ft * 0.3048)
        result = f"{coverage} clouds at {height_ft:,} ft ({height_m:,} m)"
        if cb == "CB":
            result += " — Cumulonimbus (thunderstorm)"
        elif cb == "TCU":
            result += " — Towering Cumulus"
        return result
    return coverage


def decode_temp_dewpoint(token):
    """
    Decode a temperature/dew-point group (e.g. '20/15', 'M02/M08').
    'M' prefix denotes sub-zero Celsius values.
    Returns ((temp_c, temp_f), (dew_c, dew_f)) tuples, or (None, None) on failure.
    """
    m = re.match(r"^(M?\d{2})/(M?\d{2})$", token)
    if not m:
        return None, None

    def parse_t(s):
        # 'M' prefix = negative temperature
        return -int(s[1:]) if s.startswith("M") else int(s)

    temp_c = parse_t(m.group(1))
    dew_c = parse_t(m.group(2))
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    dew_f = round(dew_c * 9 / 5 + 32, 1)
    return (temp_c, temp_f), (dew_c, dew_f)


def decode_altimeter(token):
    """
    Decode an altimeter/QNH setting.
    'A' prefix = inches of mercury (US); 'Q' prefix = hectopascals (ICAO/Europe).
    Returns a dual-unit string or None.
    """
    m = re.match(r"^A(\d{4})$", token)
    if m:
        inhg = int(m.group(1)) / 100
        hpa = round(inhg * 33.8639)
        return f"{inhg:.2f} inHg ({hpa} hPa)"
    m = re.match(r"^Q(\d{4})$", token)
    if m:
        hpa = int(m.group(1))
        inhg = round(hpa / 33.8639, 2)
        return f"{hpa} hPa ({inhg:.2f} inHg)"
    return None


# ---------------------------------------------------------------------------
# Flight category
# ---------------------------------------------------------------------------

def flight_category(visibility_token, sky_tokens):
    """
    Determine FAA flight category (VFR / MVFR / IFR / LIFR) from visibility
    and the lowest reported ceiling (BKN or OVC layer).

    Returns (code, label, bootstrap-color-class) tuple.
    """
    vis_miles = None
    m = re.match(r"^(\d+)SM$", visibility_token)
    if m:
        vis_miles = float(m.group(1))
    m = re.match(r"^(\d+)/(\d+)SM$", visibility_token)
    if m:
        vis_miles = int(m.group(1)) / int(m.group(2))
    if visibility_token in ("9999", "CAVOK"):
        vis_miles = 10.0

    # Find the lowest ceiling (BKN or OVC layer)
    ceiling_ft = None
    for tok in sky_tokens:
        m = re.match(r"(BKN|OVC)(\d{3})", tok)
        if m:
            h = int(m.group(2)) * 100
            if ceiling_ft is None or h < ceiling_ft:
                ceiling_ft = h
    if ceiling_ft is None:
        ceiling_ft = 99999  # no ceiling reported = unlimited

    if vis_miles is not None:
        if vis_miles < 1 or ceiling_ft < 500:
            return "LIFR", "Low IFR", "danger"
        if vis_miles < 3 or ceiling_ft < 1000:
            return "IFR", "IFR", "warning"
        if vis_miles <= 5 or ceiling_ft <= 3000:
            return "MVFR", "Marginal VFR", "info"
    return "VFR", "Visual Flight Rules", "success"


# ---------------------------------------------------------------------------
# Remarks decoder
# ---------------------------------------------------------------------------

def decode_remarks(tokens):
    """
    Decode common RMK (remarks) tokens appended after the main METAR body.
    Handles: PK WND, SLP (sea-level pressure), T-group (precise temp), P-group (precip).
    Returns a list of decoded strings.
    """
    decoded = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]

        # Peak wind: PK WND dddff/HHmm
        m = re.match(r"^PK WND (\d{3})(\d{2,3})/(\d{2,4})$", tok)
        if m:
            decoded.append(f"Peak wind {m.group(1)}° at {m.group(2)} kt at {m.group(3)}")
            i += 1
            continue

        # Sea-level pressure: SLPppp (last 3 digits; leading 9 or 10 inferred)
        m = re.match(r"^SLP(\d{3})$", tok)
        if m:
            slp = int(m.group(1))
            # Values < 500 are prefixed with 10xx, >= 500 with 9xx
            slp_hpa = (9000 + slp) / 10 if slp < 500 else (8000 + slp) / 10
            decoded.append(f"Sea-level pressure: {slp_hpa:.1f} hPa")
            i += 1
            continue

        # Precise temperature group: Tsss/ddd (sign bit 0=positive, 1=negative)
        m = re.match(r"^T([01]\d{3})([01]\d{3})$", tok)
        if m:
            def parse_tg(s):
                sign = -1 if s[0] == "1" else 1
                return sign * int(s[1:]) / 10
            t = parse_tg(m.group(1))
            d = parse_tg(m.group(2))
            decoded.append(f"Precise temp: {t}°C, dew point: {d}°C")
            i += 1
            continue

        # Hourly precipitation: Pppp (hundredths of an inch)
        m = re.match(r"^P(\d{4})$", tok)
        if m:
            precip = int(m.group(1)) / 100
            decoded.append(f"Hourly precipitation: {precip:.2f} inches")
            i += 1
            continue

        i += 1
    return decoded


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def decode_metar(raw):
    """
    Parse a complete raw METAR string and return a structured dict containing:
      - 'raw'             : original METAR string
      - 'station'         : ICAO identifier
      - 'fields'          : list of {label, value, icon} dicts for display
      - 'flight_category' : {code, label, class} for VFR/MVFR/IFR/LIFR badge
      - 'errors'          : list of any parse warnings

    The function is intentionally permissive — unknown tokens are skipped
    rather than raising exceptions, so a partial decode is always returned.
    """
    result = {"raw": raw, "fields": [], "errors": []}
    tokens = raw.strip().split()
    if not tokens:
        result["errors"].append("Empty METAR string.")
        return result

    idx = 0  # current token index

    # --- Report type (optional prefix) ---
    if tokens[idx] in ("METAR", "SPECI"):
        report_type = (
            "Routine Observation" if tokens[idx] == "METAR"
            else "Special Observation (significant change)"
        )
        result["fields"].append({"label": "Report Type", "value": report_type, "icon": "clipboard"})
        idx += 1

    # --- AUTO flag (fully automated station, no human observer) ---
    auto = False
    if idx < len(tokens) and tokens[idx] == "AUTO":
        auto = True
        idx += 1

    # --- Station identifier ---
    if idx < len(tokens):
        result["station"] = tokens[idx]
        result["fields"].append({
            "label": "Station",
            "value": tokens[idx] + (" (Automated Station)" if auto else ""),
            "icon": "map-pin",
        })
        idx += 1

    # --- Observation date/time (DDHHmmZ) ---
    if idx < len(tokens) and re.match(r"^\d{6}Z$", tokens[idx]):
        t = tokens[idx]
        day, hour, minute = int(t[0:2]), int(t[2:4]), int(t[4:6])
        now = datetime.now(timezone.utc)
        result["fields"].append({
            "label": "Observation Time",
            "value": f"Day {day} of month, {hour:02d}:{minute:02d} UTC (current UTC: {now.strftime('%H:%M')})",
            "icon": "clock",
        })
        idx += 1

    # --- COR: corrected report ---
    if idx < len(tokens) and tokens[idx] == "COR":
        result["fields"].append({
            "label": "Note", "value": "This is a corrected observation", "icon": "alert-circle"
        })
        idx += 1

    # --- Wind group ---
    if idx < len(tokens) and re.match(r"^(VRB|\d{3})\d{2,3}(G\d{2,3})?(KT|MPS|KMH)$", tokens[idx]):
        decoded = decode_wind(tokens[idx])
        if decoded:
            result["fields"].append({"label": "Wind", "value": decoded, "icon": "wind"})
        idx += 1

    # --- Wind variability range (e.g. '280V350' after the main wind group) ---
    if idx < len(tokens) and re.match(r"^\d{3}V\d{3}$", tokens[idx]):
        m = re.match(r"^(\d{3})V(\d{3})$", tokens[idx])
        if m:
            v1, v2 = deg_to_compass(int(m.group(1))), deg_to_compass(int(m.group(2)))
            result["fields"].append({
                "label": "Wind Variable Between",
                "value": f"{m.group(1)}° ({v1}) and {m.group(2)}° ({v2})",
                "icon": "wind",
            })
        idx += 1

    # --- Visibility ---
    if idx < len(tokens):
        vis_token = tokens[idx]
        # US METARs sometimes split a mixed fraction across two tokens: '1 1/2SM'
        if re.match(r"^\d+$", vis_token) and idx + 1 < len(tokens) and re.match(r"^\d+/\d+SM$", tokens[idx + 1]):
            vis_token = vis_token + " " + tokens[idx + 1]
            idx += 1
        decoded = decode_visibility(vis_token)
        if decoded:
            # Store the original token for flight-category calculation
            result["visibility_token"] = tokens[idx] if "SM" in tokens[idx] else vis_token
            result["fields"].append({"label": "Visibility", "value": decoded, "icon": "eye"})
            idx += 1

    # --- Runway Visual Range (RVR) — reported but not further decoded ---
    while idx < len(tokens) and re.match(r"^R\d{2}[LCR]?/", tokens[idx]):
        result["fields"].append({"label": "Runway Visual Range", "value": tokens[idx], "icon": "eye"})
        idx += 1

    # --- Weather phenomena and sky condition groups ---
    weather_list = []
    sky_tokens = []   # kept for flight-category ceiling calculation

    while idx < len(tokens):
        tok = tokens[idx]

        # CAVOK shorthand: no significant cloud, no precipitation, vis > 10 km
        if tok == "CAVOK":
            result["fields"].append({
                "label": "Sky Condition",
                "value": "CAVOK — No significant clouds below 5,000 ft, no precipitation, visibility > 10 km",
                "icon": "sun",
            })
            result.setdefault("visibility_token", "CAVOK")
            idx += 1
            continue

        wx = decode_weather(tok)
        if wx:
            weather_list.append(wx)
            idx += 1
            continue

        # Sky condition layer (FEW/SCT/BKN/OVC)
        if re.match(r"^(FEW|SCT|BKN|OVC|SKC|CLR)", tok):
            sky = decode_sky(tok)
            if sky:
                sky_tokens.append(tok)
                result["fields"].append({"label": "Cloud Layer", "value": sky, "icon": "cloud"})
                idx += 1
                continue

        # Vertical visibility (sky obscured): VV/// or VVddd
        if tok == "VV///" or re.match(r"^VV\d{3}$", tok):
            m = re.match(r"^VV(\d{3})$", tok)
            if m:
                ht = int(m.group(1)) * 100
                result["fields"].append({
                    "label": "Vertical Visibility",
                    "value": f"{ht:,} ft (sky obscured)",
                    "icon": "cloud",
                })
            else:
                result["fields"].append({
                    "label": "Vertical Visibility",
                    "value": "Indefinite ceiling (sky obscured)",
                    "icon": "cloud",
                })
            sky_tokens.append(tok)
            idx += 1
            continue

        break  # unrecognised token — likely start of temp group or RMK

    if weather_list:
        result["fields"].append({"label": "Weather", "value": "; ".join(weather_list), "icon": "cloud-rain"})

    # --- Temperature / Dew point ---
    if idx < len(tokens) and re.match(r"^M?\d{2}/M?\d{2}$", tokens[idx]):
        temp, dew = decode_temp_dewpoint(tokens[idx])
        if temp and dew:
            temp_c, temp_f = temp
            dew_c, dew_f = dew
            result["fields"].append({"label": "Temperature", "value": f"{temp_c}°C ({temp_f}°F)", "icon": "thermometer"})
            result["fields"].append({"label": "Dew Point", "value": f"{dew_c}°C ({dew_f}°F)", "icon": "droplets"})
            # Small spread -> moisture near saturation -> fog/low cloud risk
            spread = temp_c - dew_c
            if spread <= 2:
                fog_risk = "High fog/low cloud risk (small temperature-dew point spread)"
            elif spread <= 5:
                fog_risk = "Moderate fog risk"
            else:
                fog_risk = "Low fog risk"
            result["fields"].append({
                "label": "Temp/Dew Point Spread",
                "value": f"{spread}°C — {fog_risk}",
                "icon": "activity",
            })
            idx += 1

    # --- Altimeter / QNH ---
    if idx < len(tokens) and re.match(r"^[AQ]\d{4}$", tokens[idx]):
        alt = decode_altimeter(tokens[idx])
        if alt:
            result["fields"].append({"label": "Altimeter / QNH", "value": alt, "icon": "gauge"})
        idx += 1

    # --- Remarks section ---
    if idx < len(tokens) and tokens[idx] == "RMK":
        idx += 1
        remarks_raw = " ".join(tokens[idx:])
        remark_parts = decode_remarks(tokens[idx:])
        result["fields"].append({"label": "Remarks (Raw)", "value": remarks_raw, "icon": "message-square"})
        if remark_parts:
            result["fields"].append({
                "label": "Remarks Decoded",
                "value": " | ".join(remark_parts),
                "icon": "info",
            })

    # --- Flight category badge ---
    vis_tok = result.get("visibility_token", "")
    cat, cat_label, cat_class = flight_category(vis_tok, sky_tokens)
    result["flight_category"] = {"code": cat, "label": cat_label, "class": cat_class}

    return result

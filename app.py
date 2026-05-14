"""
app.py
------
Flask web application for the METAR Reader.

Routes:
  GET  /          — Landing page with search form
  POST /decode    — Fetch a live METAR for the given ICAO code and render the
                    decoded result
  GET  /api/decode?icao=XXXX — JSON API endpoint for programmatic access

Data source: aviationweather.gov (FAA / NOAA) — no API key required.
"""

from flask import Flask, render_template, request, jsonify
import requests
from metar_decoder import decode_metar

app = Flask(__name__)

# Aviation Weather Center METAR endpoint (returns JSON by default)
AVWX_URL = "https://aviationweather.gov/api/data/metar"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_metar(icao):
    """
    Fetch the latest METAR observation for the given ICAO station identifier.

    Returns a 3-tuple: (raw_metar, station_name, location_string)
      - raw_metar      : the raw METAR string (e.g. 'KJFK 141851Z ...')
      - station_name   : human-readable name returned by the API (e.g. 'JFK INTL')
      - location_string: formatted lat/lon string, or an error message if the
                         fetch failed (in which case raw_metar is None)
    """
    icao = icao.strip().upper()
    try:
        resp = requests.get(
            AVWX_URL,
            params={"ids": icao, "format": "json", "taf": "false"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()

        # API returns a list when multiple stations are queried; we only ask for one
        entry = None
        if isinstance(data, list) and data:
            entry = data[0]
        elif isinstance(data, dict):
            entry = data

        if not entry:
            return None, None, None

        raw = entry.get("rawOb") or entry.get("raw_text")
        # Station name comes back in 'name' (newer API) or 'site' (legacy)
        name = (entry.get("name") or entry.get("site") or "").strip()
        # Build a lat/lon label if coordinates are present
        lat = entry.get("lat")
        lon = entry.get("lon")
        location = None
        if lat is not None and lon is not None:
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            location = f"{abs(lat):.2f}°{ns}, {abs(lon):.2f}°{ew}"

        return raw, name, location

    except requests.exceptions.Timeout:
        return None, None, "Request timed out. Try again."
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return None, None, f"Airport '{icao}' not found."
        return None, None, f"HTTP error: {e}"
    except Exception as e:
        return None, None, str(e)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    """Render the empty search page."""
    return render_template("index.html")


@app.route("/decode", methods=["POST"])
def decode():
    """
    Accept an ICAO code from the HTML form, fetch the live METAR,
    decode it, and render the results page.
    """
    icao = request.form.get("icao", "").strip().upper()

    # Basic validation before hitting the external API
    if not icao:
        return render_template("index.html", error="Please enter an airport ICAO code.")
    if len(icao) < 3 or len(icao) > 4:
        return render_template(
            "index.html",
            error="ICAO codes are 3–4 characters (e.g. KJFK, EGLL).",
            icao=icao,
        )

    raw, name, location = fetch_metar(icao)

    # When raw is None, location holds the error message
    if raw is None:
        err = location or f"No METAR data available for {icao}."
        return render_template("index.html", error=err, icao=icao)

    decoded = decode_metar(raw)
    # Fall back to the ICAO code itself if the API didn't return a name
    airport_name = name or icao
    return render_template(
        "index.html",
        decoded=decoded,
        icao=icao,
        airport_name=airport_name,
        location=location,
    )


@app.route("/api/decode", methods=["GET"])
def api_decode():
    """
    JSON API endpoint — returns the fully decoded METAR as a JSON object.
    Query parameter: icao (required)
    Example: GET /api/decode?icao=EGLL
    """
    icao = request.args.get("icao", "").strip().upper()
    if not icao:
        return jsonify({"error": "icao parameter required"}), 400

    raw, name, location = fetch_metar(icao)
    if raw is None:
        return jsonify({"error": location or f"No data for {icao}"}), 404

    result = decode_metar(raw)
    result["airport_name"] = name or icao
    result["location"] = location
    return jsonify(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # debug=True enables auto-reload and the interactive debugger
    # Do NOT use debug=True in production
    app.run(debug=True, port=5000)

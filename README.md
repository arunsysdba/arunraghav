# ✈️ METAR Reader

A Flask web application that fetches live METAR weather reports for any airport and decodes them into plain English.

## What is a METAR?

A **METAR** (Meteorological Aerodrome Report) is a standardised weather observation issued by airports worldwide. The format is highly abbreviated and cryptic — for example:

```
KJFK 141851Z 27015G25KT 10SM FEW045 BKN250 22/14 A2992 RMK AO2 SLP132
```

This app translates every token into human-readable text.

## Features

- Live METAR data fetched from [aviationweather.gov](https://aviationweather.gov) (no API key required)
- Full token-by-token decoding: wind, visibility, clouds, temperature, altimeter, remarks
- Flight category badge: **VFR / MVFR / IFR / LIFR** with colour coding
- Temperature ↔ dew-point spread with fog-risk assessment
- Dual units throughout (metric + imperial)
- JSON API endpoint for programmatic access
- Clean dark-themed UI with quick-pick buttons for major airports

## Quick Start

```bash
# Clone and install
git clone https://github.com/<your-username>/metar-reader.git
cd metar-reader
pip install -r requirements.txt

# Run
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

## API

```
GET /api/decode?icao=EGLL
```

Returns the decoded METAR as JSON.

## Tech Stack

- **Backend**: Python 3 / Flask
- **Data**: [aviationweather.gov](https://aviationweather.gov/api/data/metar)
- **Frontend**: Tailwind CSS (CDN), vanilla JS

## Disclaimer

For educational and reference purposes only. **Do not use for flight planning or operational decisions.**

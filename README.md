# ELD Trip Planner

A full-stack Django + React project for the assessment that accepts:

- current location
- pickup location
- dropoff location
- current cycle used (hours)

…and returns:

- a route map with planned stops
- a stop-by-stop HOS-compliant trip plan
- completed daily log sheets rendered graphically

## What this implementation covers

This project is built around the assessment requirements from the uploaded instructions and the FMCSA HOS guide:

- Django backend + React frontend
- free map stack using Nominatim + OSRM
- property-carrying driver assumptions
- 70-hour / 8-day cycle
- 11-hour driving limit
- 14-hour driving window
- 10 consecutive hours off duty before driving again
- 30-minute break after 8 cumulative driving hours
- fuel stop at least every 1,000 miles
- 1 hour on-duty for pickup and 1 hour on-duty for dropoff
- paper-style daily log sheets with remarks and totals

## Important assumptions

Because the assessment input does **not** provide prior 8-day detail, only the current accumulated cycle hours, the planner makes one explicit operational assumption:

- when the driver reaches the weekly 70-hour limit and still has driving left, the planner inserts a **34-hour restart**

That is a safe, explainable approach for this assessment when the full historical 8-day distribution is unavailable.

This version intentionally does **not** model:

- adverse driving conditions
- split sleeper berth
- short-haul exceptions
- live truck stop search / real POI fuel discovery
- exact paper-log legal formatting edge cases for every exception

## Stack

### Backend
- Django 5
- Django REST Framework
- django-cors-headers
- requests

### Frontend
- React + Vite
- react-leaflet
- Leaflet

### Free routing / geocoding
- Nominatim for geocoding
- OSRM public demo server for routing

## Project structure

```text
eld-trip-planner/
  backend/
    api/
      services/
        geocoding.py
        routing.py
        hos.py
      serializers.py
      views.py
      tests.py
    config/
      settings.py
      urls.py
  frontend/
    public/
      blank-paper-log.png
    src/
      components/
        TripForm.jsx
        RouteMap.jsx
        SummaryCards.jsx
        StopsTable.jsx
        DailyLogSheet.jsx
      App.jsx
      api.js
```

## Local setup

### 1) Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Backend runs at:

```text
http://127.0.0.1:8000
```

### 2) Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Frontend runs at:

```text
http://127.0.0.1:5173
```

## Environment variables

### backend/.env.example

```env
DEBUG=True
SECRET_KEY=change-me
ALLOWED_HOSTS=127.0.0.1,localhost
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
USER_AGENT=eld-trip-planner-demo/1.0
GEOCODER_URL=https://nominatim.openstreetmap.org/search
ROUTER_URL=https://router.project-osrm.org/route/v1/driving
```

### frontend/.env.example

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## API

### `POST /api/trips/plan/`

Request:

```json
{
  "current_location": "Dallas, TX",
  "pickup_location": "Nashville, TN",
  "dropoff_location": "Atlanta, GA",
  "current_cycle_used": 38
}
```

Response includes:

- route summary
- planned stops
- planning assumptions
- daily logs
- map polyline coordinates

## Deploy notes

### Frontend
- deploy `frontend` to Vercel

### Backend
- deploy `backend` to Render or Railway
- set the frontend domain in `CORS_ALLOWED_ORIGINS`
- set `DEBUG=False`
- set a real `SECRET_KEY`

## Testing

Run backend tests with:

```bash
cd backend
python manage.py test
```

## Demo behavior notes

- Breaks are inserted as soon as the 8-hour cumulative driving threshold is reached.
- Fuel stops are inserted every 1,000 route miles.
- Pickup and dropoff each consume 1 hour of on-duty time.
- Daily logs are generated from the planned activity timeline and split by calendar day.
- The paper log sheet is rendered in the frontend by drawing an SVG path over the provided blank log template image.

## Suggested next improvements

- exact timezone handling by geocoded location / route
- reverse geocoding for break and fuel stop labels
- optional user-selected trip start date/time
- PDF export of completed daily logs
- commercial fuel / rest POI lookup
- persistence of trip history
- screenshot / image export of log sheets

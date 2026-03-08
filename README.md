# 🛡 SafeRoute — Crime-Aware Navigation for Chicago

> **Hackathon Project** | Crime-aware A\* pathfinding that routes pedestrians around danger zones using real Chicago crime data.

---

## What It Does

SafeRoute analyzes 600,000+ real crime incidents in Chicago and builds a danger-weighted street graph. When you enter an origin and destination, it computes **three routes simultaneously**:

| Route | Strategy |
|-------|----------|
| ⚡ **Fastest** | Pure distance — shortest path, ignores crime |
| ⚖ **Balanced** | Modest detour — avoids the worst danger zones |
| 🛡 **Safest** | Maximum avoidance — routes around all high-crime clusters |

Safety scores update dynamically based on **time of day** — a route that scores 70/100 at noon may score 20/100 at 2 AM.

---

## Demo

![SafeRoute Screenshot](screenshot.png)

- Dark map with **red danger clusters** overlaid (HDBSCAN crime hotspots)
- Three colour-coded routes: red (fastest), blue (balanced), green (safest)
- Live safety score bars with time-of-day slider

---

## How It Works

### Pipeline

```
Chicago Crime CSV (2001–Present)
        ↓
  Step 1: Clean + filter data (analysis.ipynb)
        ↓
  Step 2: Assign severity scores per crime type
        ↓
  Step 3: HDBSCAN clustering → danger hotspots
        ↓
  Step 4: OSMnx street graph + danger_score on each edge
        ↓
  Step 5: A* routing with 3 safety weights (main.py)
        ↓
  Step 6: FastAPI backend + Leaflet.js frontend (index.html)
```

### A\* Cost Function

The core routing uses a **proportional danger penalty**:

```python
cost = length × (1 + danger^1.5 × time_multiplier × safety_weight)
```

- `danger_score` on each edge is derived from nearby crime cluster intensity
- `time_multiplier`: 1× day → 3× evening → 6× late night → 10× (0–5 AM)
- Hard distance caps prevent runaway detours at night

---

## Project Structure

```
saferoute/
├── main.py              # FastAPI backend — A* routing engine
├── analysis.ipynb       # Data cleaning, severity scoring, HDBSCAN clustering
├── astar_routing.py     # A* algorithm validation & testing
├── index.html           # Frontend — Leaflet.js map + sidebar UI
├── requirements.txt     # Python dependencies
└── README.md
```

> **Generated files (not in repo — see Setup below):**
> `chicago_crimes_clean.csv`, `chicago_clusters.json`, `chicago_safety_graph.graphml`

---

## Setup & Running

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/saferoute.git
cd saferoute
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Download the crime dataset

1. Go to [Chicago Data Portal — Crimes 2001 to Present](https://data.cityofchicago.org/Public-Safety/Crimes-2001-to-Present/ijzp-q8t2)
2. Click **Export → CSV**
3. Save as `Crimes_-_2001_to_Present.csv` in the project folder

### 4. Run the data pipeline

Open `analysis.ipynb` in Jupyter and run all cells top to bottom. This generates:
- `chicago_crimes_clean.csv`
- `chicago_clusters.json`
- `chicago_safety_graph.graphml`

> ⏱ HDBSCAN clustering on 80k sampled points takes ~3–5 minutes.

### 5. Start the backend

```bash
uvicorn main:app --reload --port 8000
```

You should see:
```
✅ Graph loaded: 42,XXX nodes, 98,XXX edges
✅ Clusters loaded: 85 clusters
```

### 6. Open the frontend

Simply open `index.html` in your browser:
```
file:///path/to/saferoute/index.html
```

The sidebar will show **API ONLINE · 85 CLUSTERS** when connected.

---

## Usage

1. **Click the map** to set your origin (orange dot)
2. **Click again** to set your destination (red dot)
3. **Drag the time slider** to simulate different hours of the day
4. Click **▶ CALCULATE ROUTES**
5. Toggle between Fastest / Balanced / Safest using the layer buttons

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Data processing | Python, Pandas, NumPy |
| Clustering | HDBSCAN (density-based crime hotspots) |
| Street graph | OSMnx (OpenStreetMap) |
| Routing | Custom A\* with danger-weighted edges |
| Backend | FastAPI + Uvicorn |
| Frontend | Vanilla JS + Leaflet.js |
| Map tiles | CartoDB Dark Matter |

---

## Crime Severity Weights

| Crime Type | Severity |
|-----------|----------|
| Homicide | 10 |
| Criminal Sexual Assault | 10 |
| Kidnapping | 9 |
| Weapons Violation | 8 |
| Robbery | 8 |
| Assault | 7 |
| Battery | 6 |
| Stalking | 5 |
| Motor Vehicle Theft | 3 |
| Theft / Criminal Damage | 2 |

---

## API Reference

### `POST /route`
```json
{
  "start_lat": 41.8827,
  "start_lon": -87.6233,
  "end_lat": 41.9100,
  "end_lon": -87.6770,
  "hour": 2
}
```

Returns fastest, balanced, and safest route coordinates with safety scores.

### `GET /clusters`
Returns all HDBSCAN danger cluster centres, sizes, and intensities for the heatmap overlay.

### `GET /health`
Returns API status, graph node/edge count, and cluster count.

---

## Limitations

- Graph and clusters are precomputed for **Chicago only**
- Crime data accuracy depends on Chicago PD reporting
- Routing is optimized for **walking** (speed assumption: 5 km/h)
- Does not account for real-time incidents

---

## License

MIT License — feel free to fork and adapt for other cities.

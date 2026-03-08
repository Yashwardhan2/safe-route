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

---

## ⚡ Quick Setup & Run

### Step 1 — Clone the repo

```bash
git clone https://github.com/Yashwardhan2/safe-route.git
cd safe-route
```

### Step 2 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Download the prebuilt data files

These files are too large for GitHub. Download and place them in the project root folder.

📁 **[Download chicago_safety_graph.graphml + chicago_clusters.json from Google Drive](https://drive.google.com/drive/folders/1NPMAbZPd_lqyIjMvjXXdRVu7uQ7cuaPB?usp=drive_link)**

After downloading, your folder should look like:
```
safe-route/
├── chicago_safety_graph.graphml   ← downloaded
├── chicago_clusters.json          ← downloaded
├── main.py
├── index.html
├── requirements.txt
└── README.md
```

### Step 4 — Start the backend

Open a terminal in the project folder and run:

```bash
uvicorn main:app --reload --port 8000
```

Wait until you see **both** lines appear:
```
✅ Graph loaded: 42,XXX nodes, 98,XXX edges
✅ Clusters loaded: 85 clusters
```

> ⚠ Keep this terminal running. Do not close it.

### Step 5 — Open the frontend

Double-click `index.html` to open it in your browser.

The sidebar will show **🟢 API ONLINE · 85 CLUSTERS** when connected successfully.

---

## Usage

1. **Click the map** to set your origin (orange dot)
2. **Click again** to set your destination (red dot)
3. **Drag the time slider** to simulate different hours of the day
4. Click **▶ CALCULATE ROUTES**
5. Toggle Fastest / Balanced / Safest using the layer buttons
6. Hover over red circles to see danger cluster details

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `API OFFLINE` in sidebar | Make sure `uvicorn` is still running in terminal |
| `FileNotFoundError: chicago_safety_graph.graphml` | Download from Drive link above, place in project root |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |
| Blank map / routes not showing | Check terminal for errors, ensure port 8000 is free |

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

### `GET /clusters`
Returns all HDBSCAN danger cluster centres, sizes, and intensities.

### `GET /health`
Returns API status, node/edge count, and cluster count.

---

## Want to Regenerate the Data from Scratch?

1. Download crime data from [Chicago Data Portal](https://data.cityofchicago.org/Public-Safety/Crimes-2001-to-Present/ijzp-q8t2) → Export → CSV
2. Save as `Crimes_-_2001_to_Present.csv` in the project root
3. Open `analysis.ipynb` in Jupyter and run all cells

> ⏱ Takes ~10–15 minutes total.

---

## Limitations

- Precomputed for **Chicago only**
- Crime data accuracy depends on Chicago PD reporting
- Optimized for **walking** (5 km/h assumption)
- Does not account for real-time incidents

---

## License

MIT License — feel free to fork and adapt for other cities.

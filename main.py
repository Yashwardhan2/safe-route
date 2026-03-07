# ── STEP 5: FASTAPI BACKEND ───────────────────────────────
# File: main.py
# Run with: uvicorn main:app --reload --port 8000

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import osmnx as ox
import heapq
import json
import numpy as np
from math import radians, sin, cos, sqrt, atan2
from contextlib import asynccontextmanager

# ── GLOBAL STATE (loaded once on startup) ─────────────────
G            = None
cluster_info = None


# ── STARTUP: LOAD GRAPH + CLUSTERS ────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global G, cluster_info

    print("Loading graph...")
    G = ox.load_graphml("chicago_safety_graph.graphml")
    print(f"✅ Graph loaded: {G.number_of_nodes():,} nodes, "
          f"{G.number_of_edges():,} edges")

    print("Loading clusters...")
    with open("chicago_clusters.json", "r") as f:
        raw = json.load(f)
    # json keys are always strings — convert back to int
    cluster_info = {int(k): v for k, v in raw.items()}
    print(f"✅ Clusters loaded: {len(cluster_info)} clusters")

    yield   # app runs here

    print("Shutting down...")


app = FastAPI(
    title="SafeRoute API",
    description="Crime-aware A* routing for Chicago",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow frontend (any origin during dev — tighten in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REQUEST / RESPONSE SCHEMAS ────────────────────────────
class RouteRequest(BaseModel):
    start_lat: float
    start_lon: float
    end_lat:   float
    end_lon:   float
    hour:      int = 12        # default to noon


class RouteInfo(BaseModel):
    coordinates:    list[list[float]]   # [[lat, lon], ...]
    safety_score:   float
    total_length_m: float


class RouteResponse(BaseModel):
    fastest:  RouteInfo | None
    balanced: RouteInfo | None
    safest:   RouteInfo | None
    hour:     int


# ── HELPER FUNCTIONS ──────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi       = radians(lat2 - lat1)
    dlambda    = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dlambda/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def get_time_multiplier(hour: int) -> float:
    if   6  <= hour <= 17: return 1.0
    elif 18 <= hour <= 21: return 3.0
    elif 22 <= hour <= 23: return 6.0
    else:                  return 10.0   # 0-5 AM


def compute_edge_cost(data: dict, hour: int, safety_weight: float) -> float:
    length        = float(data.get("length", 50))
    danger        = float(data.get("danger_score", 0.0))
    time_mult     = get_time_multiplier(hour)
    danger_penalty = (danger ** 1.5) * 500 * time_mult * safety_weight
    return max(1.0, length + danger_penalty)


def calculate_safety_score(path_nodes: list, hour: int) -> float:
    if len(path_nodes) < 2:
        return 50.0

    dangers = []
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i + 1]
        if G.has_edge(u, v):
            edge = min(G[u][v].values(),
                       key=lambda d: float(d.get("length", 50)))
            dangers.append(float(edge.get("danger_score", 0.0)))

    if not dangers:
        return 50.0

    avg_danger       = np.mean(dangers)
    time_mult        = get_time_multiplier(hour)
    danger_component = avg_danger * 70
    time_component   = ((time_mult - 1) / 9) * 30
    score            = 100 - danger_component - time_component
    return round(float(np.clip(score, 0, 100)), 1)


# ── A* ALGORITHM ──────────────────────────────────────────
def astar(start_node: int, end_node: int,
          hour: int, safety_weight: float) -> list | None:

    end_lat = G.nodes[end_node]["y"]
    end_lon = G.nodes[end_node]["x"]

    def heuristic(node):
        return haversine(G.nodes[node]["y"], G.nodes[node]["x"],
                         end_lat, end_lon)

    open_set  = []
    came_from = {}
    g_score   = {start_node: 0.0}
    visited   = set()
    heapq.heappush(open_set, (heuristic(start_node), start_node))

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == end_node:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(start_node)
            path.reverse()
            return path

        if current in visited:
            continue
        visited.add(current)

        for neighbor in G.neighbors(current):
            if neighbor in visited:
                continue
            edge_data = min(
                G[current][neighbor].values(),
                key=lambda d: compute_edge_cost(d, hour, safety_weight),
            )
            tentative_g = (g_score[current] +
                           compute_edge_cost(edge_data, hour, safety_weight))

            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor]   = tentative_g
                f = tentative_g + heuristic(neighbor)
                heapq.heappush(open_set, (f, neighbor))

    return None   # no path found


# ── ROUTE ENDPOINT ────────────────────────────────────────
@app.post("/route", response_model=RouteResponse)
def get_routes(req: RouteRequest):
    if not (0 <= req.hour <= 23):
        raise HTTPException(status_code=400,
                            detail="hour must be 0–23")

    # Snap to nearest graph nodes
    try:
        start_node = ox.nearest_nodes(G, X=req.start_lon, Y=req.start_lat)
        end_node   = ox.nearest_nodes(G, X=req.end_lon,   Y=req.end_lat)
    except Exception as e:
        raise HTTPException(status_code=400,
                            detail=f"Could not find nodes: {e}")

    configs = [
        ("fastest",  0.0),
        ("balanced", 0.5),
        ("safest",   1.0),
    ]

    results = {}
    for name, weight in configs:
        path = astar(start_node, end_node, req.hour, weight)
        if path is None:
            results[name] = None
            continue

        coords = [[G.nodes[n]["y"], G.nodes[n]["x"]] for n in path]
        total_len = sum(
            float(
                min(G[path[i]][path[i+1]].values(),
                    key=lambda d: float(d.get("length", 50))
                    ).get("length", 50)
            )
            for i in range(len(path) - 1)
            if G.has_edge(path[i], path[i+1])
        )
        score = calculate_safety_score(path, req.hour)
        results[name] = RouteInfo(
            coordinates=coords,
            safety_score=score,
            total_length_m=round(total_len, 1),
        )

    return RouteResponse(
        fastest=results.get("fastest"),
        balanced=results.get("balanced"),
        safest=results.get("safest"),
        hour=req.hour,
    )


# ── CLUSTERS ENDPOINT (for heatmap overlay) ───────────────
@app.get("/clusters")
def get_clusters():
    """Return all cluster centres + metadata for the map heatmap."""
    return {
        "clusters": [
            {
                "id":          cid,
                "lat":         info["centre_lat"],
                "lon":         info["centre_lon"],
                "intensity":   info["intensity"],
                "size":        info["size"],
                "peak_hour":   info["peak_hour"],
                "avg_severity": info["avg_severity"],
                # radius in metres — proportional to cluster size
                "radius_m":    int(min(info["size"] * 8, 1500)),
            }
            for cid, info in cluster_info.items()
        ],
        "total": len(cluster_info),
    }


# ── HEALTH CHECK ──────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status":   "ok",
        "nodes":    G.number_of_nodes() if G else 0,
        "edges":    G.number_of_edges() if G else 0,
        "clusters": len(cluster_info)   if cluster_info else 0,
    }


# ── DEV SERVER ────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
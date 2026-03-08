# ── FASTAPI BACKEND ───────────────────────────────────────
# File: main.py
# Run with: uvicorn main:app --reload --port 8000
#
# FIX: Balanced route was 66km when fastest=40km and safest=67km.
# Root cause: weight=0.2 produced nearly the same penalty as weight=1.0.
# Solution:
#   [1] Balanced weight 0.2 → 0.05  (4× weaker penalty)
#   [2] astar() accepts optional max_length cap
#   [3] Balanced capped at fastest × 1.30 (max 30% longer)
#   [4] Safest capped at fastest × 1.80 (max 80% longer — unchanged behaviour)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import osmnx as ox
import heapq
import json
import numpy as np
from math import radians, sin, cos, sqrt, atan2
from contextlib import asynccontextmanager

# ── GLOBAL STATE ──────────────────────────────────────────
G            = None
cluster_info = None


# ── STARTUP ───────────────────────────────────────────────
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
    cluster_info = {int(k): v for k, v in raw.items()}
    print(f"✅ Clusters loaded: {len(cluster_info)} clusters")

    yield
    print("Shutting down...")


app = FastAPI(
    title="SafeRoute API",
    description="Crime-aware A* routing for Chicago",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── SCHEMAS ───────────────────────────────────────────────
class RouteRequest(BaseModel):
    start_lat: float
    start_lon: float
    end_lat:   float
    end_lon:   float
    hour:      int = 12

class RouteInfo(BaseModel):
    coordinates:    list[list[float]]
    safety_score:   float
    total_length_m: float
    extra_minutes:  float = 0.0
    danger_avoided: bool  = False

class RouteResponse(BaseModel):
    fastest:      RouteInfo | None
    balanced:     RouteInfo | None
    safest:       RouteInfo | None
    hour:         int
    already_safe: bool = False
    message:      str  = ""


# ── HELPERS ───────────────────────────────────────────────
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
    else:                  return 10.0   # 0–5 AM


def compute_edge_cost(data: dict, hour: int, safety_weight: float) -> float:
    """
    PROPORTIONAL formula (Gemini's insight, validated).

    Cost = length × (1 + danger^1.5 × time_mult × weight)

    Why proportional beats additive:
      Additive flat +500 means a 50m dangerous alley costs 350m (600% markup)
      while a 2km dangerous boulevard costs 2300m (only 15% markup).
      This is backwards — longer dangerous roads should cost MORE to traverse.

    Proportional fixes this: every dangerous edge scales with its own length.
      danger=0.7, daytime:
        balanced(1.5): 100m → 188m  (1.9×)
        safest(5.0):   100m → 393m  (3.9×)
      Safest is always 2–2.3× more expensive than balanced at the same edge,
      guaranteeing the two modes find genuinely different paths.

    Night explosion is handled by the distance caps in astar(), not here.
    """
    length    = float(data.get("length", 50))
    danger    = float(data.get("danger_score", 0.0))
    time_mult = get_time_multiplier(hour)
    factor    = (danger ** 1.5) * time_mult * safety_weight
    return max(1.0, length * (1.0 + factor))


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


# ── A* WITH OPTIONAL DISTANCE CAP ─────────────────────────
def astar(start_node: int, end_node: int,
          hour: int, safety_weight: float,
          max_length: float = float('inf')) -> list | None:
    """
    FIX [2]: max_length caps the physical distance A* is allowed to travel.
    Edges that would push total real distance beyond max_length are pruned.
    This is the hard guarantee that balanced never takes a 66km path.
    """
    end_lat = G.nodes[end_node]["y"]
    end_lon = G.nodes[end_node]["x"]

    def heuristic(node):
        return haversine(G.nodes[node]["y"], G.nodes[node]["x"],
                         end_lat, end_lon)

    open_set  = []
    came_from = {}
    g_score   = {start_node: 0.0}
    real_dist = {start_node: 0.0}   # tracks actual metres, separate from weighted cost
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

            # ── Prune if this edge would exceed the physical cap ──
            real_step = float(edge_data.get("length", 50))
            new_real  = real_dist.get(current, 0.0) + real_step
            if new_real > max_length:
                continue

            tentative_g = (g_score[current] +
                           compute_edge_cost(edge_data, hour, safety_weight))

            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor]  = current
                g_score[neighbor]    = tentative_g
                real_dist[neighbor]  = new_real
                f = tentative_g + heuristic(neighbor)
                heapq.heappush(open_set, (f, neighbor))

    return None


# ── ROUTE ENDPOINT ────────────────────────────────────────
@app.post("/route", response_model=RouteResponse)
def get_routes(req: RouteRequest):
    if not (0 <= req.hour <= 23):
        raise HTTPException(status_code=400, detail="hour must be 0–23")

    try:
        start_node = ox.nearest_nodes(G, X=req.start_lon, Y=req.start_lat)
        end_node   = ox.nearest_nodes(G, X=req.end_lon,   Y=req.end_lat)
    except Exception as e:
        raise HTTPException(status_code=400,
                            detail=f"Could not find nodes: {e}")

    # Step 1: find fastest (no penalty) to get baseline distance
    fastest_path = astar(start_node, end_node, req.hour, 0.0)
    if fastest_path is None:
        raise HTTPException(status_code=404, detail="No path found")

    fastest_len = sum(
        float(min(G[fastest_path[i]][fastest_path[i+1]].values(),
              key=lambda d: float(d.get("length", 50))
              ).get("length", 50))
        for i in range(len(fastest_path) - 1)
        if G.has_edge(fastest_path[i], fastest_path[i+1])
    )

    # ── FIX [3] + [4]: Hard distance caps ─────────────────
    # BALANCED: max 55% longer than fastest.
    # Raised from ×1.30 — old cap was too tight; when no path found
    # within 30%, balanced fell back to fastest (identical routes).
    # ×1.55 gives A* enough room to find a genuine intermediate path.
    # On the 18.78km baseline → balanced can go up to 29.1km.
    balanced_cap = fastest_len * 1.55

    # SAFEST: max 80% longer than fastest.
    # On a 40km trip → safest can go up to 72km (plenty of room).
    # Adjust this multiplier up/down to taste.
    safest_cap = fastest_len * 1.80

    def path_to_info(path):
        coords = [[G.nodes[n]["y"], G.nodes[n]["x"]] for n in path]
        total_len = sum(
            float(min(G[path[i]][path[i+1]].values(),
                  key=lambda d: float(d.get("length", 50))
                  ).get("length", 50))
            for i in range(len(path) - 1)
            if G.has_edge(path[i], path[i+1])
        )
        score      = calculate_safety_score(path, req.hour)
        extra_m    = max(0.0, total_len - fastest_len)
        extra_mins = round(extra_m / 83.3, 1)
        return RouteInfo(
            coordinates=coords,
            safety_score=score,
            total_length_m=round(total_len, 1),
            extra_minutes=extra_mins,
            danger_avoided=total_len > fastest_len * 1.05,
        )

    results = {"fastest": path_to_info(fastest_path)}

    # Weights tuned for proportional cost formula:
    #   balanced=3.0 → 2.76× markup on danger=0.7 edge (clear intermediate path)
    #   safest=5.0   → 3.93× markup on danger=0.7 edge (strong avoidance)
    # Weight raised 1.5→3.0 so balanced is no longer identical to fastest.
    # Distance caps still apply — night explosions are impossible.
    configs = [
        ("balanced", 3.0, balanced_cap),
        ("safest",   5.0, safest_cap),
    ]

    for name, weight, cap in configs:
        path = astar(start_node, end_node, req.hour, weight, cap)
        results[name] = path_to_info(path) if path else results["fastest"]

    # ── MESSAGE LOGIC ─────────────────────────────────────
    fastest_score  = results["fastest"].safety_score
    safest_score   = results["safest"].safety_score
    safest_len     = results["safest"].total_length_m

    routes_differ  = (safest_len - fastest_len) > (fastest_len * 0.05)
    score_improved = (safest_score - fastest_score) > 5
    already_safe   = (not routes_differ) and fastest_score >= 65

    if already_safe:
        message = (f"This route has no major danger zones. "
                   f"All paths are similar (score: {fastest_score}/100).")
    elif fastest_score < 50 and not routes_differ:
        message = (f"🚨 DANGER: All routes pass through high-crime zones "
                   f"(score: {fastest_score}/100). "
                   f"No safe alternative found within detour limit.")
    elif fastest_score < 50 and routes_differ and not score_improved:
        message = (f"🚨 DANGER: Route area is high-crime (score: {fastest_score}/100). "
                   f"Rerouting provides minimal improvement. Stay alert.")
    elif routes_differ and score_improved:
        mins        = round((safest_len - fastest_len) / 83.3, 1)
        improvement = round(safest_score - fastest_score, 1)
        message = (f"Safest route adds {mins} min but improves "
                   f"safety score by +{improvement} points.")
    else:
        message = "Minor rerouting available — see route options."

    return RouteResponse(
        fastest=results.get("fastest"),
        balanced=results.get("balanced"),
        safest=results.get("safest"),
        hour=req.hour,
        already_safe=already_safe,
        message=message,
    )


# ── CLUSTERS ENDPOINT ─────────────────────────────────────
@app.get("/clusters")
def get_clusters():
    return {
        "clusters": [
            {
                "id":           cid,
                "lat":          info["centre_lat"],
                "lon":          info["centre_lon"],
                "intensity":    info["intensity"],
                "size":         info["size"],
                "peak_hour":    info["peak_hour"],
                "avg_severity": info["avg_severity"],
                "radius_m":     int(min(info["size"] * 8, 1500)),
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
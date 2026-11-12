# Flying-Cars-Network-Team-2026

## 1. Rural NSW Vertiport Model

An optimization model that decides where to build vertiports so air taxis can give rural NSW communities fast emergency medical access. It is built in three phases, each extending the last.

## The Problem

Given candidate vertiport sites, SA2 regions (demand points) and emergency hospitals, choose the **fewest sites** so that a target share of SA2s can reach an emergency hospital within a time threshold `T`.

An SA2 is **covered** by a vertiport if:

> road time (SA2 → vertiport) + flight time (vertiport → nearest emergency hospital) ≤ `T`

Road times come from OpenStreetMaps (OSRM); flight times use haversine distance at 250 km/h.

## Phase 0: Base Model (`optim_model.py`)

A classic set-covering / maximal-coverage formulation.

- **Variables:** `y[i]` = build vertiport *i*; `z[j]` = SA2 *j* covered
- **Objective:** minimise Σ `y[i]`
- **Constraints:** `z[j] ≤ Σ a[i,j]·y[i]`, and covered SA2s ≥ α × total
- **Defaults:** T = 90 min, Speed = 250 km/h
- **Outputs:** selected sites, uncovered regions, sensitivity plots across T and α, and an interactive map

## Phase 1: Risk-Aware Model (`parametric_model.py`)

Adds an operational-risk penalty for weather so the model avoids hazardous sites.

**Objective:** minimise Σ `y[i]` + λ · Σ `risk[i]·y[i]`

Risk is a weighted blend of three hazards, each normalised to 0–1:

| Hazard | Basis | Weight |
|---|---|---|
| Bushfire | BFPL vegetation category | 3 |
| Wind | % of observations above threshold | 5 |
| Rain | Average mm/day and heavy-rain days | 1 |

**Mitigation discounts**
- **Bushfire:** −10% per nearby Category 1 site within 15 min (capped at 50%)
- **Wind:** −50% if a safe alternate vertiport is within 30 min

Sites with missing data get worst-case severity. λ controls the trade-off, so a site is only worth adding if it saves more than 1/λ in risk.

## Phase 2: Two-Stage Model (`parametric_model_two_stage.py`)

Existing candidates often cannot reach every SA2 (for example at 100% coverage). Stage 2 runs when this happens and recommends **new infrastructure**.

- **Candidate pool:** all NSW hospitals (de-duplicated within 0.3 km) plus open space (parks, showgrounds, ovals, sports grounds)
- **New decisions:** `q[p]` = build a helipad at site *p*; a site can only operate if built; new helipads can also serve as flight destinations
- **Costs:** hospital helipads carry a build penalty (2.0) plus risk; open-space pads carry none
- **Destination rule:** a park only counts as a destination if within 0.5 km by road of a hospital

**Outputs:** `stage2_new_helipads.csv`, `stage2_sa2_coverage.csv`, `stage2_candidate_pool.csv`, a stage-2 map (orange = covered only via new sites), and a combined two-stage sensitivity plot.

## Quick Start

```bash
pip install pandas numpy pyomo folium geopandas shapely matplotlib requests openpyxl
# CBC solver must be installed (or set VERTIPORT_SOLVER)
python optim_model.py                   # base model
python parametric_model.py              # + risk
python parametric_model_two_stage.py    # + new helipads / parks
```

**Required data:** vertiport, SA2, and hospital coordinate files; `d_ij.xlsx` and `vertiport_hospital_distances.xlsx`; bushfire, wind and rain risk files; the ABS SA2 shapefile; and (Phase 2) `All_NSW_hospitals_with_lat_lon.xlsx` and `nsw_openspace.csv`.

## Key Limitations
- Public OSRM road times are approximate
- Straight-line flight distances ignore terrain and airspace
- Open-space sites have no risk data and carry zero risk cost by default

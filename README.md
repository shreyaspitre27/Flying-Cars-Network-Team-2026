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


## 2. Airport Shuttle Model

An optimization model that decides where to build vertiports so eVTOL air taxis can shuttle NSW residents to **Western Sydney International (WSI) Airport**. It adapts the rural model to an airport-access use case and is based on the **Joby S4** (pilot + 4 passengers, 225 km/h cruise, 246 km range).

## The Problem

Given candidate vertiport sites and NSW suburbs (demand points), choose the **lowest-cost set of sites** so that a target share of the reachable population can get to WSI faster by driving to a vertiport and flying direct to the airport.

A suburb is **covered** by a vertiport if:

> road time (suburb → vertiport) ≤ 30 min
> flight time (vertiport → WSI, incl. 4 min takeoff/landing) ≤ `T`
> road time + flight time is at least 10 min faster than driving straight to WSI

Road times come from OpenStreetMaps (OSRM); flight times use haversine distance at 225 km/h. There is no fixed range limit, because `T` sets how far a vertiport can be from WSI (T = 60 min → 210 km, within the S4's 246 km range).

## Changes from the Rural Model

| | Rural model | Airport shuttle model |
|---|---|---|
| Demand | SA2 regions | ABS suburbs (2021 Census population) |
| Destination | Nearest emergency hospital | WSI only |
| Candidate sites | Existing vertiports and hospitals | Existing helipads/airfields + new-build parks, ovals, car parks and shopping-centre rooftops |
| Objective | Fewest sites (+ risk) | Lowest total build-cost index |
| Coverage target | Share of SA2s | Share of people and suburbs, statewide and per SA4 region |
| Hazards | Bushfire, wind, rain | Not modelled |

## Step 1: Suburb Demand (`prepare_suburb_demand.py`)

Builds the demand points from the ABS suburb (SAL) and SA4 boundaries and the 2021 Census population.

## Step 2: Candidate Sites

| Script | Purpose |
|---|---|
| `build_shuttle_vertiports_existing_sites.py` | Existing helipads, heliports, airfields and airports → `vertiport_shuttle_existing_candidates.xlsx` |
| `make_new_build_candidates.py` | New-build sites (parks, ovals, car parks, shopping-centre rooftops) from NSW Points of Interest → `vertiport_shuttle_new_build_candidates.xlsx` |
| `build_shuttle_vertiports.py` / `add_osm_parks_ovals.py` | Earlier candidate-building scripts → `vertiport_shuttle_candidates.xlsx` |
| `plot_all_vertiports.py` | Maps every candidate → `shuttle_vertiports_map.html` |

Each site gets a relative **cost index** by type:

| Site type | Cost index |
|---|---|
| Existing helipad, heliport, airfield or airport | 0.5 |
| Park/oval landing site or NSW POI helipad | 0.6 |
| New park or oval | 1.0 |
| New car park | 1.5 |
| New shopping-centre rooftop | 2.0 |

## Step 3: Optimization Model (`shuttle_optim_model.py`)

A set-covering model with population and regional targets.

- **Variables:** `y[j]` = build vertiport *j*; `z[i]` = suburb *i* covered
- **Objective:** minimise Σ `cost[j]·y[j]`
- **Constraints:**
  - `z[i] ≤ Σ a[i,j]·y[j]`
  - covered people ≥ 95% of reachable people statewide, and ≥ 80% in each SA4 region
  - covered suburbs ≥ 80% of populated suburbs statewide, and ≥ 70% in each SA4 region
- **Defaults:** T = 60 min, Speed = 225 km/h, max drive = 30 min, min time saving = 10 min
- **Solver:** CBC, 300 s time limit, 0.5% optimality gap
- **Outputs:** selected sites, suburb and region coverage CSVs, sensitivity plots across T (30/45/60 min) and coverage (70–95%), and an interactive map

## Results (T = 60 min, 95% coverage)

- **69 vertiports** (29 existing, 40 new-build), total cost index 55.1
- **1,582 suburbs, 6.2 million people** covered: 95% of reachable population, 77% of NSW
- Median trip to WSI is **41 min by eVTOL vs 101 min by car** (59% faster)
- The solver stopped at the time limit, within 2% of optimal

## Quick Start

```bash
pip install pandas numpy pyomo folium geopandas shapely matplotlib requests openpyxl
# CBC solver must be installed
python prepare_suburb_demand.py                     # suburb demand
python build_shuttle_vertiports_existing_sites.py   # existing sites
python make_new_build_candidates.py                 # new-build sites
python shuttle_optim_model.py                       # optimisation
```

**Required data:** the ABS SAL and SA4 shapefiles and the 2021 Census G01 DataPack; `nsw_poi_helipads.csv`; `vertiport_name_with_coord.xlsx`; and the existing and new-build candidate files. Road times are fetched from OSRM on the first run and cached, so later runs are faster.

## Key Limitations
- Each passenger boards at a single vertiport; rideshare pick-ups across several vertiports are not modelled
- Luggage weight and the S4's payload limit are not considered
- Public transport and weather/bushfire hazards are not modelled
- Road times assume no traffic, and flight range assumes no energy reserve
- Candidate sites are found by name and not checked for size or planning approval, and cost index values are relative assumptions

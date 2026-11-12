import pandas as pd
import numpy as np
from pyomo.environ import *
from math import radians, sin, cos, sqrt, atan2, floor
import requests
import time
import folium
from folium.plugins import MeasureControl
import matplotlib.pyplot as plt
import geopandas as gpd
from shapely.geometry import Point

#--------------------
# LOAD THE DATA SETS
#--------------------

dfi = pd.read_excel('vertiport_name_with_coord.xlsx')
dfj = pd.read_excel('sa2_names_with_coord.xlsx')
dfh = pd.read_excel('Emergency_hospitals_with_lat_lon.xlsx')

candidate_coords = dict(zip(dfi['name'],     zip(dfi['latitude'], dfi['longitude'])))
demand_coords    = dict(zip(dfj['SA2_Name'], zip(dfj['latitude'], dfj['longitude'])))
hospital_coords  = dict(zip(dfh['Name'],     zip(dfh['latitude'], dfh['longitude'])))

#--------------------
#   PARAMETERS
#--------------------
UAV_SPEED_KMH      = 250
TIME_THRESHOLD     = 90
COVERAGE_THRESHOLD = 0.85

#--------------------
# D_IH MATRIX
#--------------------
'''
def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

rows = []
for i, (i_lat, i_lon) in candidate_coords.items():
    for h, (h_lat, h_lon) in hospital_coords.items():
        dist = haversine_km(i_lat, i_lon, h_lat, h_lon)
        rows.append({'vertiport': i, 'hospital': h, 'distance_km': round(dist, 2)})

d_ih = pd.DataFrame(rows)
d_ih_pivot = d_ih.pivot(index='vertiport', columns='hospital', values='distance_km')
d_ih_pivot.to_excel('vertiport_hospital_distances.xlsx')
print('d_ih matrix saved')

#--------------------
# D_IJ MATRIX
#--------------------

def get_osrm_table(demand_coords, candidate_coords, chunk_size=25):
    demand_list    = list(demand_coords.keys())
    candidate_list = list(candidate_coords.keys())
    demand_vals    = list(demand_coords.values())
    candidate_vals = list(candidate_coords.values())
    rows = []

    for i_start in range(0, len(demand_list), chunk_size):
        i_keys = demand_list[i_start:i_start + chunk_size]
        i_vals = demand_vals[i_start:i_start + chunk_size]

        for j_start in range(0, len(candidate_list), chunk_size):
            j_keys = candidate_list[j_start:j_start + chunk_size]
            j_vals = candidate_vals[j_start:j_start + chunk_size]

            all_coords   = i_vals + j_vals
            coords_str   = ';'.join(f"{lon},{lat}" for lat, lon in all_coords)
            n_i          = len(i_keys)
            sources      = ';'.join(str(k) for k in range(n_i))
            destinations = ';'.join(str(k) for k in range(n_i, n_i + len(j_keys)))

            url = (f"http://router.project-osrm.org/table/v1/driving/{coords_str}"
                   f"?sources={sources}&destinations={destinations}&annotations=duration,distance")

            response = requests.get(url, timeout=60)
            data = response.json()

            for i, i_name in enumerate(i_keys):
                for j, j_name in enumerate(j_keys):
                    rows.append({
                        'sa2':         i_name,
                        'vertiport':   j_name,
                        'time_min':    data['durations'][i][j] / 60,
                        'distance_km': data['distances'][i][j] / 1000
                    })
            time.sleep(0.3)

    return pd.DataFrame(rows)

d_ij = get_osrm_table(demand_coords, candidate_coords)
d_ij.to_excel('d_ij.xlsx', index=False)
print("D_ij matrix saved")

'''
#--------------------
# LOAD MATRICES
#--------------------
d_ih = pd.read_excel('vertiport_hospital_distances.xlsx')
d_ih = d_ih.set_index('vertiport')
d_ij = pd.read_excel('d_ij.xlsx')

road_time_lookup = {(row['sa2'], row['vertiport']): row['time_min']
                    for _, row in d_ij.iterrows()}

#--------------------
# FUNCTIONS
#--------------------

def build_coverage_matrix(demand_coords, candidate_coords, road_time_lookup, d_ih, UAV_SPEED_KMH, T):
    a = {}
    for i in candidate_coords:
        for j in demand_coords:
            road_time = road_time_lookup[j, i]
            air_time  = d_ih.loc[i].min() / UAV_SPEED_KMH * 60
            a[i, j]   = 1 if road_time + air_time <= T else 0
    return a

def run_model(a, demand_coords, candidate_coords, alpha):
    I = list(candidate_coords.keys())
    J = list(demand_coords.keys())

    mod = ConcreteModel()
    mod.I = Set(initialize=I)
    mod.J = Set(initialize=J)
    mod.y = Var(mod.I, domain=Binary)
    mod.z = Var(mod.J, domain=Binary)

    mod.obj = Objective(expr=sum(mod.y[i] for i in I), sense=minimize)

    mod.cov = Constraint(mod.J, rule=lambda mod, j:
        mod.z[j] <= sum(a[i, j] * mod.y[i] for i in I))

    mod.demand = Constraint(expr=
        sum(mod.z[j] for j in J) >= floor(alpha * len(J)))

    result = SolverFactory('cbc').solve(mod)

    if result.solver.termination_condition == TerminationCondition.optimal:
        selected  = [i for i in I if value(mod.y[i]) > 0.5]
        covered   = [j for j in J if value(mod.z[j]) > 0.5]
        uncovered = [j for j in J if value(mod.z[j]) < 0.5]
        return 'optimal', selected, covered, uncovered
    else:
        return 'infeasible', [], [], []

#--------------------
# MAIN MODEL
#--------------------

a = build_coverage_matrix(demand_coords, candidate_coords, road_time_lookup, d_ih, UAV_SPEED_KMH, TIME_THRESHOLD)

# sanity check
coverable = [j for j in demand_coords if any(a[i, j] == 1 for i in candidate_coords)]
print(f"Max achievable coverage: {len(coverable)}/{len(demand_coords)} = {len(coverable)/len(demand_coords)*100:.1f}%")
print(f"Requested coverage: {COVERAGE_THRESHOLD*100}%")

status, selected, covered, uncovered = run_model(a, demand_coords, candidate_coords, COVERAGE_THRESHOLD)

#--------------------
# RESULTS
#--------------------

print(f"\nTime threshold  = {TIME_THRESHOLD} min")
print(f"Vehicle speed   = {UAV_SPEED_KMH} km/h")
print(f"Coverage target = {COVERAGE_THRESHOLD*100}%\n")

if status == 'optimal':
    print(f"Minimum vertiports : {len(selected)}")
    print("Selected sites     :")
    for port in selected:
        print('\t', port)
    print(f"\nRegions covered    : {len(covered)} / {len(demand_coords)}")
    print("Uncovered regions  :")
    for reg in uncovered:
        print('\t', reg)
else:
    print("INFEASIBLE — lower COVERAGE_THRESHOLD or increase TIME_THRESHOLD")


#--------------------
# SENSITIVITY ANALYSIS
#--------------------
'''
time_thresholds  = [30, 45, 60, 75, 90, 105, 120]
coverage_targets = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1]

results = {}

for T in time_thresholds:
    a_temp = build_coverage_matrix(demand_coords, candidate_coords, road_time_lookup, d_ih, UAV_SPEED_KMH, T)
    for alpha in coverage_targets:
        s, sel, cov, uncov = run_model(a_temp, demand_coords, candidate_coords, alpha)
        if s == 'optimal':
            results[T, alpha] = len(sel)
            print(f"T={T:3d} min | coverage={alpha*100:.0f}% | vertiports={len(sel)}")
        else:
            results[T, alpha] = None
            print(f"T={T:3d} min | coverage={alpha*100:.0f}% | INFEASIBLE")

fig, axes = plt.subplots(1, 2, figsize=(16, 6))

ax1 = axes[0]
for alpha in coverage_targets:
    y_vals = [results[T, alpha] if results[T, alpha] is not None else np.nan for T in time_thresholds]
    ax1.plot(time_thresholds, y_vals, marker='o', label=f'{alpha*100:.0f}%')
    for T, v in zip(time_thresholds, y_vals):
        if not np.isnan(v):
            ax1.annotate(str(int(v)), (T, v), textcoords="offset points", xytext=(0, 6), ha='center', fontsize=8)

ax1.set_xlabel('Time Threshold (minutes)')
ax1.set_ylabel('Minimum Vertiports Required')
ax1.set_title('Vertiports vs Time Threshold')
ax1.legend(title='Coverage Target')
ax1.grid(True, linestyle='--', alpha=0.5)

ax2 = axes[1]
for T in time_thresholds:
    y_vals = [results[T, alpha] if results[T, alpha] is not None else np.nan for alpha in coverage_targets]
    ax2.plot([a*100 for a in coverage_targets], y_vals, marker='o', label=f'{T} min')
    for alpha, v in zip(coverage_targets, y_vals):
        if not np.isnan(v):
            ax2.annotate(str(int(v)), (alpha*100, v), textcoords="offset points", xytext=(0, 6), ha='center', fontsize=8)

ax2.set_xlabel('Coverage Target (%)')
ax2.set_ylabel('Minimum Vertiports Required') 
ax2.set_title('Vertiports vs Coverage Target')
ax2.legend(title='Time Threshold')
ax2.grid(True, linestyle='--', alpha=0.5)

plt.tight_layout()
plt.savefig('sensitivity_analysis.png', dpi=150)
plt.show()
print("Plot saved to sensitivity_analysis.png")

for alpha in coverage_targets:
    vals = [(T, results[T, alpha]) for T in time_thresholds if results[T, alpha] is not None]
    if len(vals) < 2:
        continue
    best_efficiency = 0
    best_T = None
    for k in range(1, len(vals)):
        T_prev, n_prev = vals[k-1]
        T_curr, n_curr = vals[k]
        drop       = n_prev - n_curr
        time_cost  = T_curr - T_prev
        efficiency = drop / time_cost
        if efficiency > best_efficiency:
            best_efficiency = efficiency
            best_T = T_curr
    print(f"Coverage {alpha*100:.0f}%: biggest gain at T={best_T} min ({best_efficiency:.2f} vertiports saved per minute)")
'''
#--------------------
# MAP
#--------------------
SA2_SHAPEFILE = 'SA2_2021_AUST_GDA2020.shp'   # path to the ABS boundary file
SA2_NAME_COL  = 'SA2_NAME21'                   # SA2 name column in that file

def match_polygons(names):
        """Return the boundary polygons that contain each SA2's centroid."""
        if not names:
            return None
        pts = gpd.GeoDataFrame(
            {'sa2': names},
            geometry=[Point(demand_coords[i][1], demand_coords[i][0]) for i in names],  # (lon, lat)
            crs='EPSG:4326'
        )
        joined = gpd.sjoin(pts, gdf[[SA2_NAME_COL, 'geometry']], how='left', predicate='within')
        idx = set(joined['index_right'].dropna().astype(int))

        missing = joined.loc[joined['index_right'].isna(), 'sa2'].tolist()
        if missing:
            near = gpd.sjoin_nearest(
                pts[pts['sa2'].isin(missing)].to_crs(epsg=3577),
                gdf[['geometry']].to_crs(epsg=3577),
                how='left'
            )
            idx |= set(near['index_right'].astype(int))

        out = gdf.loc[sorted(idx)].copy()
        out['geometry'] = out.geometry.simplify(0.001, preserve_topology=True)
        return out

if status == 'optimal':
    m_map = folium.Map(
        location=[-33.0, 151.0],
        zoom_start=7,
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        attr='Esri, HERE, Garmin, FAO, NOAA, USGS'
    )

    MeasureControl(
        position='bottomleft',
        primaryLengthUnit='kilometers',
        secondaryLengthUnit='meters',
        activeColor='orange',
        completedColor='green'
    ).add_to(m_map)

    m_map.get_root().html.add_child(folium.Element('''
        <style>.leaflet-interactive:focus { outline: none !important; }</style>
    '''))

    gdf = gpd.read_file(SA2_SHAPEFILE).to_crs(epsg=4326)

    covered_gdf   = match_polygons(covered)
    uncovered_gdf = match_polygons(uncovered)

    # uncovered regions
    if uncovered_gdf is not None:
        folium.GeoJson(
            uncovered_gdf[[SA2_NAME_COL, 'geometry']],
            style_function=lambda f: {
                'fillColor':   '#000000',
                'color':       '#000000',
                'weight':      1,
                'fillOpacity': 0.6,
            },
            tooltip=folium.GeoJsonTooltip(fields=[SA2_NAME_COL], aliases=['Uncovered:'])
        ).add_to(m_map)

    # covered regions
    if covered_gdf is not None:
        folium.GeoJson(
            covered_gdf[[SA2_NAME_COL, 'geometry']],
            style_function=lambda f: {
                'fillColor':   '#7fb8e0',
                'color':       '#2b7bb9',
                'weight':      1.5,
                'fillOpacity': 0.6,
            },
            tooltip=folium.GeoJsonTooltip(fields=[SA2_NAME_COL], aliases=['Region:'])
        ).add_to(m_map)

    # selected vertiports
    for j in selected:
        lat, lon = candidate_coords[j]
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(j, max_width=200),
            tooltip=j,
            icon=folium.Icon(color='red', icon='plane', prefix='fa')
        ).add_to(m_map)

    # reachable hospitals
    for h, (h_lat, h_lon) in hospital_coords.items():
        reachable = any(d_ih.loc[j, h] / UAV_SPEED_KMH * 60 <= TIME_THRESHOLD for j in selected)
        if reachable:
            folium.CircleMarker(
                location=[h_lat, h_lon], radius=2, color='green', fill=True, fill_color='green', fill_opacity=0.2,
                popup=folium.Popup(h, max_width=200), tooltip=h
            ).add_to(m_map)


    legend_html = '''
    <div style="position: fixed; bottom: 50px; right: 50px; width: 230px;
         background-color: white; border:2px solid grey; z-index:9999;
         font-size:14px; padding: 10px; border-radius: 5px;">
    <p style="margin: 0 0 10px 0; font-weight: bold;">Legend</p>
    <p style="margin: 5px 0;"><i style="background:#7fb8e0; width:12px; height:12px;
       display:inline-block; border:1px solid #2b7bb9;"></i> Covered Regions (SA2)</p>
    <p style="margin: 5px 0;"><i style="background:black; width:12px; height:12px;
       display:inline-block; border:1px solid black;"></i> Uncovered Regions (SA2)</p>
    <p style="margin: 5px 0;"><i class="fa fa-map-marker" style="color:red; font-size:16px;
       width:12px; text-align:center;"></i> Selected Vertiports</p>
    <p style="margin: 5px 0;"><i style="background:green; width:12px; height:12px;
       display:inline-block; border-radius:50%;"></i> Reachable Hospitals</p>
    </div>
    '''
m_map.get_root().html.add_child(folium.Element(legend_html))
m_map.save('vertiports_map_base.html')
print("Map saved to vertiports_map_base.html")
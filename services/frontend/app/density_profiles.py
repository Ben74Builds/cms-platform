"""
Density-based operational profiles.

Classifies stations by surrounding urban density and assigns a plausible fleet
composition, incident rate, mobilization time and travel speed to each tier, so
the simulator produces activity that behaves like a real service instead of a
uniform random walk.

The TIER MECHANISM is the point of this module. The numbers below are
ILLUSTRATIVE and deliberately coarse — they are not any service's operational
figures. Recalibrate them on your own dispatch history before drawing any
conclusion from a simulation (see response_time_model.py).

Usage:
    from density_profiles import classify_station, get_tier_profile, compute_fleet

Density tiers:
    dense_urban: city centre and inner ring
    urban:       outer city and inner suburbs
    suburban:    outer suburbs
    rural:       peripheral areas
"""

import math
from pathlib import Path

# ============================================================================
# Density tier profiles — illustrative calibration, see module docstring
# ============================================================================

DENSITY_TIERS = {
    "dense_urban": {
        "label": "Dense Urban",
        "description": "City center, high-rise, dense population (>5000 buildings/km²)",
        # Illustrative
        "units_per_station": 8,     # Illustrative
        "fleet": {"2": 3, "3": 3, "5": 2},  # 3 VSAV, 3 EP, 2 MEA
        # Incident rates
        "dispatches_per_1000_pop_day": 0.48,  # 32/day for ~67k catchment
        "hourly_weight": [0.025, 0.022, 0.018, 0.015, 0.014, 0.013,  # 0-5h
                          0.015, 0.020, 0.032, 0.045, 0.050, 0.053,  # 6-11h
                          0.054, 0.053, 0.052, 0.053, 0.054, 0.055,  # 12-17h
                          0.056, 0.056, 0.053, 0.050, 0.044, 0.039], # 18-23h
        # Response characteristics
        "avg_mobilization_sec": 150,
        "avg_travel_sec": 350,
        "avg_road_distance_m": 2000,
        "avg_speed_kmh": 20,
        "p90_mobilization_sec": 250,
        "p90_travel_sec": 600,
        # Night mobilization (firefighters sleeping)
        "night_mobilization_sec": 210,  # 22h-6h
        "day_mobilization_sec": 135,    # 6h-22h
        # Building density threshold
        "min_buildings_per_km2": 5000,
    },
    "urban": {
        "label": "Urban",
        "description": "City suburbs, mixed residential/commercial (2000-5000 buildings/km²)",
        "units_per_station": 5,
        "fleet": {"2": 2, "3": 2, "5": 1},  # 2 VSAV, 2 EP, 1 MEA
        "dispatches_per_1000_pop_day": 0.34,
        "hourly_weight": [0.025, 0.022, 0.018, 0.015, 0.014, 0.013,
                          0.015, 0.020, 0.032, 0.045, 0.050, 0.053,
                          0.054, 0.053, 0.052, 0.053, 0.054, 0.055,
                          0.056, 0.056, 0.053, 0.050, 0.044, 0.039],
        "avg_mobilization_sec": 140,
        "avg_travel_sec": 400,
        "avg_road_distance_m": 2500,
        "avg_speed_kmh": 25,
        "p90_mobilization_sec": 250,
        "p90_travel_sec": 650,
        "night_mobilization_sec": 200,
        "day_mobilization_sec": 130,
        "min_buildings_per_km2": 2000,
    },
    "suburban": {
        "label": "Suburban",
        "description": "Residential suburbs, lower density (500-2000 buildings/km²)",
        "units_per_station": 3,
        "fleet": {"2": 1, "3": 1, "5": 1},  # 1 VSAV, 1 EP, 1 MEA
        "dispatches_per_1000_pop_day": 0.20,
        "hourly_weight": [0.025, 0.022, 0.018, 0.015, 0.014, 0.013,
                          0.015, 0.020, 0.032, 0.045, 0.050, 0.053,
                          0.054, 0.053, 0.052, 0.053, 0.054, 0.055,
                          0.056, 0.056, 0.053, 0.050, 0.044, 0.039],
        "avg_mobilization_sec": 150,
        "avg_travel_sec": 400,
        "avg_road_distance_m": 3000,
        "avg_speed_kmh": 25,
        "p90_mobilization_sec": 250,
        "p90_travel_sec": 700,
        "night_mobilization_sec": 210,
        "day_mobilization_sec": 135,
        "min_buildings_per_km2": 500,
    },
    "rural": {
        "label": "Rural",
        "description": "Low density, scattered buildings (<500 buildings/km²)",
        "units_per_station": 2,
        "fleet": {"2": 1, "3": 1, "5": 0},  # 1 VSAV, 1 EP
        "dispatches_per_1000_pop_day": 0.10,
        "hourly_weight": [0.025, 0.022, 0.018, 0.015, 0.014, 0.013,
                          0.015, 0.020, 0.032, 0.045, 0.050, 0.053,
                          0.054, 0.053, 0.052, 0.053, 0.054, 0.055,
                          0.056, 0.056, 0.053, 0.050, 0.044, 0.039],
        "avg_mobilization_sec": 130,
        "avg_travel_sec": 350,
        "avg_road_distance_m": 1750,
        "avg_speed_kmh": 20,
        "p90_mobilization_sec": 200,
        "p90_travel_sec": 600,
        "night_mobilization_sec": 195,
        "day_mobilization_sec": 125,
        "min_buildings_per_km2": 0,
    },
}

# Tier order for classification (check from densest to sparsest)
_TIER_ORDER = ["dense_urban", "urban", "suburban", "rural"]


def classify_station_by_buildings(lat, lon, buildings_geojson_path, radius_km=2.0):
    """
    Classify a station's density tier by counting buildings within radius.
    Returns (tier_name, building_count, buildings_per_km2).
    """
    import json

    area_km2 = math.pi * radius_km ** 2
    count = 0

    try:
        with open(buildings_geojson_path) as f:
            for line in f:
                # Fast scan for coordinates without full JSON parse
                if '"coordinates"' not in line:
                    continue
                # Extract first coordinate pair
                try:
                    idx = line.index('"coordinates"')
                    # Find first number after coordinates
                    rest = line[idx + 15:]
                    nums = []
                    for part in rest.replace('[', ' ').replace(']', ' ').replace(',', ' ').split():
                        try:
                            nums.append(float(part))
                            if len(nums) == 2:
                                break
                        except ValueError:
                            continue
                    if len(nums) == 2:
                        blon, blat = nums[0], nums[1]
                        dlat = (blat - lat) * 111.0
                        dlon = (blon - lon) * 111.0 * math.cos(math.radians(lat))
                        if dlat * dlat + dlon * dlon <= radius_km * radius_km:
                            count += 1
                except (ValueError, IndexError):
                    continue
    except FileNotFoundError:
        pass

    density = count / area_km2 if area_km2 > 0 else 0

    for tier in _TIER_ORDER:
        if density >= DENSITY_TIERS[tier]["min_buildings_per_km2"]:
            return tier, count, round(density)

    return "rural", count, round(density)


def classify_station_by_population(population, area_km2=None):
    """
    Quick classification when building data isn't available.
    Uses population density thresholds as proxy.
    """
    if area_km2 and area_km2 > 0:
        pop_density = population / area_km2
    else:
        pop_density = population  # Assume it's already density

    # Population density to building density approximation
    # ~1 building per 2-3 people in urban areas
    est_building_density = pop_density / 2.5

    for tier in _TIER_ORDER:
        if est_building_density >= DENSITY_TIERS[tier]["min_buildings_per_km2"]:
            return tier

    return "rural"


def get_tier_profile(tier):
    """Get the full operational profile for a density tier."""
    return DENSITY_TIERS.get(tier, DENSITY_TIERS["urban"])


def compute_fleet_for_stations(stations, population=None):
    """
    Assign density-aware fleet to each station.
    If population is given, scales incident rates accordingly.

    Args:
        stations: list of dicts with 'name', 'lat', 'lon', 'type' (csp/cs/cpi)
        population: estimated city population

    Returns:
        stations list with 'fleet', 'tier', 'density_info' added
    """
    for s in stations:
        # Determine tier from station type and name
        station_type = s.get("type", "").lower()
        name = s.get("name", "").lower()

        if station_type == "csp" or "csp " in name or "principal" in name:
            tier = "urban"
        elif station_type == "cpi" or "cpi " in name or "première intervention" in name:
            tier = "rural"
        elif station_type == "cs" or "cs " in name:
            tier = "suburban"
        elif station_type == "fire_station":
            # Infer from name
            if "csp" in name:
                tier = "urban"
            elif "cpi" in name:
                tier = "rural"
            else:
                tier = "suburban"
        else:
            tier = "suburban"

        profile = get_tier_profile(tier)

        s["tier"] = tier
        s["tier_label"] = profile["label"]
        s["fleet"] = dict(profile["fleet"])
        s["units_per_station"] = profile["units_per_station"]
        s["avg_speed_kmh"] = profile["avg_speed_kmh"]
        s["avg_mobilization_sec"] = profile["avg_mobilization_sec"]
        s["density_info"] = {
            "dispatches_per_1000_pop_day": profile["dispatches_per_1000_pop_day"],
            "night_mobilization_sec": profile["night_mobilization_sec"],
            "day_mobilization_sec": profile["day_mobilization_sec"],
        }

    return stations


def get_simulation_params(stations, population, duration_days=7):
    """
    Compute realistic simulation parameters from density profiles.

    Returns dict with:
        - per-station fleet and tier
        - estimated total daily incidents
        - recommended speed per tier
        - hourly incident distribution
    """
    total_daily_incidents = 0
    tier_counts = {}

    for s in stations:
        tier = s.get("tier", "suburban")
        profile = get_tier_profile(tier)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

        # Estimate catchment population per station
        catchment_pop = population / max(len(stations), 1)
        daily = catchment_pop * profile["dispatches_per_1000_pop_day"] / 1000
        total_daily_incidents += daily

    return {
        "total_daily_incidents": round(total_daily_incidents),
        "total_incidents_for_period": round(total_daily_incidents * duration_days),
        "tier_distribution": tier_counts,
        "hourly_weight": DENSITY_TIERS["urban"]["hourly_weight"],  # Same shape across tiers
        "recommended_coverage_threshold_sec": 600,
    }


# ============================================================================
# API-friendly summary
# ============================================================================

def get_all_profiles():
    """Return all tier profiles for the frontend."""
    return {
        tier: {
            "label": p["label"],
            "description": p["description"],
            "fleet": p["fleet"],
            "units_per_station": p["units_per_station"],
            "avg_speed_kmh": p["avg_speed_kmh"],
            "avg_mobilization_sec": p["avg_mobilization_sec"],
            "avg_travel_sec": p["avg_travel_sec"],
            "avg_road_distance_m": p["avg_road_distance_m"],
            "dispatches_per_1000_pop_day": p["dispatches_per_1000_pop_day"],
        }
        for tier, p in DENSITY_TIERS.items()
    }

"""Property assessment engine: pure, deterministic maths from a versioned benchmark set."""
import copy

import pytest
from pydantic import ValidationError

from app.schemas.assessment import PROPERTY_TYPES, AssessmentInput, BenchmarkSet
from app.services import assessment_benchmarks
from app.services import assessment_engine as engine


@pytest.fixture()
def bench():
    return assessment_benchmarks.seed()


def inp(**over):
    base = dict(plot_size=30000, plot_unit="sqft", rooms=12, property_type="hotel", amenities=["pool"],
                experiences=["trekking"], city="Madikeri", district="Kodagu", landmark="tourist_spot", landmark_km=8,
                seasonality="hill_coffee", competitor_density="medium")
    base.update(over)
    return AssessmentInput(**base)


@pytest.mark.parametrize("sqft,segment", [(4999, "small"), (5000, "medium"), (43559, "medium"), (43560, "large")])
def test_segment_boundaries(sqft, segment):
    assert engine.segment_for(sqft) == segment


def test_acres_are_converted(bench):
    r = engine.project(bench, inp(plot_size=1, plot_unit="acres"))
    assert r["plot_sqft"] == 43560 and r["segment"] == "large"


@pytest.mark.parametrize("ptype", PROPERTY_TYPES)
@pytest.mark.parametrize("size,rooms", [(4000, 2), (20000, 8), (130680, 30)])     # small, medium, large
def test_every_type_and_segment_is_ordered_and_non_negative(bench, ptype, size, rooms):
    r = engine.project(bench, inp(property_type=ptype, plot_size=size, rooms=rooms, amenities=[]))
    y = r["yearly"]
    assert 0 < y["low"]["revenue"] <= y["likely"]["revenue"] <= y["high"]["revenue"]
    assert y["low"]["net_operating_income"] <= y["likely"]["net_operating_income"] <= y["high"]["net_operating_income"]
    assert len(r["monthly"]) == 12
    for m in r["monthly"]:
        assert 0 <= m["revenue"]["low"] <= m["revenue"]["likely"] <= m["revenue"]["high"]
        assert 0 <= m["occupancy"]["likely"] <= bench["limits"]["occupancy_cap"]
    pay = r["payback_months"]
    if all(pay.values()):
        assert pay["high"] <= pay["likely"] <= pay["low"]
    assert r["investment"]["total"] > 0
    assert r["benchmark_version"] == bench["version"] and r["benchmark_sample"] is True


def test_same_input_same_output(bench):
    assert engine.project(bench, inp()) == engine.project(copy.deepcopy(bench), inp())


def test_monthly_sums_match_the_year(bench):
    r = engine.project(bench, inp())
    for s in ("low", "likely", "high"):
        assert abs(sum(m["revenue"][s] for m in r["monthly"]) - r["yearly"][s]["revenue"]) <= 12


def test_flat_season_gives_flat_occupancy(bench):
    bench["seasonality"]["even"]["weights"] = [1.0] * 12
    r = engine.project(bench, inp(seasonality="even"))
    assert len({m["occupancy"]["likely"] for m in r["monthly"]}) == 1


def test_season_drives_the_curve(bench):
    r = engine.project(bench, inp(seasonality="hill_coffee"))
    occ = {m["month"]: m["occupancy"]["likely"] for m in r["monthly"]}
    assert occ["Dec"] > occ["Jul"]


def test_event_space_without_rooms_earns_from_events_only(bench):
    r = engine.project(bench, inp(property_type="event_space", rooms=0, plot_size=2, plot_unit="acres", amenities=[],
                                  experiences=[]))
    y = r["yearly"]["likely"]
    assert y["room_revenue"] == 0 and y["event_revenue"] > 0 and y["revenue"] == y["event_revenue"]
    assert all(m["occupancy"]["likely"] == 0 for m in r["monthly"])


def test_amenities_raise_rate_and_capex(bench):
    plain = engine.project(bench, inp(amenities=[]))
    rich = engine.project(bench, inp(amenities=["pool", "spa", "restaurant"]))
    assert rich["adr"] > plain["adr"]
    assert rich["investment"]["amenities"] == 2500000 + 3000000 + 3500000
    assert rich["yearly"]["likely"]["extras_revenue"] > plain["yearly"]["likely"]["extras_revenue"]   # restaurant F&B


def test_competition_and_distance_move_the_numbers(bench):
    near = engine.project(bench, inp(landmark_km=2, competitor_density="low"))
    far = engine.project(bench, inp(landmark_km=200, competitor_density="high"))
    assert near["yearly"]["likely"]["revenue"] > far["yearly"]["likely"]["revenue"]


def test_conversion_costs_less_than_new_build(bench):
    new = engine.project(bench, inp(build_status="new"))["investment"]
    conv = engine.project(bench, inp(build_status="conversion"))["investment"]
    assert conv["build_cost"] < new["build_cost"] and conv["fitout"] == new["fitout"]


@pytest.mark.parametrize("city,district,tier", [("Bengaluru", None, "metro"), ("Madikeri", "Kodagu", "leisure"),
                                                ("Mysuru", None, "tier2"), ("Nowhere", None, "other")])
def test_location_tier(bench, city, district, tier):
    r = engine.project(bench, inp(city=city, district=district))
    assert r["location_tier"] == tier
    assert ("did not recognise" in " ".join(r["warnings"])) == (tier == "other")


def test_unknown_amenity_is_refused(bench):
    with pytest.raises(engine.AssessmentError):
        engine.project(bench, inp(amenities=["helipad"]))


def test_zoning_fills_the_plot_and_canvas(bench):
    z = engine.project(bench, inp(plot_size=2, plot_unit="acres", rooms=20))["zoning"]
    assert z["fits"] and abs(sum(zone["sqft"] for zone in z["zones"]) - z["plot_sqft"]) <= len(z["zones"])
    canvas = z["width"] * z["height"]
    for zone in z["zones"]:
        assert 0 <= zone["x"] and zone["x"] + zone["w"] <= z["width"] + 0.5
        assert 0 <= zone["y"] and zone["y"] + zone["h"] <= z["height"] + 0.5
        assert abs(zone["w"] * zone["h"] / canvas - zone["sqft"] / z["plot_sqft"]) < 0.01
    assert z["zones"][-1]["key"] == "green"


def test_too_many_rooms_for_the_plot_is_flagged(bench):
    r = engine.project(bench, inp(plot_size=6000, rooms=60, property_type="rural_retreat"))
    assert r["zoning"]["fits"] is False and r["zoning"]["max_keys"] < 60
    assert any("do not fit" in w for w in r["warnings"])


def test_summary_is_only_the_headline(bench):
    s = engine.summary(engine.project(bench, inp()))
    assert set(s["yearly_revenue"]) == {"low", "likely", "high"}
    assert "monthly" not in s and "zoning" not in s and "assumptions" not in s


@pytest.mark.parametrize("over", [{"rooms": 0}, {"plot_size": 100}, {"plot_size": 3000, "plot_unit": "acres"},
                                  {"amenities": ["pool", "pool"]}, {"landmark_km": -1}, {"property_type": "castle"}])
def test_input_bounds(over):
    with pytest.raises(ValidationError):
        inp(**over)


# ── Benchmark set validation ─────────────────────────────────────────────────

def test_seed_is_valid_and_every_entry_is_labelled_sample(bench):
    BenchmarkSet.model_validate(bench)
    for section in ("property_types", "location_tiers", "landmarks", "competitor_density", "seasonality",
                    "amenities", "experiences"):
        for key, entry in bench[section].items():
            assert entry["note"] == "sample — owner to confirm", f"{section}.{key}"
    for section in ("scenarios", "limits", "costs", "cta"):
        assert bench[section]["note"] == "sample — owner to confirm"


@pytest.mark.parametrize("mutate", [
    lambda b: b["scenarios"]["low"].update(adr_mult=1.5),               # low above likely
    lambda b: b["property_types"].pop("farmhouse"),
    lambda b: b["landmarks"]["highway"]["bands"].reverse(),
    lambda b: b["seasonality"]["even"].update(weights=[1.0] * 11),
    lambda b: b["property_types"]["hotel"].update(base_occupancy=1.4),
    lambda b: b.update(unexpected=True),
])
def test_bad_benchmark_sets_are_refused(bench, mutate):
    mutate(bench)
    with pytest.raises(ValidationError):
        BenchmarkSet.model_validate(bench)

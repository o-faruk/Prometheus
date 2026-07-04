from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    code: str  # EIA balancing-authority / respondent code
    display_name: str
    timezone: str
    weather_lat: float
    weather_lon: float


REGIONS: dict[str, Region] = {
    "CISO": Region(
        code="CISO",
        display_name="California ISO",
        timezone="America/Los_Angeles",
        weather_lat=34.05,  # Los Angeles — largest load center inside CAISO territory
        weather_lon=-118.25,
    ),
    "ERCO": Region(
        code="ERCO",
        display_name="Electric Reliability Council of Texas",
        timezone="America/Chicago",
        weather_lat=32.78,  # Dallas — largest metro load center inside ERCOT territory
        weather_lon=-96.80,
    ),
    "PJM": Region(
        code="PJM",
        display_name="PJM Interconnection",
        timezone="America/New_York",
        # PJM spans 13 states + DC — one weather point is a much rougher approximation
        # here than for CAISO/ERCOT, which are comparatively geographically concentrated.
        # Philadelphia as a representative core-footprint city; flagged as a known
        # limitation in NOTES.md rather than a resolved design choice.
        weather_lat=39.95,
        weather_lon=-75.16,
    ),
}

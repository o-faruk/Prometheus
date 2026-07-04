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
}

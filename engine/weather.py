"""Weather multipliers. Values live in engine/config/weather.yaml (all TUNABLE)."""

from pathlib import Path
from typing import Annotated, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field

from core.contracts.match import Weather

CONFIG = Path(__file__).parent / "config" / "weather.yaml"

Multiplier = Annotated[float, Field(gt=0, le=3)]


class WeatherEffects(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ball_speed: Multiplier
    pass_success: Multiplier
    loose_ball: Multiplier
    long_pass_accuracy: Multiplier
    cross_accuracy: Multiplier
    fatigue_rate: Multiplier


def load_weather(path=CONFIG):
    raw = yaml.safe_load(Path(path).read_text())
    expected = set(get_args(Weather))
    if set(raw) != expected:
        raise ValueError(f"weather config must define exactly {sorted(expected)}")
    return {name: WeatherEffects.model_validate(values) for name, values in raw.items()}

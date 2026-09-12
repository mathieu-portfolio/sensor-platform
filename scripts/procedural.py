"""CLI adapter for the runtime's versioned procedural configuration API."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProceduralConfig:
    scenario_seed: int = 2026
    sensor_layout_seed: int = 73
    duration: int = 20
    target_count: int = 4
    sensor_count: int = 3

    def __post_init__(self):
        for name, low, high in (("scenario_seed", 0, 2**32-1), ("sensor_layout_seed", 0, 2**32-1),
                                ("duration", 4, 120), ("target_count", 1, 12), ("sensor_count", 1, 8)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer in {low}..{high}")

    def text(self):
        return (f"SENSOR_PROCEDURAL 1\n{self.scenario_seed} {self.sensor_layout_seed} "
                f"{self.duration} {self.target_count} {self.sensor_count}\n")

    def arguments(self):
        return [value for name, number in vars(self).items()
                for value in ("--" + name.replace("_", "-"), str(number))]


def add_arguments(parser):
    defaults = ProceduralConfig()
    for name, help_text in (("scenario_seed", "target generation seed (uint32)"),
                            ("sensor_layout_seed", "independent sensor network seed (uint32)"),
                            ("duration", "simulated seconds (4..120)"),
                            ("target_count", "number of targets (1..12)"),
                            ("sensor_count", "number of radars (1..8)")):
        parser.add_argument("--" + name.replace("_", "-"), type=int,
                            default=getattr(defaults, name), help=help_text)


def from_arguments(args):
    return ProceduralConfig(**{name: getattr(args, name) for name in ProceduralConfig.__dataclass_fields__})

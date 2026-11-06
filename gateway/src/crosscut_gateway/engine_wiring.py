"""Start-up and reload wiring checks between the policy and the plant (ADR 014).

A parameter target in the policy needs a plant that reads and writes parameters and, when the
plant knows its map, a ``pid_param`` target of the same tag in it - and the other way round.
Nothing is dropped silently: any mismatch is a PolicyError, so start-up or reload is refused.
"""

from __future__ import annotations

from collections.abc import Collection

from crosscut_gateway.interfaces import ControlSystem, ParamControlSystem
from crosscut_gateway.policy import PolicyError


def _mapped_param_tags(plant: ControlSystem) -> frozenset[str] | None:
    """Tags the plant map declares as ``pid_param`` targets; None when the plant has no map."""
    source = getattr(plant, "param_tags", None)
    if not callable(source):
        return None
    return frozenset(source())


def _check_overlap(setpoints: Collection[str], params: Collection[str]) -> None:
    """Refuse a tag that is both a setpoint and a parameter target."""
    both = sorted(set(setpoints) & set(params))
    if both:
        raise PolicyError(f"tag {both[0]!r} is both a setpoint and a parameter target")


def _check_plant_map(
    mapped: frozenset[str], setpoints: Collection[str], params: Collection[str]
) -> None:
    """Refuse parameter targets missing from the plant map and map entries without a policy."""
    missing = sorted(set(params) - mapped)
    if missing:
        raise PolicyError(f"policy parameter target {missing[0]!r} is not a pid_param target "
                          "in the plant map")
    extra = sorted(mapped - set(params))
    if extra:
        use = "a setpoint target of the policy" if extra[0] in setpoints else "not in the policy"
        raise PolicyError(f"plant map pid_param target {extra[0]!r} has no pid_param policy "
                          f"({use})")


def check_param_wiring(
    plant: ControlSystem, setpoints: Collection[str], params: Collection[str]
) -> None:
    """Raise PolicyError unless the policy's parameter targets and the plant match exactly.

    ``setpoints`` and ``params`` are the target tags of the policy. A plant that has no
    ``param_tags()`` (a test fake) is only checked for the parameter methods.
    """
    _check_overlap(setpoints, params)
    if params and not isinstance(plant, ParamControlSystem):
        raise PolicyError("policy has parameter targets but the plant cannot read or write "
                          "parameters")
    mapped = _mapped_param_tags(plant)
    if mapped is not None:
        _check_plant_map(mapped, setpoints, params)

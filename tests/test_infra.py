"""infra/main.tf against the code and ARCHITECTURE §5: drift here is a broken deploy or a silently
missed run."""

import importlib
from pathlib import Path

import hcl2

MAIN_TF = Path(__file__).parents[1] / "infra" / "main.tf"


def _unquote(v):
    """python-hcl2 keeps HCL's quotes on keys and strings."""
    if isinstance(v, dict):
        return {_unquote(k): _unquote(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_unquote(x) for x in v]
    return v[1:-1] if isinstance(v, str) and v[:1] == v[-1:] == '"' else v


def _app() -> dict:
    with MAIN_TF.open() as f:
        modules = _unquote(hcl2.load(f)["module"])
    return next(m["app"] for m in modules if "app" in m)


def test_the_trading_functions_exist_and_every_handler_resolves():
    functions = _app()["functions"]

    assert {"evening", "open_exit", "morning_check", "heartbeat"} <= set(functions)
    for name, fn in functions.items():
        module, attr = fn["handler"].rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module), attr)), name


def _field(spec: str, lo: int, hi: int) -> set[int]:
    """One cron minute/hour field: '*', 'a,b', 'a-b', 'a/n', 'a-b/n'."""
    out: set[int] = set()
    for part in spec.split(","):
        rng, _, step = part.partition("/")
        start, end = (lo, hi) if rng == "*" else (int(rng.split("-")[0]), int(rng.split("-")[-1]))
        if step and "-" not in rng and rng != "*":
            end = hi
        out |= set(range(start, end + 1, int(step or 1)))
    return out


def _times(function: str) -> set[str]:
    times = set()
    for s in _app()["schedules"].values():
        if s["function"] != function:
            continue
        minute, hour, dom, month, dow, year = s["expression"].removeprefix("cron(")[:-1].split()
        assert (dom, month, dow, year, s["timezone"]) == ("?", "*", "MON-FRI", "*",
                                                         "America/New_York")
        times |= {f"{h:02d}:{m:02d}" for h in _field(hour, 0, 23) for m in _field(minute, 0, 59)}
    return times


def test_the_trading_runs_fire_at_the_architectures_times_new_york_weekdays():
    assert _times("evening") == {"16:30", "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
                                 "20:00", "20:30", "21:00", "21:30", "22:00", "22:30", "23:00"}
    assert _times("open_exit") == {"09:35"}
    assert _times("morning_check") == {"09:50"}
    assert _times("heartbeat") == {"23:15"}


def test_only_the_trading_schedules_wait_for_trading_enabled_and_all_target_real_functions():
    app = _app()
    trading = {"evening", "open_exit", "morning_check", "heartbeat"}

    for name, s in app["schedules"].items():
        assert s["function"] in app["functions"], name
        gated = s.get("enabled") == "${var.trading_enabled}"
        assert gated == (s["function"] in trading), name

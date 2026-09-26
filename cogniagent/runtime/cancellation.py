"""Cooperative cancellation shared by planner and request lifecycle."""


class PlannerCancelled(RuntimeError):
    pass


def check_planner_cancelled(event):
    if event is not None and event.is_set():
        raise PlannerCancelled("Planning stopped by operator.")

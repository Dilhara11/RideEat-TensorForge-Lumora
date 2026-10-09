"""HTTP routers."""

from . import health, jobs, predict, ui

ROUTERS = [health.router, predict.router, jobs.router, ui.router]

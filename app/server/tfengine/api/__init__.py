"""HTTP routers."""

from . import health, jobs, predict, root

ROUTERS = [health.router, predict.router, jobs.router, root.router]

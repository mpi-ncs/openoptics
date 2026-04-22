# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""OpenOptics dashboard: live telemetry + historical replay in the browser.

Public API::

    from openoptics.dashboard import DashboardService, DashboardConfig, NullDashboard
    from openoptics.dashboard.collectors import DeviceMetricCollector

See ``openoptics.dashboard.service`` for lifecycle; ``openoptics.dashboard.events``
for the event schema; ``openoptics.dashboard.collectors.base`` for writing
custom collectors.
"""
from .config import DashboardConfig
from .events import MetricSample, TopologyUpdate
from .service import DashboardService, NullDashboard

# Backward-compatible alias for the (now-deleted) top-level
# ``openoptics.Dashboard`` class. Any user code doing
# ``from openoptics import Dashboard`` keeps working.
Dashboard = DashboardService

__all__ = [
    "DashboardService",
    "DashboardConfig",
    "NullDashboard",
    "MetricSample",
    "TopologyUpdate",
    "Dashboard",
]

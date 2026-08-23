#!/usr/bin/env python3
"""Print the current graph-operation route map as JSON for live test harnesses."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_logseq.logseq import LogSeq

print(json.dumps(LogSeq.api_route_manifest(), indent=2, sort_keys=True))

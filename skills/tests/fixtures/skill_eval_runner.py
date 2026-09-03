#!/usr/bin/env python3
import json
import sys

request = json.load(sys.stdin)
# Deterministic fixture for scheduler/aggregation tests only.
selected = "demo" if "skills" in request["task"].lower() else None
print(json.dumps({
    "selected_skill": selected,
    "task_success": True,
    "response": {"run_id": request["run_id"]},
    "total_tokens": 10,
}))

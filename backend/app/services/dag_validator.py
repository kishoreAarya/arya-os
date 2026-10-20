"""
AryaOS V1 Stage 25 Phase 2 — Action DAG Validator.

Provides bounded, deterministic cycle detection and structure validation
for autonomous goal action execution graphs.
Enforces:
- Non-empty node identifiers
- No duplicate node identifiers
- No self-dependencies (source == target)
- No dangling edge references (edges pointing to non-existent nodes)
- No cyclic dependencies (Kahn's topological sort algorithm)
- No duplicate edges
"""
from __future__ import annotations

from typing import Any
from fastapi import HTTPException, status


class DAGValidationError(HTTPException):
    """Raised when a goal plan DAG fails structural or acyclic validation."""

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"DAG Validation Error: {detail}",
        )


def validate_plan_dag(
    plan_dag_json: dict[str, Any],
    action_client_ids: list[str] | None = None,
) -> list[str]:
    """Validate DAG acyclicity, node existence, and edge integrity.

    Supports:
    - Standard dict format with `nodes` and `edges`:
        {
            "nodes": [{"id": "act-01"}, {"id": "act-02"}], # or list of string IDs
            "edges": [{"from": "act-01", "to": "act-02"}]   # or "source" / "target"
        }
    - Dependency map format:
        {
            "action_dependencies": {
                "act-02": ["act-01"]
            }
        }

    Args:
        plan_dag_json: The raw JSON plan dictionary.
        action_client_ids: Optional list of action node IDs declared on the goal.

    Returns:
        Topologically sorted list of node IDs if valid.

    Raises:
        DAGValidationError: If cycles, self-dependencies, dangling edges, or duplicates are detected.
    """
    if not plan_dag_json and not action_client_ids:
        return []

    node_set: set[str] = set()
    node_list: list[str] = []

    # 1. Collect nodes from action_client_ids if provided
    if action_client_ids:
        for cid in action_client_ids:
            clean_id = (cid or "").strip()
            if not clean_id:
                raise DAGValidationError("Action node client_action_id cannot be empty")
            if clean_id in node_set:
                raise DAGValidationError(f"Duplicate action node identifier '{clean_id}'")
            node_set.add(clean_id)
            node_list.append(clean_id)

    # 2. Collect nodes from plan_dag_json["nodes"] if present
    raw_nodes = plan_dag_json.get("nodes")
    if isinstance(raw_nodes, list):
        for raw_node in raw_nodes:
            if isinstance(raw_node, dict):
                node_id = str(raw_node.get("id") or raw_node.get("client_action_id") or "").strip()
            else:
                node_id = str(raw_node).strip()

            if not node_id:
                raise DAGValidationError("Encountered empty node identifier in DAG nodes list")

            if node_id not in node_set:
                if action_client_ids:
                    # Node in DAG is not declared in goal action nodes
                    raise DAGValidationError(
                        f"Node '{node_id}' in plan_dag_json was not declared in goal actions"
                    )
                node_set.add(node_id)
                node_list.append(node_id)

    # 3. Collect edges
    # Graph representation: adj[u] = list of v where u -> v (u precedes v)
    adj: dict[str, list[str]] = {nid: [] for nid in node_set}
    in_degree: dict[str, int] = {nid: 0 for nid in node_set}
    edge_set: set[tuple[str, str]] = set()

    # Form A: "edges" list
    raw_edges = plan_dag_json.get("edges")
    if isinstance(raw_edges, list):
        for edge in raw_edges:
            if not isinstance(edge, dict):
                raise DAGValidationError(f"Malformed edge entry: {edge}")

            source = str(edge.get("from") or edge.get("source") or edge.get("parent") or "").strip()
            target = str(edge.get("to") or edge.get("target") or edge.get("child") or "").strip()

            if not source or not target:
                raise DAGValidationError(f"Edge missing source or target: {edge}")

            if source == target:
                raise DAGValidationError(f"Self-dependency detected on node '{source}'")

            if source not in node_set:
                raise DAGValidationError(f"Edge references unknown source node '{source}'")
            if target not in node_set:
                raise DAGValidationError(f"Edge references unknown target node '{target}'")

            edge_key = (source, target)
            if edge_key in edge_set:
                raise DAGValidationError(f"Duplicate edge detected: '{source}' -> '{target}'")

            edge_set.add(edge_key)
            adj[source].append(target)
            in_degree[target] += 1

    # Form B: "action_dependencies" map: target -> list of sources (upstream dependencies)
    dep_map = plan_dag_json.get("action_dependencies")
    if isinstance(dep_map, dict):
        for target_id, sources in dep_map.items():
            target = str(target_id).strip()
            if target not in node_set:
                raise DAGValidationError(f"Dependency map references unknown target '{target}'")

            if not isinstance(sources, list):
                raise DAGValidationError(f"Dependencies for '{target}' must be a list")

            for src in sources:
                source = str(src).strip()
                if not source:
                    continue
                if source == target:
                    raise DAGValidationError(f"Self-dependency detected on node '{source}'")
                if source not in node_set:
                    raise DAGValidationError(f"Node '{target}' depends on unknown node '{source}'")

                edge_key = (source, target)
                if edge_key in edge_set:
                    continue  # ignore duplicate if specified in both

                edge_set.add(edge_key)
                adj[source].append(target)
                in_degree[target] += 1

    # 4. Kahn's Algorithm for Topological Sort & Cycle Detection
    queue: list[str] = [nid for nid in node_set if in_degree[nid] == 0]
    topological_order: list[str] = []

    while queue:
        u = queue.pop(0)
        topological_order.append(u)

        for v in adj[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    if len(topological_order) < len(node_set):
        remaining = [nid for nid in node_set if nid not in topological_order]
        raise DAGValidationError(
            f"Cyclic dependency detected in execution graph involving nodes: {sorted(remaining)}"
        )

    return topological_order

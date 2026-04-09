# A* 탐색 알고리즘으로 가능한 경로를 찾는다.
from __future__ import annotations

from dataclasses import dataclass
import heapq
import math

from src.data.schemas import RoutePoint, RouteResult


@dataclass(frozen=True, slots=True)
class BusNodeSpec:
    """탐색 엔진이 경로 계산에 사용하는 최소 버스 정보."""

    bus_id: str
    label: str
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class RouteCandidateSpec:
    """후보 경로 계산에 필요한 입력."""

    candidate_id: str
    candidate_label: str
    latitude: float
    longitude: float
    base_distance_km: float
    construction_cost: float


@dataclass(frozen=True, slots=True)
class GraphEdgeSpec:
    """탐색 그래프의 양방향 간선 최소 스펙."""

    from_node_id: str
    to_node_id: str
    distance_km: float | None = None


@dataclass(frozen=True, slots=True)
class _RouteNodeSpec:
    node_id: str
    label: str
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class _RoutePlanVariant:
    plan_name: str
    path_node_ids: list[str]
    total_distance_km: float
    calibrated_distance_km: float
    repeated_node_count: int
    relay_hop_count: int


def build_mock_route(
    start_bus: BusNodeSpec,
    end_bus: BusNodeSpec,
    candidate: RouteCandidateSpec,
    *,
    via_bus: BusNodeSpec | None = None,
    load_scale: float = 1.0,
) -> RouteResult:
    """1주차용 mock 경로 결과를 공통 RouteResult 형식으로 반환한다."""

    path_node_ids = [start_bus.bus_id]
    waypoints = [_to_route_point(start_bus)]

    if via_bus is not None:
        path_node_ids.append(via_bus.bus_id)
        waypoints.append(_to_route_point(via_bus))

    path_node_ids.extend([candidate.candidate_id, end_bus.bus_id])
    waypoints.extend(
        [
            RoutePoint(
                point_id=candidate.candidate_id,
                label=candidate.candidate_label,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
            ),
            _to_route_point(end_bus),
        ]
    )

    scale_penalty = max(0.0, load_scale - 1.0) * 6.0
    hub_penalty = 3.5 if via_bus is not None else 0.0
    total_distance_km = round(candidate.base_distance_km + hub_penalty + scale_penalty, 1)
    estimated_cost = round(
        (total_distance_km * 0.42) + (candidate.construction_cost * 4.8),
        1,
    )

    summary_parts = [f"{start_bus.label}에서 {end_bus.label}까지"]
    if via_bus is not None:
        summary_parts.append(f"{via_bus.label} 허브를 거쳐")
    summary_parts.append(f"{candidate.candidate_label}을 경유하는 mock 경로입니다.")

    return RouteResult(
        route_id=f"route-{candidate.candidate_id.lower()}",
        start_bus_id=start_bus.bus_id,
        end_bus_id=end_bus.bus_id,
        path_node_ids=path_node_ids,
        waypoints=waypoints,
        total_distance_km=total_distance_km,
        estimated_cost=estimated_cost,
        source="mock",
        summary=" ".join(summary_parts),
    )


def build_k_nearest_edges(
    bus_nodes: list[BusNodeSpec],
    *,
    neighbor_count: int = 3,
) -> list[GraphEdgeSpec]:
    """버스 좌표 기준으로 k-nearest 양방향 간선을 생성한다."""

    if neighbor_count < 1:
        raise ValueError("neighbor_count must be at least 1.")

    unique_buses = list({bus.bus_id: bus for bus in bus_nodes}.values())
    edges: list[GraphEdgeSpec] = []
    seen_pairs: set[tuple[str, str]] = set()

    for bus in unique_buses:
        neighbors = sorted(
            (other for other in unique_buses if other.bus_id != bus.bus_id),
            key=lambda other: _distance_km(
                bus.latitude,
                bus.longitude,
                other.latitude,
                other.longitude,
            ),
        )[:neighbor_count]

        for other in neighbors:
            pair = tuple(sorted((bus.bus_id, other.bus_id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append(
                GraphEdgeSpec(
                    from_node_id=bus.bus_id,
                    to_node_id=other.bus_id,
                    distance_km=_distance_km(
                        bus.latitude,
                        bus.longitude,
                        other.latitude,
                        other.longitude,
                    ),
                )
            )

    return edges


def build_astar_route(
    start_bus: BusNodeSpec,
    end_bus: BusNodeSpec,
    candidate: RouteCandidateSpec,
    *,
    bus_nodes: list[BusNodeSpec],
    edges: list[GraphEdgeSpec] | None = None,
    via_bus: BusNodeSpec | None = None,
    load_scale: float = 1.0,
    candidate_link_count: int = 3,
) -> RouteResult:
    """실제 A* 계산 기반 최소 RouteResult 를 생성한다.

    후보지는 그래프의 독립 노드로 추가하고, 가까운 bus 노드들과 연결한 뒤
    start -> candidate -> end 또는 start -> via -> candidate -> end 순으로
    구간별 A* 탐색을 수행한다.
    """

    if candidate_link_count < 1:
        raise ValueError("candidate_link_count must be at least 1.")

    resolved_bus_nodes = _unique_bus_nodes(bus_nodes, start_bus, end_bus, via_bus)
    resolved_edges = list(edges) if edges is not None else build_k_nearest_edges(resolved_bus_nodes)
    route_nodes = _build_route_nodes(resolved_bus_nodes, candidate)
    adjacency = _build_adjacency(
        route_nodes,
        resolved_edges + _build_candidate_edges(candidate, resolved_bus_nodes, candidate_link_count),
        load_scale=load_scale,
    )

    route_variants = [
        _build_route_variant(
            plan_name="direct",
            leg_pairs=_build_leg_pairs(start_bus, end_bus, candidate, via_bus=None),
            route_nodes=route_nodes,
            adjacency=adjacency,
            load_scale=load_scale,
        )
    ]
    if via_bus is not None:
        route_variants.append(
            _build_route_variant(
                plan_name="via_hub",
                leg_pairs=_build_leg_pairs(start_bus, end_bus, candidate, via_bus=via_bus),
                route_nodes=route_nodes,
                adjacency=adjacency,
                load_scale=load_scale,
            )
        )

    selected_variant = min(route_variants, key=lambda variant: variant.calibrated_distance_km)
    path_node_ids = selected_variant.path_node_ids
    waypoints = [_to_route_point_from_node(route_nodes[node_id]) for node_id in path_node_ids]
    estimated_cost = _estimate_route_cost(
        total_distance_km=selected_variant.total_distance_km,
        calibrated_distance_km=selected_variant.calibrated_distance_km,
        construction_cost=candidate.construction_cost,
        repeated_node_count=selected_variant.repeated_node_count,
    )

    summary_parts = [f"{start_bus.label}에서 {end_bus.label}까지"]
    if selected_variant.plan_name == "via_hub" and via_bus is not None:
        summary_parts.append(f"{via_bus.label} 허브를 포함한")
    else:
        summary_parts.append("허브 우회보다 직결 비용이 낮은")
    summary_parts.append(
        f"{candidate.candidate_label} 후보지 경유 A* 보정 경로입니다."
    )
    if selected_variant.repeated_node_count > 0:
        summary_parts.append("반복 노드 패널티를 반영해 루프 경로를 배제했습니다.")

    return RouteResult(
        route_id=f"astar-{candidate.candidate_id.lower()}",
        start_bus_id=start_bus.bus_id,
        end_bus_id=end_bus.bus_id,
        path_node_ids=path_node_ids,
        waypoints=waypoints,
        total_distance_km=round(selected_variant.total_distance_km, 1),
        estimated_cost=estimated_cost,
        source="astar",
        summary=" ".join(summary_parts),
    )


def _unique_bus_nodes(
    bus_nodes: list[BusNodeSpec],
    start_bus: BusNodeSpec,
    end_bus: BusNodeSpec,
    via_bus: BusNodeSpec | None,
) -> list[BusNodeSpec]:
    resolved = {bus.bus_id: bus for bus in bus_nodes}
    resolved[start_bus.bus_id] = start_bus
    resolved[end_bus.bus_id] = end_bus
    if via_bus is not None:
        resolved[via_bus.bus_id] = via_bus
    return list(resolved.values())


def _build_route_nodes(
    bus_nodes: list[BusNodeSpec],
    candidate: RouteCandidateSpec,
) -> dict[str, _RouteNodeSpec]:
    route_nodes = {
        bus.bus_id: _RouteNodeSpec(
            node_id=bus.bus_id,
            label=bus.label,
            latitude=bus.latitude,
            longitude=bus.longitude,
        )
        for bus in bus_nodes
    }
    route_nodes[candidate.candidate_id] = _RouteNodeSpec(
        node_id=candidate.candidate_id,
        label=candidate.candidate_label,
        latitude=candidate.latitude,
        longitude=candidate.longitude,
    )
    return route_nodes


def _build_candidate_edges(
    candidate: RouteCandidateSpec,
    bus_nodes: list[BusNodeSpec],
    candidate_link_count: int,
) -> list[GraphEdgeSpec]:
    nearest_buses = sorted(
        bus_nodes,
        key=lambda bus: _distance_km(
            candidate.latitude,
            candidate.longitude,
            bus.latitude,
            bus.longitude,
        ),
    )[:candidate_link_count]

    return [
        GraphEdgeSpec(
            from_node_id=candidate.candidate_id,
            to_node_id=bus.bus_id,
            distance_km=_distance_km(
                candidate.latitude,
                candidate.longitude,
                bus.latitude,
                bus.longitude,
            ),
        )
        for bus in nearest_buses
    ]


def _build_adjacency(
    route_nodes: dict[str, _RouteNodeSpec],
    edges: list[GraphEdgeSpec],
    *,
    load_scale: float,
) -> dict[str, list[tuple[str, float, float]]]:
    adjacency: dict[str, list[tuple[str, float, float]]] = {
        node_id: [] for node_id in route_nodes
    }

    scale_factor = 1.0 + max(0.0, load_scale - 1.0) * 0.15

    for edge in edges:
        if edge.from_node_id not in route_nodes or edge.to_node_id not in route_nodes:
            raise ValueError(
                f"Unknown node id in edge: {edge.from_node_id} -> {edge.to_node_id}"
            )

        distance_km = edge.distance_km
        if distance_km is None:
            start_node = route_nodes[edge.from_node_id]
            end_node = route_nodes[edge.to_node_id]
            distance_km = _distance_km(
                start_node.latitude,
                start_node.longitude,
                end_node.latitude,
                end_node.longitude,
            )

        traversal_cost = distance_km * scale_factor
        adjacency[edge.from_node_id].append((edge.to_node_id, distance_km, traversal_cost))
        adjacency[edge.to_node_id].append((edge.from_node_id, distance_km, traversal_cost))

    return adjacency


def _build_leg_pairs(
    start_bus: BusNodeSpec,
    end_bus: BusNodeSpec,
    candidate: RouteCandidateSpec,
    via_bus: BusNodeSpec | None,
) -> list[tuple[str, str]]:
    if via_bus is None:
        return [
            (start_bus.bus_id, candidate.candidate_id),
            (candidate.candidate_id, end_bus.bus_id),
        ]

    return [
        (start_bus.bus_id, via_bus.bus_id),
        (via_bus.bus_id, candidate.candidate_id),
        (candidate.candidate_id, end_bus.bus_id),
    ]


def _build_route_variant(
    *,
    plan_name: str,
    leg_pairs: list[tuple[str, str]],
    route_nodes: dict[str, _RouteNodeSpec],
    adjacency: dict[str, list[tuple[str, float, float]]],
    load_scale: float,
) -> _RoutePlanVariant:
    path_node_ids: list[str] = []
    total_distance_km = 0.0
    straight_line_distance_km = 0.0

    for leg_start, leg_end in leg_pairs:
        leg_path, leg_distance = _run_astar_leg(
            start_id=leg_start,
            end_id=leg_end,
            route_nodes=route_nodes,
            adjacency=adjacency,
        )
        total_distance_km += leg_distance
        straight_line_distance_km += _heuristic_cost(route_nodes, leg_start, leg_end)
        path_node_ids = _merge_path_ids(path_node_ids, leg_path)

    repeated_node_count = len(path_node_ids) - len(set(path_node_ids))
    relay_hop_count = max(0, len(path_node_ids) - (len(leg_pairs) + 1))
    calibrated_distance_km = _calibrate_route_distance(
        total_distance_km=total_distance_km,
        straight_line_distance_km=straight_line_distance_km,
        relay_hop_count=relay_hop_count,
        repeated_node_count=repeated_node_count,
        load_scale=load_scale,
    )

    return _RoutePlanVariant(
        plan_name=plan_name,
        path_node_ids=path_node_ids,
        total_distance_km=total_distance_km,
        calibrated_distance_km=calibrated_distance_km,
        repeated_node_count=repeated_node_count,
        relay_hop_count=relay_hop_count,
    )


def _run_astar_leg(
    *,
    start_id: str,
    end_id: str,
    route_nodes: dict[str, _RouteNodeSpec],
    adjacency: dict[str, list[tuple[str, float, float]]],
) -> tuple[list[str], float]:
    if start_id == end_id:
        return [start_id], 0.0

    frontier: list[tuple[float, float, str]] = []
    heapq.heappush(frontier, (_heuristic_cost(route_nodes, start_id, end_id), 0.0, start_id))

    came_from: dict[str, str | None] = {start_id: None}
    search_costs: dict[str, float] = {start_id: 0.0}
    distance_costs: dict[str, float] = {start_id: 0.0}

    while frontier:
        _, current_cost, current_id = heapq.heappop(frontier)
        if current_id == end_id:
            return _reconstruct_path(
                came_from=came_from,
                distance_costs=distance_costs,
                end_id=end_id,
            )

        if current_cost > search_costs.get(current_id, float("inf")):
            continue

        for neighbor_id, edge_distance_km, traversal_cost in adjacency[current_id]:
            tentative_search_cost = current_cost + traversal_cost
            if tentative_search_cost >= search_costs.get(neighbor_id, float("inf")):
                continue

            came_from[neighbor_id] = current_id
            search_costs[neighbor_id] = tentative_search_cost
            distance_costs[neighbor_id] = distance_costs[current_id] + edge_distance_km

            priority = tentative_search_cost + _heuristic_cost(
                route_nodes,
                neighbor_id,
                end_id,
            )
            heapq.heappush(frontier, (priority, tentative_search_cost, neighbor_id))

    raise ValueError(f"A* route not found: {start_id} -> {end_id}")


def _reconstruct_path(
    *,
    came_from: dict[str, str | None],
    distance_costs: dict[str, float],
    end_id: str,
) -> tuple[list[str], float]:
    path = [end_id]
    current_id = end_id

    while came_from[current_id] is not None:
        current_id = came_from[current_id]  # type: ignore[assignment]
        path.append(current_id)

    path.reverse()
    return path, distance_costs[end_id]


def _merge_path_ids(existing_path: list[str], new_path: list[str]) -> list[str]:
    if not existing_path:
        return list(new_path)
    if not new_path:
        return list(existing_path)
    if existing_path[-1] == new_path[0]:
        return existing_path + new_path[1:]
    return existing_path + new_path


def _estimate_route_cost(
    *,
    total_distance_km: float,
    calibrated_distance_km: float,
    construction_cost: float,
    repeated_node_count: int,
) -> float:
    repeat_penalty = repeated_node_count * 3.5
    distance_basis = max(total_distance_km, calibrated_distance_km)
    estimated_cost = (distance_basis * 0.44) + (construction_cost * 4.6) + repeat_penalty
    return round(estimated_cost, 1)


def _calibrate_route_distance(
    *,
    total_distance_km: float,
    straight_line_distance_km: float,
    relay_hop_count: int,
    repeated_node_count: int,
    load_scale: float,
) -> float:
    detour_km = max(0.0, total_distance_km - straight_line_distance_km)
    relay_penalty_km = relay_hop_count * 6.0
    repeated_penalty_km = repeated_node_count * 40.0
    load_penalty_km = max(0.0, load_scale - 1.0) * 12.0
    return (
        total_distance_km
        + (detour_km * 0.8)
        + relay_penalty_km
        + repeated_penalty_km
        + load_penalty_km
    )


def _heuristic_cost(
    route_nodes: dict[str, _RouteNodeSpec],
    start_id: str,
    end_id: str,
) -> float:
    start_node = route_nodes[start_id]
    end_node = route_nodes[end_id]
    return _distance_km(
        start_node.latitude,
        start_node.longitude,
        end_node.latitude,
        end_node.longitude,
    )


def _distance_km(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> float:
    earth_radius_km = 6371.0
    lat1 = math.radians(start_latitude)
    lon1 = math.radians(start_longitude)
    lat2 = math.radians(end_latitude)
    lon2 = math.radians(end_longitude)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_km * c


def _to_route_point(bus: BusNodeSpec) -> RoutePoint:
    return RoutePoint(
        point_id=bus.bus_id,
        label=bus.label,
        latitude=bus.latitude,
        longitude=bus.longitude,
    )


def _to_route_point_from_node(node: _RouteNodeSpec) -> RoutePoint:
    return RoutePoint(
        point_id=node.node_id,
        label=node.label,
        latitude=node.latitude,
        longitude=node.longitude,
    )

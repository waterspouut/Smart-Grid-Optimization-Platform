# A* 탐색 알고리즘으로 가능한 경로를 찾는다.
from __future__ import annotations

from dataclasses import dataclass

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
    """후보 경로 계산에 필요한 mock 입력."""

    candidate_id: str
    candidate_label: str
    latitude: float
    longitude: float
    base_distance_km: float
    construction_cost: float


def build_mock_route(
    start_bus: BusNodeSpec,
    end_bus: BusNodeSpec,
    candidate: RouteCandidateSpec,
    *,
    via_bus: BusNodeSpec | None = None,
    load_scale: float = 1.0,
) -> RouteResult:
    """1주차용 mock 경로 결과를 공통 RouteResult 형식으로 반환한다.

    실제 A* 구현 전까지는 서비스 계층이 이 함수를 호출해
    경로 결과 형식을 고정한다.
    """

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


def _to_route_point(bus: BusNodeSpec) -> RoutePoint:
    return RoutePoint(
        point_id=bus.bus_id,
        label=bus.label,
        latitude=bus.latitude,
        longitude=bus.longitude,
    )

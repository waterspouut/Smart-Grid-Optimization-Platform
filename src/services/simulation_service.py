# 송전탑 설치 시뮬레이션과 결과 조합 흐름을 조율한다.
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from src.data.schemas import (
    FallbackInfo,
    RecommendationResult,
    RoutePoint,
    RouteResult,
    ScenarioContext,
    ScoreBreakdown,
    SimulationDelta,
    SimulationInput,
    SimulationResult,
)


_BUS_METADATA: dict[str, dict[str, float | str]] = {
    "BUS_001": {"name": "서울", "latitude": 37.5665, "longitude": 126.9780},
    "BUS_002": {"name": "인천", "latitude": 37.4563, "longitude": 126.7052},
    "BUS_003": {"name": "수원", "latitude": 37.2636, "longitude": 127.0286},
    "BUS_004": {"name": "춘천", "latitude": 37.8813, "longitude": 127.7298},
    "BUS_005": {"name": "강릉", "latitude": 37.7519, "longitude": 128.8761},
    "BUS_006": {"name": "원주", "latitude": 37.3422, "longitude": 127.9202},
    "BUS_007": {"name": "대전", "latitude": 36.3504, "longitude": 127.3845},
    "BUS_008": {"name": "청주", "latitude": 36.6424, "longitude": 127.4890},
    "BUS_009": {"name": "광주", "latitude": 35.1595, "longitude": 126.8526},
    "BUS_010": {"name": "전주", "latitude": 35.8242, "longitude": 127.1480},
    "BUS_011": {"name": "대구", "latitude": 35.8714, "longitude": 128.6014},
    "BUS_012": {"name": "울산", "latitude": 35.5384, "longitude": 129.3114},
    "BUS_013": {"name": "부산", "latitude": 35.1796, "longitude": 129.0756},
}

_DEFAULT_CANDIDATES: dict[str, dict[str, float | str]] = {
    "SITE_NORTH": {
        "label": "북부 우회안",
        "latitude": 36.9300,
        "longitude": 127.5200,
        "distance_km": 48.0,
        "construction_cost": 19.5,
        "congestion_relief": 32.0,
        "environmental_risk": 6.5,
        "policy_risk": 4.0,
    },
    "SITE_CENTRAL": {
        "label": "중앙 균형안",
        "latitude": 36.2800,
        "longitude": 127.7600,
        "distance_km": 41.0,
        "construction_cost": 17.0,
        "congestion_relief": 29.0,
        "environmental_risk": 4.0,
        "policy_risk": 3.0,
    },
    "SITE_SOUTH": {
        "label": "남부 확장안",
        "latitude": 35.9800,
        "longitude": 128.0500,
        "distance_km": 54.0,
        "construction_cost": 15.0,
        "congestion_relief": 24.0,
        "environmental_risk": 3.0,
        "policy_risk": 2.5,
    },
}


class SimulationService:
    """시뮬레이션 페이지용 mock 입력과 결과를 공통 계약 형식으로 맞춘다."""

    def build_default_input(
        self,
        scenario: ScenarioContext | None = None,
        *,
        created_at: datetime | None = None,
        start_bus_id: str = "BUS_001",
        end_bus_id: str = "BUS_011",
        candidate_site_ids: list[str] | None = None,
        load_scale: float = 1.0,
        notes: str = "",
    ) -> SimulationInput:
        resolved_at = _round_to_hour(created_at or datetime.now())
        resolved_scenario = self._resolve_scenario(scenario, resolved_at)

        return SimulationInput(
            scenario=resolved_scenario,
            start_bus_id=start_bus_id,
            end_bus_id=end_bus_id,
            candidate_site_ids=candidate_site_ids or list(_DEFAULT_CANDIDATES),
            load_scale=load_scale,
            notes=notes,
        )

    def run_mock_simulation(
        self,
        simulation_input: SimulationInput | None = None,
        *,
        created_at: datetime | None = None,
    ) -> SimulationResult:
        resolved_at = _round_to_hour(created_at or datetime.now())
        resolved_input, input_warnings = self._normalize_input(simulation_input, resolved_at)
        recommendations = self._build_mock_recommendations(resolved_input)
        selected_route = recommendations[0].route if recommendations else None
        deltas = self._build_mock_deltas(resolved_input, recommendations[0] if recommendations else None)

        warnings = input_warnings + [
            "SimulationService는 현재 A* 탐색과 점수화 엔진 대신 mock 시뮬레이션 결과를 반환합니다.",
        ]

        return SimulationResult(
            scenario=resolved_input.scenario,
            created_at=resolved_at,
            source="mock",
            simulation_input=resolved_input,
            selected_route=selected_route,
            recommendations=recommendations,
            deltas=deltas,
            summary=self._build_summary(resolved_input, recommendations, deltas),
            warnings=warnings,
            fallback=FallbackInfo(
                enabled=True,
                mode="mock_data",
                reason="A* 경로 탐색과 score_function 엔진이 아직 연결되지 않아 mock 결과를 사용합니다.",
                primary_path="src.engine.search.astar_router -> src.engine.search.score_function",
                active_path="src.services.simulation_service.SimulationService.run_mock_simulation",
            ),
        )

    def _resolve_scenario(
        self,
        scenario: ScenarioContext | None,
        created_at: datetime,
    ) -> ScenarioContext:
        if scenario is not None:
            if scenario.created_at is None:
                scenario.created_at = created_at
            return scenario

        return ScenarioContext(
            scenario_id="simulation-mock",
            title="Simulation Mock Scenario",
            description="시뮬레이션 mock 서비스 기본 시나리오",
            region="South Korea",
            created_at=created_at,
            created_by="SimulationService",
        )

    def _normalize_input(
        self,
        simulation_input: SimulationInput | None,
        created_at: datetime,
    ) -> tuple[SimulationInput, list[str]]:
        warnings: list[str] = []

        if simulation_input is None:
            warnings.append("SimulationInput이 없어 기본 mock 입력을 사용합니다.")
            return self.build_default_input(created_at=created_at), warnings

        start_bus_id = simulation_input.start_bus_id or "BUS_001"
        end_bus_id = simulation_input.end_bus_id or "BUS_011"
        candidate_site_ids = simulation_input.candidate_site_ids or list(_DEFAULT_CANDIDATES)
        scenario = simulation_input.scenario

        if not simulation_input.start_bus_id:
            warnings.append("시작 버스가 비어 있어 BUS_001을 사용합니다.")
        if not simulation_input.end_bus_id:
            warnings.append("종료 버스가 비어 있어 BUS_011을 사용합니다.")
        if not simulation_input.candidate_site_ids:
            warnings.append("후보지가 비어 있어 기본 후보 3개를 사용합니다.")
        if scenario.created_at is None:
            scenario.created_at = created_at

        return (
            replace(
                simulation_input,
                scenario=scenario,
                start_bus_id=start_bus_id,
                end_bus_id=end_bus_id,
                candidate_site_ids=candidate_site_ids,
            ),
            warnings,
        )

    def _build_mock_recommendations(
        self,
        simulation_input: SimulationInput,
    ) -> list[RecommendationResult]:
        scored_recommendations: list[RecommendationResult] = []

        for index, candidate_id in enumerate(simulation_input.candidate_site_ids):
            candidate = _get_candidate(candidate_id, index)
            route = self._build_mock_route(simulation_input, candidate_id, candidate, index)
            score = self._build_mock_score(simulation_input, candidate)
            scored_recommendations.append(
                RecommendationResult(
                    candidate_id=candidate_id,
                    candidate_label=str(candidate["label"]),
                    route=route,
                    score=score,
                    rationale=self._build_rationale(simulation_input, candidate, score),
                )
            )

        scored_recommendations.sort(
            key=lambda recommendation: (
                recommendation.score.total_score if recommendation.score else float("-inf")
            ),
            reverse=True,
        )

        for rank, recommendation in enumerate(scored_recommendations, start=1):
            recommendation.rank = rank

        return scored_recommendations

    def _build_mock_route(
        self,
        simulation_input: SimulationInput,
        candidate_id: str,
        candidate: dict[str, float | str],
        index: int,
    ) -> RouteResult:
        start_bus = _get_bus(simulation_input.start_bus_id)
        end_bus = _get_bus(simulation_input.end_bus_id)
        hub_bus_id = "BUS_007" if simulation_input.end_bus_id != "BUS_007" else "BUS_010"
        hub_bus = _get_bus(hub_bus_id)
        scale_penalty = max(0.0, simulation_input.load_scale - 1.0) * 6.0
        total_distance = round(float(candidate["distance_km"]) + (index * 3.5) + scale_penalty, 1)
        estimated_cost = round((total_distance * 0.42) + float(candidate["construction_cost"]) * 4.8, 1)

        return RouteResult(
            route_id=f"route-{candidate_id.lower()}",
            start_bus_id=simulation_input.start_bus_id,
            end_bus_id=simulation_input.end_bus_id,
            path_node_ids=[
                simulation_input.start_bus_id,
                hub_bus_id,
                candidate_id,
                simulation_input.end_bus_id,
            ],
            waypoints=[
                RoutePoint(
                    point_id=simulation_input.start_bus_id,
                    label=str(start_bus["name"]),
                    latitude=float(start_bus["latitude"]),
                    longitude=float(start_bus["longitude"]),
                ),
                RoutePoint(
                    point_id=hub_bus_id,
                    label=str(hub_bus["name"]),
                    latitude=float(hub_bus["latitude"]),
                    longitude=float(hub_bus["longitude"]),
                ),
                RoutePoint(
                    point_id=candidate_id,
                    label=str(candidate["label"]),
                    latitude=float(candidate["latitude"]),
                    longitude=float(candidate["longitude"]),
                ),
                RoutePoint(
                    point_id=simulation_input.end_bus_id,
                    label=str(end_bus["name"]),
                    latitude=float(end_bus["latitude"]),
                    longitude=float(end_bus["longitude"]),
                ),
            ],
            total_distance_km=total_distance,
            estimated_cost=estimated_cost,
            source="mock",
            summary=(
                f"{start_bus['name']}에서 {end_bus['name']}까지 "
                f"{candidate['label']}을 경유하는 mock 경로입니다."
            ),
        )

    def _build_mock_score(
        self,
        simulation_input: SimulationInput,
        candidate: dict[str, float | str],
    ) -> ScoreBreakdown:
        load_bonus = max(0.0, simulation_input.load_scale - 1.0) * 18.0
        distance_cost = round(float(candidate["distance_km"]) * 0.58, 1)
        construction_cost = round(float(candidate["construction_cost"]) * 1.85, 1)
        congestion_relief = round(float(candidate["congestion_relief"]) + load_bonus, 1)
        environmental_risk = round(float(candidate["environmental_risk"]) * 2.2, 1)
        policy_risk = round(float(candidate["policy_risk"]) * 2.0, 1)
        total_score = round(
            100.0
            + congestion_relief
            - distance_cost
            - construction_cost
            - environmental_risk
            - policy_risk,
            1,
        )

        return ScoreBreakdown(
            total_score=total_score,
            distance_cost=distance_cost,
            construction_cost=construction_cost,
            congestion_relief=congestion_relief,
            environmental_risk=environmental_risk,
            policy_risk=policy_risk,
            notes=[
                "현재 점수는 mock 가중치로 계산됩니다.",
                "2주차에 astar_router와 score_function 결과로 교체할 예정입니다.",
            ],
        )

    def _build_rationale(
        self,
        simulation_input: SimulationInput,
        candidate: dict[str, float | str],
        score: ScoreBreakdown,
    ) -> str:
        return (
            f"{candidate['label']}은 부하 배율 {simulation_input.load_scale:.0%} 기준으로 "
            f"혼잡 완화 점수 {score.congestion_relief:.1f}를 확보하면서 "
            f"환경·정책 리스크를 상대적으로 낮게 유지하는 안입니다."
        )

    def _build_mock_deltas(
        self,
        simulation_input: SimulationInput,
        top_recommendation: RecommendationResult | None,
    ) -> list[SimulationDelta]:
        before_peak_utilization = round(88.0 + max(0.0, simulation_input.load_scale - 1.0) * 24.0, 1)
        after_peak_utilization = round(max(62.0, before_peak_utilization - 12.5), 1)
        before_risk_lines = 4.0 if simulation_input.load_scale >= 1.1 else 3.0
        after_risk_lines = max(1.0, before_risk_lines - 2.0)
        before_losses = round(4.8 + max(0.0, simulation_input.load_scale - 1.0) * 1.2, 1)
        after_losses = round(max(3.2, before_losses - 0.7), 1)
        before_margin = round(11.0 - max(0.0, simulation_input.load_scale - 1.0) * 6.0, 1)
        after_margin = round(before_margin + 7.5, 1)

        deltas = [
            SimulationDelta(
                metric_id="peak_utilization",
                label="최대 선로 이용률",
                before_value=before_peak_utilization,
                after_value=after_peak_utilization,
                unit="%",
                improvement=round(before_peak_utilization - after_peak_utilization, 1),
                status="improved",
            ),
            SimulationDelta(
                metric_id="risk_lines",
                label="고위험 선로 수",
                before_value=before_risk_lines,
                after_value=after_risk_lines,
                unit="lines",
                improvement=round(before_risk_lines - after_risk_lines, 1),
                status="improved",
            ),
            SimulationDelta(
                metric_id="losses",
                label="예상 송전 손실",
                before_value=before_losses,
                after_value=after_losses,
                unit="%",
                improvement=round(before_losses - after_losses, 1),
                status="improved",
            ),
            SimulationDelta(
                metric_id="operating_margin",
                label="운영 여유도",
                before_value=before_margin,
                after_value=after_margin,
                unit="%",
                improvement=round(after_margin - before_margin, 1),
                status="improved",
            ),
        ]

        if top_recommendation is not None and top_recommendation.route is not None:
            deltas.append(
                SimulationDelta(
                    metric_id="route_distance",
                    label="적용 경로 길이",
                    before_value=0.0,
                    after_value=top_recommendation.route.total_distance_km,
                    unit="km",
                    improvement=round(-top_recommendation.route.total_distance_km, 1),
                    status="worsened",
                )
            )

        return deltas

    def _build_summary(
        self,
        simulation_input: SimulationInput,
        recommendations: list[RecommendationResult],
        deltas: list[SimulationDelta],
    ) -> str:
        if not recommendations:
            return "시뮬레이션 mock 결과를 만들었지만 추천안을 생성하지 못했습니다."

        top_recommendation = recommendations[0]
        utilization_delta = next(
            (delta for delta in deltas if delta.metric_id == "peak_utilization"),
            None,
        )
        utilization_text = ""
        if utilization_delta is not None:
            utilization_text = (
                f" 최대 이용률은 {utilization_delta.before_value:.1f}%에서 "
                f"{utilization_delta.after_value:.1f}%로 개선됩니다."
            )

        return (
            f"{simulation_input.start_bus_id} -> {simulation_input.end_bus_id} 구간에서는 "
            f"{top_recommendation.candidate_label}이 1순위 추천안입니다. "
            f"총점 {top_recommendation.score.total_score:.1f}점, "
            f"예상 경로 길이 {top_recommendation.route.total_distance_km:.1f}km입니다."
            f"{utilization_text}"
        )


def _round_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _get_bus(bus_id: str) -> dict[str, float | str]:
    return _BUS_METADATA.get(
        bus_id,
        {"name": bus_id, "latitude": 36.3504, "longitude": 127.3845},
    )


def _get_candidate(candidate_id: str, index: int) -> dict[str, float | str]:
    if candidate_id in _DEFAULT_CANDIDATES:
        return _DEFAULT_CANDIDATES[candidate_id]

    return {
        "label": candidate_id,
        "latitude": 36.15 + (index * 0.18),
        "longitude": 127.55 + (index * 0.12),
        "distance_km": 46.0 + (index * 4.0),
        "construction_cost": 18.0 + index,
        "congestion_relief": 26.0 - (index * 1.5),
        "environmental_risk": 4.5 + (index * 0.6),
        "policy_risk": 3.0 + (index * 0.4),
    }

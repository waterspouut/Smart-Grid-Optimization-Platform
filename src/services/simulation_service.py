# 송전탑 설치 시뮬레이션과 결과 조합 흐름을 조율한다.
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from src.services.monitoring_service import MonitoringService
from src.services.result_metadata import (
    build_fallback_info,
    build_fallback_warning,
    build_no_fallback_info,
    build_source_warning,
)
from src.engine.powerflow import dc_power_flow as _dcpf
from src.engine.powerflow.congestion_metrics import (
    compute_congestion_summary,
    compute_line_statuses,
)
from src.data.schemas import (
    FallbackInfo,
    MonitoringResult,
    RecommendationResult,
    ResultSource,
    RouteResult,
    ScenarioContext,
    ScoreBreakdown,
    SimulationDelta,
    SimulationInput,
    SimulationResult,
)
from src.engine.search.astar_router import (
    BusNodeSpec,
    GraphEdgeSpec,
    RouteCandidateSpec,
    build_astar_route,
    build_k_nearest_edges,
    build_mock_route,
)
from src.engine.search.score_function import (
    CandidateScoreInput,
    build_recommendation,
    calculate_score,
    calculate_mock_score,
    rank_recommendations,
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

    def list_bus_options(self) -> list[tuple[str, str]]:
        """페이지 입력용 버스 선택 옵션을 반환한다."""
        return [
            (bus_id, str(metadata["name"]))
            for bus_id, metadata in _BUS_METADATA.items()
        ]

    def list_candidate_options(self) -> list[tuple[str, str]]:
        """페이지 입력용 후보지 선택 옵션을 반환한다."""
        return [
            (candidate_id, str(candidate["label"]))
            for candidate_id, candidate in _DEFAULT_CANDIDATES.items()
        ]

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
        recommendations = self._build_recommendations(resolved_input, use_actual_route=False)
        deltas = self._build_mock_deltas(
            resolved_input,
            recommendations[0] if recommendations else None,
        )

        return self._build_result(
            simulation_input=resolved_input,
            created_at=resolved_at,
            source="mock",
            recommendations=recommendations,
            deltas=deltas,
            warnings=input_warnings + [build_fallback_warning("SimulationService", "mock_data")],
            fallback=build_fallback_info(
                mode="mock_data",
                reason="실제 A* 탐색과 점수화 대신 search 엔진의 mock 계약 함수를 사용합니다.",
                primary_path="src.engine.search.astar_router -> src.engine.search.score_function",
                active_path="src.services.simulation_service.SimulationService.run_mock_simulation",
            ),
        )

    def run_simulation(
        self,
        simulation_input: SimulationInput | None = None,
        *,
        created_at: datetime | None = None,
    ) -> SimulationResult:
        """4주차용 보정 A* + 통합 시뮬레이션 진입점.

        설치 전 baseline은 MonitoringService의 DC Power Flow를 사용하고,
        설치 후 delta는 추천안 기반 counterfactual DC Power Flow로 계산한다.
        """

        resolved_at = _round_to_hour(created_at or datetime.now())
        resolved_input, input_warnings = self._normalize_input(simulation_input, resolved_at)

        try:
            recommendations = self._build_recommendations(resolved_input, use_actual_route=True)
            monitoring_before = self._get_monitoring_baseline(
                simulation_input=resolved_input,
                created_at=resolved_at,
            )
            deltas, delta_warnings, fallback = self._resolve_deltas(
                simulation_input=resolved_input,
                recommendations=recommendations,
                monitoring_before=monitoring_before,
            )

            return self._build_result(
                simulation_input=resolved_input,
                created_at=resolved_at,
                source="astar",
                recommendations=recommendations,
                deltas=deltas,
                warnings=input_warnings + delta_warnings,
                fallback=fallback,
            )

        except Exception as exc:  # noqa: BLE001
            fallback_result = self.run_mock_simulation(
                simulation_input=resolved_input,
                created_at=resolved_at,
            )
            fallback_result.warnings.insert(
                0,
                f"A* route/score 실패 → mock fallback 전환. 원인: {exc}",
            )
            fallback_result.fallback = build_fallback_info(
                mode="mock_data",
                reason=str(exc),
                primary_path="src.engine.search.astar_router.build_astar_route -> src.engine.search.score_function.calculate_score",
                active_path="src.services.simulation_service.SimulationService.run_mock_simulation",
            )
            return fallback_result

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

    def _build_recommendations(
        self,
        simulation_input: SimulationInput,
        *,
        use_actual_route: bool,
    ) -> list[RecommendationResult]:
        scored_recommendations: list[RecommendationResult] = []
        bus_nodes = self._build_bus_nodes() if use_actual_route else []
        bus_edges = self._build_bus_edges(bus_nodes) if use_actual_route else []
        start_bus = _to_bus_node_spec(simulation_input.start_bus_id)
        end_bus = _to_bus_node_spec(simulation_input.end_bus_id)
        hub_bus_id = "BUS_007" if simulation_input.end_bus_id != "BUS_007" else "BUS_010"
        hub_bus = _to_bus_node_spec(hub_bus_id)

        for index, candidate_id in enumerate(simulation_input.candidate_site_ids):
            candidate = _get_candidate(candidate_id, index)
            route = self._build_candidate_route(
                simulation_input=simulation_input,
                candidate_id=candidate_id,
                candidate=candidate,
                start_bus=start_bus,
                end_bus=end_bus,
                hub_bus=hub_bus,
                bus_nodes=bus_nodes,
                bus_edges=bus_edges,
                use_actual_route=use_actual_route,
            )
            score_input = self._build_candidate_score_input(
                candidate_id=candidate_id,
                candidate=candidate,
                load_scale=simulation_input.load_scale,
            )
            score = (
                calculate_score(score_input, route=route)
                if use_actual_route
                else calculate_mock_score(score_input)
            )
            scored_recommendations.append(
                build_recommendation(
                    candidate_id=candidate_id,
                    candidate_label=str(candidate["label"]),
                    route=route,
                    score=score,
                    rationale=self._build_rationale(simulation_input, candidate, score),
                )
            )

        return rank_recommendations(scored_recommendations)

    def _build_candidate_route(
        self,
        *,
        simulation_input: SimulationInput,
        candidate_id: str,
        candidate: dict[str, float | str],
        start_bus: BusNodeSpec,
        end_bus: BusNodeSpec,
        hub_bus: BusNodeSpec,
        bus_nodes: list[BusNodeSpec],
        bus_edges: list[GraphEdgeSpec],
        use_actual_route: bool,
    ) -> RouteResult:
        candidate_spec = _to_route_candidate_spec(candidate_id, candidate)
        if use_actual_route:
            return build_astar_route(
                start_bus=start_bus,
                end_bus=end_bus,
                candidate=candidate_spec,
                bus_nodes=bus_nodes,
                edges=bus_edges,
                via_bus=hub_bus,
                load_scale=simulation_input.load_scale,
            )

        return build_mock_route(
            start_bus=start_bus,
            end_bus=end_bus,
            candidate=candidate_spec,
            via_bus=hub_bus,
            load_scale=simulation_input.load_scale,
        )

    def _build_candidate_score_input(
        self,
        *,
        candidate_id: str,
        candidate: dict[str, float | str],
        load_scale: float,
    ) -> CandidateScoreInput:
        return CandidateScoreInput(
            candidate_id=candidate_id,
            candidate_label=str(candidate["label"]),
            distance_km=float(candidate["distance_km"]),
            construction_cost=float(candidate["construction_cost"]),
            congestion_relief=float(candidate["congestion_relief"]),
            environmental_risk=float(candidate["environmental_risk"]),
            policy_risk=float(candidate["policy_risk"]),
            load_scale=load_scale,
        )

    def _get_monitoring_baseline(
        self,
        *,
        simulation_input: SimulationInput,
        created_at: datetime,
    ) -> MonitoringResult:
        return MonitoringService().run_dc_power_flow(
            scenario=simulation_input.scenario,
            load_scale=simulation_input.load_scale,
            created_at=created_at,
        )

    def _resolve_deltas(
        self,
        *,
        simulation_input: SimulationInput,
        recommendations: list[RecommendationResult],
        monitoring_before: MonitoringResult,
    ) -> tuple[list[SimulationDelta], list[str], FallbackInfo]:
        top_recommendation = recommendations[0] if recommendations else None
        use_actual_baseline = (
            not monitoring_before.fallback.enabled
            and monitoring_before.source == "dc_power_flow"
        )

        if use_actual_baseline:
            try:
                monitoring_after, counterfactual_warnings = self._build_counterfactual_monitoring(
                    simulation_input=simulation_input,
                    monitoring_before=monitoring_before,
                    top_recommendation=top_recommendation,
                )
                deltas = self._build_actual_deltas(
                    monitoring_before=monitoring_before,
                    monitoring_after=monitoring_after,
                    top_recommendation=top_recommendation,
                )
                return (
                    deltas,
                    [build_source_warning("SimulationService", "astar")] + counterfactual_warnings,
                    build_no_fallback_info(),
                )
            except Exception as exc:  # noqa: BLE001
                deltas = self._build_heuristic_deltas(
                    monitoring_before=monitoring_before,
                    top_recommendation=top_recommendation,
                )
                warnings = [
                    build_fallback_warning("SimulationService", "mock_data"),
                    f"설치 후 counterfactual DC Power Flow 실패 → heuristic delta 사용. 원인: {exc}",
                ]
                fallback = build_fallback_info(
                    mode="mock_data",
                    reason="설치 후 counterfactual DC Power Flow 계산에 실패해 heuristic delta를 사용합니다.",
                    primary_path="src.engine.powerflow.dc_power_flow.solve -> counterfactual network",
                    active_path="src.services.simulation_service.SimulationService._build_heuristic_deltas",
                )
                return deltas, warnings, fallback

        deltas = self._build_mock_deltas(simulation_input, top_recommendation)
        warnings = [build_fallback_warning("SimulationService", "mock_data")]
        warnings.append("경로 탐색과 점수화는 보정된 A* 경로를 사용하고, 설치 전후 비교 delta는 mock 규칙을 사용합니다.")
        if monitoring_before.fallback.enabled:
            warnings.append(
                "설치 전 baseline Monitoring 결과가 fallback이라 비교 delta도 mock 규칙으로 유지합니다."
            )
        fallback = build_fallback_info(
            mode="mock_data",
            reason="설치 전 baseline DC Power Flow가 준비되지 않아 설치 전후 비교 delta는 mock 규칙을 사용합니다.",
            primary_path="src.engine.powerflow.dc_power_flow -> src.engine.powerflow.congestion_metrics",
            active_path="src.services.simulation_service.SimulationService._build_mock_deltas",
        )
        return deltas, warnings, fallback

    def _build_result(
        self,
        *,
        simulation_input: SimulationInput,
        created_at: datetime,
        source: ResultSource,
        recommendations: list[RecommendationResult],
        deltas: list[SimulationDelta],
        warnings: list[str],
        fallback: FallbackInfo,
    ) -> SimulationResult:
        selected_route = recommendations[0].route if recommendations else None
        return SimulationResult(
            scenario=simulation_input.scenario,
            created_at=created_at,
            source=source,
            simulation_input=simulation_input,
            selected_route=selected_route,
            recommendations=recommendations,
            deltas=deltas,
            summary=self._build_summary(simulation_input, recommendations, deltas),
            warnings=warnings,
            fallback=fallback,
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

    def _build_counterfactual_monitoring(
        self,
        *,
        simulation_input: SimulationInput,
        monitoring_before: MonitoringResult,
        top_recommendation: RecommendationResult | None,
    ) -> tuple[MonitoringResult, list[str]]:
        buses = _dcpf.build_default_buses(simulation_input.load_scale)
        line_inputs, reinforced_line_ids = self._build_counterfactual_line_inputs(
            monitoring_before=monitoring_before,
            top_recommendation=top_recommendation,
        )
        dc_result = _dcpf.solve(buses, line_inputs)
        if not dc_result.converged:
            raise RuntimeError(dc_result.error)

        line_statuses = compute_line_statuses(dc_result)
        congestion_summary = compute_congestion_summary(line_statuses)
        reinforced_label = ", ".join(reinforced_line_ids) if reinforced_line_ids else "없음"
        warnings = [
            "설치 전후 delta는 counterfactual DC Power Flow 결과를 사용합니다.",
            f"병렬 지원선 적용 대상 선로: {reinforced_label}",
        ]

        return (
            MonitoringResult(
                scenario=simulation_input.scenario,
                created_at=monitoring_before.created_at,
                source="dc_power_flow",
                load_scale=simulation_input.load_scale,
                line_statuses=line_statuses,
                congestion_summary=congestion_summary,
                summary=(
                    "추천안 적용 후 상위 혼잡 선로에 병렬 지원선을 추가한 "
                    "counterfactual DC Power Flow 결과입니다."
                ),
                warnings=warnings,
                fallback=build_no_fallback_info(),
            ),
            warnings,
        )

    def _build_counterfactual_line_inputs(
        self,
        *,
        monitoring_before: MonitoringResult,
        top_recommendation: RecommendationResult | None,
    ) -> tuple[list[_dcpf.LineInput], list[str]]:
        line_inputs = _dcpf.build_default_line_inputs()
        if top_recommendation is None or top_recommendation.score is None:
            return line_inputs, []

        line_inputs_by_id = {line.line_id: line for line in line_inputs}
        stressed_lines = [
            line
            for line in monitoring_before.line_statuses
            if line.status in {"warning", "critical", "overload"}
        ] or monitoring_before.line_statuses[:1]

        route = top_recommendation.route
        score = top_recommendation.score
        route_distance_km = route.total_distance_km if route is not None else 0.0
        route_distance_factor = max(0.70, 1.0 - (route_distance_km / 1000.0))
        relief_factor = min(0.35, score.congestion_relief / 120.0)
        reinforcement_count = min(
            len(stressed_lines),
            2 if (score.congestion_relief >= 28.0 or route_distance_km <= 48.0) else 1,
        )

        support_lines: list[_dcpf.LineInput] = []
        reinforced_line_ids: list[str] = []
        for index, stressed_line in enumerate(stressed_lines[:reinforcement_count], start=1):
            base_line = line_inputs_by_id.get(stressed_line.line_id)
            if base_line is None:
                continue

            reactance_scale = min(
                1.22,
                max(1.04, 1.16 - (relief_factor * 0.22) - ((route_distance_factor - 0.70) * 0.15) + ((index - 1) * 0.06)),
            )
            capacity_scale = min(
                1.10,
                max(0.90, 0.86 + (relief_factor * 0.45) + (route_distance_factor * 0.12) - ((index - 1) * 0.04)),
            )
            support_lines.append(
                _dcpf.LineInput(
                    line_id=f"CF_{base_line.line_id}_{index}",
                    from_bus=base_line.from_bus,
                    to_bus=base_line.to_bus,
                    reactance_pu=round(base_line.reactance_pu * reactance_scale, 5),
                    capacity_mw=round(base_line.capacity_mw * capacity_scale, 1),
                )
            )
            reinforced_line_ids.append(base_line.line_id)

        return line_inputs + support_lines, reinforced_line_ids

    def _build_actual_deltas(
        self,
        *,
        monitoring_before: MonitoringResult,
        monitoring_after: MonitoringResult,
        top_recommendation: RecommendationResult | None,
    ) -> list[SimulationDelta]:
        route = top_recommendation.route if top_recommendation is not None else None
        before_peak_utilization = round(
            monitoring_before.congestion_summary.max_utilization * 100.0,
            1,
        )
        after_peak_utilization = round(
            monitoring_after.congestion_summary.max_utilization * 100.0,
            1,
        )
        before_risk_lines = float(
            sum(
                1
                for line in monitoring_before.line_statuses
                if line.status in {"warning", "critical", "overload"}
            )
        )
        after_risk_lines = float(
            sum(
                1
                for line in monitoring_after.line_statuses
                if line.status in {"warning", "critical", "overload"}
            )
        )
        before_losses = round(monitoring_before.congestion_summary.total_loss_mw, 1)
        after_losses = round(monitoring_after.congestion_summary.total_loss_mw, 1)
        before_margin = round(max(0.0, 100.0 - before_peak_utilization), 1)
        after_margin = round(max(0.0, 100.0 - after_peak_utilization), 1)

        if top_recommendation is None:
            return [
                SimulationDelta(
                    metric_id="peak_utilization",
                    label="최대 선로 이용률",
                    before_value=before_peak_utilization,
                    after_value=after_peak_utilization,
                    unit="%",
                    improvement=round(before_peak_utilization - after_peak_utilization, 1),
                    status=_delta_status(after_peak_utilization, before_peak_utilization, lower_is_better=True),
                ),
                SimulationDelta(
                    metric_id="risk_lines",
                    label="고위험 선로 수",
                    before_value=before_risk_lines,
                    after_value=after_risk_lines,
                    unit="lines",
                    improvement=round(before_risk_lines - after_risk_lines, 1),
                    status=_delta_status(after_risk_lines, before_risk_lines, lower_is_better=True),
                ),
                SimulationDelta(
                    metric_id="losses",
                    label="예상 송전 손실",
                    before_value=before_losses,
                    after_value=after_losses,
                    unit="MW",
                    improvement=round(before_losses - after_losses, 1),
                    status=_delta_status(after_losses, before_losses, lower_is_better=True),
                ),
                SimulationDelta(
                    metric_id="operating_margin",
                    label="운영 여유도",
                    before_value=before_margin,
                    after_value=after_margin,
                    unit="%",
                    improvement=round(after_margin - before_margin, 1),
                    status=_delta_status(after_margin, before_margin, lower_is_better=False),
                ),
            ]

        deltas = [
            SimulationDelta(
                metric_id="peak_utilization",
                label="최대 선로 이용률",
                before_value=before_peak_utilization,
                after_value=after_peak_utilization,
                unit="%",
                improvement=round(before_peak_utilization - after_peak_utilization, 1),
                status=_delta_status(after_peak_utilization, before_peak_utilization, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="risk_lines",
                label="고위험 선로 수",
                before_value=before_risk_lines,
                after_value=after_risk_lines,
                unit="lines",
                improvement=round(before_risk_lines - after_risk_lines, 1),
                status=_delta_status(after_risk_lines, before_risk_lines, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="losses",
                label="예상 송전 손실",
                before_value=before_losses,
                after_value=after_losses,
                unit="MW",
                improvement=round(before_losses - after_losses, 1),
                status=_delta_status(after_losses, before_losses, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="operating_margin",
                label="운영 여유도",
                before_value=before_margin,
                after_value=after_margin,
                unit="%",
                improvement=round(after_margin - before_margin, 1),
                status=_delta_status(after_margin, before_margin, lower_is_better=False),
            ),
        ]

        if route is not None:
            deltas.append(
                SimulationDelta(
                    metric_id="route_distance",
                    label="적용 경로 길이",
                    before_value=0.0,
                    after_value=route.total_distance_km,
                    unit="km",
                    improvement=round(-route.total_distance_km, 1),
                    status="worsened",
                )
            )

        return deltas

    def _build_heuristic_deltas(
        self,
        *,
        monitoring_before: MonitoringResult,
        top_recommendation: RecommendationResult | None,
    ) -> list[SimulationDelta]:
        return self._build_actual_deltas_heuristic(
            monitoring_before=monitoring_before,
            top_recommendation=top_recommendation,
        )

    def _build_actual_deltas_heuristic(
        self,
        *,
        monitoring_before: MonitoringResult,
        top_recommendation: RecommendationResult | None,
    ) -> list[SimulationDelta]:
        before_peak_utilization = round(
            monitoring_before.congestion_summary.max_utilization * 100.0,
            1,
        )
        before_risk_lines = float(
            sum(
                1
                for line in monitoring_before.line_statuses
                if line.status in {"warning", "critical", "overload"}
            )
        )
        before_losses = round(monitoring_before.congestion_summary.total_loss_mw, 1)
        before_margin = round(max(0.0, 100.0 - before_peak_utilization), 1)

        if top_recommendation is None or top_recommendation.score is None:
            return [
                SimulationDelta(
                    metric_id="peak_utilization",
                    label="최대 선로 이용률",
                    before_value=before_peak_utilization,
                    after_value=before_peak_utilization,
                    unit="%",
                    improvement=0.0,
                    status="unchanged",
                ),
                SimulationDelta(
                    metric_id="risk_lines",
                    label="고위험 선로 수",
                    before_value=before_risk_lines,
                    after_value=before_risk_lines,
                    unit="lines",
                    improvement=0.0,
                    status="unchanged",
                ),
                SimulationDelta(
                    metric_id="losses",
                    label="예상 송전 손실",
                    before_value=before_losses,
                    after_value=before_losses,
                    unit="MW",
                    improvement=0.0,
                    status="unchanged",
                ),
                SimulationDelta(
                    metric_id="operating_margin",
                    label="운영 여유도",
                    before_value=before_margin,
                    after_value=before_margin,
                    unit="%",
                    improvement=0.0,
                    status="unchanged",
                ),
            ]

        score = top_recommendation.score
        route = top_recommendation.route
        route_distance_km = route.total_distance_km if route is not None else 0.0
        route_distance_factor = max(0.55, 1.0 - (route_distance_km / 900.0))
        relief_strength = score.congestion_relief
        risk_penalty = (score.environmental_risk * 0.10) + (score.policy_risk * 0.08)

        peak_reduction = max(
            0.0,
            min(25.0, (relief_strength * 0.42 * route_distance_factor) - risk_penalty),
        )
        after_peak_utilization = round(max(50.0, before_peak_utilization - peak_reduction), 1)

        risk_reduction = max(0.0, min(before_risk_lines, round(peak_reduction / 5.5, 1)))
        after_risk_lines = round(max(0.0, before_risk_lines - risk_reduction), 1)

        loss_reduction = max(
            0.0,
            min(
                before_losses * 0.45,
                before_losses * (0.10 + (relief_strength / 220.0) * route_distance_factor),
            ),
        )
        after_losses = round(max(0.0, before_losses - loss_reduction), 1)

        after_margin = round(min(100.0, max(0.0, 100.0 - after_peak_utilization)), 1)

        deltas = [
            SimulationDelta(
                metric_id="peak_utilization",
                label="최대 선로 이용률",
                before_value=before_peak_utilization,
                after_value=after_peak_utilization,
                unit="%",
                improvement=round(before_peak_utilization - after_peak_utilization, 1),
                status=_delta_status(after_peak_utilization, before_peak_utilization, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="risk_lines",
                label="고위험 선로 수",
                before_value=before_risk_lines,
                after_value=after_risk_lines,
                unit="lines",
                improvement=round(before_risk_lines - after_risk_lines, 1),
                status=_delta_status(after_risk_lines, before_risk_lines, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="losses",
                label="예상 송전 손실",
                before_value=before_losses,
                after_value=after_losses,
                unit="MW",
                improvement=round(before_losses - after_losses, 1),
                status=_delta_status(after_losses, before_losses, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="operating_margin",
                label="운영 여유도",
                before_value=before_margin,
                after_value=after_margin,
                unit="%",
                improvement=round(after_margin - before_margin, 1),
                status=_delta_status(after_margin, before_margin, lower_is_better=False),
            ),
        ]

        if route is not None:
            deltas.append(
                SimulationDelta(
                    metric_id="route_distance",
                    label="적용 경로 길이",
                    before_value=0.0,
                    after_value=route.total_distance_km,
                    unit="km",
                    improvement=round(-route.total_distance_km, 1),
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

    def _build_bus_nodes(self) -> list[BusNodeSpec]:
        return [
            _to_bus_node_spec(bus_id)
            for bus_id in _BUS_METADATA
        ]

    def _build_bus_edges(
        self,
        bus_nodes: list[BusNodeSpec],
    ) -> list[GraphEdgeSpec]:
        return build_k_nearest_edges(bus_nodes, neighbor_count=3)


def _round_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _delta_status(
    after_value: float,
    before_value: float,
    *,
    lower_is_better: bool,
) -> str:
    if abs(after_value - before_value) < 1e-9:
        return "unchanged"
    if lower_is_better:
        return "improved" if after_value < before_value else "worsened"
    return "improved" if after_value > before_value else "worsened"


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


def _to_bus_node_spec(bus_id: str) -> BusNodeSpec:
    bus = _get_bus(bus_id)
    return BusNodeSpec(
        bus_id=bus_id,
        label=str(bus["name"]),
        latitude=float(bus["latitude"]),
        longitude=float(bus["longitude"]),
    )


def _to_route_candidate_spec(
    candidate_id: str,
    candidate: dict[str, float | str],
) -> RouteCandidateSpec:
    return RouteCandidateSpec(
        candidate_id=candidate_id,
        candidate_label=str(candidate["label"]),
        latitude=float(candidate["latitude"]),
        longitude=float(candidate["longitude"]),
        base_distance_km=float(candidate["distance_km"]),
        construction_cost=float(candidate["construction_cost"]),
    )

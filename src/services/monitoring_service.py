# 모니터링 흐름과 혼잡 요약 생성을 조율한다.
from __future__ import annotations

from datetime import datetime, timedelta
from math import sin

from src.data.schemas import (
    FallbackInfo,
    LineStatusSnapshot,
    MonitoringKpi,
    MonitoringResult,
    ScenarioContext,
    TimeSeriesPoint,
)


_BUS_NAMES: dict[str, str] = {
    "BUS_001": "서울",
    "BUS_004": "춘천",
    "BUS_007": "대전",
    "BUS_009": "광주",
    "BUS_010": "전주",
    "BUS_011": "대구",
    "BUS_013": "부산",
}

_LINE_BLUEPRINTS: list[dict[str, float | str]] = [
    {"line_id": "L04", "from_bus": "BUS_001", "to_bus": "BUS_007", "flow_mw": 2440.0, "limit_mw": 3000.0},
    {"line_id": "L10", "from_bus": "BUS_007", "to_bus": "BUS_009", "flow_mw": 1590.0, "limit_mw": 2000.0},
    {"line_id": "L13", "from_bus": "BUS_010", "to_bus": "BUS_011", "flow_mw": 1230.0, "limit_mw": 2000.0},
    {"line_id": "L15", "from_bus": "BUS_011", "to_bus": "BUS_013", "flow_mw": 2140.0, "limit_mw": 3000.0},
    {"line_id": "L17", "from_bus": "BUS_007", "to_bus": "BUS_011", "flow_mw": 2225.0, "limit_mw": 2500.0},
]


class MonitoringService:
    """모니터링 페이지용 mock 결과를 공통 계약 형식으로 조합한다."""

    def get_monitoring_result(
        self,
        scenario: ScenarioContext | None = None,
        *,
        as_of: datetime | None = None,
        load_scale: float = 1.0,
    ) -> MonitoringResult:
        created_at = _round_to_hour(as_of or datetime.now())
        resolved_scenario = self._resolve_scenario(scenario, created_at)
        line_statuses = self._build_mock_line_statuses(load_scale)
        trend_points = self._build_mock_trend_points(created_at, load_scale)
        kpis = self._build_mock_kpis(line_statuses, trend_points)
        warnings = self._build_warnings(line_statuses)

        return MonitoringResult(
            scenario=resolved_scenario,
            created_at=created_at,
            source="mock",
            kpis=kpis,
            line_statuses=line_statuses,
            trend_points=trend_points,
            summary=self._build_summary(line_statuses, trend_points),
            warnings=warnings,
            fallback=FallbackInfo(
                enabled=True,
                mode="mock_data",
                reason="dc_power_flow 및 congestion_metrics 엔진이 아직 연결되지 않아 mock 결과를 사용합니다.",
                primary_path="src.engine.powerflow.dc_power_flow -> src.engine.powerflow.congestion_metrics",
                active_path="src.services.monitoring_service.MonitoringService.get_monitoring_result",
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
            scenario_id="monitoring-mock",
            title="Monitoring Mock Scenario",
            description="모니터링 mock 서비스 기본 시나리오",
            region="South Korea",
            created_at=created_at,
            created_by="MonitoringService",
        )

    def _build_mock_line_statuses(
        self,
        load_scale: float,
    ) -> list[LineStatusSnapshot]:
        line_statuses: list[LineStatusSnapshot] = []

        for blueprint in _LINE_BLUEPRINTS:
            flow_mw = round(float(blueprint["flow_mw"]) * load_scale, 1)
            utilization = round(flow_mw / float(blueprint["limit_mw"]), 3)
            from_bus = str(blueprint["from_bus"])
            to_bus = str(blueprint["to_bus"])
            line_statuses.append(
                LineStatusSnapshot(
                    line_id=str(blueprint["line_id"]),
                    from_bus=from_bus,
                    to_bus=to_bus,
                    from_bus_name=_BUS_NAMES.get(from_bus, from_bus),
                    to_bus_name=_BUS_NAMES.get(to_bus, to_bus),
                    flow_mw=flow_mw,
                    utilization=utilization,
                    risk_level=_classify_risk(utilization),
                )
            )

        return sorted(
            line_statuses,
            key=lambda item: item.utilization,
            reverse=True,
        )

    def _build_mock_trend_points(
        self,
        created_at: datetime,
        load_scale: float,
    ) -> list[TimeSeriesPoint]:
        trend_points: list[TimeSeriesPoint] = []
        base_load_mw = 10950.0 * load_scale

        for hour_offset in range(-11, 1):
            timestamp = created_at + timedelta(hours=hour_offset)
            wave = sin((timestamp.hour / 24.0) * 6.28318)
            value = round(base_load_mw + (wave * 780.0) + (hour_offset * 18.0), 1)
            trend_points.append(
                TimeSeriesPoint(
                    timestamp=timestamp,
                    value=max(value, 0.0),
                    label=f"{timestamp:%H}:00",
                )
            )

        return trend_points

    def _build_mock_kpis(
        self,
        line_statuses: list[LineStatusSnapshot],
        trend_points: list[TimeSeriesPoint],
    ) -> list[MonitoringKpi]:
        latest_load = trend_points[-1].value if trend_points else 0.0
        previous_load = trend_points[-2].value if len(trend_points) >= 2 else latest_load
        peak_utilization = max((line.utilization for line in line_statuses), default=0.0)
        risk_line_count = sum(
            1 for line in line_statuses if line.risk_level in {"high", "critical"}
        )
        operating_margin = round(max(0.0, 1.0 - peak_utilization) * 100.0, 1)

        return [
            MonitoringKpi(
                metric_id="current_load",
                label="현재 총부하",
                value=latest_load,
                unit="MW",
                status="critical" if latest_load >= 12000 else "warning",
                delta=round(latest_load - previous_load, 1),
            ),
            MonitoringKpi(
                metric_id="peak_utilization",
                label="최대 이용률",
                value=round(peak_utilization * 100.0, 1),
                unit="%",
                status=_kpi_status_from_risk(_classify_risk(peak_utilization)),
                delta=None,
            ),
            MonitoringKpi(
                metric_id="risk_lines",
                label="고위험 선로 수",
                value=float(risk_line_count),
                unit="lines",
                status="critical" if risk_line_count >= 2 else "warning",
                delta=None,
            ),
            MonitoringKpi(
                metric_id="operating_margin",
                label="운영 여유도",
                value=operating_margin,
                unit="%",
                status="critical" if operating_margin < 12.0 else "warning",
                delta=None,
            ),
        ]

    def _build_warnings(
        self,
        line_statuses: list[LineStatusSnapshot],
    ) -> list[str]:
        warnings = [
            "MonitoringService는 현재 mock 계산 결과를 반환합니다.",
        ]
        critical_lines = [line.line_id for line in line_statuses if line.risk_level == "critical"]
        high_lines = [line.line_id for line in line_statuses if line.risk_level == "high"]

        if critical_lines:
            warnings.append(
                f"즉시 확인이 필요한 critical 선로: {', '.join(critical_lines)}"
            )
        elif high_lines:
            warnings.append(
                f"혼잡 임계치에 근접한 high 선로: {', '.join(high_lines)}"
            )

        return warnings

    def _build_summary(
        self,
        line_statuses: list[LineStatusSnapshot],
        trend_points: list[TimeSeriesPoint],
    ) -> str:
        latest_load = trend_points[-1].value if trend_points else 0.0
        busiest_line = line_statuses[0] if line_statuses else None
        high_or_above = sum(
            1 for line in line_statuses if line.risk_level in {"high", "critical"}
        )

        if busiest_line is None:
            return "모니터링 mock 결과를 만들었지만 표시할 선로 상태가 없습니다."

        return (
            f"현재 총부하는 {latest_load:,.0f}MW이며 "
            f"{busiest_line.from_bus_name}-{busiest_line.to_bus_name}({busiest_line.line_id}) "
            f"선로가 이용률 {busiest_line.utilization * 100:.1f}%로 가장 혼잡합니다. "
            f"고위험 선로는 {high_or_above}건입니다."
        )


def _round_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _classify_risk(utilization: float) -> str:
    if utilization >= 0.90:
        return "critical"
    if utilization >= 0.75:
        return "high"
    if utilization >= 0.55:
        return "medium"
    return "low"


def _kpi_status_from_risk(risk_level: str) -> str:
    if risk_level == "critical":
        return "critical"
    if risk_level == "high":
        return "warning"
    return "normal"

# 모니터링 흐름과 혼잡 요약 생성을 조율한다.
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from src.data.schemas import (
    CongestionSummary,
    LineStatus,
    MonitoringKpi,
    MonitoringResult,
    ScenarioContext,
    TimeSeriesPoint,
)
from src.engine.powerflow import dc_power_flow as _dcpf
from src.engine.powerflow.congestion_metrics import (
    compute_congestion_summary,
    compute_line_statuses,
)
from src.services.result_metadata import (
    build_fallback_info,
    build_fallback_warning,
    build_no_fallback_info,
    build_source_warning,
)

# ── 한국 345kV 주요 버스 (13개) ────────────────────────────────────────────────
# (bus_id, 이름)
_BUSES: dict[str, str] = {
    "B01": "신가평",
    "B02": "양주",
    "B03": "신용인",
    "B04": "신안성",
    "B05": "신평택",
    "B06": "서울동",
    "B07": "분당",
    "B08": "동서울",
    "B09": "수원",
    "B10": "신시흥",
    "B11": "인천북",
    "B12": "신강남",
    "B13": "신서울",
}

# ── mock 선로 정의 ─────────────────────────────────────────────────────────────
# (line_id, from_bus, to_bus, base_flow_mw, capacity_mw)
# base_flow_mw: 부하 배율 1.0 기준 기본 전력 흐름
# capacity_mw : 열적 한계 용량
_MOCK_LINE_DEFS: list[tuple[str, str, str, float, float]] = [
    ("L01", "B01", "B02", 210.0, 400.0),   # 신가평 → 양주
    ("L02", "B02", "B06", 285.0, 400.0),   # 양주 → 서울동
    ("L03", "B13", "B06", 260.0, 350.0),   # 신서울 → 서울동
    ("L04", "B06", "B08", 175.0, 300.0),   # 서울동 → 동서울
    ("L05", "B06", "B12", 310.0, 350.0),   # 서울동 → 신강남  (경고 구간)
    ("L06", "B08", "B07", 140.0, 200.0),   # 동서울 → 분당
    ("L07", "B12", "B07", 185.0, 200.0),   # 신강남 → 분당    (경고 구간)
    ("L08", "B07", "B03", 155.0, 250.0),   # 분당 → 신용인
    ("L09", "B03", "B09", 125.0, 200.0),   # 신용인 → 수원
    ("L10", "B09", "B04", 108.0, 200.0),   # 수원 → 신안성
    ("L11", "B04", "B05", 92.0,  180.0),   # 신안성 → 신평택
    ("L12", "B05", "B10", 145.0, 150.0),   # 신평택 → 신시흥  (위험 구간)
    ("L13", "B10", "B11", 68.0,  180.0),   # 신시흥 → 인천북
    ("L14", "B11", "B13", 115.0, 250.0),   # 인천북 → 신서울
    ("L15", "B02", "B11", 78.0,  250.0),   # 양주 → 인천북
]


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _round_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _congestion_status(util: float) -> str:
    if util >= 1.0:
        return "overload"
    if util >= 0.9:
        return "critical"
    if util >= 0.7:
        return "warning"
    return "normal"


def _classify_risk(util: float) -> str:
    if util >= 0.9:
        return "critical"
    if util >= 0.75:
        return "high"
    if util >= 0.55:
        return "medium"
    return "low"


def _kpi_status_from_risk(risk_level: str) -> str:
    if risk_level == "critical":
        return "critical"
    if risk_level == "high":
        return "warning"
    return "normal"


def _build_lines(load_scale: float) -> list[LineStatus]:
    rng = random.Random(42)
    lines: list[LineStatus] = []
    for lid, fb, tb, base_flow, cap in _MOCK_LINE_DEFS:
        noise = 1.0 + rng.uniform(-0.04, 0.04)
        flow = round(base_flow * load_scale * noise, 1)
        util = round(flow / cap, 4)
        loss = round(flow * 0.004 * util, 2)
        lines.append(
            LineStatus(
                line_id=lid,
                from_bus=fb,
                to_bus=tb,
                from_bus_name=_BUSES[fb],
                to_bus_name=_BUSES[tb],
                flow_mw=flow,
                capacity_mw=cap,
                utilization=util,
                status=_congestion_status(util),      # type: ignore[arg-type]
                risk_level=_classify_risk(util),      # type: ignore[arg-type]
                loss_mw=loss,
            )
        )
    return lines


def _build_congestion_summary(lines: list[LineStatus]) -> CongestionSummary:
    counts: dict[str, int] = {"normal": 0, "warning": 0, "critical": 0, "overload": 0}
    for line in lines:
        counts[line.status] += 1
    avg_util = sum(l.utilization for l in lines) / len(lines)
    total_loss = sum(l.loss_mw for l in lines)
    max_line = max(lines, key=lambda l: l.utilization)
    return CongestionSummary(
        total_lines=len(lines),
        normal_count=counts["normal"],
        warning_count=counts["warning"],
        critical_count=counts["critical"],
        overload_count=counts["overload"],
        avg_utilization=round(avg_util, 4),
        total_loss_mw=round(total_loss, 2),
        max_utilization=round(max_line.utilization, 4),
        max_utilization_line_id=max_line.line_id,
    )


def _build_kpis(
    cs: CongestionSummary,
    trend_points: list[TimeSeriesPoint],
) -> list[MonitoringKpi]:
    latest_load = trend_points[-1].value if trend_points else 0.0
    previous_load = trend_points[-2].value if len(trend_points) >= 2 else latest_load
    danger = cs.critical_count + cs.overload_count
    operating_margin = round(max(0.0, 1.0 - cs.max_utilization) * 100.0, 1)
    return [
        MonitoringKpi(
            metric_id="current_load",
            label="현재 총부하",
            value=latest_load,
            unit="MW",
            status="critical" if latest_load >= 40_000 else "warning" if latest_load >= 35_000 else "normal",
            delta=round(latest_load - previous_load, 1),
        ),
        MonitoringKpi(
            metric_id="peak_utilization",
            label="최대 이용률",
            value=round(cs.max_utilization * 100, 1),
            unit="%",
            status=_kpi_status_from_risk(_classify_risk(cs.max_utilization)),
        ),
        MonitoringKpi(
            metric_id="danger_lines",
            label="위험·과부하 선로",
            value=float(danger),
            unit="lines",
            status="critical" if danger > 0 else "normal",
            delta=float(cs.warning_count),
        ),
        MonitoringKpi(
            metric_id="operating_margin",
            label="운영 여유도",
            value=operating_margin,
            unit="%",
            status="critical" if operating_margin < 10.0 else "warning" if operating_margin < 25.0 else "normal",
        ),
    ]


def _build_trend_points(load_scale: float, base_time: datetime) -> list[TimeSeriesPoint]:
    """과거 12시간 총부하 mock 추세 (sinusoidal 패턴)."""
    base_load = 35_000.0
    base_hour = _round_to_hour(base_time)
    points: list[TimeSeriesPoint] = []
    for offset in range(-11, 1):
        t = base_hour + timedelta(hours=offset)
        wave = math.sin((t.hour / 24.0) * 2 * math.pi) * 0.15
        load = base_load * load_scale * (1.0 + wave)
        points.append(TimeSeriesPoint(timestamp=t, value=round(load, 0), label=f"{t:%H}:00"))
    return points


def _build_summary_text(cs: CongestionSummary, lines: list[LineStatus]) -> str:
    danger = cs.critical_count + cs.overload_count
    if danger == 0 and cs.warning_count == 0:
        return f"전체 {cs.total_lines}개 선로 정상 운영 중. 평균 이용률 {cs.avg_utilization*100:.1f}%."
    busiest = max(lines, key=lambda l: l.utilization)
    parts = []
    if danger > 0:
        parts.append(f"위험·과부하 {danger}개")
    if cs.warning_count > 0:
        parts.append(f"경고 {cs.warning_count}개")
    return (
        f"{', '.join(parts)} 선로 감지. "
        f"{busiest.from_bus_name}→{busiest.to_bus_name}({busiest.line_id}) "
        f"이용률 {busiest.utilization*100:.1f}%로 최대. 즉각 점검 권고."
    )


def _build_warnings(lines: list[LineStatus]) -> list[str]:
    warnings = [build_fallback_warning("MonitoringService", "mock_data")]
    critical = [l.line_id for l in lines if l.risk_level == "critical"]
    high = [l.line_id for l in lines if l.risk_level == "high"]
    if critical:
        warnings.append(f"즉시 확인이 필요한 critical 선로: {', '.join(critical)}")
    elif high:
        warnings.append(f"혼잡 임계치에 근접한 high 선로: {', '.join(high)}")
    return warnings


# ── 공개 함수 (하위 호환) ──────────────────────────────────────────────────────

def run_mock_monitoring(load_scale: float = 1.0) -> MonitoringResult:
    """mock 선로 데이터로 MonitoringResult 를 생성한다 (하위 호환 함수).

    Parameters
    ----------
    load_scale:
        전체 부하 배율. 1.0 = 기준 부하.
    """
    scenario = ScenarioContext(
        scenario_id="mock-001",
        title="Mock Scenario",
        created_at=datetime.now(),
        created_by="run_mock_monitoring",
    )
    return MonitoringService().run_mock_monitoring(scenario=scenario, load_scale=load_scale)


# ── MonitoringService 클래스 ───────────────────────────────────────────────────

class MonitoringService:
    """모니터링 흐름을 조율하는 서비스 클래스.

    1주차: run_mock_monitoring() 만 구현.
    3단계 이후: run_dc_power_flow() 로 교체 예정.
    """

    def run_mock_monitoring(
        self,
        scenario: ScenarioContext | None = None,
        load_scale: float = 1.0,
        *,
        created_at: datetime | None = None,
    ) -> MonitoringResult:
        """mock 데이터로 MonitoringResult 를 생성한다.

        Parameters
        ----------
        scenario:
            Monitoring, Simulation, Prediction 이 공유하는 시나리오 컨텍스트.
            None 이면 기본 mock 시나리오를 생성한다.
        load_scale:
            전체 부하 배율. 1.0 = 기준 부하.
        created_at:
            결과 기준 시각. None 이면 현재 시각을 사용한다.
        """
        now = _round_to_hour(created_at or datetime.now())
        resolved_scenario = self._resolve_scenario(scenario, now)
        lines = _build_lines(load_scale)
        cs = _build_congestion_summary(lines)
        trend = _build_trend_points(load_scale, now)

        return MonitoringResult(
            scenario=resolved_scenario,
            created_at=now,
            source="mock",
            load_scale=load_scale,
            line_statuses=lines,
            congestion_summary=cs,
            kpis=_build_kpis(cs, trend),
            trend_points=trend,
            summary=_build_summary_text(cs, lines),
            warnings=_build_warnings(lines),
            fallback=build_fallback_info(
                mode="mock_data",
                reason="실제 dc_power_flow 엔진 대신 mock 결과를 사용합니다.",
                primary_path="src.engine.powerflow.dc_power_flow",
                active_path="src.services.monitoring_service.MonitoringService.run_mock_monitoring",
            ),
        )

    def run_dc_power_flow(
        self,
        scenario: ScenarioContext | None = None,
        load_scale: float = 1.0,
        *,
        created_at: datetime | None = None,
    ) -> MonitoringResult:
        """DC Power Flow 계산으로 MonitoringResult 를 생성한다.

        DC 계산이 실패하면 자동으로 run_mock_monitoring() 으로 fallback 한다.

        Parameters
        ----------
        scenario:
            공유 시나리오 컨텍스트. None 이면 기본 시나리오를 생성한다.
        load_scale:
            전체 부하 배율. 1.0 = 기준 부하.
        created_at:
            결과 기준 시각. None 이면 현재 시각을 사용한다.
        """
        now = _round_to_hour(created_at or datetime.now())
        resolved_scenario = self._resolve_scenario(scenario, now)

        try:
            buses = _dcpf.build_default_buses(load_scale)
            lines = _dcpf.build_default_line_inputs()
            dc_result = _dcpf.solve(buses, lines)

            if not dc_result.converged:
                raise RuntimeError(dc_result.error)

            line_statuses = compute_line_statuses(dc_result)
            cs = compute_congestion_summary(line_statuses)
            trend = _build_trend_points(load_scale, now)

            return MonitoringResult(
                scenario=resolved_scenario,
                created_at=now,
                source="dc_power_flow",
                load_scale=load_scale,
                line_statuses=line_statuses,
                congestion_summary=cs,
                kpis=_build_kpis(cs, trend),
                trend_points=trend,
                summary=_build_summary_text(cs, line_statuses),
                warnings=[build_source_warning("MonitoringService", "dc_power_flow")],
                fallback=build_no_fallback_info(),
            )

        except Exception as exc:  # noqa: BLE001
            fallback_result = self.run_mock_monitoring(
                scenario=resolved_scenario,
                load_scale=load_scale,
                created_at=created_at,
            )
            fallback_result.warnings.insert(
                0,
                f"DC Power Flow 실패 → mock fallback 전환. 원인: {exc}",
            )
            fallback_result.fallback = build_fallback_info(
                mode="mock_data",
                reason=str(exc),
                primary_path="src.engine.powerflow.dc_power_flow.solve",
                active_path="src.services.monitoring_service.MonitoringService.run_mock_monitoring",
            )
            return fallback_result

    def get_monitoring_result(
        self,
        scenario: ScenarioContext | None = None,
        load_scale: float = 1.0,
        *,
        created_at: datetime | None = None,
    ) -> MonitoringResult:
        """기존 호출부 호환용 wrapper."""
        return self.run_mock_monitoring(
            scenario=scenario,
            load_scale=load_scale,
            created_at=created_at,
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

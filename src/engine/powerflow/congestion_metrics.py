# 전력 흐름 결과를 바탕으로 혼잡 지표와 과부하 지표를 계산한다.
from __future__ import annotations

from src.data.schemas import (
    CongestionSummary,
    LineStatus,
)
from src.engine.powerflow.dc_power_flow import DCFlowResult

# ── 한국 345kV 버스 이름 매핑 ─────────────────────────────────────────────────

_BUS_NAMES: dict[str, str] = {
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


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

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


# ── 공개 함수 ─────────────────────────────────────────────────────────────────

def compute_line_statuses(
    dc_result: DCFlowResult,
    bus_names: dict[str, str] | None = None,
) -> list[LineStatus]:
    """DCFlowResult 로부터 LineStatus 목록을 생성한다.

    Parameters
    ----------
    dc_result:
        dc_power_flow.solve() 의 반환값. converged=True 여야 한다.
    bus_names:
        bus_id → 한국어 이름 매핑. None 이면 내장 매핑을 사용한다.

    Returns
    -------
    list[LineStatus]
        이용률 내림차순으로 정렬된 LineStatus 목록.
    """
    names = bus_names if bus_names is not None else _BUS_NAMES
    line_statuses: list[LineStatus] = []

    for ln in dc_result.line_inputs:
        flow_mw = dc_result.line_flows.get(ln.line_id, 0.0)
        abs_flow = abs(flow_mw)
        util = round(abs_flow / ln.capacity_mw, 4) if ln.capacity_mw > 0 else 0.0
        loss = round(abs_flow * 0.004 * util, 2)

        line_statuses.append(
            LineStatus(
                line_id=ln.line_id,
                from_bus=ln.from_bus,
                to_bus=ln.to_bus,
                from_bus_name=names.get(ln.from_bus, ln.from_bus),
                to_bus_name=names.get(ln.to_bus, ln.to_bus),
                flow_mw=round(flow_mw, 1),
                capacity_mw=ln.capacity_mw,
                utilization=util,
                status=_congestion_status(util),        # type: ignore[arg-type]
                risk_level=_classify_risk(util),        # type: ignore[arg-type]
                loss_mw=loss,
            )
        )

    return sorted(line_statuses, key=lambda l: l.utilization, reverse=True)


def compute_congestion_summary(
    line_statuses: list[LineStatus],
) -> CongestionSummary:
    """LineStatus 목록을 집계하여 CongestionSummary를 반환한다."""
    counts: dict[str, int] = {"normal": 0, "warning": 0, "critical": 0, "overload": 0}
    for ls in line_statuses:
        counts[ls.status] += 1

    n = len(line_statuses)
    avg_util = sum(l.utilization for l in line_statuses) / n if n else 0.0
    total_loss = sum(l.loss_mw for l in line_statuses)
    max_line = max(line_statuses, key=lambda l: l.utilization) if line_statuses else None

    return CongestionSummary(
        total_lines=n,
        normal_count=counts["normal"],
        warning_count=counts["warning"],
        critical_count=counts["critical"],
        overload_count=counts["overload"],
        avg_utilization=round(avg_util, 4),
        total_loss_mw=round(total_loss, 2),
        max_utilization=round(max_line.utilization, 4) if max_line else 0.0,
        max_utilization_line_id=max_line.line_id if max_line else "",
    )

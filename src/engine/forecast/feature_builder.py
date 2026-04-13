# 부하 예측 워크플로에 필요한 입력 피처를 구성한다.
"""
feature_builder — ForecastFeatureVector 생성 모듈

입력 계약 (load_df)
-------------------
컬럼:
    timestamp      : datetime  (tz-naive, 1시간 간격)
    bus_id         : str       (예: "BUS_001")
    load_mw        : float     (해당 노드 수요, MW)
    generation_mw  : float     (해당 노드 발전량, MW; 발전 노드 아니면 0.0)

출력 계약
---------
ForecastFeatureVector (src/data/schemas.py)
    - lag 값이 부족한 경우 0.0 으로 채움 (safe fallback)
    - regional_demand_ratio 분모가 0이면 0.0 반환

사용 예시
---------
    from src.engine.forecast.feature_builder import build_feature_vector
    fv = build_feature_vector(load_df, target_ts=ts, bus_id="BUS_001")
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.data.schemas import ForecastFeatureVector

# 모델이 사용하는 lag 목록 (시간 단위) — 변경 시 모델 재훈련 필요
LAG_HOURS: list[int] = [1, 6, 12, 24, 48, 72]


def build_feature_vector(
    load_df: pd.DataFrame,
    target_ts: datetime,
    bus_id: str,
    is_holiday: bool = False,
) -> ForecastFeatureVector:
    """단일 노드·단일 타임스텝에 대한 ForecastFeatureVector 를 반환한다."""
    bus_df = load_df[load_df["bus_id"] == bus_id].copy()
    bus_df = bus_df[bus_df["timestamp"] < target_ts].sort_values("timestamp")

    def _lag(h: int) -> float:
        lag_ts = target_ts - timedelta(hours=h)
        row = bus_df[bus_df["timestamp"] == lag_ts]
        return float(row["load_mw"].iloc[0]) if not row.empty else 0.0

    # target_ts 직전 스냅샷으로 계통 전체 지표 계산
    snap_ts = target_ts - timedelta(hours=1)
    snap = load_df[load_df["timestamp"] == snap_ts]
    total_gen = float(snap["generation_mw"].sum()) if not snap.empty else 0.0
    total_load = float(snap["load_mw"].sum()) if not snap.empty else 0.0
    regional_ratio = (_lag(1) / total_load) if total_load > 0 else 0.0

    return ForecastFeatureVector(
        timestamp=target_ts,
        bus_id=bus_id,
        load_lag_1h=_lag(1),
        load_lag_6h=_lag(6),
        load_lag_12h=_lag(12),
        load_lag_24h=_lag(24),
        load_lag_48h=_lag(48),
        load_lag_72h=_lag(72),
        hour=target_ts.hour,
        day_of_week=target_ts.weekday(),
        is_weekend=target_ts.weekday() >= 5,
        is_holiday=is_holiday,
        month=target_ts.month,
        total_generation_mw=total_gen,
        regional_demand_ratio=round(regional_ratio, 4),
    )


def build_feature_matrix(
    load_df: pd.DataFrame,
    target_timestamps: list[datetime],
    bus_ids: list[str],
    holiday_set: set[str] | None = None,
) -> list[ForecastFeatureVector]:
    """여러 노드·여러 타임스텝에 대한 ForecastFeatureVector 목록을 반환한다.

    Returns
    -------
    list[ForecastFeatureVector]  — 타임스텝 × 노드 순서
    """
    holiday_set = holiday_set or set()
    return [
        build_feature_vector(
            load_df=load_df,
            target_ts=ts,
            bus_id=bid,
            is_holiday=ts.strftime("%Y-%m-%d") in holiday_set,
        )
        for ts in target_timestamps
        for bid in bus_ids
    ]


def build_prediction_feature_matrix(
    load_df: pd.DataFrame,
    forecast_start: datetime,
    bus_ids: list[str] | None = None,
    horizon_h: int = 24,
    holiday_set: set[str] | None = None,
) -> list[ForecastFeatureVector]:
    """예측 서비스가 바로 사용할 수 있는 horizon 구간 피처 목록을 반환한다."""
    resolved_bus_ids = (
        list(dict.fromkeys(bus_ids))
        if bus_ids is not None
        else sorted(load_df["bus_id"].dropna().unique().tolist())
    )
    target_timestamps = [
        forecast_start + timedelta(hours=h)
        for h in range(1, horizon_h + 1)
    ]
    return build_feature_matrix(
        load_df=load_df,
        target_timestamps=target_timestamps,
        bus_ids=resolved_bus_ids,
        holiday_set=holiday_set,
    )

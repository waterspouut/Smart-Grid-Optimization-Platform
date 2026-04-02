# SGOP의 입력과 출력에 쓰이는 공통 데이터 스키마를 정의한다.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


# ── 예측 피처 ─────────────────────────────────────────────────────────────────

@dataclass
class ForecastFeatureVector:
    """DC Power Flow 이후 예측 모델에 투입되는 단일 타임스텝 피처 벡터.

    입력 계약
    ---------
    - 과거 부하 lag: 1h / 6h / 12h / 24h / 48h / 72h (MW, 없으면 0.0)
    - 시간 특성: hour (0-23), day_of_week (0=월 … 6=일), is_weekend, is_holiday, month
    - 계통 특성: total_generation_mw, regional_demand_ratio (해당 노드 / 전체)

    출력 계약
    ---------
    ForecastFeatureVector 인스턴스 (lstm_forecaster / baseline 양쪽에서 공통 사용)
    """

    timestamp: datetime
    bus_id: str

    # 과거 부하 이력 (MW)
    load_lag_1h: float
    load_lag_6h: float
    load_lag_12h: float
    load_lag_24h: float
    load_lag_48h: float
    load_lag_72h: float

    # 시간 특성
    hour: int            # 0-23
    day_of_week: int     # 0=월 … 6=일
    is_weekend: bool
    is_holiday: bool
    month: int           # 1-12

    # 계통 특성
    total_generation_mw: float
    regional_demand_ratio: float  # 해당 노드 부하 / 전체 부하 (0.0-1.0)


# ── 예측 결과 ─────────────────────────────────────────────────────────────────

@dataclass
class HourlyLoadPrediction:
    """단일 노드·단일 시각의 예측값과 신뢰구간."""

    timestamp: datetime
    bus_id: str
    predicted_load_mw: float
    confidence_lower_mw: float
    confidence_upper_mw: float


RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass
class RiskLine:
    """24시간 예측 구간 중 혼잡 위험이 높은 선로 정보.

    risk_level 기준
    ---------------
    critical : 이용률 >= 90%  (즉각 대응 필요)
    high     : 이용률 >= 75%  (모니터링 강화)
    medium   : 이용률 >= 55%  (주의 관찰)
    low      : 이용률 < 55%   (정상)
    """

    line_id: str
    from_bus: str
    to_bus: str
    from_bus_name: str
    to_bus_name: str
    peak_risk_hour: int          # 위험 피크 시각 (0-23)
    predicted_utilization: float  # 0.0-1.0+ (1.0 = 열적한계 100%)
    risk_level: RiskLevel
    explanation: str             # xAI 규칙 기반 설명 문장


@dataclass
class PredictionResult:
    """PredictionService.run_mock_prediction() 의 최종 반환값.

    source 값
    ----------
    "mock"     : 합성 sinusoidal 데이터 (1주차 기본값)
    "baseline" : 이동평균 / 계절성 분해 baseline 모델
    "lstm"     : 훈련된 LSTM 모델
    """

    scenario_id: str
    created_at: datetime
    load_scale: float
    forecast_horizon_h: int           # 예측 시간 수 (기본 24)
    predictions: list[HourlyLoadPrediction]
    risk_lines: list[RiskLine]        # risk_level != "low" 인 선로만 포함, 이용률 내림차순
    summary: str
    source: Literal["lstm", "baseline", "mock"]

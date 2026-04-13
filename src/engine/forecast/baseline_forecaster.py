# 이력 데이터 기반 baseline 예측 모델을 구현한다.
"""
baseline_forecaster — 시간대별 평균 기반 예측

알고리즘
--------
1. load_df 에서 bus_id별·시간대(hour)별 부하 집계
2. 동일 시간대 평균(μ)·표준편차(σ) 계산
3. 예측값 = μ,  신뢰구간 = [μ - 1σ, μ + 1σ]

LSTM 과 동일한 fit/predict 인터페이스 → service 에서 투명하게 교체 가능
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.data.schemas import ForecastFeatureVector, HourlyLoadPrediction


class BaselineForecaster:
    """시간대별 평균으로 24시간 부하를 예측한다."""

    def fit(self, history_df: pd.DataFrame) -> "BaselineForecaster":
        """이력에서 bus별·시간대별 통계를 학습한다.

        Parameters
        ----------
        history_df : timestamp, bus_id, load_mw 컬럼 포함 DataFrame
        """
        df = history_df.copy()
        df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour

        stats = (
            df.groupby(["bus_id", "hour"])["load_mw"]
            .agg(["mean", "std"])
            .reset_index()
            .rename(columns={"mean": "mu", "std": "sigma"})
        )
        stats["sigma"] = stats["sigma"].fillna(stats["mu"] * 0.08)

        self._stats = stats
        self._bus_fallback: dict[str, float] = (
            df.groupby("bus_id")["load_mw"].mean().to_dict()
        )
        self._bus_ids: list[str] = sorted(df["bus_id"].unique().tolist())
        return self

    def predict(
        self,
        forecast_start: datetime | None = None,
        horizon_h: int = 24,
        target_features: list[ForecastFeatureVector] | None = None,
    ) -> list[HourlyLoadPrediction]:
        """forecast_start 이후 horizon_h 시간의 예측값을 반환한다."""
        if not hasattr(self, "_stats"):
            raise RuntimeError("fit() 을 먼저 호출하세요.")
        if target_features is None and forecast_start is None:
            raise ValueError("forecast_start 또는 target_features 중 하나는 필요합니다.")

        target_points: list[tuple[datetime, str, int]] = []
        if target_features is not None:
            target_points = [
                (feature.timestamp, feature.bus_id, feature.hour)
                for feature in target_features
            ]
        else:
            for h in range(1, horizon_h + 1):
                ts = forecast_start + timedelta(hours=h)
                hour = ts.hour
                for bus_id in self._bus_ids:
                    target_points.append((ts, bus_id, hour))

        results: list[HourlyLoadPrediction] = []
        for ts, bus_id, hour in target_points:
            row = self._stats[
                (self._stats["bus_id"] == bus_id) & (self._stats["hour"] == hour)
            ]
            if row.empty:
                mu = self._bus_fallback.get(bus_id, 0.0)
                sigma = mu * 0.08
            else:
                mu = float(row["mu"].iloc[0])
                sigma = float(row["sigma"].iloc[0])

            results.append(HourlyLoadPrediction(
                timestamp=ts,
                bus_id=bus_id,
                predicted_load_mw=round(max(0.0, mu), 1),
                confidence_lower_mw=round(max(0.0, mu - sigma), 1),
                confidence_upper_mw=round(mu + sigma, 1),
            ))
        return results

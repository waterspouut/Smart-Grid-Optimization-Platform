# 그래프 이웃 정보를 사용해 미래 부하 값을 예측한다.
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.data.schemas import ForecastFeatureVector, HourlyLoadPrediction

LOOKBACK_H = 24
HORIZON_H = 24

_GRAPH_EDGE_DEFS: list[tuple[str, str]] = [
    ("BUS_001", "BUS_002"),
    ("BUS_001", "BUS_003"),
    ("BUS_001", "BUS_004"),
    ("BUS_001", "BUS_007"),
    ("BUS_002", "BUS_003"),
    ("BUS_004", "BUS_005"),
    ("BUS_004", "BUS_006"),
    ("BUS_006", "BUS_007"),
    ("BUS_007", "BUS_008"),
    ("BUS_007", "BUS_009"),
    ("BUS_008", "BUS_010"),
    ("BUS_009", "BUS_010"),
    ("BUS_010", "BUS_011"),
    ("BUS_011", "BUS_012"),
    ("BUS_011", "BUS_013"),
    ("BUS_012", "BUS_013"),
    ("BUS_007", "BUS_011"),
]


def _group_target_features(
    target_features: list[ForecastFeatureVector],
) -> dict[str, list[ForecastFeatureVector]]:
    grouped: dict[str, list[ForecastFeatureVector]] = {}
    for feature in target_features:
        grouped.setdefault(feature.bus_id, []).append(feature)

    for bus_features in grouped.values():
        bus_features.sort(key=lambda item: item.timestamp)
    return grouped


def _build_neighbor_map(
    bus_ids: list[str],
    graph_edges: list[tuple[str, str]] | None = None,
) -> dict[str, list[str]]:
    resolved_edges = graph_edges or _GRAPH_EDGE_DEFS
    neighbor_map = {bus_id: set() for bus_id in bus_ids}
    for from_bus, to_bus in resolved_edges:
        if from_bus in neighbor_map and to_bus in neighbor_map:
            neighbor_map[from_bus].add(to_bus)
            neighbor_map[to_bus].add(from_bus)

    ordered_bus_ids = sorted(bus_ids)
    for index, bus_id in enumerate(ordered_bus_ids):
        if neighbor_map[bus_id]:
            continue
        fallback_neighbors = []
        if index > 0:
            fallback_neighbors.append(ordered_bus_ids[index - 1])
        if index < len(ordered_bus_ids) - 1:
            fallback_neighbors.append(ordered_bus_ids[index + 1])
        neighbor_map[bus_id].update(fallback_neighbors)

    return {
        bus_id: sorted(neighbors)
        for bus_id, neighbors in neighbor_map.items()
    }


class GNNForecaster:
    """인접 버스 메시지 패싱 기반 최소 GNN 예측기."""

    def fit(
        self,
        history_df: pd.DataFrame,
        graph_edges: list[tuple[str, str]] | None = None,
    ) -> "GNNForecaster":
        df = history_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values(["bus_id", "timestamp"])
        df["hour"] = df["timestamp"].dt.hour

        stats = (
            df.groupby(["bus_id", "hour"])["load_mw"]
            .agg(["mean", "std"])
            .reset_index()
            .rename(columns={"mean": "mu", "std": "sigma"})
        )
        stats["sigma"] = stats["sigma"].fillna(stats["mu"] * 0.07)

        self._stats = stats
        self._bus_means = df.groupby("bus_id")["load_mw"].mean().to_dict()
        self._bus_ids = sorted(df["bus_id"].unique().tolist())
        self._neighbor_map = _build_neighbor_map(self._bus_ids, graph_edges=graph_edges)
        self._temperature_supported = "temperature_c" in df.columns
        if self._temperature_supported:
            self._temperature_mean = (
                df.groupby("bus_id")["temperature_c"].mean().to_dict()
            )
        return self

    def predict(
        self,
        history_df: pd.DataFrame,
        forecast_start: datetime,
        horizon_h: int = HORIZON_H,
        target_features: list[ForecastFeatureVector] | None = None,
    ) -> list[HourlyLoadPrediction]:
        if not hasattr(self, "_stats"):
            raise RuntimeError("fit() 을 먼저 호출하세요.")

        df = history_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values(["bus_id", "timestamp"])

        targets_by_bus: dict[str, list[ForecastFeatureVector]] = {}
        if target_features is not None:
            targets_by_bus = _group_target_features(target_features)
            unknown_bus_ids = sorted(set(targets_by_bus) - set(self._bus_ids))
            if unknown_bus_ids:
                raise ValueError(
                    f"target_features에 학습되지 않은 bus_id가 포함되어 있습니다: {unknown_bus_ids}"
                )

        target_timestamps = (
            sorted({feature.timestamp for feature in target_features})
            if target_features is not None
            else [forecast_start + timedelta(hours=h) for h in range(1, horizon_h + 1)]
        )
        recent_loads = self._build_recent_load_windows(df=df, forecast_start=forecast_start)
        recent_temps = self._build_recent_temperature_state(df=df)

        prediction_map: dict[tuple[datetime, str], HourlyLoadPrediction] = {}
        for target_ts in target_timestamps:
            bus_step_predictions: dict[str, float] = {}
            for bus_id in self._bus_ids:
                stats_row = self._stats[
                    (self._stats["bus_id"] == bus_id) & (self._stats["hour"] == target_ts.hour)
                ]
                hourly_mu = (
                    float(stats_row["mu"].iloc[0])
                    if not stats_row.empty
                    else float(self._bus_means.get(bus_id, 0.0))
                )
                sigma = (
                    float(stats_row["sigma"].iloc[0])
                    if not stats_row.empty
                    else hourly_mu * 0.07
                )
                own_recent = self._blend_recent_signal(recent_loads[bus_id], fallback=hourly_mu)
                neighbor_recent = self._neighbor_recent_signal(
                    bus_id=bus_id,
                    recent_loads=recent_loads,
                    pending_predictions=bus_step_predictions,
                    fallback=own_recent,
                )
                temp_adjustment = self._temperature_adjustment(
                    bus_id=bus_id,
                    recent_temps=recent_temps,
                )

                predicted_load = (
                    (hourly_mu * 0.48)
                    + (own_recent * 0.34)
                    + (neighbor_recent * 0.18)
                ) * temp_adjustment
                predicted_load = float(max(0.0, predicted_load))
                bus_step_predictions[bus_id] = predicted_load

                ci = max(sigma * 0.9, predicted_load * 0.05)
                prediction_map[(target_ts, bus_id)] = HourlyLoadPrediction(
                    timestamp=target_ts,
                    bus_id=bus_id,
                    predicted_load_mw=round(predicted_load, 1),
                    confidence_lower_mw=round(max(0.0, predicted_load - ci), 1),
                    confidence_upper_mw=round(predicted_load + ci, 1),
                )

            for bus_id, predicted_load in bus_step_predictions.items():
                recent_loads[bus_id].append(predicted_load)

        if target_features is None:
            return sorted(
                prediction_map.values(),
                key=lambda item: (item.timestamp, item.bus_id),
            )

        return [
            prediction_map[(feature.timestamp, feature.bus_id)]
            for feature in target_features
            if (feature.timestamp, feature.bus_id) in prediction_map
        ]

    def _build_recent_load_windows(
        self,
        *,
        df: pd.DataFrame,
        forecast_start: datetime,
    ) -> dict[str, deque[float]]:
        recent_loads: dict[str, deque[float]] = {}
        window_end = forecast_start - timedelta(hours=1)
        for bus_id in self._bus_ids:
            bus_df = df[df["bus_id"] == bus_id].sort_values("timestamp")
            eligible = bus_df[bus_df["timestamp"] <= window_end]
            source_df = eligible if not eligible.empty else bus_df
            values = source_df["load_mw"].tail(LOOKBACK_H).tolist()
            if len(values) < LOOKBACK_H:
                pad_value = float(self._bus_means.get(bus_id, 0.0))
                values = ([pad_value] * (LOOKBACK_H - len(values))) + values
            recent_loads[bus_id] = deque(
                [float(value) for value in values[-LOOKBACK_H:]],
                maxlen=LOOKBACK_H,
            )
        return recent_loads

    def _build_recent_temperature_state(
        self,
        *,
        df: pd.DataFrame,
    ) -> dict[str, float]:
        if not self._temperature_supported:
            return {}

        recent_temps: dict[str, float] = {}
        for bus_id in self._bus_ids:
            bus_df = df[df["bus_id"] == bus_id].sort_values("timestamp")
            if bus_df.empty or "temperature_c" not in bus_df.columns:
                continue
            recent_temps[bus_id] = float(bus_df["temperature_c"].iloc[-1])
        return recent_temps

    def _blend_recent_signal(self, values: deque[float], *, fallback: float) -> float:
        last_value = values[-1] if values else fallback
        last_three = list(values)[-3:] if values else [fallback]
        last_six = list(values)[-6:] if values else [fallback]
        return float(
            (last_value * 0.45)
            + (np.mean(last_three) * 0.30)
            + (np.mean(last_six) * 0.15)
            + (fallback * 0.10)
        )

    def _neighbor_recent_signal(
        self,
        *,
        bus_id: str,
        recent_loads: dict[str, deque[float]],
        pending_predictions: dict[str, float],
        fallback: float,
    ) -> float:
        neighbor_values = [
            pending_predictions.get(neighbor_id, recent_loads[neighbor_id][-1])
            for neighbor_id in self._neighbor_map.get(bus_id, [])
            if neighbor_id in recent_loads
        ]
        if not neighbor_values:
            return fallback
        return float(np.mean(neighbor_values))

    def _temperature_adjustment(
        self,
        *,
        bus_id: str,
        recent_temps: dict[str, float],
    ) -> float:
        if not self._temperature_supported:
            return 1.0
        latest_temp = recent_temps.get(bus_id)
        temp_mean = self._temperature_mean.get(bus_id)
        if latest_temp is None or temp_mean is None:
            return 1.0
        anomaly = latest_temp - temp_mean
        return float(np.clip(1.0 + (anomaly * 0.004), 0.94, 1.06))

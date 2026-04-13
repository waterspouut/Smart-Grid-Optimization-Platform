# LSTM 기반 모델로 미래 부하 값을 예측한다.
"""
lstm_forecaster — LSTM 기반 24시간 부하 예측

아키텍처
--------
입력  : (batch, 24, 5)  — 최근 24h × [load_norm, hour_sin, hour_cos, is_weekend, temp_norm]
출력  : (batch, 24)     — 다음 24h 정규화 부하
구조  : LSTM(64) → Dropout(0.2) → Dense(24)

학습 전략
---------
- bus 별 독립 MinMaxScaler 로 정규화 (계통 규모 차이 흡수)
- 하나의 공유 모델 학습 (전 버스 데이터 합산 → 일반화 성능 확보)
- EarlyStopping(patience=3) 으로 최적 에포크 자동 선택
- 학습 후 models/lstm/model.keras + scalers.pkl 저장
"""
from __future__ import annotations

import pickle
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.schemas import ForecastFeatureVector, HourlyLoadPrediction

_MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "lstm"
_MODEL_PATH = _MODEL_DIR / "model.keras"
_SCALER_PATH = _MODEL_DIR / "scalers.pkl"

LOOKBACK_H = 24
HORIZON_H = 24
FEATURE_DIM = 5  # load_norm, hour_sin, hour_cos, is_weekend, temp_norm


def _time_features(ts_series: pd.Series) -> np.ndarray:
    """timestamp Series → [hour_sin, hour_cos, is_weekend] 배열."""
    hour = ts_series.dt.hour.values
    dow  = ts_series.dt.dayofweek.values
    return np.stack([
        np.sin(2 * np.pi * hour / 24),
        np.cos(2 * np.pi * hour / 24),
        (dow >= 5).astype(float),
    ], axis=1)


def _build_windows(
    load_norm: np.ndarray,
    time_feats: np.ndarray,
    temp_norm: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """슬라이딩 윈도우 X(lookback, 5), y(horizon,) 생성."""
    X, y = [], []
    n = len(load_norm)
    for i in range(n - LOOKBACK_H - HORIZON_H + 1):
        x_load = load_norm[i: i + LOOKBACK_H].reshape(-1, 1)
        x_time = time_feats[i: i + LOOKBACK_H]
        x_temp = temp_norm[i: i + LOOKBACK_H].reshape(-1, 1)
        X.append(np.hstack([x_load, x_time, x_temp]))
        y.append(load_norm[i + LOOKBACK_H: i + LOOKBACK_H + HORIZON_H])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


def _group_target_features(
    target_features: list[ForecastFeatureVector],
) -> dict[str, list[ForecastFeatureVector]]:
    grouped: dict[str, list[ForecastFeatureVector]] = {}
    for feature in target_features:
        grouped.setdefault(feature.bus_id, []).append(feature)

    for bus_features in grouped.values():
        bus_features.sort(key=lambda feature: feature.timestamp)
    return grouped


class LSTMForecaster:
    """LSTM 기반 24시간 부하 예측기.

    사용 흐름
    ---------
    1. fit(history_df)          — 학습 후 models/lstm/ 에 저장
    2. predict(history_df, ts)  — 저장된 모델 로드 후 추론
    """

    def fit(
        self,
        history_df: pd.DataFrame,
        epochs: int = 20,
        batch_size: int = 64,
        validation_split: float = 0.1,
        test_split: float = 0.0,
    ) -> "LSTMForecaster":
        """history_df 로 LSTM 을 학습하고 모델을 저장한다.

        Parameters
        ----------
        history_df : timestamp, bus_id, load_mw 컬럼 포함 DataFrame (1시간 간격)
        test_split : 0.0 초과 시 시간 순서 기준 뒷부분을 테스트셋으로 분리.
        """
        from sklearn.preprocessing import MinMaxScaler
        import tensorflow as tf

        df = history_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values(["bus_id", "timestamp"])

        # ── train / test 시간 분리 ─────────────────────────────────────────────
        if test_split > 0.0:
            timestamps = sorted(df["timestamp"].unique())
            split_idx = int(len(timestamps) * (1.0 - test_split))
            split_ts = timestamps[split_idx]
            train_df = df[df["timestamp"] < split_ts]
            test_df  = df[df["timestamp"] >= split_ts]
            print(f"[분할] 학습: ~ {split_ts}  |  테스트: {split_ts} ~ ({len(timestamps) - split_idx}h)")
        else:
            train_df = df
            test_df  = None

        # ── 기온 공통 스케일러 ─────────────────────────────────────────────────
        has_temp = "temperature_c" in train_df.columns
        temp_scaler = MinMaxScaler()
        if has_temp:
            temp_scaler.fit(train_df["temperature_c"].dropna().values.reshape(-1, 1))

        scalers: dict[str, MinMaxScaler] = {}
        X_train_all, y_train_all = [], []
        X_test_all,  y_test_all  = [], []

        bus_ids = sorted(df["bus_id"].unique())
        for bus_id in bus_ids:
            tr = train_df[train_df["bus_id"] == bus_id].set_index("timestamp").sort_index()
            scaler = MinMaxScaler()
            load_norm_tr = scaler.fit_transform(tr["load_mw"].values.reshape(-1, 1)).flatten()
            scalers[bus_id] = scaler

            temp_norm_tr = (
                temp_scaler.transform(tr["temperature_c"].fillna(0).values.reshape(-1, 1)).flatten()
                if has_temp else np.zeros(len(tr))
            )
            X, y = _build_windows(load_norm_tr, _time_features(tr.index.to_series()), temp_norm_tr)
            X_train_all.append(X)
            y_train_all.append(y)

            if test_df is not None:
                te = test_df[test_df["bus_id"] == bus_id].set_index("timestamp").sort_index()
                if len(te) >= LOOKBACK_H + HORIZON_H:
                    load_norm_te = scaler.transform(te["load_mw"].values.reshape(-1, 1)).flatten()
                    temp_norm_te = (
                        temp_scaler.transform(te["temperature_c"].fillna(0).values.reshape(-1, 1)).flatten()
                        if has_temp else np.zeros(len(te))
                    )
                    Xt, yt = _build_windows(load_norm_te, _time_features(te.index.to_series()), temp_norm_te)
                    X_test_all.append(Xt)
                    y_test_all.append(yt)

        X_train = np.concatenate(X_train_all, axis=0)
        y_train = np.concatenate(y_train_all, axis=0)

        idx = np.random.permutation(len(X_train))
        X_train, y_train = X_train[idx], y_train[idx]

        print(f"[샘플] 학습: {len(X_train):,}개" + (
            f"  |  테스트: {sum(len(x) for x in X_test_all):,}개" if X_test_all else ""
        ))

        model = tf.keras.Sequential([
            tf.keras.layers.Input(shape=(LOOKBACK_H, FEATURE_DIM)),
            tf.keras.layers.LSTM(64),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(HORIZON_H),
        ])
        model.compile(optimizer="adam", loss="mse", metrics=["mae"])
        model.fit(
            X_train, y_train,
            epochs=epochs,
            batch_size=batch_size,
            validation_split=validation_split,
            callbacks=[
                tf.keras.callbacks.EarlyStopping(
                    monitor="val_loss", patience=3, restore_best_weights=True
                )
            ],
            verbose=1,
        )

        # ── 테스트셋 평가 ──────────────────────────────────────────────────────
        if X_test_all:
            X_test = np.concatenate(X_test_all, axis=0)
            y_test = np.concatenate(y_test_all, axis=0)
            y_pred = model.predict(X_test, verbose=0)

            mse  = float(np.mean((y_pred - y_test) ** 2))
            rmse = float(np.sqrt(mse))
            mae  = float(np.mean(np.abs(y_pred - y_test)))
            mask = y_test > 1e-6
            mape = float(np.mean(np.abs((y_pred[mask] - y_test[mask]) / y_test[mask])) * 100)
            ss_res = float(np.sum((y_test - y_pred) ** 2))
            ss_tot = float(np.sum((y_test - y_test.mean()) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

            print("\n" + "=" * 45)
            print("  테스트셋 평가 결과 (정규화 공간 기준)")
            print("=" * 45)
            print(f"  MSE  : {mse:.6f}")
            print(f"  RMSE : {rmse:.6f}")
            print(f"  MAE  : {mae:.6f}")
            print(f"  MAPE : {mape:.2f}%")
            print(f"  R²   : {r2:.4f}")
            print("=" * 45)

        _MODEL_DIR.mkdir(parents=True, exist_ok=True)
        model.save(_MODEL_PATH)
        with open(_SCALER_PATH, "wb") as f:
            pickle.dump({"scalers": scalers, "bus_ids": bus_ids, "temp_scaler": temp_scaler}, f)

        self._model = model
        self._scalers = scalers
        self._bus_ids = bus_ids
        self._temp_scaler = temp_scaler
        return self

    def predict(
        self,
        history_df: pd.DataFrame,
        forecast_start: datetime,
        horizon_h: int = HORIZON_H,
        target_features: list[ForecastFeatureVector] | None = None,
    ) -> list[HourlyLoadPrediction]:
        """forecast_start 이전 24h 이력으로 다음 horizon_h 시간을 예측한다."""
        self._load_if_needed()

        df = history_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        targets_by_bus: dict[str, list[ForecastFeatureVector]] = {}
        if target_features is not None:
            targets_by_bus = _group_target_features(target_features)
            unknown_bus_ids = sorted(set(targets_by_bus) - set(self._bus_ids))
            if unknown_bus_ids:
                raise ValueError(
                    f"target_features에 학습되지 않은 bus_id가 포함되어 있습니다: {unknown_bus_ids}"
                )

        prediction_map: dict[tuple[datetime, str], HourlyLoadPrediction] = {}
        window_end   = forecast_start - timedelta(hours=1)
        window_start = forecast_start - timedelta(hours=LOOKBACK_H)

        for bus_id in self._bus_ids:
            bus_target_features = targets_by_bus.get(bus_id)
            if target_features is not None and not bus_target_features:
                continue

            bus_df = (
                df[df["bus_id"] == bus_id]
                .set_index("timestamp")
                .sort_index()
            )
            window = bus_df.loc[window_start:window_end, "load_mw"]
            if len(window) < LOOKBACK_H:
                pad = np.zeros(LOOKBACK_H - len(window))
                load_vals = np.concatenate([pad, window.values])
            else:
                load_vals = window.values[-LOOKBACK_H:]

            scaler = self._scalers[bus_id]
            load_norm = scaler.transform(load_vals.reshape(-1, 1)).flatten()

            ts_idx = pd.date_range(end=window_end, periods=LOOKBACK_H, freq="h")
            time_feats = _time_features(pd.Series(ts_idx))

            if "temperature_c" in df.columns and self._temp_scaler is not None:
                temp_window = bus_df.loc[window_start:window_end, "temperature_c"]
                if len(temp_window) < LOOKBACK_H:
                    pad = np.zeros(LOOKBACK_H - len(temp_window))
                    temp_vals = np.concatenate([pad, temp_window.values])
                else:
                    temp_vals = temp_window.values[-LOOKBACK_H:]
                temp_norm = self._temp_scaler.transform(temp_vals.reshape(-1, 1)).flatten()
            else:
                temp_norm = np.zeros(LOOKBACK_H)

            X = np.hstack([load_norm.reshape(-1, 1), time_feats, temp_norm.reshape(-1, 1)])[np.newaxis].astype(np.float32)
            pred_norm = self._model.predict(X, verbose=0)[0]
            pred_mw = scaler.inverse_transform(pred_norm.reshape(-1, 1)).flatten()

            if bus_target_features is not None:
                target_timestamps = [
                    feature.timestamp
                    for feature in bus_target_features[:horizon_h]
                ]
            else:
                target_timestamps = [
                    forecast_start + timedelta(hours=h)
                    for h in range(1, horizon_h + 1)
                ]

            for ts, mw in zip(target_timestamps, pred_mw[: len(target_timestamps)]):
                mw = float(max(0.0, mw))
                ci = mw * 0.06
                prediction_map[(ts, bus_id)] = HourlyLoadPrediction(
                    timestamp=ts,
                    bus_id=bus_id,
                    predicted_load_mw=round(mw, 1),
                    confidence_lower_mw=round(max(0.0, mw - ci), 1),
                    confidence_upper_mw=round(mw + ci, 1),
                )

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

    def is_trained(self) -> bool:
        return _MODEL_PATH.exists() and _SCALER_PATH.exists()

    def _load_if_needed(self) -> None:
        if hasattr(self, "_model"):
            return
        if not self.is_trained():
            raise RuntimeError("학습된 LSTM 모델이 없습니다. fit() 을 먼저 실행하세요.")
        import tensorflow as tf
        self._model = tf.keras.models.load_model(_MODEL_PATH)
        with open(_SCALER_PATH, "rb") as f:
            data = pickle.load(f)
        self._scalers = data["scalers"]
        self._bus_ids = data["bus_ids"]
        self._temp_scaler = data.get("temp_scaler")

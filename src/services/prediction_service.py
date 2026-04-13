# 예측 워크플로와 결과 처리 흐름을 조율한다.
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.data.schemas import (
    HourlyLoadPrediction,
    PredictionResult,
    RiskLine,
    ScenarioContext,
)
from src.services.result_metadata import (
    build_fallback_info,
    build_fallback_warning,
    build_no_fallback_info,
    build_source_warning,
)

# ── 13-노드 정의 ───────────────────────────────────────────────────────────────
_BUSES: list[dict] = [
    {"bus_id": "BUS_001", "name": "서울",  "peak_mw": 7000},
    {"bus_id": "BUS_002", "name": "인천",  "peak_mw": 3500},
    {"bus_id": "BUS_003", "name": "수원",  "peak_mw": 2500},
    {"bus_id": "BUS_004", "name": "춘천",  "peak_mw": 1000},
    {"bus_id": "BUS_005", "name": "강릉",  "peak_mw":  800},
    {"bus_id": "BUS_006", "name": "원주",  "peak_mw": 1200},
    {"bus_id": "BUS_007", "name": "대전",  "peak_mw": 3000},
    {"bus_id": "BUS_008", "name": "청주",  "peak_mw": 1500},
    {"bus_id": "BUS_009", "name": "광주",  "peak_mw": 2500},
    {"bus_id": "BUS_010", "name": "전주",  "peak_mw": 1200},
    {"bus_id": "BUS_011", "name": "대구",  "peak_mw": 3500},
    {"bus_id": "BUS_012", "name": "울산",  "peak_mw": 2000},
    {"bus_id": "BUS_013", "name": "부산",  "peak_mw": 4000},
]

# ── 선로 정의 (from, to, thermal_limit_mw) ────────────────────────────────────
_LINES: list[dict] = [
    {"line_id": "L01", "from": "BUS_001", "to": "BUS_002", "limit_mw": 3000},
    {"line_id": "L02", "from": "BUS_001", "to": "BUS_003", "limit_mw": 2500},
    {"line_id": "L03", "from": "BUS_001", "to": "BUS_004", "limit_mw": 1500},
    {"line_id": "L04", "from": "BUS_001", "to": "BUS_007", "limit_mw": 3000},
    {"line_id": "L05", "from": "BUS_002", "to": "BUS_003", "limit_mw": 2000},
    {"line_id": "L06", "from": "BUS_004", "to": "BUS_005", "limit_mw": 1000},
    {"line_id": "L07", "from": "BUS_004", "to": "BUS_006", "limit_mw": 1500},
    {"line_id": "L08", "from": "BUS_006", "to": "BUS_007", "limit_mw": 2000},
    {"line_id": "L09", "from": "BUS_007", "to": "BUS_008", "limit_mw": 2000},
    {"line_id": "L10", "from": "BUS_007", "to": "BUS_009", "limit_mw": 2000},
    {"line_id": "L11", "from": "BUS_008", "to": "BUS_010", "limit_mw": 1500},
    {"line_id": "L12", "from": "BUS_009", "to": "BUS_010", "limit_mw": 1500},
    {"line_id": "L13", "from": "BUS_010", "to": "BUS_011", "limit_mw": 2000},
    {"line_id": "L14", "from": "BUS_011", "to": "BUS_012", "limit_mw": 4000},
    {"line_id": "L15", "from": "BUS_011", "to": "BUS_013", "limit_mw": 3000},
    {"line_id": "L16", "from": "BUS_012", "to": "BUS_013", "limit_mw": 3500},
    {"line_id": "L17", "from": "BUS_007", "to": "BUS_011", "limit_mw": 2500},
]


def _hourly_factor(hour: int, day_of_week: int) -> float:
    """시간대·요일별 부하 배율 (0.55 ~ 1.0).

    이중 피크 패턴: 오전 10시 + 오후 14시
    주말은 평일 대비 85% 수준
    """
    weekend_coef = 0.85 if day_of_week >= 5 else 1.0
    morning = 0.6 * np.exp(-((hour - 10) ** 2) / 8.0)
    afternoon = 0.4 * np.exp(-((hour - 14) ** 2) / 10.0)
    base = 0.55 + 0.30 * (morning + afternoon)
    return float(np.clip(base * weekend_coef, 0.50, 1.00))


class PredictionService:
    """예측 워크플로와 결과 처리 흐름을 조율한다.

    1주차: run_mock_prediction() 사용 (합성 데이터 기반, API 없음)
    2주차 이후: generate_load_history() → feature_builder → lstm/baseline 연결
    """

    def generate_load_history(
        self,
        end_ts: datetime,
        hours: int = 72,
        load_scale: float = 1.0,
        rng_seed: int = 42,
    ) -> pd.DataFrame:
        """과거 hours 시간의 합성 부하 이력을 DataFrame 으로 반환한다.

        컬럼: timestamp, bus_id, bus_name, load_mw, generation_mw
        feature_builder.build_feature_vector() 의 load_df 입력 계약을 만족한다.
        """
        rng = np.random.default_rng(rng_seed)
        start_ts = end_ts - timedelta(hours=hours)
        timestamps = [start_ts + timedelta(hours=h) for h in range(hours)]

        rows: list[dict] = []
        for ts in timestamps:
            factor = _hourly_factor(ts.hour, ts.weekday())
            for bus in _BUSES:
                noise = float(rng.normal(0, 0.03))
                load_mw = bus["peak_mw"] * load_scale * factor * (1 + noise)
                gen_mw = (
                    5000.0 * (1 + float(rng.normal(0, 0.015)))
                    if bus["bus_id"] == "BUS_012"
                    else 0.0
                )
                rows.append({
                    "timestamp": ts,
                    "bus_id": bus["bus_id"],
                    "bus_name": bus["name"],
                    "load_mw": round(max(0.0, load_mw), 1),
                    "generation_mw": round(max(0.0, gen_mw), 1),
                })
        return pd.DataFrame(rows)

    def run_mock_prediction(
        self,
        load_scale: float = 1.0,
        created_at: datetime | None = None,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
    ) -> PredictionResult:
        """합성 패턴 기반 24시간 예측 결과를 반환한다.

        Parameters
        ----------
        load_scale     : 부하 배율 (1.0 = 기본, 1.2 = 20% 증가)
        created_at     : 공통 서비스 인터페이스 기준 시각
        forecast_start : 기존 호출부 호환용 예측 기준 시각
        """
        now = (created_at or forecast_start or datetime.now()).replace(
            minute=0, second=0, microsecond=0
        )
        resolved_scenario = self._resolve_scenario(scenario, now)
        predictions = self._generate_predictions(now, load_scale)
        risk_lines = self._compute_risk_lines(predictions, load_scale)
        summary = self._build_summary(now, predictions, risk_lines)

        return PredictionResult(
            scenario_id=resolved_scenario.scenario_id,
            created_at=now,
            load_scale=load_scale,
            forecast_horizon_h=24,
            predictions=predictions,
            risk_lines=risk_lines,
            summary=summary,
            source="mock",
            scenario=resolved_scenario,
            warnings=self._build_warnings(),
            fallback=build_fallback_info(
                mode="mock_data",
                reason="실제 예측 모델 대신 PredictionService의 mock 패턴 예측 결과를 사용합니다.",
                primary_path="src.engine.forecast.feature_builder -> baseline/lstm/gnn forecaster",
                active_path="src.services.prediction_service.PredictionService.run_mock_prediction",
            ),
        )

    def run_baseline_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
    ) -> PredictionResult:
        """KPX 실데이터 기반 baseline 예측 결과를 반환한다.

        Parameters
        ----------
        raw_dir        : sukub*.csv 가 있는 디렉터리 경로
        load_scale     : 부하 배율
        forecast_start : 예측 기준 시각 (None 이면 현재 시각)
        """
        from src.data.adapters.public_data_adapter import load_kpx_csvs

        now = (forecast_start or datetime.now()).replace(minute=0, second=0, microsecond=0)
        resolved_scenario = self._resolve_scenario(scenario, now)

        load_df = self._apply_load_scale(load_kpx_csvs(raw_dir), load_scale)
        predictions = self._predict_baseline(
            load_df=load_df,
            forecast_start=now,
        )

        return self._build_prediction_result(
            scenario=resolved_scenario,
            created_at=now,
            load_scale=load_scale,
            predictions=predictions,
            source="baseline",
            warnings=[],
        )

    def run_lstm_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
        retrain: bool = False,
        epochs: int = 20,
    ) -> PredictionResult:
        """LSTM 학습/추론 기반 24시간 예측 결과를 반환한다.

        Parameters
        ----------
        raw_dir        : sukub*.csv 가 있는 디렉터리 경로
        load_scale     : 부하 배율
        forecast_start : 예측 기준 시각 (None 이면 현재 시각)
        retrain        : True 이면 저장된 모델 무시하고 재학습
        epochs         : 재학습 시 에포크 수
        """
        now = (forecast_start or datetime.now()).replace(minute=0, second=0, microsecond=0)
        resolved_scenario = self._resolve_scenario(scenario, now)
        load_df = self._load_weather_history(raw_dir)
        history_df = self._apply_load_scale(load_df, load_scale)
        target_features = self._build_target_features(
            load_df=history_df,
            forecast_start=now,
        )
        predictions, warnings = self._predict_lstm(
            training_df=load_df,
            history_df=history_df,
            forecast_start=now,
            target_features=target_features,
            retrain=retrain,
            epochs=epochs,
        )

        return self._build_prediction_result(
            scenario=resolved_scenario,
            created_at=now,
            load_scale=load_scale,
            predictions=predictions,
            source="lstm",
            warnings=warnings,
        )

    def run_gnn_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
    ) -> PredictionResult:
        """그래프 기반 최소 GNN 예측 결과를 반환한다."""
        now = (forecast_start or datetime.now()).replace(minute=0, second=0, microsecond=0)
        resolved_scenario = self._resolve_scenario(scenario, now)

        history_df = self._apply_load_scale(self._load_weather_history(raw_dir), load_scale)
        target_features = self._build_target_features(
            load_df=history_df,
            forecast_start=now,
        )
        predictions = self._predict_gnn(
            history_df=history_df,
            forecast_start=now,
            target_features=target_features,
        )

        return self._build_prediction_result(
            scenario=resolved_scenario,
            created_at=now,
            load_scale=load_scale,
            predictions=predictions,
            source="gnn",
            warnings=[],
        )

    def run_hybrid_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
        retrain: bool = False,
        epochs: int = 20,
    ) -> PredictionResult:
        """LSTM + GNN 병렬 조합 예측을 반환하고 실패 시 baseline 으로 전환한다."""
        now = (forecast_start or datetime.now()).replace(minute=0, second=0, microsecond=0)
        resolved_scenario = self._resolve_scenario(scenario, now)
        load_df = self._load_weather_history(raw_dir)
        history_df = self._apply_load_scale(load_df, load_scale)
        target_features = self._build_target_features(
            load_df=history_df,
            forecast_start=now,
        )

        lstm_predictions: list[HourlyLoadPrediction] | None = None
        gnn_predictions: list[HourlyLoadPrediction] | None = None
        lstm_warnings: list[str] = []
        branch_errors: list[str] = []

        try:
            lstm_predictions, lstm_warnings = self._predict_lstm(
                training_df=load_df,
                history_df=history_df,
                forecast_start=now,
                target_features=target_features,
                retrain=retrain,
                epochs=epochs,
            )
        except Exception as exc:  # noqa: BLE001
            branch_errors.append(f"LSTM 실패: {_summarize_prediction_error(exc)}")

        try:
            gnn_predictions = self._predict_gnn(
                history_df=history_df,
                forecast_start=now,
                target_features=target_features,
            )
        except Exception as exc:  # noqa: BLE001
            branch_errors.append(f"GNN 실패: {_summarize_prediction_error(exc)}")

        if lstm_predictions is not None and gnn_predictions is not None:
            predictions = _combine_prediction_lists(
                primary=lstm_predictions,
                secondary=gnn_predictions,
                primary_weight=0.65,
                secondary_weight=0.35,
            )
            warnings = [
                build_source_warning("PredictionService", "hybrid"),
                "LSTM 65% + GNN 35% 가중 평균으로 병렬 조합 예측을 사용합니다.",
            ]
            warnings.extend(f"LSTM: {warning}" for warning in lstm_warnings)

            return self._build_prediction_result(
                scenario=resolved_scenario,
                created_at=now,
                load_scale=load_scale,
                predictions=predictions,
                source="hybrid",
                warnings=warnings,
            )

        baseline_result = self.run_baseline_prediction(
            raw_dir=raw_dir,
            load_scale=load_scale,
            forecast_start=now,
            scenario=resolved_scenario,
        )
        baseline_result.summary = (
            "LSTM+GNN 병렬 예측 실패로 baseline 결과를 사용합니다. "
            f"{baseline_result.summary}"
        )
        baseline_result.warnings = branch_errors + baseline_result.warnings
        baseline_result.fallback = build_fallback_info(
            mode="baseline_model",
            reason="LSTM+GNN 병렬 예측 중 하나 이상이 실패해 baseline 예측으로 전환했습니다.",
            primary_path="src.engine.forecast.lstm_forecaster + src.engine.forecast.gnn_forecaster",
            active_path="src.services.prediction_service.PredictionService.run_baseline_prediction",
        )
        return baseline_result

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _generate_predictions(
        self, now: datetime, load_scale: float
    ) -> list[HourlyLoadPrediction]:
        rng = np.random.default_rng(seed=7)
        predictions: list[HourlyLoadPrediction] = []
        for h in range(1, 25):
            ts = now + timedelta(hours=h)
            factor = _hourly_factor(ts.hour, ts.weekday())
            for bus in _BUSES:
                noise = float(rng.normal(0, 0.025))
                pred = bus["peak_mw"] * load_scale * factor * (1 + noise)
                ci = pred * 0.08  # ±8% 신뢰구간
                predictions.append(HourlyLoadPrediction(
                    timestamp=ts,
                    bus_id=bus["bus_id"],
                    predicted_load_mw=round(max(0.0, pred), 1),
                    confidence_lower_mw=round(max(0.0, pred - ci), 1),
                    confidence_upper_mw=round(pred + ci, 1),
                ))
        return predictions

    def _compute_risk_lines(
        self,
        predictions: list[HourlyLoadPrediction],
        load_scale: float,
    ) -> list[RiskLine]:
        """선로별 예측 이용률을 계산하고 위험도를 분류한다.

        흐름 근사: |from_load - to_load| × 0.40
        (2주차에 DC Power Flow 결과로 교체 예정)
        """
        bus_name = {b["bus_id"]: b["name"] for b in _BUSES}
        load_map: dict[tuple[int, str], float] = {
            (p.timestamp.hour, p.bus_id): p.predicted_load_mw
            for p in predictions
        }

        risk_lines: list[RiskLine] = []
        for line in _LINES:
            fbus, tbus, limit = line["from"], line["to"], line["limit_mw"]

            peak_util, peak_h = 0.0, 0
            for h in range(1, 25):
                f_load = load_map.get((h, fbus), 0.0)
                t_load = load_map.get((h, tbus), 0.0)
                util = abs(f_load - t_load) * 0.40 / limit
                if util > peak_util:
                    peak_util, peak_h = util, h

            level = _classify_risk(peak_util)
            if level == "low":
                continue

            risk_lines.append(RiskLine(
                line_id=line["line_id"],
                from_bus=fbus,
                to_bus=tbus,
                from_bus_name=bus_name[fbus],
                to_bus_name=bus_name[tbus],
                peak_risk_hour=peak_h,
                predicted_utilization=round(peak_util, 3),
                risk_level=level,
                explanation=_build_explanation(
                    line["line_id"], bus_name[fbus], bus_name[tbus],
                    peak_util, peak_h, level, load_scale,
                ),
            ))

        return sorted(risk_lines, key=lambda r: r.predicted_utilization, reverse=True)

    def _build_summary(
        self,
        now: datetime,
        predictions: list[HourlyLoadPrediction],
        risk_lines: list[RiskLine],
    ) -> str:
        n_critical = sum(1 for r in risk_lines if r.risk_level == "critical")
        n_high = sum(1 for r in risk_lines if r.risk_level == "high")
        n_medium = sum(1 for r in risk_lines if r.risk_level == "medium")

        hourly_total: dict[int, float] = {}
        for p in predictions:
            h = p.timestamp.hour
            hourly_total[h] = hourly_total.get(h, 0.0) + p.predicted_load_mw
        peak_h = max(hourly_total, key=hourly_total.__getitem__)
        peak_ts = now.replace(hour=peak_h) + (
            timedelta(days=1) if peak_h <= now.hour else timedelta()
        )

        parts = [f"향후 24시간 기준 부하 피크는 {peak_ts:%m/%d %H시}입니다."]
        if n_critical:
            parts.append(f"위험(critical) 선로 {n_critical}건 즉각 확인 필요.")
        if n_high:
            parts.append(f"경고(high) 선로 {n_high}건 모니터링 강화 권장.")
        if n_medium:
            parts.append(f"주의(medium) 선로 {n_medium}건.")
        if not risk_lines:
            parts.append("위험 선로 없음. 정상 운영 범위입니다.")
        return " ".join(parts)

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
            scenario_id="prediction-mock",
            title="Prediction Mock Scenario",
            description="예측 mock 서비스 기본 시나리오",
            region="South Korea",
            created_at=created_at,
            created_by="PredictionService",
        )

    def _build_warnings(self) -> list[str]:
        return [
            build_fallback_warning("PredictionService", "mock_data"),
            "실제 baseline/LSTM/GNN 모델이 연결되기 전까지 합성 패턴 기반 예측을 사용합니다.",
        ]

    def _build_prediction_result(
        self,
        *,
        scenario: ScenarioContext,
        created_at: datetime,
        load_scale: float,
        predictions: list[HourlyLoadPrediction],
        source: str,
        warnings: list[str],
    ) -> PredictionResult:
        risk_lines = self._compute_risk_lines(predictions, load_scale)
        summary = self._build_summary(created_at, predictions, risk_lines)
        return PredictionResult(
            scenario_id=scenario.scenario_id,
            created_at=created_at,
            load_scale=load_scale,
            forecast_horizon_h=24,
            predictions=predictions,
            risk_lines=risk_lines,
            summary=summary,
            source=source,
            scenario=scenario,
            warnings=warnings,
            fallback=build_no_fallback_info(),
        )

    def _load_weather_history(self, raw_dir: str) -> pd.DataFrame:
        from src.data.adapters.public_data_adapter import load_kpx_with_weather

        return load_kpx_with_weather(raw_dir)

    def _apply_load_scale(self, load_df: pd.DataFrame, load_scale: float) -> pd.DataFrame:
        if load_scale == 1.0:
            return load_df

        scaled_df = load_df.copy()
        scaled_df["load_mw"] = scaled_df["load_mw"] * load_scale
        return scaled_df

    def _build_target_features(
        self,
        *,
        load_df: pd.DataFrame,
        forecast_start: datetime,
    ) -> list:
        from src.engine.forecast.feature_builder import build_prediction_feature_matrix

        return build_prediction_feature_matrix(
            load_df=load_df,
            forecast_start=forecast_start,
        )

    def _predict_baseline(
        self,
        *,
        load_df: pd.DataFrame,
        forecast_start: datetime,
    ) -> list[HourlyLoadPrediction]:
        from src.engine.forecast.baseline_forecaster import BaselineForecaster

        forecaster = BaselineForecaster().fit(load_df)
        target_features = self._build_target_features(
            load_df=load_df,
            forecast_start=forecast_start,
        )
        return forecaster.predict(target_features=target_features)

    def _predict_lstm(
        self,
        *,
        training_df: pd.DataFrame,
        history_df: pd.DataFrame,
        forecast_start: datetime,
        target_features: list,
        retrain: bool,
        epochs: int,
    ) -> tuple[list[HourlyLoadPrediction], list[str]]:
        from src.engine.forecast.lstm_forecaster import LSTMForecaster

        forecaster = LSTMForecaster()
        if retrain or not forecaster.is_trained():
            forecaster.fit(training_df, epochs=epochs)

        warnings: list[str] = []
        try:
            predictions = forecaster.predict(
                history_df=history_df,
                forecast_start=forecast_start,
                target_features=target_features,
            )
        except Exception as exc:
            if retrain or not _is_recoverable_lstm_model_error(exc):
                raise

            forecaster = LSTMForecaster()
            forecaster.fit(training_df, epochs=epochs)
            predictions = forecaster.predict(
                history_df=history_df,
                forecast_start=forecast_start,
                target_features=target_features,
            )
            warnings.append(
                "저장된 LSTM 모델 로드에 실패해 현재 환경에서 재학습 후 예측을 수행했습니다."
            )
            warnings.append(f"LSTM 모델 재학습 원인: {_summarize_lstm_model_error(exc)}")

        return predictions, warnings

    def _predict_gnn(
        self,
        *,
        history_df: pd.DataFrame,
        forecast_start: datetime,
        target_features: list,
    ) -> list[HourlyLoadPrediction]:
        from src.engine.forecast.gnn_forecaster import GNNForecaster

        return (
            GNNForecaster()
            .fit(history_df)
            .predict(
                history_df=history_df,
                forecast_start=forecast_start,
                target_features=target_features,
            )
        )


# ── 순수 함수 ──────────────────────────────────────────────────────────────────

def _classify_risk(utilization: float) -> str:
    if utilization >= 0.90:
        return "critical"
    if utilization >= 0.75:
        return "high"
    if utilization >= 0.55:
        return "medium"
    return "low"


def _is_recoverable_lstm_model_error(exc: Exception) -> bool:
    message = str(exc)
    recoverable_markers = (
        "could not be deserialized properly",
        "quantization_config",
        "load_model",
    )
    return any(marker in message for marker in recoverable_markers)


def _summarize_lstm_model_error(exc: Exception) -> str:
    message = str(exc)
    if "quantization_config" in message:
        return "저장된 model.keras가 현재 Keras 버전의 Dense 설정과 호환되지 않았습니다."
    if "could not be deserialized properly" in message:
        return "저장된 model.keras를 현재 Keras 환경에서 역직렬화하지 못했습니다."
    if "load_model" in message:
        return "저장된 LSTM 모델 로드에 실패했습니다."
    return message.splitlines()[0] if message else exc.__class__.__name__


def _summarize_prediction_error(exc: Exception) -> str:
    message = str(exc).strip()
    return message.splitlines()[0] if message else exc.__class__.__name__


def _combine_prediction_lists(
    *,
    primary: list[HourlyLoadPrediction],
    secondary: list[HourlyLoadPrediction],
    primary_weight: float,
    secondary_weight: float,
) -> list[HourlyLoadPrediction]:
    secondary_map = {
        (prediction.timestamp, prediction.bus_id): prediction
        for prediction in secondary
    }
    combined: list[HourlyLoadPrediction] = []
    total_weight = primary_weight + secondary_weight

    for prediction in primary:
        key = (prediction.timestamp, prediction.bus_id)
        secondary_prediction = secondary_map.get(key)
        if secondary_prediction is None:
            raise ValueError(f"병렬 조합 대상 예측 키가 맞지 않습니다: {key}")

        predicted_load = (
            (prediction.predicted_load_mw * primary_weight)
            + (secondary_prediction.predicted_load_mw * secondary_weight)
        ) / total_weight
        lower_bound = (
            (prediction.confidence_lower_mw * primary_weight)
            + (secondary_prediction.confidence_lower_mw * secondary_weight)
        ) / total_weight
        upper_bound = (
            (prediction.confidence_upper_mw * primary_weight)
            + (secondary_prediction.confidence_upper_mw * secondary_weight)
        ) / total_weight
        combined.append(
            HourlyLoadPrediction(
                timestamp=prediction.timestamp,
                bus_id=prediction.bus_id,
                predicted_load_mw=round(predicted_load, 1),
                confidence_lower_mw=round(max(0.0, lower_bound), 1),
                confidence_upper_mw=round(max(predicted_load, upper_bound), 1),
            )
        )

    return combined


def _build_explanation(
    line_id: str,
    from_name: str,
    to_name: str,
    utilization: float,
    peak_hour: int,
    risk_level: str,
    load_scale: float,
) -> str:
    pct = int(utilization * 100)
    hour_str = f"{peak_hour:02d}:00"
    scale_note = (
        f" (부하 배율 {load_scale:.0%} 적용)" if abs(load_scale - 1.0) > 0.01 else ""
    )
    if risk_level == "critical":
        return (
            f"{from_name}–{to_name} 선로({line_id})는 {hour_str}에 이용률 {pct}%로 "
            f"열적한계를 초과할 위험이 있습니다{scale_note}. "
            f"즉각적인 우회 경로 또는 발전 재배치가 필요합니다."
        )
    if risk_level == "high":
        return (
            f"{from_name}–{to_name} 선로({line_id})는 {hour_str}에 이용률 {pct}%로 "
            f"혼잡 임계치에 근접합니다{scale_note}. "
            f"수요 측 대응 또는 ESS 방전 검토를 권장합니다."
        )
    return (
        f"{from_name}–{to_name} 선로({line_id})는 {hour_str}에 이용률 {pct}%로 "
        f"관리 수준 내에 있으나 지속 모니터링이 필요합니다{scale_note}."
    )

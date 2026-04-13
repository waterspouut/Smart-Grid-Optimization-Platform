# 미래 부하 예측 결과를 보여주는 페이지를 구성한다.
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data.schemas import PredictionResult, ScenarioContext
from src.services.prediction_service import PredictionService

# ── 페이지 설정 ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="부하 예측 | SGOP",
    page_icon="📈",
    layout="wide",
)

# ── 상수 ──────────────────────────────────────────────────────────────────────
_ALL_BUSES = [
    ("BUS_001", "서울"), ("BUS_002", "인천"), ("BUS_003", "수원"),
    ("BUS_004", "춘천"), ("BUS_005", "강릉"), ("BUS_006", "원주"),
    ("BUS_007", "대전"), ("BUS_008", "청주"), ("BUS_009", "광주"),
    ("BUS_010", "전주"), ("BUS_011", "대구"), ("BUS_012", "울산"),
    ("BUS_013", "부산"),
]
_DEFAULT_BUSES = ["BUS_001", "BUS_007", "BUS_011", "BUS_013"]

_RISK_COLOR = {
    "critical": "#e74c3c",
    "high":     "#e67e22",
    "medium":   "#f1c40f",
}
_RISK_LABEL = {
    "critical": "🔴 위험",
    "high":     "🟠 경고",
    "medium":   "🟡 주의",
}


def _get_shared_scenario() -> ScenarioContext:
    scenario = st.session_state.get("sgop_shared_scenario")
    if isinstance(scenario, ScenarioContext):
        return scenario

    created_at = datetime.now().replace(minute=0, second=0, microsecond=0)
    scenario = ScenarioContext(
        scenario_id="sgop-demo-scenario",
        title="SGOP Demo Scenario",
        description="Monitoring, Simulation, Prediction이 공유하는 기본 시나리오",
        region="South Korea",
        created_at=created_at,
        created_by="streamlit-session",
    )
    st.session_state.sgop_shared_scenario = scenario
    return scenario


def _run_prediction_with_fallback(
    svc: PredictionService,
    *,
    model_source: str,
    raw_dir: str,
    load_scale: float,
    scenario: ScenarioContext,
    retrain: bool = False,
    epochs: int = 20,
) -> PredictionResult:
    if model_source == "Mock":
        return svc.run_mock_prediction(
            load_scale=load_scale,
            scenario=scenario,
        )

    try:
        if model_source == "Baseline":
            return svc.run_baseline_prediction(
                raw_dir=raw_dir,
                load_scale=load_scale,
                scenario=scenario,
            )
        if model_source == "GNN":
            return svc.run_gnn_prediction(
                raw_dir=raw_dir,
                load_scale=load_scale,
                scenario=scenario,
            )
        if model_source == "LSTM+GNN":
            return svc.run_hybrid_prediction(
                raw_dir=raw_dir,
                load_scale=load_scale,
                forecast_start=None,
                scenario=scenario,
                retrain=retrain,
                epochs=epochs,
            )

        return svc.run_lstm_prediction(
            raw_dir=raw_dir,
            load_scale=load_scale,
            forecast_start=None,
            scenario=scenario,
            retrain=retrain,
            epochs=epochs,
        )
    except Exception as exc:  # noqa: BLE001
        fallback_result = svc.run_mock_prediction(
            load_scale=load_scale,
            scenario=scenario,
        )
        fallback_result.summary = (
            f"{model_source} 예측 실패로 mock 결과를 사용합니다. "
            f"{fallback_result.summary}"
        )
        fallback_result.warnings.insert(
            0,
            f"{model_source} 예측 실패 → mock fallback 전환. 원인: {exc}",
        )
        fallback_result.fallback.reason = (
            f"{model_source} 예측이 실패해 mock 패턴 예측 결과를 사용합니다. 원인: {exc}"
        )
        return fallback_result


_RAW_DIR = str(
    __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "raw"
)

# ── 사이드바 ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("예측 설정")

    model_source = st.radio(
        "예측 모델",
        options=["Mock", "Baseline", "LSTM", "GNN", "LSTM+GNN"],
        index=0,
        help=(
            "Mock: 합성 패턴 (즉시)\n"
            "Baseline: KPX 실데이터 시간대 평균 (빠름)\n"
            "LSTM: KPX 실데이터 신경망 예측 (학습 필요)\n"
            "GNN: 인접 노드 그래프 기반 예측\n"
            "LSTM+GNN: 두 모델 병렬 조합, 실패 시 baseline 전환"
        ),
    )

    if model_source in {"LSTM", "LSTM+GNN"}:
        retrain = st.checkbox("모델 재학습", value=False,
                              help="체크 시 저장된 모델을 무시하고 재학습합니다.")
        epochs = st.slider("에포크", 5, 50, 20, step=5)
    else:
        retrain, epochs = False, 20

    st.divider()

    load_scale = st.slider(
        "부하 배율",
        min_value=0.80, max_value=1.30, value=1.00, step=0.05,
        help="1.0 = 기본 부하. 1.2 = 20% 증가 시나리오.",
    )

    bus_options = {name: bid for bid, name in _ALL_BUSES}
    default_names = [name for bid, name in _ALL_BUSES if bid in _DEFAULT_BUSES]
    selected_names = st.multiselect(
        "그래프에 표시할 노드",
        options=list(bus_options.keys()),
        default=default_names,
    )
    selected_bus_ids = [bus_options[n] for n in selected_names]

    st.divider()
    run_btn = st.button("예측 실행", type="primary", use_container_width=True)

# ── Session State 초기화 ───────────────────────────────────────────────────────
if "pred_result" not in st.session_state:
    st.session_state.pred_result = None
if "pred_scale" not in st.session_state:
    st.session_state.pred_scale = None

# ── 예측 실행 (버튼 or 최초 진입) ─────────────────────────────────────────────
shared_scenario = _get_shared_scenario()
cached_result = st.session_state.pred_result

source_changed = (
    st.session_state.get("pred_source") != model_source
)

if run_btn or cached_result is None or source_changed:
    svc = PredictionService()

    if model_source == "Baseline":
        spinner_msg = "KPX 실데이터 로딩 및 Baseline 예측 중..."
        with st.spinner(spinner_msg):
            st.session_state.pred_result = _run_prediction_with_fallback(
                svc,
                model_source=model_source,
                raw_dir=_RAW_DIR,
                load_scale=load_scale,
                scenario=shared_scenario,
            )

    elif model_source == "LSTM":
        spinner_msg = "LSTM 모델 학습/추론 중... (수 분 소요될 수 있습니다)"
        with st.spinner(spinner_msg):
            st.session_state.pred_result = _run_prediction_with_fallback(
                svc,
                model_source=model_source,
                raw_dir=_RAW_DIR,
                load_scale=load_scale,
                scenario=shared_scenario,
                retrain=retrain,
                epochs=epochs,
            )

    elif model_source == "GNN":
        spinner_msg = "GNN 그래프 예측 중..."
        with st.spinner(spinner_msg):
            st.session_state.pred_result = _run_prediction_with_fallback(
                svc,
                model_source=model_source,
                raw_dir=_RAW_DIR,
                load_scale=load_scale,
                scenario=shared_scenario,
            )

    elif model_source == "LSTM+GNN":
        spinner_msg = "LSTM+GNN 병렬 예측 중... (수 분 소요될 수 있습니다)"
        with st.spinner(spinner_msg):
            st.session_state.pred_result = _run_prediction_with_fallback(
                svc,
                model_source=model_source,
                raw_dir=_RAW_DIR,
                load_scale=load_scale,
                scenario=shared_scenario,
                retrain=retrain,
                epochs=epochs,
            )

    else:  # Mock
        with st.spinner("Mock 예측 중..."):
            st.session_state.pred_result = _run_prediction_with_fallback(
                svc,
                model_source=model_source,
                raw_dir=_RAW_DIR,
                load_scale=load_scale,
                scenario=shared_scenario,
            )

    st.session_state.pred_scale = load_scale
    st.session_state.pred_source = model_source

result: PredictionResult = st.session_state.pred_result
if result.scenario is not None:
    st.session_state.sgop_shared_scenario = result.scenario

# ── 헤더 ──────────────────────────────────────────────────────────────────────
st.title("📈 24시간 부하 예측")
scenario_id = result.scenario.scenario_id if result.scenario is not None else result.scenario_id
st.caption(
    f"기준 시각: {result.created_at:%Y-%m-%d %H:%M}  |  "
    f"소스: {result.source.upper()}  |  "
    f"부하 배율: {result.load_scale:.0%}  |  "
    f"시나리오: {scenario_id}"
)

if result.fallback.enabled:
    st.warning(
        f"Fallback 사용 중: `{result.fallback.mode}`  |  {result.fallback.reason}"
    )

for warning in result.warnings:
    st.caption(f"- {warning}")

# ── 요약 배너 ─────────────────────────────────────────────────────────────────
n_critical = sum(1 for r in result.risk_lines if r.risk_level == "critical")
n_high     = sum(1 for r in result.risk_lines if r.risk_level == "high")
n_medium   = sum(1 for r in result.risk_lines if r.risk_level == "medium")

col_s1, col_s2, col_s3, col_s4 = st.columns(4)
col_s1.metric("예측 구간", f"{result.forecast_horizon_h}시간")
col_s2.metric("위험 선로", n_critical, delta=f"high {n_high}", delta_color="inverse")
col_s3.metric("주의 선로", n_medium)

# 피크 시각
hourly_total: dict[int, float] = {}
for p in result.predictions:
    h = p.timestamp.hour
    hourly_total[h] = hourly_total.get(h, 0.0) + p.predicted_load_mw
peak_h = max(hourly_total, key=hourly_total.__getitem__)
peak_ts = result.created_at.replace(hour=peak_h) + (
    timedelta(days=1) if peak_h <= result.created_at.hour else timedelta()
)
col_s4.metric("예측 피크", f"{peak_ts:%H:%M}")

st.info(result.summary)

st.divider()

# ── Section 1: 예측 그래프 ────────────────────────────────────────────────────
st.subheader("시간대별 부하 예측")

pred_df = pd.DataFrame([
    {
        "timestamp": p.timestamp,
        "bus_id": p.bus_id,
        "predicted_load_mw": p.predicted_load_mw,
        "confidence_lower_mw": p.confidence_lower_mw,
        "confidence_upper_mw": p.confidence_upper_mw,
    }
    for p in result.predictions
])

bus_id_to_name = {bid: name for bid, name in _ALL_BUSES}

if not selected_bus_ids:
    st.warning("사이드바에서 노드를 1개 이상 선택하세요.")
else:
    fig = go.Figure()

    for bus_id in selected_bus_ids:
        bus_df = pred_df[pred_df["bus_id"] == bus_id].sort_values("timestamp")
        name = bus_id_to_name.get(bus_id, bus_id)
        timestamps = bus_df["timestamp"].tolist()

        # 신뢰구간 밴드
        fig.add_trace(go.Scatter(
            x=timestamps + timestamps[::-1],
            y=bus_df["confidence_upper_mw"].tolist() + bus_df["confidence_lower_mw"].tolist()[::-1],
            fill="toself",
            fillcolor="rgba(100,100,200,0.08)",
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
            name=f"{name} CI",
        ))

        # 예측값 라인
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=bus_df["predicted_load_mw"],
            mode="lines+markers",
            name=name,
            marker={"size": 4},
            line={"width": 2},
            hovertemplate=f"<b>{name}</b><br>%{{x|%H:%M}}<br>%{{y:,.0f}} MW<extra></extra>",
        ))

    # 현재 시각 수직선
    now_str = result.created_at.isoformat()
    fig.add_shape(
        type="line",
        x0=now_str, x1=now_str, y0=0, y1=1,
        xref="x", yref="paper",
        line={"dash": "dot", "color": "gray", "width": 1.5},
    )
    fig.add_annotation(
        x=now_str, y=1, xref="x", yref="paper",
        text="현재", showarrow=False,
        font={"color": "gray", "size": 11},
        xanchor="left", yanchor="bottom",
    )

    fig.update_layout(
        xaxis_title="시각",
        yaxis_title="예측 부하 (MW)",
        legend={"orientation": "h", "y": -0.2},
        hovermode="x unified",
        height=420,
        margin={"t": 20, "b": 60},
    )
    st.plotly_chart(fig, width="stretch")

st.divider()

# ── Section 2: 위험도 카드 ────────────────────────────────────────────────────
st.subheader("위험 선로 목록")

if not result.risk_lines:
    st.success("예측 구간 내 위험 선로가 없습니다.")
else:
    top_lines = result.risk_lines[:6]  # 최대 6개
    cols = st.columns(min(3, len(top_lines)))

    for idx, rline in enumerate(top_lines):
        col = cols[idx % 3]
        color = _RISK_COLOR.get(rline.risk_level, "#95a5a6")
        label = _RISK_LABEL.get(rline.risk_level, rline.risk_level)
        util_pct = int(rline.predicted_utilization * 100)

        with col:
            st.markdown(
                f"""
                <div style="
                    border-left: 4px solid {color};
                    padding: 12px 14px;
                    border-radius: 6px;
                    background: #fafafa;
                    margin-bottom: 12px;
                ">
                    <div style="font-size:0.78rem; color:#666;">{rline.line_id}</div>
                    <div style="font-size:1.05rem; font-weight:600;">
                        {rline.from_bus_name} → {rline.to_bus_name}
                    </div>
                    <div style="margin-top:6px;">
                        <span style="
                            background:{color}22; color:{color};
                            padding:2px 8px; border-radius:4px;
                            font-size:0.82rem; font-weight:600;
                        ">{label}</span>
                        &nbsp;
                        <span style="font-size:0.85rem; color:#333;">
                            이용률 <b>{util_pct}%</b>
                        </span>
                    </div>
                    <div style="font-size:0.78rem; color:#888; margin-top:4px;">
                        피크 예상: {rline.peak_risk_hour:02d}:00
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

st.divider()

# ── Section 3: 설명 카드 (xAI) ────────────────────────────────────────────────
st.subheader("AI 설명")

if not result.risk_lines:
    st.info("위험 선로가 없어 설명이 생성되지 않았습니다.")
else:
    for rline in result.risk_lines:
        color = _RISK_COLOR.get(rline.risk_level, "#95a5a6")
        label = _RISK_LABEL.get(rline.risk_level, rline.risk_level)
        with st.expander(
            f"{label}  {rline.from_bus_name}–{rline.to_bus_name} ({rline.line_id})",
            expanded=(rline.risk_level == "critical"),
        ):
            col_e1, col_e2, col_e3 = st.columns(3)
            col_e1.metric("이용률", f"{int(rline.predicted_utilization * 100)}%")
            col_e2.metric("피크 시각", f"{rline.peak_risk_hour:02d}:00")
            col_e3.metric("위험 등급", label)
            st.markdown(f"> {rline.explanation}")

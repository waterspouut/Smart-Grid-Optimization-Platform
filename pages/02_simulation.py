# 신규 송전탑 설치 시뮬레이션 페이지를 구성한다.
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data.schemas import ScenarioContext, SimulationInput, SimulationResult
from src.services.simulation_service import SimulationService


st.set_page_config(
    page_title="시뮬레이션 | SGOP",
    page_icon="🗺️",
    layout="wide",
)


def _get_shared_scenario() -> ScenarioContext:
    scenario = st.session_state.get("sgop_shared_scenario")
    if isinstance(scenario, ScenarioContext):
        return scenario

    created_at = datetime.now().replace(minute=0, second=0, microsecond=0)
    scenario = ScenarioContext(
        scenario_id="sgop-demo-scenario",
        title="SGOP Demo Scenario",
        description="Monitoring과 Simulation이 공유하는 기본 시나리오",
        region="South Korea",
        created_at=created_at,
        created_by="streamlit-session",
    )
    st.session_state.sgop_shared_scenario = scenario
    return scenario


service = SimulationService()
bus_options = service.list_bus_options()
candidate_options = service.list_candidate_options()
bus_ids = [bus_id for bus_id, _ in bus_options]
candidate_ids = [candidate_id for candidate_id, _ in candidate_options]
bus_labels = {bus_id: f"{name} ({bus_id})" for bus_id, name in bus_options}
candidate_labels = {
    candidate_id: f"{label} ({candidate_id})"
    for candidate_id, label in candidate_options
}

with st.sidebar:
    st.header("시뮬레이션 입력")
    start_bus_id = st.selectbox(
        "시작 버스",
        options=bus_ids,
        index=bus_ids.index("BUS_001"),
        format_func=lambda bus_id: bus_labels[bus_id],
    )
    end_bus_id = st.selectbox(
        "종료 버스",
        options=bus_ids,
        index=bus_ids.index("BUS_011"),
        format_func=lambda bus_id: bus_labels[bus_id],
    )
    candidate_site_ids = st.multiselect(
        "후보지",
        options=candidate_ids,
        default=candidate_ids,
        format_func=lambda candidate_id: candidate_labels[candidate_id],
    )
    load_scale = st.slider(
        "부하 배율",
        min_value=0.80,
        max_value=1.30,
        value=1.00,
        step=0.05,
    )
    notes = st.text_area(
        "시나리오 메모",
        value="주요 혼잡 구간 우회와 운영 여유도 확보를 목표로 한 mock 시뮬레이션",
        height=120,
    )
    st.caption("페이지는 SimulationService 입력/출력 계약만 사용합니다.")


st.title("🗺️ 송전탑 설치 시뮬레이션")

if start_bus_id == end_bus_id:
    st.error("시작 버스와 종료 버스는 다르게 선택해야 합니다.")
    st.stop()

if not candidate_site_ids:
    st.error("후보지는 1개 이상 선택해야 합니다.")
    st.stop()

simulation_input = SimulationInput(
    scenario=_get_shared_scenario(),
    start_bus_id=start_bus_id,
    end_bus_id=end_bus_id,
    candidate_site_ids=candidate_site_ids,
    load_scale=load_scale,
    notes=notes,
)

with st.spinner("시뮬레이션 결과를 생성하는 중입니다..."):
    result: SimulationResult = service.run_mock_simulation(simulation_input)

st.session_state.sgop_shared_scenario = result.scenario

st.caption(
    f"기준 시각: {result.created_at:%Y-%m-%d %H:%M}  |  "
    f"소스: {result.source.upper()}  |  "
    f"시나리오: {result.scenario.scenario_id}"
)
st.info(result.summary)

if result.fallback.enabled:
    st.warning(
        f"Fallback 사용 중: `{result.fallback.mode}`  |  {result.fallback.reason}"
    )

for warning in result.warnings:
    st.caption(f"- {warning}")

top_recommendation = result.recommendations[0] if result.recommendations else None
peak_delta = next(
    (delta for delta in result.deltas if delta.metric_id == "peak_utilization"),
    None,
)

metric_cols = st.columns(4)
metric_cols[0].metric(
    "1순위 후보",
    top_recommendation.candidate_label if top_recommendation else "-",
)
metric_cols[1].metric(
    "추천 총점",
    f"{top_recommendation.score.total_score:.1f}"
    if top_recommendation and top_recommendation.score
    else "-",
)
metric_cols[2].metric(
    "적용 경로 길이",
    f"{top_recommendation.route.total_distance_km:.1f} km"
    if top_recommendation and top_recommendation.route
    else "-",
)
metric_cols[3].metric(
    "최대 이용률 개선",
    f"{peak_delta.improvement:.1f}%p" if peak_delta else "-",
)

st.divider()
col_left, col_right = st.columns([1.1, 1.2])

with col_left:
    st.subheader("선정 경로")
    if result.selected_route is None or not result.selected_route.waypoints:
        st.info("표시할 경로 정보가 없습니다.")
    else:
        route_df = pd.DataFrame(
            [
                {
                    "point_id": waypoint.point_id,
                    "label": waypoint.label,
                    "latitude": waypoint.latitude,
                    "longitude": waypoint.longitude,
                }
                for waypoint in result.selected_route.waypoints
            ]
        )

        route_fig = go.Figure()
        route_fig.add_trace(
            go.Scatter(
                x=route_df["longitude"],
                y=route_df["latitude"],
                mode="lines+markers+text",
                text=route_df["label"],
                textposition="top center",
                line={"width": 3, "color": "#1f77b4"},
                marker={"size": 10, "color": "#d62728"},
                hovertemplate="%{text}<br>위도 %{y:.3f}<br>경도 %{x:.3f}<extra></extra>",
                name="경로",
            )
        )
        route_fig.update_layout(
            height=360,
            margin={"t": 20, "b": 20},
            xaxis_title="경도",
            yaxis_title="위도",
            showlegend=False,
        )
        st.plotly_chart(route_fig, width="stretch")

with col_right:
    st.subheader("설치 전후 비교")
    delta_df = pd.DataFrame(
        [
            {
                "metric_id": delta.metric_id,
                "지표": delta.label,
                "설치 전": delta.before_value,
                "설치 후": delta.after_value,
                "개선량": delta.improvement,
                "단위": delta.unit,
                "상태": delta.status,
            }
            for delta in result.deltas
        ]
    )

    if delta_df.empty:
        st.info("표시할 비교 결과가 없습니다.")
    else:
        delta_fig = go.Figure()
        delta_fig.add_trace(
            go.Bar(
                x=delta_df["지표"],
                y=delta_df["개선량"],
                marker_color=[
                    "#2ca02c" if status == "improved" else "#ff7f0e" if status == "unchanged" else "#d62728"
                    for status in delta_df["상태"]
                ],
                hovertemplate="%{x}<br>%{y:.1f}<extra></extra>",
                name="개선량",
            )
        )
        delta_fig.update_layout(
            height=360,
            margin={"t": 20, "b": 80},
            yaxis_title="개선량",
            showlegend=False,
        )
        st.plotly_chart(delta_fig, width="stretch")

st.divider()
st.subheader("추천안 비교")

recommendation_df = pd.DataFrame(
    [
        {
            "순위": recommendation.rank,
            "후보지": recommendation.candidate_label,
            "총점": recommendation.score.total_score if recommendation.score else None,
            "거리(km)": recommendation.route.total_distance_km if recommendation.route else None,
            "예상 비용": recommendation.route.estimated_cost if recommendation.route else None,
            "혼잡 완화": recommendation.score.congestion_relief if recommendation.score else None,
            "환경 리스크": recommendation.score.environmental_risk if recommendation.score else None,
            "정책 리스크": recommendation.score.policy_risk if recommendation.score else None,
        }
        for recommendation in result.recommendations
    ]
)

if recommendation_df.empty:
    st.info("추천안이 없습니다.")
else:
    st.dataframe(recommendation_df, width="stretch", hide_index=True)

for recommendation in result.recommendations:
    with st.expander(f"{recommendation.rank}위 {recommendation.candidate_label}"):
        st.write(recommendation.rationale)
        if recommendation.route is not None:
            st.write(recommendation.route.summary)
            st.caption(
                "경로 노드: " + " -> ".join(recommendation.route.path_node_ids)
            )
        if recommendation.score is not None and recommendation.score.notes:
            for note in recommendation.score.notes:
                st.caption(f"- {note}")

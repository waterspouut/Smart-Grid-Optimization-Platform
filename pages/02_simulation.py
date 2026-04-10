from __future__ import annotations
import streamlit as st
import folium
from streamlit_folium import st_folium

# 오름님의 엔진 및 서비스 모듈 임포트
from src.engine.powerflow.dc_power_flow import solve, build_default_buses, build_default_line_inputs
from src.services.simulation_service import SimulationService

st.set_page_config(page_title="시뮬레이션 | SGOP", layout="wide")

# --- 1. 서비스 초기화 ---
sim_service = SimulationService()
bus_options = sim_service.list_bus_options()
candidate_options = sim_service.list_candidate_options()

def get_congestion_color(flow_mw, capacity_mw):
    if capacity_mw <= 0: return "#9ca3af"
    congestion = (abs(flow_mw) / capacity_mw) * 100
    if congestion >= 80: return "#ef4444"  # 빨강
    elif congestion >= 50: return "#eab308" # 노랑
    else: return "#22c55e" # 초록

# --- 2. 사이드바 입력창 (SimulationService 연동) ---
with st.sidebar:
    st.header("⚡ 시뮬레이션 제어")
    start_bus = st.selectbox("시작 버스", options=[b[0] for b in bus_options], format_func=lambda x: dict(bus_options)[x], index=0)
    end_bus = st.selectbox("종료 버스", options=[b[0] for b in bus_options], format_func=lambda x: dict(bus_options)[x], index=10)
    
    selected_candidates = st.multiselect(
        "경유 후보지 선택", 
        options=[c[0] for c in candidate_options],
        default=[c[0] for c in candidate_options],
        format_func=lambda x: dict(candidate_options)[x]
    )
    
    load_scale = st.slider("시스템 전체 부하 배율", 0.5, 1.5, 1.0, 0.05)

st.title("🗺️ 송전망 혼잡도 및 A* 최적 경로 시뮬레이션")

# --- 3. 엔진 및 시뮬레이션 가동 ---
buses = build_default_buses(load_scale=load_scale)
lines = build_default_line_inputs()
pf_result = solve(buses, lines)

sim_input = sim_service.build_default_input(
    start_bus_id=start_bus, 
    end_bus_id=end_bus, 
    candidate_site_ids=selected_candidates, 
    load_scale=load_scale
)
sim_result = sim_service.run_simulation(sim_input)

# --- 4. 화면 레이아웃 (지도 & 지표) ---
col_map, col_info = st.columns([2, 1])

with col_map:
    st.subheader("📍 A* 최적 경로 및 계통 혼잡 지도")
    m = folium.Map(location=[36.5, 127.5], zoom_start=7, tiles='CartoDB positron')
    
    bus_coords = {
        "BUS_001": [37.5665, 126.9780], "BUS_002": [37.4563, 126.7052], 
        "BUS_003": [37.2636, 127.0286], "BUS_004": [37.8813, 127.7298],
        "BUS_005": [37.7519, 128.8761], "BUS_006": [37.3422, 127.9202],
        "BUS_007": [36.3504, 127.3845], "BUS_008": [36.6424, 127.4890],
        "BUS_009": [35.1595, 126.8526], "BUS_010": [35.8242, 127.1480],
        "BUS_011": [35.8714, 128.6014], "BUS_012": [35.5384, 129.3114],
        "BUS_013": [35.1796, 129.0756]
    }

    # 1. 기존 혼잡망 그리기 (선 살려내기 코드 적용 완료!)
    for line in lines:
        f_num = line.from_bus.replace('B', '')
        t_num = line.to_bus.replace('B', '')
        f_bus = f"BUS_{f_num.zfill(3)}"
        t_bus = f"BUS_{t_num.zfill(3)}"
        
        if f_bus in bus_coords and t_bus in bus_coords:
            current_flow = pf_result.line_flows.get(line.line_id, 0)
            folium.PolyLine(
                locations=[bus_coords[f_bus], bus_coords[t_bus]],
                color=get_congestion_color(current_flow, line.capacity_mw),
                weight=4, opacity=0.4
            ).add_to(m)

    # 2. 신규 A* 최적 경로 그리기 (파란색 점선)
    if sim_result.selected_route and sim_result.selected_route.waypoints:
        route_coords = [[wp.latitude, wp.longitude] for wp in sim_result.selected_route.waypoints]
        
        folium.PolyLine(
            locations=route_coords,
            color="#2563eb",
            weight=5,
            dash_array="10",
            tooltip="추천 A* 신규 송전 경로",
            opacity=0.9
        ).add_to(m)
        
        for wp in sim_result.selected_route.waypoints:
            folium.CircleMarker(
                location=[wp.latitude, wp.longitude],
                radius=6, popup=wp.label, tooltip=wp.label,
                color="#2563eb", fill=True, fill_color="#ffffff", fill_opacity=1.0
            ).add_to(m)
        
    # 3. 지도 왼쪽 아래에 범례(Legend) 박스 추가하기
    legend_html = '''
    <div style="position: fixed; 
         bottom: 30px; left: 30px; width: 170px; height: 135px; 
         background-color: rgba(255, 255, 255, 0.95); z-index:9999; font-size:13px;
         border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px;
         box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
         <div style="font-weight: bold; margin-bottom: 5px;">🚥 선로 상태 범례</div>
         <div style="margin-bottom: 2px;"><span style="color:#22c55e; font-size:16px;">■</span> 원활 (50% 미만)</div>
         <div style="margin-bottom: 2px;"><span style="color:#eab308; font-size:16px;">■</span> 주의 (50~80%)</div>
         <div style="margin-bottom: 2px;"><span style="color:#ef4444; font-size:16px;">■</span> 혼잡 (80% 이상)</div>
         <div><span style="color:#2563eb; font-weight:bold; font-size:16px;">╍</span> 신규 A* 경로</div>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))

    st_folium(m, width="100%", height=550, returned_objects=[])

with col_info:
    # --- 5. 설치 전/후 비교 카드 UI ---
    st.subheader("📊 설치 전/후 비교 (Deltas)")
    
    if sim_result.deltas:
        for delta in sim_result.deltas:
            delta_color = "normal" if delta.status != "worsened" else "inverse"
            st.metric(
                label=delta.label,
                value=f"{delta.after_value} {delta.unit}",
                delta=f"{delta.improvement} {delta.unit} ({'개선' if delta.improvement > 0 else '증가'})",
                delta_color=delta_color
            )
    else:
        st.info("비교할 데이터가 없습니다.")
        
    st.divider()
    st.write("**💡 종합 요약**")
    st.success(sim_result.summary)
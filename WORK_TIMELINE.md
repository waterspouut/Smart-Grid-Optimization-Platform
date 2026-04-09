# WORK_TIMELINE.md

## 목적
- 이 파일은 SGOP 저장소의 작업 타임라인과 최근 변경 맥락을 기록한다.
- 새 작업을 시작할 때는 최신 항목부터 읽고, 작업이 끝나면 결과를 추가한다.
- `AGENTS.md`를 읽었다면 이 파일도 같이 읽는 것이 기본 규칙이다.

## 기록 규칙
- 항목 순서는 최신 작업이 아래에 오도록 시간순으로 쌓는다.
- 각 항목에는 최소한 `날짜`, `작업`, `수정 파일`, `검증`, `다음 작업`을 남긴다.
- 구현이 아니라 조사만 했더라도 다음 사람이나 다음 세션이 바로 이어받을 수 있을 만큼 구체적으로 적는다.

## 타임라인

### 2026-03-30
- 작업: MVP 범위, fallback, 역할 분담, 개발 흐름을 문서 기준으로 고정했다.
- 수정 파일: `meeting_plan/MEETING_PLAN_2026-03-30.md`, `DEVELOPMENT_FLOW_2026-03-30.md`
- 검증: 문서 기준 합의안 작성
- 다음 작업: 공통 계약 스키마 정의

### 2026-04-04 1순위 완료
- 작업: 공통 계약 스키마를 `src/data/schemas.py`에 정리했다.
- 수정 파일: `src/data/schemas.py`
- 검증: 서비스/페이지 공통 계약 타입 추가 완료
- 다음 작업: `Monitoring`, `Simulation` 서비스 mock 반환 뼈대 구현

### 2026-04-04 Streamlit 실행 안정화
- 작업: WSL/로컬 환경에서 Streamlit 첫 실행과 파일 감시 문제를 줄이기 위한 로컬 설정을 추가했다.
- 수정 파일: `.streamlit/config.toml`
- 검증: Streamlit HTML/정적 자산 응답 확인
- 다음 작업: 서비스와 페이지 mock 연결 계속 진행

### 2026-04-04 2순위 완료
- 작업: `MonitoringService`, `SimulationService`에 공통 계약 기준 mock 반환 뼈대를 구현했다.
- 수정 파일: `src/services/monitoring_service.py`, `src/services/simulation_service.py`
- 검증:
  - `python3 -c "from src.services.monitoring_service import MonitoringService; result = MonitoringService().get_monitoring_result(load_scale=1.05); print(result.source, result.scenario.scenario_id, len(result.kpis), len(result.line_statuses), len(result.trend_points), result.fallback.mode)"`
  - `python3 -c "from src.services.simulation_service import SimulationService; svc = SimulationService(); result = svc.run_mock_simulation(svc.build_default_input(load_scale=1.1)); print(result.source, result.scenario.scenario_id, len(result.recommendations), len(result.deltas), result.selected_route.route_id, result.fallback.mode)"`
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.monitoring_service import MonitoringService; from src.services.simulation_service import SimulationService; scenario = ScenarioContext(scenario_id='shared-001'); monitoring = MonitoringService().get_monitoring_result(scenario=scenario); simulation = SimulationService().run_mock_simulation(SimulationService().build_default_input(scenario=scenario)); print(monitoring.scenario.scenario_id, simulation.scenario.scenario_id, monitoring.scenario.created_at is not None, simulation.simulation_input.scenario.scenario_id)"`
  - `python3 -m compileall app.py pages src`
- 다음 작업: `pages/01_monitoring.py`, `pages/02_simulation.py`가 서비스만 호출하도록 정리

### 2026-04-04 3순위 완료
- 작업: `Monitoring`, `Simulation` 페이지를 서비스 반환 결과만 렌더링하는 구조로 구현했다.
- 수정 파일: `pages/01_monitoring.py`, `pages/02_simulation.py`, `src/services/simulation_service.py`, `AGENTS.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
- 다음 작업: `pages/03_prediction.py`까지 같은 `ScenarioContext`를 공유하도록 정리하고, 이후 엔진 구현으로 내려가기

### 2026-04-04 4순위 완료
- 작업: `A*` 결과 포맷과 추천 점수 포맷을 search 엔진 계약으로 고정하고, 비용 요소 초안을 코드 상수로 정리했다.
- 수정 파일: `src/engine/search/astar_router.py`, `src/engine/search/score_function.py`, `src/services/simulation_service.py`, `AGENTS.md`
- 검증:
  - `python3 -c "from src.engine.search.astar_router import BusNodeSpec, RouteCandidateSpec, build_mock_route; start = BusNodeSpec('BUS_001', '서울', 37.5665, 126.9780); end = BusNodeSpec('BUS_011', '대구', 35.8714, 128.6014); hub = BusNodeSpec('BUS_007', '대전', 36.3504, 127.3845); candidate = RouteCandidateSpec('SITE_CENTRAL', '중앙 균형안', 36.28, 127.76, 41.0, 17.0); route = build_mock_route(start, end, candidate, via_bus=hub, load_scale=1.1); print(route.route_id, route.total_distance_km, route.estimated_cost, route.path_node_ids)"`
  - `python3 -c "from src.engine.search.score_function import CandidateScoreInput, calculate_mock_score, build_recommendation, rank_recommendations; from src.data.schemas import RouteResult; route_a = RouteResult(route_id='a', start_bus_id='BUS_001', end_bus_id='BUS_011'); route_b = RouteResult(route_id='b', start_bus_id='BUS_001', end_bus_id='BUS_011'); score_a = calculate_mock_score(CandidateScoreInput('SITE_A', 'A', 41.0, 17.0, 29.0, 4.0, 3.0, 1.1)); score_b = calculate_mock_score(CandidateScoreInput('SITE_B', 'B', 54.0, 15.0, 24.0, 3.0, 2.5, 1.1)); ranked = rank_recommendations([build_recommendation('SITE_A', 'A', route_a, score_a, 'a'), build_recommendation('SITE_B', 'B', route_b, score_b, 'b')]); print(score_a.total_score, score_b.total_score, [(item.candidate_id, item.rank) for item in ranked])"`
  - `python3 -c "from src.services.simulation_service import SimulationService; svc = SimulationService(); result = svc.run_mock_simulation(svc.build_default_input(load_scale=1.1)); print(result.selected_route.route_id, result.recommendations[0].candidate_id, result.recommendations[0].score.notes[1], result.warnings[0])"`
  - `python3 -m compileall app.py pages src`
- 다음 작업: `Prediction` 페이지까지 공통 `ScenarioContext`를 공유하도록 정리하고, 이후 실제 엔진 구현 전까지 fallback 규칙을 유지

### 2026-04-04 Prediction 공통화 완료
- 작업: `PredictionService`와 `Prediction` 페이지를 공통 `ScenarioContext`, `warnings`, `fallback` 흐름에 맞췄다.
- 수정 파일: `src/services/prediction_service.py`, `pages/03_prediction.py`, `AGENTS.md`
- 검증:
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.prediction_service import PredictionService; scenario = ScenarioContext(scenario_id='shared-001'); result = PredictionService().run_mock_prediction(load_scale=1.1, scenario=scenario); print(result.scenario_id, result.scenario.scenario_id, result.fallback.mode, len(result.warnings))"`
  - `python3 -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"`
  - `python3 -m compileall app.py pages src`
- 다음 작업: 1주차-박차오름 범위에서는 fallback 문구와 서비스 입력 패턴을 더 통일할지 점검하고, 이후 실제 엔진 구현 단계로 넘어가기

### 2026-04-04 서비스 인터페이스 미세정리 및 fallback 규칙 문서화 완료
- 작업: 세 서비스의 공통 입력 축을 `scenario`, `created_at`, `load_scale` 기준으로 정리하고, fallback 규칙 초안을 문서화했다.
- 수정 파일: `src/services/monitoring_service.py`, `src/services/simulation_service.py`, `src/services/prediction_service.py`, `pages/01_monitoring.py`, `AGENTS.md`
- 검증:
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.monitoring_service import MonitoringService; from src.services.simulation_service import SimulationService; from src.services.prediction_service import PredictionService; scenario = ScenarioContext(scenario_id='shared-002'); monitoring = MonitoringService().run_mock_monitoring(scenario=scenario, created_at=None, load_scale=1.0); simulation = SimulationService().run_mock_simulation(SimulationService().build_default_input(scenario=scenario, created_at=None, load_scale=1.0)); prediction = PredictionService().run_mock_prediction(scenario=scenario, created_at=None, load_scale=1.0); print(monitoring.fallback.mode, simulation.fallback.mode, prediction.fallback.mode, monitoring.warnings[0], simulation.warnings[0], prediction.warnings[0])"`
  - `python3 -m compileall app.py pages src`
- 다음 작업: 1주차-박차오름 범위는 사실상 정리되었고, 이후에는 실제 엔진 치환 단계로 넘어가기

### 2026-04-04 Streamlit rerun 고려사항 문서화
- 작업: Streamlit rerun 구조를 작업 시 필수 고려사항으로 `AGENTS.md`에 명시했다.
- 수정 파일: `AGENTS.md`
- 검증: 문서 규칙 반영 확인
- 다음 작업: 실제 엔진 연결 단계에서 rerun-safe와 rerun-optimized 여부를 함께 점검

### 2026-04-04 랜딩 페이지 지도 요구사항 문서화
- 작업: 첫 랜딩 페이지의 지도 UX 방향을 `AGENTS.md`에 기록했다. `VWorld` 기반 대한민국 지도, 발전소/송전탑 표시, 좌측 패널 설치 UI, 지도 클릭 후 설정값 입력 흐름, 임시 에셋 교체 예정, `2.5D/3D` 우선 방향을 명시했다.
- 수정 파일: `AGENTS.md`
- 검증: 문서 규칙 반영 확인
- 다음 작업: 실제 랜딩 페이지 구현 단계에서 `VWorld` 연동 방식, 설치 인터랙션, `map_2_5d` fallback 적용 기준을 구체화

### 2026-04-04 설치 지점 3축 좌표 요구사항 문서화
- 작업: 대한민국 지형을 고려한 설치 지점 좌표를 `x, y, z` 3축 기준으로 다뤄야 한다는 요구사항을 `AGENTS.md`에 추가했다. `z`는 고도/지형 높이 정보로 간주하고, 후속 스키마와 지도 상호작용에서도 2차원 좌표로 축소하지 않도록 명시했다.
- 수정 파일: `AGENTS.md`
- 검증: 문서 규칙 반영 확인
- 다음 작업: 실제 랜딩 페이지 구현 단계에서 좌표 스키마, 지도 클릭 이벤트, 고도값 취득 방식과 `2.5D/3D` 표시 전략을 구체화

### 2026-04-09 지도 설계 상시 참조 규칙 문서화
- 작업: 브이월드 기반 랜딩 페이지의 지도 설계 원칙을 특정 주차 문맥이 아니라 상시 참조 규칙으로 정리했다. 지도 관련 작업을 시작할 때 `AGENTS.md`의 지도 섹션을 다시 읽도록 명시하고, `LOD + 영역별 정밀 조회`, 거시 표현용 폴리곤화/mesh 단순화, 클릭 시 고해상도 `x, y, z` 확정, 표현용 geometry와 분석용 좌표 분리, `map_2_5d` fallback 유지 원칙을 일반 규칙으로 정리했다.
- 수정 파일: `AGENTS.md`, `WORK_TIMELINE.md`
- 검증: 문서 규칙 반영 확인, `py -3 -m compileall app.py pages src`
- 다음 작업: 지도 어댑터와 좌표 스키마를 설계할 때 `조회 범위`, `좌표계`, `고도 산정 방식`, `fallback 메타데이터` 필드를 공통 계약으로 구체화

### 2026-04-09 Monitoring 페이지 bare-run 실패 수정
- 작업: `pages/01_monitoring.py`의 전체 선로 상태표에서 `pandas Styler` 의존성을 제거해 bare-run 실패를 없앴다. `st.dataframe(df.style...)`를 plain DataFrame 렌더링으로 바꾸고, 같은 위치의 `use_container_width` 인자도 `width="stretch"`로 정리했다.
- 수정 파일: `pages/01_monitoring.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"`
  - `python3 -c "from src.services.monitoring_service import MonitoringService; result = MonitoringService().run_mock_monitoring(load_scale=1.0); print(result.source, result.scenario.scenario_id, len(result.kpis), len(result.line_statuses), result.fallback.mode)"`
- 다음 작업: `streamlit run app.py` 기준으로 Monitoring/Simulation/Prediction 세 페이지가 실제 브라우저 환경에서도 같은 시나리오 흐름으로 안정적으로 열리는지 다시 점검

### 2026-04-09 박차오름 2주차 작업 문서 추가
- 작업: 박차오름의 2주차 `1순위 -> 4순위` 작업을 바로 따라갈 수 있도록 임시 체크리스트 문서 `PARK_CHAOREUM_WEEK2_TASKS.md`를 루트에 추가했다. `A* 최소 버전`, `점수화 v1`, `공통 결과 형식 통일`, `page-service-engine 연결 규칙 확정` 순서와 종료 후 파일 삭제 조건을 함께 기록했다.
- 수정 파일: `PARK_CHAOREUM_WEEK2_TASKS.md`, `WORK_TIMELINE.md`
- 검증: 문서 추가 및 삭제 조건 반영 확인
- 다음 작업: `PARK_CHAOREUM_WEEK2_TASKS.md` 기준으로 1순위 `A* 최소 버전 구현`부터 착수

### 2026-04-09 박차오름 2주차 1순위 A* 최소 버전 구현
- 작업: `src/engine/search/astar_router.py`에 실제 A* 최소 버전을 추가했다. 기존 `build_mock_route()`는 유지하고, `GraphEdgeSpec`, `build_k_nearest_edges()`, `build_astar_route()`를 추가해 `bus graph + candidate + via hub` 기준의 실제 경로 계산이 가능하도록 정리했다. 구간별 `start -> candidate -> end` 또는 `start -> via -> candidate -> end` 탐색, 경로 복원, 실제 `RouteResult` 반환, 비용 추정까지 포함했다. 2주차 임시 작업 문서에도 1순위 완료 상태를 체크했다.
- 수정 파일: `src/engine/search/astar_router.py`, `PARK_CHAOREUM_WEEK2_TASKS.md`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.engine.search.astar_router import BusNodeSpec, RouteCandidateSpec, build_astar_route, build_k_nearest_edges; buses=[BusNodeSpec('BUS_001','서울',37.5665,126.9780),BusNodeSpec('BUS_003','수원',37.2636,127.0286),BusNodeSpec('BUS_007','대전',36.3504,127.3845),BusNodeSpec('BUS_010','전주',35.8242,127.1480),BusNodeSpec('BUS_011','대구',35.8714,128.6014)]; candidate=RouteCandidateSpec('SITE_CENTRAL','중앙 균형안',36.28,127.76,41.0,17.0); route=build_astar_route(start_bus=buses[0], end_bus=buses[-1], candidate=candidate, bus_nodes=buses, edges=build_k_nearest_edges(buses, neighbor_count=2), via_bus=buses[2], load_scale=1.1); print(route.route_id, route.source, route.path_node_ids, round(route.total_distance_km,1), round(route.estimated_cost,1))"`
- 다음 작업: 2순위 `추천 점수화 v1 구현`에서 실제 route 결과를 입력으로 쓰는 점수 계산 함수와 정렬 로직을 정리

### 2026-04-09 박차오름 2주차 2순위 추천 점수화 v1 구현
- 작업: `src/engine/search/score_function.py`에 실제 route 반영 점수 계산 함수 `calculate_score()`를 추가했다. 기존 `calculate_mock_score()`는 유지하고, route 거리값 반영, 거리 초과 패널티, route 안정성 bonus, 정렬 tie-break 규칙까지 넣어 2주차용 점수화 v1을 분리했다. 임시 작업 문서에도 2순위 완료 상태를 체크했다.
- 수정 파일: `src/engine/search/score_function.py`, `PARK_CHAOREUM_WEEK2_TASKS.md`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.engine.search.score_function import CandidateScoreInput, calculate_score, build_recommendation, rank_recommendations; from src.data.schemas import RouteResult; route_a = RouteResult(route_id='astar-a', start_bus_id='BUS_001', end_bus_id='BUS_011', total_distance_km=39.0, source='astar'); route_b = RouteResult(route_id='astar-b', start_bus_id='BUS_001', end_bus_id='BUS_011', total_distance_km=60.0, source='astar'); score_a = calculate_score(CandidateScoreInput('SITE_A', 'A', 41.0, 17.0, 29.0, 4.0, 3.0, 1.1), route=route_a); score_b = calculate_score(CandidateScoreInput('SITE_B', 'B', 54.0, 15.0, 24.0, 3.0, 2.5, 1.1), route=route_b); ranked = rank_recommendations([build_recommendation('SITE_A', 'A', route_a, score_a, 'a'), build_recommendation('SITE_B', 'B', route_b, score_b, 'b')]); print(score_a.total_score, score_b.total_score, [(item.candidate_id, item.rank) for item in ranked], score_a.notes[1])"`
- 다음 작업: 3순위 `공통 결과 형식 통일`에서 route/score/service 반환 형식의 source, warnings, fallback 사용 규칙을 정리

### 2026-04-09 박차오름 2주차 3순위 공통 결과 형식 통일
- 작업: `SimulationService`의 actual 진입점과 search 엔진 출력이 기존 dataclass 계약을 그대로 쓰도록 정리했다. actual route는 `RouteResult(source='astar')`, actual score는 `ScoreBreakdown`으로 유지하고, `SimulationResult`는 `source`, `scenario`, `warnings`, `fallback` 메타데이터를 포함한 같은 반환 형식을 유지하도록 맞췄다. 아직 실제 power flow가 없는 delta는 partial `mock_data fallback`으로 명시했다.
- 수정 파일: `src/services/simulation_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.simulation_service import SimulationService; scenario = ScenarioContext(scenario_id='sim-v1'); svc = SimulationService(); result = svc.run_simulation(svc.build_default_input(scenario=scenario, load_scale=1.1)); print({'source': result.source, 'scenario_id': result.scenario.scenario_id, 'route_source': result.selected_route.source if result.selected_route else None, 'route_id': result.selected_route.route_id if result.selected_route else None, 'top_candidate': result.recommendations[0].candidate_id if result.recommendations else None, 'top_score': result.recommendations[0].score.total_score if result.recommendations and result.recommendations[0].score else None, 'fallback': result.fallback.mode, 'warnings': result.warnings[:2]})"`
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.monitoring_service import MonitoringService; from src.services.simulation_service import SimulationService; from src.services.prediction_service import PredictionService; scenario = ScenarioContext(scenario_id='shared-actual'); monitoring = MonitoringService().run_mock_monitoring(scenario=scenario, load_scale=1.0); simulation = SimulationService().run_simulation(SimulationService().build_default_input(scenario=scenario, load_scale=1.0)); prediction = PredictionService().run_mock_prediction(scenario=scenario, load_scale=1.0); print({'ids':[monitoring.scenario.scenario_id, simulation.scenario.scenario_id, prediction.scenario.scenario_id], 'simulation_source': simulation.source, 'route_source': simulation.selected_route.source if simulation.selected_route else None, 'fallback': simulation.fallback.mode})"`
- 다음 작업: 4순위 `page-service-engine 연결 규칙 확정`에서 Simulation 페이지가 actual route/score 결과를 직접 렌더링하도록 연결

### 2026-04-09 박차오름 2주차 4순위 page-service-engine 연결 규칙 확정
- 작업: `pages/02_simulation.py`가 더 이상 `run_mock_simulation()`을 직접 호출하지 않고 `SimulationService.run_simulation()`을 사용하도록 바꿨다. 서비스 내부 호출 흐름은 `입력 정규화 -> actual route/score 계산 -> delta mock fallback -> 결과 조립`으로 고정했고, 페이지는 서비스 반환 dataclass만 렌더링하도록 유지했다. 1~4순위가 끝나서 임시 작업 파일 `PARK_CHAOREUM_WEEK2_TASKS.md`도 규칙대로 삭제했다.
- 수정 파일: `src/services/simulation_service.py`, `pages/02_simulation.py`, `WORK_TIMELINE.md`, `PARK_CHAOREUM_WEEK2_TASKS.md(삭제)`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.simulation_service import SimulationService; scenario = ScenarioContext(scenario_id='sim-v1'); svc = SimulationService(); result = svc.run_simulation(svc.build_default_input(scenario=scenario, load_scale=1.1)); print({'source': result.source, 'route_source': result.selected_route.source if result.selected_route else None, 'top_candidate': result.recommendations[0].candidate_id if result.recommendations else None, 'top_score': result.recommendations[0].score.total_score if result.recommendations and result.recommendations[0].score else None, 'fallback': result.fallback.mode})"`
- 다음 작업: `Monitoring`의 실제 계산값과 `Simulation`의 delta 계산을 연결해 partial `mock_data fallback` 범위를 줄이기

### 2026-04-09 Simulation delta actualization 시작
- 작업: `SimulationService.run_simulation()`의 설치 전후 delta 계산을 `MonitoringService.run_dc_power_flow()` 기준으로 연결했다. 설치 전 baseline은 실제 `DC Power Flow` 결과를 사용하고, 설치 후 값은 추천안의 `route/score`를 반영한 heuristic counterfactual로 계산하도록 `_build_actual_deltas()`를 추가했다. 이에 따라 `peak_utilization`, `risk_lines`, `losses`, `operating_margin`의 before 값이 mock 상수 대신 실제 혼잡 결과를 사용하도록 바뀌었다.
- 수정 파일: `src/services/simulation_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.simulation_service import SimulationService; scenario = ScenarioContext(scenario_id='delta-actual'); svc = SimulationService(); result = svc.run_simulation(svc.build_default_input(scenario=scenario, load_scale=1.1)); print({'source': result.source, 'fallback': result.fallback.mode, 'warning0': result.warnings[0], 'warning1': result.warnings[1], 'deltas': [(d.metric_id, d.before_value, d.after_value, d.unit, d.status) for d in result.deltas]})"`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
- 다음 작업: heuristic after-state를 실제 counterfactual power flow에 더 가깝게 보정하거나, 추천 경로가 어떤 선로를 완화하는지 line-level 연결 규칙을 추가

### 2026-04-09 박차오름 2주차 3순위 메타데이터 형식 보강
- 작업: `src/services/result_metadata.py`를 추가해 서비스 결과 메타데이터 형식을 공통 헬퍼로 묶었다. `MonitoringService`, `SimulationService`, `PredictionService`가 모두 같은 경고 첫 문구 형식과 `FallbackInfo` 생성 규칙을 쓰도록 정리했다. 이에 따라 mock fallback 경고 첫 줄이 세 서비스에서 동일한 형식으로 맞춰졌고, 정상 경로인 `MonitoringService.run_dc_power_flow()`도 source 안내 문구 형식을 통일했다.
- 수정 파일: `src/services/result_metadata.py`, `src/services/monitoring_service.py`, `src/services/simulation_service.py`, `src/services/prediction_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.services.monitoring_service import MonitoringService; from src.services.simulation_service import SimulationService; from src.services.prediction_service import PredictionService; from src.data.schemas import ScenarioContext; scenario = ScenarioContext(scenario_id='meta-check'); m = MonitoringService().run_mock_monitoring(scenario=scenario); s = SimulationService().run_simulation(SimulationService().build_default_input(scenario=scenario)); p = PredictionService().run_mock_prediction(scenario=scenario); print({'monitoring_warning': m.warnings[0], 'simulation_warning': s.warnings[0], 'prediction_warning': p.warnings[0], 'monitoring_fallback': m.fallback.mode, 'simulation_fallback': s.fallback.mode, 'prediction_fallback': p.fallback.mode})"`
  - `python3 -c "from src.services.monitoring_service import MonitoringService; result = MonitoringService().run_dc_power_flow(load_scale=1.0); print(result.warnings[0], result.fallback.mode, result.source)"`
- 다음 작업: 사용자가 원할 때만 4순위 범위 변경을 이어가고, 기본적으로는 공통 계약/메타데이터 정합성 유지에 집중

### 2026-04-09 박차오름 4주차 A* 보정 및 통합 정리
- 작업: `A*` 경로 계산에서 `직결`과 `허브 경유` 경로를 둘 다 평가하고, 반복 노드와 과도한 우회를 패널티로 반영하는 보정 로직을 추가했다. 이에 따라 허브를 억지로 거치며 루프가 생기던 경로를 배제하고, `SimulationService`는 추천 생성, baseline 조회, 결과 조립 흐름을 helper 단위로 정리했다. 지도/3D 쪽은 현재 저장소 기준으로 `VWorld` 어댑터와 지도 페이지 구현이 없어서 `3D 보류 -> map_2_5d fallback`이 맞다는 판단 문서를 추가했다.
- 수정 파일: `src/engine/search/astar_router.py`, `src/engine/search/score_function.py`, `src/services/simulation_service.py`, `docs/map_feasibility_2026-04-09.md`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.services.simulation_service import SimulationService; from src.data.schemas import ScenarioContext; svc = SimulationService(); result = svc.run_simulation(svc.build_default_input(scenario=ScenarioContext(scenario_id='wk4-check'), load_scale=1.0)); print({'source': result.source, 'fallback': result.fallback.mode, 'summary': result.summary, 'warnings': result.warnings[:2]}); [print(rec.rank, rec.candidate_id, rec.route.total_distance_km if rec.route else None, rec.route.estimated_cost if rec.route else None, rec.route.path_node_ids if rec.route else None, rec.score.total_score if rec.score else None) for rec in result.recommendations]"`
  - `python3 -c "from src.engine.search.astar_router import build_astar_route; from src.services.simulation_service import SimulationService, _to_bus_node_spec, _to_route_candidate_spec, _get_candidate; svc = SimulationService(); bus_nodes = svc._build_bus_nodes(); edges = svc._build_bus_edges(bus_nodes); start = _to_bus_node_spec('BUS_001'); end = _to_bus_node_spec('BUS_011'); via = _to_bus_node_spec('BUS_007'); [print(candidate_id, route.total_distance_km, route.estimated_cost, route.path_node_ids) for candidate_id, route in [(candidate_id, build_astar_route(start, end, _to_route_candidate_spec(candidate_id, _get_candidate(candidate_id, index)), bus_nodes=bus_nodes, edges=edges, via_bus=via, load_scale=1.0)) for index, candidate_id in enumerate(['SITE_NORTH', 'SITE_CENTRAL', 'SITE_SOUTH'])]]"`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
- 다음 작업: `Beta`가 지도 오버레이를 붙일 때 `map_2_5d` fallback 규칙을 그대로 사용하고, `Simulation` 설치 후 counterfactual을 실제 power flow로 바꾸는 작업은 이후 통합 병목 제거 단계에서 진행

### MVP 완성 이후 예정 - AI 경로 최적화 학습/검증
- 작업: MVP 기능이 완성되면 AI 기반 송전망 경로 최적화를 위해 최적화와 학습을 반복 수행하고, 추천 품질이 실제로 개선되는지 검증한다. 기준 시나리오 대비 경로 비용, 혼잡 완화, 설치 제약 충족률, 재현성, fallback 전환 조건을 함께 점검한다.
- 수정 파일: `미정 (예상 범위: src/engine/search/*, src/engine/optimize/*, src/services/simulation_service.py, 검증 문서)`
- 검증: `MVP 완성 이후 수행 예정`
- 다음 작업: MVP 범위의 지도/엔진/서비스 연결을 먼저 완료한 뒤 학습 데이터셋, 평가지표, 반복 검증 루프를 설계한다.

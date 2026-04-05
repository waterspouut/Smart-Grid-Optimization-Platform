# AGENTS.md

## 목적
- 이 저장소는 SGOP MVP를 위한 Streamlit 기반 멀티페이지 앱이다.
- 현재 기준 계획 문서는 `2026-03-30` 회의안과 개발 흐름도다.
- 작업 순서는 항상 `계약 정의 -> mock -> 최소 구현 -> 실제 연결 -> 안정화`를 따른다.

## 작업 시작 전 필수 확인
- 먼저 `git status --short`를 확인한다.
- `AGENTS.md`를 읽었으면 이어서 루트의 `WORK_TIMELINE.md`도 반드시 읽는다.
- 현재 워크트리는 더럽혀져 있을 수 있다. 내가 만들지 않은 변경은 되돌리지 않는다.
- `Monitoring`, `Simulation` 서비스에는 mock 반환 뼈대가 들어가 있지만, 페이지와 엔진 연결은 아직 대부분 스텁이다.
- 현재 구현 기준점은 `Prediction` 쪽이다. 새 기능은 이 흐름을 참고하되, 페이지별 하드코딩을 늘리지 않는다.
- 외부 API, 실제 데이터, 모델 파일이 없어도 mock 기준으로 동작해야 한다.
- 작업을 시작할 때는 `WORK_TIMELINE.md`의 최신 항목을 확인하고, 작업이 끝나면 같은 파일에 결과와 검증 내용을 추가한다.

## 반드시 먼저 읽을 파일
1. `meeting_plan/MEETING_PLAN_2026-03-30.md`
2. `DEVELOPMENT_FLOW_2026-03-30.md`
3. `WORK_TIMELINE.md`
4. `src/data/schemas.py`
5. `app.py`
6. `pages/03_prediction.py`
7. `src/services/prediction_service.py`
8. `pages/01_monitoring.py`
9. `pages/02_simulation.py`
10. `src/services/monitoring_service.py`
11. `src/services/simulation_service.py`
12. `src/engine/search/astar_router.py`
13. `src/engine/search/score_function.py`
14. `src/engine/forecast/feature_builder.py`
15. `src/config/settings.py`

## 현재 저장소 상태
- `pages/03_prediction.py`와 `src/services/prediction_service.py`는 공통 시나리오와 fallback 메타데이터를 포함한 목업 수준 구현이 있다.
- `src/services/monitoring_service.py`와 `src/services/simulation_service.py`는 공통 계약 기준의 mock 반환 뼈대가 구현되어 있다.
- `pages/01_monitoring.py`와 `pages/02_simulation.py`는 서비스 결과를 바로 렌더링하는 mock 페이지가 구현되어 있다.
- `Monitoring`과 `Simulation` 페이지는 Streamlit session state의 공통 `ScenarioContext`를 공유한다.
- `Prediction` 페이지도 같은 Streamlit session state의 `ScenarioContext`를 공유한다.
- `src/data/schemas.py`가 페이지/서비스 간 공통 계약의 기준 파일이다.
- `data/mock`에는 아직 실제 fixture 파일이 없다.
- `src/engine/search/astar_router.py`, `src/engine/search/score_function.py`는 1주차용 mock 엔진 계약과 비용 요소 초안이 들어가 있다.
- `src/domain`, `src/engine/powerflow`의 다수 파일은 여전히 한 줄 스텁이다.

## 잊지 말아야 할 핵심 구조
- 전체 흐름은 `app.py -> pages/* -> src/services/* -> src/engine/* -> src/data/* / src/domain/*`이다.
- `app.py`는 Streamlit 진입점이다.
- `pages/`는 사용자 화면이다.
- `src/services/`는 화면 유스케이스를 조율하는 계층이다.
- `src/engine/`는 계산 로직과 알고리즘 엔진 계층이다.
- `src/data/`는 스키마, 로더, 전처리, 외부 어댑터 계층이다.
- `src/domain/`은 버스, 선로, 탑 후보, 시나리오 같은 핵심 개체를 담는 계층이다.
- 현재 기준 설계의 중심축은 `Prediction` 구현이며, 나머지 파트는 그 수준의 계약과 뼈대를 맞추는 단계다.

## 핵심 엔티티
- `Bus`: 전력망 버스 노드. 실제 도메인 파일은 [bus.py](/mnt/c/Users/smp05/Desktop/SGOP/src/domain/bus.py)지만 아직 스텁이다.
- `Line`: 송전선. 혼잡도, 전력 흐름, 위험도 계산의 기본 단위다. [line.py](/mnt/c/Users/smp05/Desktop/SGOP/src/domain/line.py)
- `Tower`: 신규 송전탑 후보 지점. 설치 후보와 경로 탐색의 기준 개체다. [tower.py](/mnt/c/Users/smp05/Desktop/SGOP/src/domain/tower.py)
- `Scenario`: Monitoring, Simulation, Prediction을 묶는 공통 맥락이다. [scenario.py](/mnt/c/Users/smp05/Desktop/SGOP/src/domain/scenario.py)
- `ScenarioContext`: 현재 공통 스키마에서 시나리오 식별을 담당하는 핵심 메타데이터다. [schemas.py](/mnt/c/Users/smp05/Desktop/SGOP/src/data/schemas.py)
- `RiskLine`: 선로 위험도 표현의 기준 타입이다.
- `RouteResult`: A* 또는 휴리스틱 탐색 결과의 공통 형식이다.
- `ScoreBreakdown`: 추천 점수의 구성 요소를 담는 타입이다.
- `MonitoringResult`, `SimulationResult`, `PredictionResult`: 화면이 받아야 할 핵심 결과 계약이다.
- `FallbackInfo`: mock, baseline, cached result 같은 우회 경로 사용 여부를 기록하는 공통 타입이다.

## 서비스 책임 구조
- `MonitoringService`: 현재 상태, KPI, 혼잡도, 선로 상태, 차트 입력을 만든다.
- `SimulationService`: 후보지 입력, 경로 결과, 추천 결과, 설치 전후 비교를 만든다.
- `PredictionService`: 부하 예측, 위험 선로, 설명 출력을 만든다.
- `ScenarioService`: 시나리오 저장/불러오기/비교를 맡을 예정이지만 아직 비어 있다.
- `OptimizationService`: ESS/운영 최적화 확장용이다. MVP 필수 범위는 아니다.

## 엔진 책임 구조
- `powerflow/dc_power_flow.py`: 실제 혼잡 계산의 바닥 엔진.
- `powerflow/congestion_metrics.py`: KPI, 과부하, 위험도 산출 엔진.
- `search/astar_router.py`: 후보 경로 탐색 엔진.
- `search/score_function.py`: 추천 점수화 엔진.
- `forecast/feature_builder.py`: 예측 피처 생성 엔진.
- `forecast/lstm_forecaster.py`: LSTM 예측 엔진.
- `optimize/ess_optimizer.py`: ESS 최적화 엔진.
- `explain/xai_reporter.py`: 설명 생성 계층 후보.

## 현재 공통 계약의 중심 파일
- `src/data/schemas.py`는 지금 기준 가장 중요한 파일이다.
- 새 페이지 결과 타입이 필요하면 먼저 여기에 추가한다.
- 서비스 반환은 `MonitoringResult`, `SimulationResult`, `PredictionResult` 계열로 맞춘다.
- 페이지가 직접 `dict`를 조립해 자체 계약을 만들지 않는다.
- `scenario_id`는 페이지별 독립 생성 금지다. 같은 `ScenarioContext`를 공유해야 한다.

## PDF에서 확인된 구조적 가정
- PDF에는 내부 REST API 명세는 없다.
- 대신 외부 연동 가정은 존재한다.
- 지도 계열 외부 연동은 `VWorld Open API` 전제를 갖고 있다.
- 배포/비밀정보 관리는 `Streamlit secrets` 기준으로 적혀 있다.
- 기술 스택 가정은 `Streamlit`, `Python`, `NumPy`, `SciPy`, `pandas`, `NetworkX`, `TensorFlow/Keras`, `cvxpy`, `Plotly`다.
- 필요 시 후속 확장으로 `FastAPI` 같은 별도 처리 계층을 고려할 수 있다는 취지의 서술이 있으나, 현재 프로젝트에는 실제 HTTP 엔드포인트 계약이 없다.

## PDF 기준 외부 API/배포 메모
- `VWorld`는 키 발급과 도메인 등록이 필요하다는 전제가 있다.
- `VWorld` 키는 저장소에 넣지 않고 secrets로 관리해야 한다.
- `Streamlit Community Cloud` 배포를 기본 배포 경로로 본다.
- 공개 저장소에 올릴 때는 `raw` 외부 데이터와 운영 키를 제외하고 `mock` 중심으로 공개하는 방향이 맞다.

## 랜딩 페이지 지도 UI 필수 요구사항
- 첫 랜딩 페이지는 `VWorld Open API`를 활용한 대한민국 지도 중심 화면을 목표로 한다.
- 지도에는 외부 API 또는 후속 데이터 어댑터로 불러온 `발전소`, `송전탑` 위치가 표시되어야 한다.
- 좌측 패널에는 `발전소`, `송전탑`을 개별적으로 설치할 수 있는 UI를 둔다.
- 사용 흐름은 `좌측 패널에서 설치 대상 선택 -> 지도 위 원하는 지점 클릭 -> 해당 지점 기준 설정값 입력` 순서를 기본으로 본다.
- 대한민국 지형을 고려하므로 설치 지점 좌표는 평면 좌표만이 아니라 `x, y, z` 3축 기준으로 다룬다.
- 여기서 `z`는 고도 또는 지형 높이 정보를 의미하며, 지도 클릭 후 설정값 입력 단계에서 함께 관리할 수 있어야 한다.
- 후속 스키마/서비스/지도 어댑터를 설계할 때 설치 지점 좌표를 2차원 위경도만으로 축소하지 않는다.
- 현재 임시로 표현한 `송전탑`, `발전소`, `시작`, `종료` 박스형 에셋은 최종 디자인이 아니다.
- 추후 에셋 디자인과 인터랙션은 별도 정리 대상이며, 현재 목업의 색상/레이블/도형을 그대로 확정안으로 간주하지 않는다.
- 지도 표현은 최종적으로 `2.5D` 또는 `3D` 방향을 우선 검토한다.
- 현재 수준의 단순 2D 배치는 최종안이 아니며, 기술 제약이 있으면 `Fallback 규칙 초안`의 `map_2_5d`를 적용할 수 있다.

## 공통 계약 규칙
- 페이지와 서비스 사이의 입출력은 `src/data/schemas.py`의 dataclass를 우선 사용한다.
- ad hoc `dict`를 페이지마다 새로 정의하지 않는다.
- `scenario_id`는 페이지별로 따로 만들지 말고 같은 시나리오 맥락을 공유한다.
- 서비스가 실제 계산을 못 해도 스키마 형식은 유지하고, 필요하면 `warnings`와 `fallback`에 이유를 남긴다.
- 새 결과 타입이 필요하면 먼저 `src/data/schemas.py`에 추가하고 나서 서비스/페이지를 수정한다.

## Streamlit Rerun 필수 고려사항
- Streamlit은 위젯 상호작용마다 스크립트를 다시 실행하므로 rerun 구조를 기본 전제로 생각한다.
- 페이지 간 공통 맥락은 가능하면 `st.session_state`에 저장하고 다시 읽는다.
- rerun 때마다 `scenario_id`가 바뀌거나 결과가 불필요하게 재계산되지 않도록 주의한다.
- mock 단계에서는 가벼운 재실행을 허용할 수 있지만, 실제 엔진이나 모델 연결 단계에서는 결과 캐시, 실행 버튼, `st.form`, `st.cache_data` 같은 수단을 검토한다.
- 무거운 계산은 “rerun-safe”뿐 아니라 “rerun-optimized”한지까지 확인한다.
- 새 페이지나 서비스 연결 작업을 할 때는 `초기 진입`, `위젯 변경`, `다른 페이지로 이동 후 복귀` 상황에서 상태가 어떻게 유지되는지 반드시 점검한다.

## 서비스 인터페이스 정리 원칙
- mock public 진입점은 가능하면 `run_mock_*` 패턴을 우선 사용한다.
- 서비스 공통 입력 축은 `scenario`, `created_at`, `load_scale`다.
- `SimulationService`는 도메인 입력이 많기 때문에 `SimulationInput`이 `scenario`와 `load_scale`를 감싼다.
- 기존 호출부 호환이 필요하면 legacy 인자 이름을 alias 로 유지한다.
  - `MonitoringService.get_monitoring_result(..., as_of=...)`
  - `PredictionService.run_mock_prediction(..., forecast_start=...)`
- 새 코드는 가능하면 `created_at` 이름을 우선 사용한다.

## Fallback 규칙 초안
- `mock_data`: 실제 데이터, 엔진, 모델, 외부 연동이 아직 없거나 연결되지 않았을 때 사용한다.
- `baseline_model`: 고급 예측 모델이 실패하거나 준비되지 않았을 때 baseline 예측으로 내려간다.
- `cached_result`: 재계산이 불가능하지만 직전 유효 결과를 재사용할 수 있을 때 사용한다.
- `manual_override`: 운영자가 수동으로 값을 덮어써야 할 때 사용한다.
- `map_2_5d`: 3D 지도 표현이 불안정할 때 2.5D/2D 표현으로 낮춘다.
- `warnings` 첫 문구는 가능하면 `"<ServiceName>는 현재 \`<mode>\` fallback 결과를 반환합니다."` 형식을 따른다.
- `fallback.reason`은 `실제 주 경로 대신 무엇을 사용했는지`를 한 문장으로 설명한다.
- 현재 서비스별 fallback 기준:
  - `MonitoringService`: `mock_data`
  - `SimulationService`: `mock_data`
  - `PredictionService`: `mock_data`

## 현재까지 진행된 작업
- `1순위` 작업으로 공통 계약 스키마를 `src/data/schemas.py`에 추가했다.
- 추가된 핵심 타입:
  - `FallbackInfo`
  - `ScenarioContext`
  - `MonitoringResult`
  - `SimulationInput`
  - `SimulationResult`
  - `RouteResult`
  - `ScoreBreakdown`
  - 보조 타입 (`MonitoringKpi`, `LineStatusSnapshot`, `RoutePoint`, `RecommendationResult`, `SimulationDelta`, `TimeSeriesPoint`)
- 기존 `PredictionResult`는 깨지지 않도록 `scenario`, `warnings`, `fallback` 필드를 기본값과 함께 확장했다.
- `2순위` 작업으로 `src/services/monitoring_service.py`, `src/services/simulation_service.py`에 mock 반환 뼈대를 추가했다.
- `MonitoringService`는 `MonitoringResult`를 직접 반환하며 KPI, 선로 상태, 추세 포인트, summary, warnings, fallback을 함께 만든다.
- `SimulationService`는 `SimulationInput` 기본값 생성과 `SimulationResult` 반환 뼈대를 제공하며 route, recommendation, score, delta, summary, warnings, fallback을 함께 만든다.
- 두 서비스 모두 같은 `ScenarioContext`를 넘기면 동일한 `scenario_id`를 유지하도록 맞췄다.
- `3순위` 작업으로 `pages/01_monitoring.py`, `pages/02_simulation.py`를 서비스 호출 기반 페이지로 구현했다.
- 두 페이지는 페이지 내부 mock 결과를 만들지 않고 각각 `MonitoringService`, `SimulationService`의 반환 객체만 렌더링한다.
- `Monitoring`과 `Simulation`은 같은 Streamlit session state 키로 `ScenarioContext`를 공유한다.
- `4순위` 작업으로 `src/engine/search/astar_router.py`, `src/engine/search/score_function.py`에 mock route/score 계약을 구현했다.
- `astar_router.py`는 `RouteResult`를 반환하는 mock 경로 함수와 최소 입력 스펙을 제공한다.
- `score_function.py`는 비용 요소 상수, `ScoreBreakdown` 계산, `RecommendationResult` 생성/정렬 계약을 제공한다.
- `SimulationService`는 자체 route/score 계산을 하지 않고 search 엔진의 mock 계약 함수를 호출하도록 정리했다.
- `Prediction` 공통화 작업으로 `PredictionService`가 `ScenarioContext`를 입력으로 받아 `PredictionResult.scenario`, `scenario_id`, `warnings`, `fallback`을 실제로 채우도록 정리했다.
- `pages/03_prediction.py`는 Streamlit session state의 공통 `ScenarioContext`를 읽고 다시 저장하도록 수정했다.
- 서비스 인터페이스 미세정리로 `MonitoringService.run_mock_monitoring()`을 public 진입점으로 추가하고, `created_at`를 공통 시간 인자로 맞췄다.
- fallback 규칙 초안을 `AGENTS.md`에 문서화하고, 세 서비스의 첫 warning 문구를 `mock_data fallback` 형식으로 통일했다.

## 앞으로 작업할 때 우선순위
1. mock 결과를 실제 엔진 결과로 치환하면서 `warnings`와 `fallback` 규칙을 유지한다.
2. `A*`, 점수화, power flow 같은 엔진 구현으로 내려간다.
3. 필요하면 `ScenarioService`에 시나리오 저장/불러오기 책임을 옮긴다.

## 작업 타임라인 규칙
- 작업 타임라인 기준 파일은 루트의 `WORK_TIMELINE.md`다.
- 새 작업을 시작할 때는 가장 최근 항목을 먼저 읽고 현재 우선순위와 마지막 변경 지점을 확인한다.
- 작업 중 의미 있는 변경이 끝나면 `날짜`, `작업 요약`, `수정 파일`, `검증`, `다음 작업`을 한 항목으로 추가한다.
- `AGENTS.md`의 현재 상태와 `WORK_TIMELINE.md`의 최신 항목이 충돌하면 더 최근 날짜의 `WORK_TIMELINE.md`를 우선 참고하고, 필요하면 `AGENTS.md`도 함께 갱신한다.

## 검증 규칙
- 코드 수정 후 최소한 `python3 -m compileall app.py pages src`는 실행한다.
- 가능하면 수정한 스키마를 import 하는 경로가 깨지지 않는지 확인한다.
- 테스트가 없으면 없다고 명시하고 끝내지 말고, 최소 정적 검증은 수행한다.

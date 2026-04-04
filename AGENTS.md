# AGENTS.md

## 목적
- 이 저장소는 SGOP MVP를 위한 Streamlit 기반 멀티페이지 앱이다.
- 현재 기준 계획 문서는 `2026-03-30` 회의안과 개발 흐름도다.
- 작업 순서는 항상 `계약 정의 -> mock -> 최소 구현 -> 실제 연결 -> 안정화`를 따른다.

## 작업 시작 전 필수 확인
- 먼저 `git status --short`를 확인한다.
- 현재 워크트리는 더럽혀져 있을 수 있다. 내가 만들지 않은 변경은 되돌리지 않는다.
- `Monitoring`, `Simulation`, `A*` 관련 모듈은 아직 대부분 스텁이다.
- 현재 구현 기준점은 `Prediction` 쪽이다. 새 기능은 이 흐름을 참고하되, 페이지별 하드코딩을 늘리지 않는다.
- 외부 API, 실제 데이터, 모델 파일이 없어도 mock 기준으로 동작해야 한다.

## 반드시 먼저 읽을 파일
1. `meeting_plan/MEETING_PLAN_2026-03-30.md`
2. `DEVELOPMENT_FLOW_2026-03-30.md`
3. `src/data/schemas.py`
4. `app.py`
5. `pages/03_prediction.py`
6. `src/services/prediction_service.py`
7. `pages/01_monitoring.py`
8. `pages/02_simulation.py`
9. `src/services/monitoring_service.py`
10. `src/services/simulation_service.py`
11. `src/engine/search/astar_router.py`
12. `src/engine/search/score_function.py`
13. `src/engine/forecast/feature_builder.py`
14. `src/config/settings.py`

## 현재 저장소 상태
- `pages/03_prediction.py`와 `src/services/prediction_service.py`만 목업 수준 구현이 있다.
- `src/data/schemas.py`가 페이지/서비스 간 공통 계약의 기준 파일이다.
- `data/mock`에는 아직 실제 fixture 파일이 없다.
- `src/domain`, `src/services`, `src/engine/search`, `src/engine/powerflow`의 다수 파일은 한 줄 스텁이다.

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

## 공통 계약 규칙
- 페이지와 서비스 사이의 입출력은 `src/data/schemas.py`의 dataclass를 우선 사용한다.
- ad hoc `dict`를 페이지마다 새로 정의하지 않는다.
- `scenario_id`는 페이지별로 따로 만들지 말고 같은 시나리오 맥락을 공유한다.
- 서비스가 실제 계산을 못 해도 스키마 형식은 유지하고, 필요하면 `warnings`와 `fallback`에 이유를 남긴다.
- 새 결과 타입이 필요하면 먼저 `src/data/schemas.py`에 추가하고 나서 서비스/페이지를 수정한다.

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

## 앞으로 작업할 때 우선순위
1. `src/data/schemas.py` 기준으로 서비스 반환 형식을 통일한다.
2. `Monitoring`과 `Simulation` 서비스에 mock 반환 뼈대를 만든다.
3. 각 페이지가 서비스만 호출하도록 정리한다.
4. 그다음에 `A*`, 점수화, power flow 같은 엔진 구현으로 내려간다.

## 검증 규칙
- 코드 수정 후 최소한 `python3 -m compileall app.py pages src`는 실행한다.
- 가능하면 수정한 스키마를 import 하는 경로가 깨지지 않는지 확인한다.
- 테스트가 없으면 없다고 명시하고 끝내지 말고, 최소 정적 검증은 수행한다.

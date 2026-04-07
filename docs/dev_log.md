# SGOP 개발 일지

---

## 2주차 개발 계획 (2026-04-08~)

### 목표
mock 데이터 기반 1주차를 실제 DC Power Flow 계산으로 교체.
fallback 패턴 유지: dc_power_flow 실패 시 → mock_data 자동 전환.

### 구현 순서
1. `src/engine/powerflow/dc_power_flow.py` — DC 조류 계산 엔진
2. `src/engine/powerflow/congestion_metrics.py` — 혼잡 지표 계산
3. `src/services/monitoring_service.py` — `run_dc_power_flow()` 추가 + fallback
4. `pages/01_monitoring.py` — 소스 토글(mock/dc) + 입력 검증

---

## 1주차 완료 현황 (2026-04-08 기준)

### 완료된 파일
| 파일 | 상태 | 비고 |
|------|------|------|
| `src/data/schemas.py` | 완료 | 양 브랜치 병합, LineStatus·MonitoringResult 통합 |
| `src/services/monitoring_service.py` | 완료 | 13버스/15선로 mock, MonitoringService 클래스 |
| `pages/01_monitoring.py` | 완료 | KPI·차트·위험패널·전체상태표 |
| `.gitignore` | 완료 | .venv/ 추가 |

### 핵심 스키마 (변경 금지)
```
LineStatus: line_id, from/to_bus(_name), flow_mw, capacity_mw,
            utilization, status(CongestionStatus), risk_level(RiskLevel), loss_mw
MonitoringResult: scenario, created_at, source, load_scale,
                  line_statuses, congestion_summary, kpis, trend_points,
                  summary, warnings, fallback
```

---

## 2주차 Task 1 — dc_power_flow.py

### 설계 결정
- **알고리즘**: DC Power Flow (선형 근사, 저항 무시, |V|=1.0 pu 가정)
- **슬랙 버스**: B06 서울동 (θ = 0 기준각)
- **BASE_MVA**: 100.0 (한국 전력계통 관행)
- **네트워크**: 13버스(B01~B13) / 15선로(L01~L15)

### 리액턴스 값 (per-unit, 100MVA 기준)
```
L01 B01→B02  0.020 pu  400 MW
L02 B02→B06  0.012 pu  400 MW
L03 B13→B06  0.008 pu  350 MW
L04 B06→B08  0.005 pu  300 MW
L05 B06→B12  0.008 pu  350 MW
L06 B08→B07  0.010 pu  200 MW
L07 B12→B07  0.008 pu  200 MW
L08 B07→B03  0.012 pu  250 MW
L09 B03→B09  0.012 pu  200 MW
L10 B09→B04  0.018 pu  200 MW
L11 B04→B05  0.014 pu  180 MW
L12 B05→B10  0.014 pu  150 MW  ← 위험 구간 (용량 최소)
L13 B10→B11  0.014 pu  180 MW
L14 B11→B13  0.018 pu  250 MW
L15 B02→B11  0.025 pu  250 MW
```

### 발전·부하 배분 (기준 배율 1.0, 최종 확정)
```
B01 신가평   gen=500MW  load=210MW  (대형 발전, net +290)
B02 양주     gen=200    load=240MW  (소형 분산, net  -40)
B03 신용인   gen=  0    load=180MW  (net -180)
B04 신안성   gen=120    load=150MW  (소형 분산, net  -30)
B05 신평택   gen=100    load=130MW  (소형 분산, net  -30)
B06 서울동   gen=900    load=400MW  (슬랙, net balance by DC PF)
B07 분당     gen=150    load=200MW  (소형 분산, net  -50)
B08 동서울   gen=150    load=220MW  (소형 분산, net  -70)
B09 수원     gen= 75    load=160MW  (소형 분산, net  -85)
B10 신시흥   gen=200    load=120MW  (분산발전,  net  +80) ← L13 루프 조류 해소
B11 인천북   gen=150    load=150MW  (자체 균형, net    0) ← 환형 위치 대규모 발전 제거
B12 신강남   gen= 50    load=260MW  (소형 분산, net -210)
B13 신서울   gen=400    load=180MW  (중형 발전, net +220)
```

### 2주차 Task 1 검증 결과 (load_scale=1.0)
```
L01: 290.0 MW / 400 MW ( 72.5%) [WARN]
L04: 231.0 MW / 300 MW ( 77.0%) [WARN]   ← 서울동→동서울
L05: 277.8 MW / 350 MW ( 79.4%) [WARN]   ← 서울동→신강남
L06: 161.0 MW / 200 MW ( 80.5%) [WARN]   ← 동서울→분당
L08: 178.8 MW / 250 MW ( 71.5%) [WARN]   ← 분당→신용인
L12: 146.2 MW / 150 MW ( 97.5%) [CRIT]   ← 신시흥 병목 (설계대로)
나머지 9개 선로: OK (< 70%)
```

### 주요 함수·클래스
```
BusInput(bus_id, p_gen_mw, p_load_mw, is_slack)
  └── p_inject_mw (property) = p_gen - p_load

LineInput(line_id, from_bus, to_bus, reactance_pu, capacity_mw)

DCFlowResult(line_flows: dict[str,float], bus_angles_deg: dict[str,float],
             converged: bool, error: str, line_inputs: list[LineInput])

_build_b_matrix(bus_ids, lines) → np.ndarray  # n×n 서셉턴스 행렬
solve(buses, lines) → DCFlowResult             # 메인 솔버
build_default_line_inputs() → list[LineInput]
build_default_buses(load_scale) → list[BusInput]
```

### 알고리즘 단계
```
1. B 행렬 구성 (n×n)
   B[i,i] += Σ 1/x_ij  (자기 임피던스 합)
   B[i,j] -= 1/x_ij    (상호 임피던스)

2. 슬랙 버스 행·열 제거 → B_red (n-1 × n-1)

3. P_red = [p_inject_mw / BASE_MVA] (슬랙 제외, per-unit)

4. θ_red = np.linalg.solve(B_red, P_red)  (radian)

5. θ_full 복원 (슬랙 = 0)

6. P_ij = (θ_i - θ_j) / x_ij × BASE_MVA  (MW)
```

### 오류 처리
- 슬랙 버스 != 1개 → converged=False, error 메시지
- 조건수 > 1e10 (near-singular) → converged=False
- LinAlgError → converged=False

---

## 2주차 Task 1 상태: ✅ 완료 (2026-04-08)

---

## 2주차 Task 2 — congestion_metrics.py

### 설계 결정
- DCFlowResult + 버스 이름 매핑 → list[LineStatus] + CongestionSummary
- 손실 추정: loss_mw = flow_mw × 0.004 × utilization (1주차와 동일 공식)
- 음수 조류 처리: abs(flow) 로 이용률 계산, 방향은 부호로 표현

### 주요 함수
```
compute_line_statuses(dc_result, bus_names) → list[LineStatus]
compute_congestion_summary(line_statuses) → CongestionSummary
```

## 2주차 Task 2 상태: ✅ 완료 (2026-04-08)

---

## 2주차 Task 3 — monitoring_service.py 업데이트

### 설계 결정
- `run_dc_power_flow(scenario, load_scale, created_at)` 메서드 추가
- 내부에서 dc_power_flow.solve() 호출 → 실패 시 자동으로 run_mock_monitoring() 호출
- source 필드: "dc_power_flow" 또는 "mock" (fallback 시)
- FallbackInfo.enabled = True if fallback 발생

### 검증 결과
```
DC source=dc_power_flow: normal=9, warn=5, crit=1, over=0  (L12 신평택→신시흥 97.5%)
mock source=mock:        normal=10, warn=2, crit=3, over=0
→ 두 소스 모두 L12를 최대 이용률 선로로 식별 (DC: 97.5%, mock: 96.7%)
```

## 2주차 Task 3 상태: ✅ 완료 (2026-04-08)

---

## 2주차 Task 4 — 01_monitoring.py 업데이트

### 설계 결정
- 사이드바에 소스 선택 라디오 버튼 추가: "mock" / "DC Power Flow"
- DC 선택 시 run_dc_power_flow() 호출
- DCFlowResult.converged=False 또는 예외 발생 시 st.warning() 표시
- 입력 검증: load_scale 범위 표시, 비정상 KPI 시 st.error()

## 2주차 Task 4 상태: ✅ 완료 (2026-04-08)

---

## 커밋 히스토리 (주요)

| 해시 | 메시지 |
|------|--------|
| 08586ad | monitoring 1주차 |
| a624499 | Merge pull request #2 from waterspouut/0404oreum |
| 6582513 | VWorld 랜딩 지도 UI 및 x/y/z/z 좌표 요구사항 문서화 |

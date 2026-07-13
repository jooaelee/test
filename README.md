# 창고 수요예측 파이프라인 v2 — SKU 수명주기 기반 (Warehouse Demand Forecasting)

창고 입출고 데이터로부터 **화주(shipper)에게 제공할 주간 수요예측 정보**를 생성하는
재실행 가능한 파이프라인입니다. 일별 데이터를 주간으로 집계해 **향후 4주**를 예측하며,
**매주 1회** 실행하는 것을 전제로 설계되었습니다.

이 버전은 [WH 저장소](https://github.com/jooaelee/WH)의 1차 파이프라인과 같은 목적이지만,
**다른 창고를 대상**으로 하며 예측 대상 선정 로직이 다릅니다 — 교체형 SKU 중 **아직 수명이
끝나지 않은(단종되지 않은) SKU만** 물량 상위 20% 컷의 대상으로 삼고, 지속형 SKU는 물량과
무관하게 전부 예측합니다.

---

## 🖱️ 가장 쉬운 실행 방법 (더블클릭)

터미널/명령어 없이 실행하려면:

1. **Python 설치** (컴퓨터 1대당 최초 1회만): [python.org/downloads](https://www.python.org/downloads/) 에서
   설치파일을 받아 실행 — 설치 화면에서 **"Add python.exe to PATH"** 체크박스를 꼭 체크하세요.
2. 이 저장소를 내려받아 압축을 풉니다 (GitHub의 초록색 **Code → Download ZIP** 버튼).
3. 압축을 푼 폴더에서 아래 표에 맞는 파일을 더블클릭합니다.

| 파일 | 언제 사용 | 동작 |
|---|---|---|
| **`Run.bat`** (Windows) / **`Run_Mac.command`** (Mac) | **맨 처음 한 번은 반드시 이걸로** | 검은 창이 뜨고 설치 과정·오류가 그대로 보입니다 |
| **`Start.vbs`** (Windows 전용) | 최초 설치가 끝난 **다음부터** | 검은 창 없이 더블클릭 → 몇 초 후 브라우저만 뜹니다 |
| **`Stop.bat`** (Windows 전용) | `Start.vbs`로 조용히 실행 중인 걸 끌 때 | 창이 안 보이므로 이 파일로 종료합니다 |

**처음 사용하실 때 순서**: `Run.bat` 더블클릭 → 검은 창에서 설치 진행 확인 → 브라우저가 열리고
정상 작동하는지 확인 → 다음부터는 `Start.vbs` 사용.

---

## 무엇을 하는가

| 단계 | 요구사항 | 구현 |
|---|---|---|
| 1 | 파일 입력(입고/출고/재고현황) | `data_loader` — CP949/UTF-8 등 인코딩 자동 처리, 주간 집계, 재고 없으면 입고−출고 누적으로 추정 |
| 2 | SKU 라벨링 (교체형/지속형) | `classification` — Syntetos–Boylan(ADI·CV²) 기반 |
| 3 | **교체형 중 수명이 다하지 않은 SKU 추출** | `lifecycle` — 출고 이력만으로 판정 (아래 설명) |
| 4 | **활성 교체형 상위 20% + 지속형 전체**를 예측 대상으로 선정 | `classification.select_targets` |
| 5 | 알고리즘 선택 후 정확도 평가·피처 조정 (~10회) | `tuning`+`backtest` — rolling-origin 백테스트(RMSSE) |
| 6 | 새 데이터 시 모델 고도화 | `registry` — champion–challenger |
| 7 | 리포트 생성 | `report` — 대량 출고 확률 + 소량 출고 예측치 + **SKU 수명 현황** |

### SKU 수명주기(활성/단종) 판정 — 이번 버전의 핵심 변경점

교체형(간헐수요) SKU는 언젠가 단종되거나 후속 부품번호로 대체됩니다. 이미 단종된 SKU를
예측하는 건 "어려운 예측"이 아니라 "의미 없는 예측"입니다 — 앞으로도 계속 0일 것이기
때문입니다. 그래서 각 교체형 SKU를 **출고 이력만으로** 다음과 같이 판정합니다:

- 각 SKU는 스스로의 과거 **평균 재주문 간격(ADI)** 을 가집니다.
- 마지막 출고 이후 경과한 주수가 `ADI × eol_adi_multiplier`(기본 3배)를 넘으면 **단종(EOL)**
  으로 간주합니다.
- 이 유예 기간은 `eol_min_grace_weeks`(기본 12주) ~ `eol_max_grace_weeks`(기본 52주) 사이로
  제한됩니다 — 너무 자주 나가는 SKU가 몇 주만 조용해도 단종 판정되거나, 반대로 아주 드문
  SKU가 몇 년을 기다려야 단종 판정되는 극단을 방지합니다.
- 지속형 SKU는 항상 활성으로 간주합니다 (정기적 수요는 "수명"이 끝나는 개념이 아님).

### 예측 대상 선정 (변경된 로직)

- **교체형**: 활성(단종 아님) SKU만 후보에 포함 → 그 중 물량 기준 **상위 20%**(`target_volume_quantile`)
  만 예측 대상. 단종 SKU는 과거 물량이 아무리 컸어도 대상에서 제외됩니다.
- **지속형**: 물량 컷 없이 **전부** 예측 대상 (이력이 충분하면).

이 로직은 SKU 단위뿐 아니라 고객·채널·교차 단위 시계열에도 동일하게 적용됩니다 (해당
단위 자체가 "오래 조용해졌는지"를 스스로의 과거 패턴 대비로 판단).

### 나머지는 1차 버전과 동일

- 교체형 → **Croston·SBA·TSB**, 지속형 → **SES·Holt·MA** — 시계열당 최대 10개 후보를
  rolling-origin 백테스트(RMSSE)로 평가해 최적 선택.
- 대량/소량 정의: 출고채널 기준(특송 DHL·FedEx·UPS = 소량, 그 외 = 대량) — `split_mode`로
  물량 퍼센타일 기준으로 전환 가능.
- 매 실행마다 champion–challenger로 모델을 재평가해 새 데이터에 따라 점진 개선.

---

## 실행 (CLI, 자동화용)

```bash
pip install -r requirements.txt
python scripts/run_weekly.py --config config.yaml --data-dir /path/to/data
```

산출물은 `outputs/`에 생성됩니다: `report.html`(대시보드), `forecast_4weeks.csv`,
`large_shipment_probability.csv`, `small_volume_forecast_by_customer.csv`,
`sku_classification.csv`(라벨·활성/EOL 상태 포함), `registry.json`.

`outputs/sample/`에 실제 데이터로 실행한 예시가 포함되어 있습니다.

## 설정 — `config.yaml`

수명주기 관련 새 파라미터:

```yaml
eol_adi_multiplier: 3.0     # 유예기간 = ADI × 이 배수
eol_min_grace_weeks: 12     # 유예기간 하한
eol_max_grace_weeks: 52     # 유예기간 상한
```

그 외 파라미터(`target_volume_quantile`, `split_mode`, `max_trials` 등)는 1차 버전과 동일합니다.

## 테스트

```bash
python tests/test_core.py
```

`lifecycle.py`(수명 판정)와 새 `select_targets` 로직에 대한 단위 테스트가 포함되어 있습니다.

## 구조

```
demand_forecast/
  config.py          설정
  data_loader.py     입력 적재·정리·주간 집계·재고 추정
  classification.py  ADI/CV² 라벨링 + 예측 대상 선정 (수명주기 반영)
  lifecycle.py        SKU 활성/단종(EOL) 판정  ← 이번 버전 신규
  models/            Croston·SBA·TSB (교체형) / SES·Holt·MA (지속형)
  backtest.py        rolling-origin 백테스트
  tuning.py          시계열별 ~10회 탐색·최적 선택
  forecast.py        4주 예측 + 대량확률 + 소량예측
  registry.py        모델·정확도 이력 (고도화)
  report.py          CSV + HTML 대시보드
  pipeline.py        전체 오케스트레이션
app.py                 Streamlit 웹 UI
scripts/run_weekly.py  주간 실행 CLI
tests/test_core.py     단위 테스트
config.yaml            설정값
```

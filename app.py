"""Streamlit UI for the warehouse demand-forecasting pipeline.

Upload the inbound / outbound (and optional inventory) files, tune a few knobs,
and run the same weekly pipeline used by ``scripts/run_weekly.py`` — then view the
HTML report inline and download every output.

    pip install -r requirements.txt
    streamlit run app.py

Model state (the champion registry) persists in a working directory between runs,
so re-uploading next week's data keeps improving accuracy (고도화).
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from demand_forecast.config import Config
from demand_forecast.pipeline import run


st.set_page_config(page_title="창고 수요예측", page_icon="📦", layout="wide")


# --------------------------------------------------------------------- helpers
def _save_upload(uploaded, dest: Path) -> str:
    dest.write_bytes(uploaded.getbuffer())
    return str(dest)


def _download(df_path: Path, label: str, mime: str = "text/csv"):
    if df_path.exists():
        st.download_button(label, df_path.read_bytes(), file_name=df_path.name,
                           mime=mime, use_container_width=True)


# ------------------------------------------------------------------- sidebar UI
st.sidebar.header("⚙️ 설정")
workdir = Path(st.sidebar.text_input(
    "작업 디렉터리 (모델 상태 유지)", value=".forecast_state",
    help="예측 결과와 모델 레지스트리가 저장됩니다. 매주 같은 폴더로 실행하면 정확도가 누적 개선(고도화)됩니다."))

as_of = st.sidebar.text_input("기준일 as-of (YYYY-MM-DD, 비우면 데이터 최신일)", value="")
horizon = st.sidebar.slider("예측 구간 (주)", 1, 12, 4)
vol_q = st.sidebar.slider("예측 대상 물량 컷 (상위 %)", 5, 50, 20,
                          help="상위 N% 물량 SKU·고객만 예측") / 100.0

st.sidebar.markdown("**대량 / 소량 정의**")
split_mode = st.sidebar.radio(
    "구분 기준", ["채널 (특송=소량)", "물량 퍼센타일"], index=0,
    help="특송(DHL/FedEx/UPS)은 소량, 나머지 채널은 대량으로 봅니다.")
if split_mode.startswith("채널"):
    split_mode_val = "channel"
    express_str = st.sidebar.text_input("특송(소량) 채널", value="DHL, FEDEX, UPS")
    express_channels = tuple(c.strip() for c in express_str.split(",") if c.strip())
    large_q = 0.80
else:
    split_mode_val = "quantile"
    express_channels = ("DHL", "FEDEX", "UPS")
    large_q = st.sidebar.slider("대량 출고 임계 (퍼센타일)", 50, 95, 80,
                                help="각 대상의 비영 주간 출고량이 이 퍼센타일 이상이면 '대량'") / 100.0
max_trials = st.sidebar.slider("모델 탐색 횟수 (시계열당)", 3, 10, 10)
folds = st.sidebar.slider("백테스트 폴드 수", 3, 12, 6)
keep_state = st.sidebar.checkbox("이전 실행 상태 유지 (고도화)", value=True,
                                 help="끄면 레지스트리를 초기화하고 새로 시작합니다.")


# ----------------------------------------------------------------------- header
st.title("📦 창고 수요예측")
st.caption("입고·출고 데이터를 업로드하면 교체형/지속형 라벨링 후 향후 예측치를 생성합니다 "
           "— 대량 출고 확률(SKU·고객·채널) · 소량 출고 예측치(고객별).")

c1, c2, c3 = st.columns(3)
up_out = c1.file_uploader("출고 데이터 (Outbound) *", type=["csv"])
up_in = c2.file_uploader("입고 데이터 (Inbound) *", type=["csv"])
up_inv = c3.file_uploader("재고현황 (선택)", type=["csv"],
                          help="미제공 시 입고−출고 누적으로 재고를 추정합니다.")

run_btn = st.button("🚀 예측 실행", type="primary", use_container_width=True,
                    disabled=not (up_out and up_in))
if not (up_out and up_in):
    st.info("출고·입고 파일을 업로드하면 실행 버튼이 활성화됩니다. (CSV, CP949/UTF-8 모두 지원)")


# --------------------------------------------------------------------- run flow
def execute():
    workdir.mkdir(parents=True, exist_ok=True)
    data_dir = workdir / "input"
    out_dir = workdir / "outputs"
    data_dir.mkdir(exist_ok=True)
    out_dir.mkdir(exist_ok=True)
    registry_path = workdir / "registry.json"
    if not keep_state and registry_path.exists():
        registry_path.unlink()

    out_path = _save_upload(up_out, data_dir / "outbound.csv")
    in_path = _save_upload(up_in, data_dir / "inbound.csv")
    inv_path = _save_upload(up_inv, data_dir / "inventory.csv") if up_inv else None

    cfg = Config(
        inbound_path=in_path, outbound_path=out_path, inventory_path=inv_path,
        as_of=as_of.strip() or None, horizon_weeks=horizon,
        target_volume_quantile=1.0 - vol_q,
        split_mode=split_mode_val, express_channels=express_channels,
        large_quantile=large_q,
        max_trials=max_trials, backtest_folds=folds,
        output_dir=str(out_dir), registry_path=str(registry_path),
        report_html=str(out_dir / "report.html"),
    )
    return run(cfg, base_dir="."), out_dir


if run_btn:
    try:
        with st.spinner("데이터 적재 · 라벨링 · 모델 탐색 · 예측 생성 중…"):
            result, out_dir = execute()
        st.session_state["result_meta"] = result.meta
        st.session_state["out_dir"] = str(out_dir)
        st.success("완료했습니다.")
    except Exception as exc:  # surface a readable error rather than a traceback wall
        st.error(f"실행 중 오류: {exc}")
        st.exception(exc)
        st.stop()


# ----------------------------------------------------------------------- results
meta = st.session_state.get("result_meta")
out_dir = Path(st.session_state["out_dir"]) if st.session_state.get("out_dir") else None
if meta and out_dir:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("예측 대상 시계열", f"{meta.get('n_targets', 0):,}")
    m2.metric("SKU 예측 대상", f"{meta.get('n_sku_targets', 0):,}")
    bn = meta.get("beats_naive_share")
    m3.metric("나이브 대비 우수", f"{bn*100:.0f}%" if bn is not None else "-",
              help="RMSSE<1: 전주-반복 기준선보다 나은 시계열 비율")
    m4.metric("런타임", f"{meta.get('runtime_sec', 0):.0f}s")

    tabs = st.tabs(["📊 리포트", "🔺 대량 출고 확률", "🔹 소량 출고 예측", "📅 4주 예측", "🏷️ 분류", "⬇️ 다운로드"])

    with tabs[0]:
        rp = out_dir / "report.html"
        if rp.exists():
            st.components.v1.html(rp.read_text(encoding="utf-8"), height=1600, scrolling=True)

    def _show(csv_name, sort_col=None, ascending=False, top=200):
        p = out_dir / csv_name
        if not p.exists():
            st.info("데이터 없음"); return
        df = pd.read_csv(p)
        if sort_col and sort_col in df.columns:
            df = df.sort_values(sort_col, ascending=ascending)
        st.dataframe(df.head(top), use_container_width=True, height=560)

    with tabs[1]:
        st.caption("각 대상의 향후 예측구간 내 최소 1회 대량출고 발생 확률.")
        _show("large_shipment_probability.csv", "p_large_4w")
    with tabs[2]:
        st.caption("고객별 정상(소량) 출고의 기대 물량.")
        _show("small_volume_forecast_by_customer.csv", "routine_total_4w")
    with tabs[3]:
        st.caption("대상 시계열별 주간 예측치와 선택된 모델·정확도.")
        _show("forecast_4weeks.csv", "forecast_total_4w")
    with tabs[4]:
        st.caption("전 시계열의 특성(ADI·CV²)·라벨·예측 대상 여부.")
        _show("sku_classification.csv", "total_qty")
    with tabs[5]:
        st.write("생성된 파일을 내려받습니다.")
        _download(out_dir / "report.html", "리포트 (HTML)", "text/html")
        _download(out_dir / "large_shipment_probability.csv", "대량 출고 확률 (CSV)")
        _download(out_dir / "small_volume_forecast_by_customer.csv", "소량 출고 예측 (CSV)")
        _download(out_dir / "forecast_4weeks.csv", "4주 예측 (CSV)")
        _download(out_dir / "sku_classification.csv", "SKU 분류 (CSV)")

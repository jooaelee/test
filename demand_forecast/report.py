"""Write the run's deliverables: machine-readable CSVs + a self-contained,
theme-aware HTML dashboard for the shipper (화주).

The HTML uses the validated data-viz reference palette (blue = 교체형,
aqua = 지속형; a sequential blue ramp encodes probability magnitude) and is fully
inline — no external CSS/JS/fonts — so it renders anywhere and can be published
as an Artifact as-is.
"""
from __future__ import annotations

from pathlib import Path
import html
import numpy as np
import pandas as pd

from .config import Config


# ----------------------------------------------------------------- CSV outputs
def write_outputs(result, cfg: Config):
    out = Path(cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _safe_csv(result.forecasts, out / "forecast_4weeks.csv")
    _safe_csv(result.large_prob, out / "large_shipment_probability.csv")
    _safe_csv(result.small_forecast, out / "small_volume_forecast_by_customer.csv")
    _safe_csv(result.classes, out / "sku_classification.csv")
    html_str = build_html(result, cfg)
    Path(cfg.report_html).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.report_html).write_text(html_str, encoding="utf-8")
    return cfg.report_html


def _safe_csv(df: pd.DataFrame, path: Path):
    if df is None or df.empty:
        pd.DataFrame().to_csv(path, index=False)
    else:
        df.to_csv(path, index=False, encoding="utf-8-sig")


# ------------------------------------------------------------------ formatting
def _int(x):
    try:
        return f"{float(x):,.0f}"
    except (TypeError, ValueError):
        return "-"


def _pct(x, d=1):
    try:
        return f"{float(x) * 100:.{d}f}%"
    except (TypeError, ValueError):
        return "-"


def _num(x, d=2):
    try:
        v = float(x)
        return "-" if not np.isfinite(v) else f"{v:.{d}f}"
    except (TypeError, ValueError):
        return "-"


def _esc(x):
    return html.escape(str(x)) if x is not None else ""


def _prob_bar(p):
    """Sequential-blue horizontal bar for a probability in [0,1]."""
    try:
        p = max(0.0, min(1.0, float(p)))
    except (TypeError, ValueError):
        p = 0.0
    w = round(p * 100, 1)
    return (f'<div class="bar"><span class="bar-fill" style="width:{w}%"></span>'
            f'<span class="bar-val">{p*100:.1f}%</span></div>')


# --------------------------------------------------------------- HTML sections
def _stat_tiles(meta):
    tiles = [
        ("예측 대상 시계열", _int(meta.get("n_targets")), "활성 교체형 상위 20% + 지속형 전체"),
        ("SKU 예측 대상", _int(meta.get("n_sku_targets")), "활성 교체형 상위 20% SKU + 지속형 SKU"),
        ("학습 데이터", f'{_int(meta.get("n_weeks"))}주', f'{meta.get("data_start")} ~ {meta.get("as_of")}'),
        ("예측 구간", f'{meta.get("horizon_weeks")}주', " · ".join(meta.get("future_weeks", []))),
    ]
    cells = "".join(
        f'<div class="tile"><div class="tile-label">{_esc(l)}</div>'
        f'<div class="tile-value">{v}</div>'
        f'<div class="tile-sub">{_esc(s)}</div></div>'
        for l, v, s in tiles)
    return f'<div class="tiles">{cells}</div>'


def _label_split(classes):
    if classes is None or classes.empty:
        return ""
    tgt = classes[classes["is_target"]]
    n_int = int((tgt["label"] == "교체형").sum())
    n_con = int((tgt["label"] == "지속형").sum())
    total = max(n_int + n_con, 1)
    sb = (tgt["sb_class"].value_counts().to_dict())
    sb_rows = "".join(
        f'<tr><td>{_esc(k)}</td><td class="num">{_int(v)}</td></tr>'
        for k, v in sorted(sb.items(), key=lambda kv: -kv[1]))
    return f"""
    <div class="card">
      <h3>SKU 특성 라벨링 <span class="muted">(예측 대상 기준)</span></h3>
      <div class="split">
        <span class="seg seg-int" style="flex:{n_int}">교체형 {n_int}</span>
        <span class="seg seg-con" style="flex:{n_con}">지속형 {n_con}</span>
      </div>
      <p class="muted small">교체형(간헐수요) → Croston · SBA · TSB &nbsp;|&nbsp; 지속형(연속수요) → SES · Holt · MA
         &nbsp;·&nbsp; 전체 대상의 {_pct(n_int/total)}가 교체형</p>
      <details><summary>Syntetos–Boylan 세부 분류</summary>
        <table class="mini"><thead><tr><th>클래스</th><th class="num">SKU수</th></tr></thead>
        <tbody>{sb_rows}</tbody></table>
      </details>
    </div>"""


def _lifecycle_card(meta):
    total = meta.get("sku_replacement_total") or 0
    active = meta.get("sku_replacement_active") or 0
    eol = meta.get("sku_replacement_eol") or 0
    if total == 0:
        return ""
    mult = meta.get("eol_adi_multiplier")
    grace_min = meta.get("eol_min_grace_weeks")
    grace_max = meta.get("eol_max_grace_weeks")
    mult_txt = f"{mult:.1f}" if mult is not None else "—"
    return f"""
    <div class="card">
      <h3>SKU 수명 현황 <span class="muted">교체형 SKU · 출고 이력 기준</span></h3>
      <div class="split">
        <span class="seg seg-good" style="flex:{max(active,1) if eol==0 else active}">활성(수명 유지) {active}</span>
        <span class="seg seg-eol" style="flex:{max(eol,1) if active==0 else eol}">단종(EOL) {eol}</span>
      </div>
      <p class="muted small">교체형 SKU {_int(total)}개 중 <b>{_pct(active/total if total else 0)}</b>가 여전히
        활성 상태입니다. 마지막 출고 이후 경과 주수가 그 SKU의 평균 재주문 간격(ADI)의
        {mult_txt}배(최소 {_int(grace_min)}주~최대 {_int(grace_max)}주)를
        넘어서면 단종으로 간주해 예측 대상에서 제외합니다 — 대상 선정은 <b>활성 SKU 중 물량 상위 20%</b>
        + <b>지속형 SKU 전체</b> 기준입니다.</p>
    </div>"""


def _large_table(df, key_col, key_label, title, note, top=15):
    if df is None or df.empty:
        return ""
    sub = df[df["grain"] == key_col].copy()
    if sub.empty:
        return ""
    sub = sub.sort_values("p_large_4w", ascending=False).head(top)
    # In channel mode a pure-express channel has no 대량 events; drop those rows
    # from the channel breakdown so only 비특송(대량) channels are listed.
    if key_col == "channel" and "bulk_share" in sub.columns:
        sub = sub[sub["bulk_share"] > 0]
        if sub.empty:
            return ""
    rows = []
    for _, r in sub.iterrows():
        name = r.get(key_col if key_col != "sku" else "item_code",
                     r.get("item_code", r.get("customer", r.get("channel"))))
        rows.append(
            f'<tr><td class="key">{_esc(name)}</td>'
            f'<td>{_prob_bar(r["p_large_4w"])}</td>'
            f'<td class="num">{_pct(r["p_large_week"])}</td>'
            f'<td class="num">{_int(r["expected_large_size"])}</td>'
            f'<td class="num">{_pct(r.get("bulk_share"))}</td>'
            f'<td class="num muted">{_esc(r.get("last_large_week") or "-")}</td></tr>')
    return f"""
    <div class="card">
      <h3>{_esc(title)}</h3>
      <p class="muted small">{_esc(note)}</p>
      <div class="scroll"><table>
        <thead><tr>
          <th>{_esc(key_label)}</th><th>4주내 대량출고 확률</th><th class="num">주간확률</th>
          <th class="num">예상 대량규모(EA)</th><th class="num">비특송 비중</th><th class="num">최근 대량주</th>
        </tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    </div>"""


def _small_table(df, meta, top=20):
    if df is None or df.empty:
        return ""
    sub = df.head(top)
    rows = []
    for _, r in sub.iterrows():
        rows.append(
            f'<tr><td class="key">{_esc(r["customer"])}</td>'
            f'<td>{_label_pill(r["label"])}</td>'
            f'<td class="num">{_int(r["routine_weekly"])}</td>'
            f'<td class="num strong">{_int(r["routine_total_4w"])}</td>'
            f'<td class="num muted">{_int(r["forecast_total_4w"])}</td>'
            f'<td class="num">{_pct(r["p_occurrence_week"])}</td>'
            f'<td class="num">{_num(r["rmsse"])}</td></tr>')
    channel_mode = meta.get("split_mode") == "channel"
    if channel_mode:
        exp = " · ".join(meta.get("express_channels", []))
        note = f"특송({exp}) 채널로 나가는 소량 출고의 기대 물량. 총 예측치는 특송+화물 전체 기대 물량."
        col_small = "특송 주간(EA)"; col_small_tot = "특송 4주 합(EA)"
    else:
        note = "스파이크(대량주)를 각 고객의 임계값에서 winsorize 후 산출한 정상 수요 기대치. 총 예측치는 대량 포함 기대 물량."
        col_small = "정상 주간(EA)"; col_small_tot = "정상 4주 합(EA)"
    return f"""
    <div class="card">
      <h3>소량 출고 예측치 — 고객별 <span class="muted">향후 {meta.get('horizon_weeks')}주</span></h3>
      <p class="muted small">{_esc(note)}</p>
      <div class="scroll"><table>
        <thead><tr>
          <th>고객</th><th>라벨</th><th class="num">{col_small}</th>
          <th class="num">{col_small_tot}</th><th class="num">총 4주 기대(EA)</th>
          <th class="num">주간 출고확률</th><th class="num">RMSSE</th>
        </tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    </div>"""


def _sku_forecast_table(df, meta, top=20):
    if df is None or df.empty:
        return ""
    sub = df[df["grain"] == "sku"].copy()
    if sub.empty:
        return ""
    sub = sub.sort_values("forecast_total_4w", ascending=False).head(top)
    wk_cols = [c for c in sub.columns if c.startswith("w") and "_" in c
               and c.split("_")[0][1:].isdigit()]
    wk_cols = sorted(wk_cols, key=lambda c: int(c.split("_")[0][1:]))
    head_wk = "".join(f'<th class="num">{c.split("_",1)[1]}</th>' for c in wk_cols)
    rows = []
    for _, r in sub.iterrows():
        wk_cells = "".join(f'<td class="num">{_int(r[c])}</td>' for c in wk_cols)
        rows.append(
            f'<tr><td class="key">{_esc(r["item_code"])}</td>'
            f'<td>{_label_pill(r["label"])}</td>'
            f'<td class="num muted">{_esc(r["model"])}</td>'
            f'{wk_cells}'
            f'<td class="num strong">{_int(r["forecast_total_4w"])}</td>'
            f'<td class="num">{_num(r["rmsse"])}</td></tr>')
    return f"""
    <div class="card">
      <h3>SKU별 4주 출고 예측 <span class="muted">상위 {len(sub)} (예측물량 기준)</span></h3>
      <div class="scroll"><table>
        <thead><tr><th>SKU</th><th>라벨</th><th>모델</th>{head_wk}
          <th class="num">4주 합</th><th class="num">RMSSE</th></tr></thead>
        <tbody>{''.join(rows)}</tbody></table></div>
    </div>"""


def _model_summary(forecasts, meta):
    if forecasts is None or forecasts.empty:
        return ""
    mc = forecasts["model"].value_counts().to_dict()
    mrows = "".join(f'<tr><td>{_esc(k)}</td><td class="num">{_int(v)}</td></tr>'
                    for k, v in sorted(mc.items(), key=lambda kv: -kv[1]))
    imp = forecasts["acc_change_vs_prev"].dropna()
    med_rmsse = meta.get("median_rmsse")
    beats = meta.get("beats_naive_share")
    if len(imp):
        improved = int((imp < 0).sum())
        worsened = int((imp > 0).sum())
        med_change = float(imp.median()) * 100
        imp_note = (f'직전 실행 대비 재평가된 {len(imp)}개 시계열 중 '
                    f'<b>{improved}개 개선</b> · {worsened}개 악화 '
                    f'(시계열별 RMSSE 중앙값 변화 {med_change:+.1f}%)')
    else:
        imp_note = '첫 실행 — 다음 주 실행부터 정확도 변화(고도화)가 기록됩니다.'
    beats_pct = _pct(beats, 0) if beats is not None else "-"
    return f"""
    <div class="card">
      <h3>모델 선택 · 정확도 <span class="muted">시계열당 최대 {int(forecasts['n_trials'].max()) if len(forecasts) else 0}회 탐색</span></h3>
      <div class="two-col">
        <table class="mini"><thead><tr><th>선택된 모델</th><th class="num">시계열수</th></tr></thead>
          <tbody>{mrows}</tbody></table>
        <div class="note-box">
          <div><span class="muted">나이브 대비 우수(RMSSE&lt;1)</span> <b>{beats_pct}</b>
            <span class="muted small">전주-반복 기준선 대비. 활성 시계열 중앙값 RMSSE {_num(med_rmsse, 3)} (n={_int(meta.get('n_active_series'))})</span></div>
          <div class="mt"><span class="muted">고도화 (새 데이터 반영)</span><br>{imp_note}</div>
        </div>
      </div>
    </div>"""


def _label_pill(label):
    cls = "pill-int" if label == "교체형" else "pill-con"
    return f'<span class="pill {cls}">{_esc(label)}</span>'


def _definition_card(meta):
    """Explain the 대량/소량 split so the numbers are interpretable."""
    if meta.get("split_mode") != "channel":
        return f"""
    <div class="card">
      <h3>대량 / 소량 정의 <span class="muted">물량 기준</span></h3>
      <p class="muted small">각 대상의 비영(非0) 주간 출고량이 상위 {int(100*(1-0.8))}퍼센타일 이상이면 <b>대량</b>,
        그 외를 <b>소량</b>으로 정의합니다. (config <code>split_mode: quantile</code>)</p>
    </div>"""
    exp = " · ".join(meta.get("express_channels", []))
    vshare = _pct(meta.get("express_vol_share"), 1)
    cshare = _pct(meta.get("express_cnt_share"), 0)
    return f"""
    <div class="card">
      <h3>대량 / 소량 정의 <span class="muted">출고채널 기준</span></h3>
      <div class="split">
        <span class="seg seg-con" style="flex:1">소량 = 특송 &nbsp;({exp})</span>
        <span class="seg seg-int" style="flex:2">대량 = 비특송 &nbsp;(화물·픽업: TAIUN·TAIUN_AIR·CUSTOMER_PICK_UP 등)</span>
      </div>
      <p class="muted small">특송은 <b>주문건수의 {cshare}</b>를 차지하지만 <b>물량은 {vshare}</b>에 불과 — 소포성 소량 출고.
        대량(비특송)은 소건이지만 물량 대부분을 차지합니다. 따라서 대량은 <b>발생 확률</b>(공간·인력 계획),
        소량은 <b>기대 물량</b>(특송비·포장 계획)으로 리포팅합니다.</p>
    </div>"""


def build_html(result, cfg: Config) -> str:
    meta = result.meta
    channel = meta.get("split_mode") == "channel"
    large_def = ("비특송(화물·픽업) 채널로 나가는 출고를 '대량'으로 정의. 4주 내 최소 1회 대량출고 발생 확률."
                 if channel else
                 "각 대상의 비영 주간 출고량 상위 20% 이상을 '대량'으로 정의. 4주 내 최소 1회 대량출고 발생 확률.")
    body = "".join([
        _stat_tiles(meta),
        _definition_card(meta),
        _label_split(result.classes),
        _lifecycle_card(meta),
        _large_table(result.large_prob, "sku", "SKU",
                     "대량 출고 확률 — SKU별", large_def),
        _large_table(result.large_prob, "customer", "고객",
                     "대량 출고 확률 — 고객별",
                     "고객별 대량(비특송) 출고 발생 확률 (창고 공간·인력 사전계획용)."),
        _large_table(result.large_prob, "channel", "출고채널",
                     "대량 출고 확률 — 비특송 채널별",
                     "비특송(화물·픽업) 채널별 대량출고 발생 확률."),
        _small_table(result.small_forecast, meta),
        _sku_forecast_table(result.forecasts, meta),
        _model_summary(result.forecasts, meta),
    ])
    gen = f'생성 {meta.get("as_of")} · 학습 {meta.get("n_weeks")}주 · 런타임 {meta.get("runtime_sec")}s'
    return _PAGE.replace("{{BODY}}", body).replace("{{GEN}}", _esc(gen)) \
                .replace("{{ASOF}}", _esc(meta.get("as_of"))) \
                .replace("{{WINDOW}}", _esc(" ~ ".join([
                    meta.get("future_weeks", ["", ""])[0],
                    meta.get("future_weeks", ["", ""])[-1]])))


_PAGE = """<div class="viz-root">
<style>
.viz-root{
  --surface-1:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
  --grid:#e1e0d9;--base:#c3c2b7;--border:rgba(11,11,11,.10);
  --int:#2a78d6;--con:#1baf7a;--seq:#2a78d6;--seq-bg:#cde2fb;
  --good:#006300;--bad:#d03b3b;
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);
  background:var(--plane);line-height:1.45;padding:28px 22px 60px;
}
@media (prefers-color-scheme:dark){.viz-root{
  --surface-1:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--base:#383835;--border:rgba(255,255,255,.10);
  --int:#3987e5;--con:#199e70;--seq:#3987e5;--seq-bg:#184f95;--good:#0ca30c;--bad:#e06a6a;}}
:root[data-theme="dark"] .viz-root{
  --surface-1:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;
  --grid:#2c2c2a;--base:#383835;--border:rgba(255,255,255,.10);
  --int:#3987e5;--con:#199e70;--seq:#3987e5;--seq-bg:#184f95;--good:#0ca30c;--bad:#e06a6a;}
:root[data-theme="light"] .viz-root{
  --surface-1:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;
  --grid:#e1e0d9;--base:#c3c2b7;--border:rgba(11,11,11,.10);
  --int:#2a78d6;--con:#1baf7a;--seq:#2a78d6;--seq-bg:#cde2fb;--good:#006300;--bad:#d03b3b;}
.viz-root *{box-sizing:border-box}
.viz-root h1{font-size:22px;margin:0 0 2px;letter-spacing:-.01em}
.viz-root h3{font-size:15px;margin:0 0 10px;letter-spacing:-.01em}
.viz-root .lede{color:var(--ink2);margin:0 0 20px;font-size:13.5px}
.viz-root .muted{color:var(--muted);font-weight:400}
.viz-root .small{font-size:12px}
.viz-root .strong{font-weight:700}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:18px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:14px 16px}
.tile-label{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.tile-value{font-size:26px;font-weight:700;margin:4px 0 2px;letter-spacing:-.02em}
.tile-sub{font-size:11.5px;color:var(--ink2)}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:18px 18px 16px;margin-bottom:16px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.03em}
td.num,th.num{text-align:right}
td.key{font-weight:600;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
tbody tr:hover{background:color-mix(in srgb,var(--seq-bg) 30%,transparent)}
.mini{width:auto;min-width:220px}
.bar{position:relative;background:var(--seq-bg);border-radius:4px;height:18px;min-width:130px;overflow:hidden}
.bar-fill{position:absolute;left:0;top:0;bottom:0;background:var(--seq);border-radius:4px}
.bar-val{position:relative;padding-left:8px;font-size:11px;line-height:18px;color:var(--ink);mix-blend-mode:normal}
.split{display:flex;gap:2px;height:34px;border-radius:8px;overflow:hidden;margin:6px 0 10px}
.seg{display:flex;align-items:center;justify-content:center;color:#fff;font-size:12.5px;font-weight:600;min-width:64px}
.seg-int{background:var(--int)}.seg-con{background:var(--con)}
.seg-good{background:var(--good)}.seg-eol{background:var(--bad)}
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11px;font-weight:600;color:#fff}
.pill-int{background:var(--int)}.pill-con{background:var(--con)}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:640px){.two-col{grid-template-columns:1fr}}
.note-box{font-size:13px}.note-box .mt{margin-top:10px}
details{margin-top:8px}summary{cursor:pointer;color:var(--ink2);font-size:12.5px}
.footer{color:var(--muted);font-size:11.5px;margin-top:22px;border-top:1px solid var(--grid);padding-top:12px}
.badge{display:inline-block;background:var(--seq-bg);color:var(--seq);padding:2px 10px;border-radius:20px;font-size:11.5px;font-weight:600}
</style>
<h1>창고 수요예측 리포트 <span class="muted">· ESSENCORE HK</span></h1>
<p class="lede">화주 대상 주간 수요예측 — 기준일 <b>{{ASOF}}</b>, 예측구간 <span class="badge">{{WINDOW}}</span>.
  교체형/지속형 라벨링 후 SKU·고객·채널별 <b>대량 출고 확률</b>과 고객별 <b>소량 출고 예측치</b>를 제공합니다.</p>
{{BODY}}
<div class="footer">{{GEN}} · 방법론: Syntetos–Boylan 분류 · Croston/SBA/TSB(교체형) · SES/Holt/MA(지속형) · rolling-origin backtest(RMSSE) · champion–challenger 고도화</div>
</div>"""

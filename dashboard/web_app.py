"""
Streamlit web dashboard för Boränteagent Sverige.

Starta med:  streamlit run dashboard/web_app.py
Öppnas automatiskt i webbläsaren på  http://localhost:8501
"""

import sys
from pathlib import Path

# Lägg till projektets rot i Python-sökvägen
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analysis.calculator import (
    annual_cost,
    discount_vs_list,
    market_summary,
    monthly_cost,
    savings_vs_alternative,
    spread_vs_reference,
)
from config import BINDING_PERIODS
from storage import database as db

# ── Sidkonfiguration ──────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Boränteagent Sverige",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Lösenordsskydd ────────────────────────────────────────────────────────────

def _check_password() -> bool:
    """
    Returnerar True om användaren angett rätt lösenord.
    Lösenordet hämtas från .streamlit/secrets.toml (lokalt)
    eller Streamlit Cloud Settings → Secrets (i produktion).
    """
    try:
        correct = st.secrets["password"]
    except (KeyError, FileNotFoundError):
        # Ingen secrets-fil = öppen åtkomst (t.ex. lokal utveckling utan lösenord)
        return True

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    # Visa inloggningssida
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown("## 🏠 Boränteagent Sverige")
        st.markdown("Ange lösenord för att fortsätta.")
        pwd = st.text_input("Lösenord", type="password", key="pwd_input")
        if st.button("Logga in", use_container_width=True):
            if pwd == correct:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Fel lösenord – försök igen.")
    return False


if not _check_password():
    st.stop()


# ── Initiera databas ──────────────────────────────────────────────────────────
# På Streamlit Cloud finns databasen som komprimerad fil i repot.
# Vi packar upp den automatiskt om den inte redan finns.

def _init_database() -> None:
    root = Path(__file__).parent.parent
    db_path = root / "data" / "borantor.db"
    db_gz_path = root / "data" / "borantor.db.gz"

    if not db_path.exists() and db_gz_path.exists():
        import gzip, shutil
        with gzip.open(db_gz_path, "rb") as f_in:
            with open(db_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    db.init_db()

_init_database()


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_list_rates():
    return db.get_list_rates(limit=10000)

@st.cache_data(ttl=300)
def load_latest_list_rates():
    return db.get_latest_list_rates()

@st.cache_data(ttl=300)
def load_reference_rates():
    return db.get_latest_reference_rates()

@st.cache_data(ttl=300)
def load_reference_history(series_key: str, days: int = 180):
    return db.get_reference_rate_history(series_key, days)

@st.cache_data(ttl=300)
def load_my_offers():
    return db.get_my_offers()

@st.cache_data(ttl=300)
def load_warnings():
    return db.get_warnings(acknowledged=False)


PERIOD_ORDER = list(BINDING_PERIODS.keys())
PERIOD_LABELS = BINDING_PERIODS


# ── Sidofält ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🏠 Boränteagent")
    st.markdown("**Sverige**")
    st.divider()
    page = st.radio(
        "Navigering",
        ["Marknadsöversikt", "Historiska trender", "Min lånesituation", "Referensräntor", "Varningar", "➕ Mata in räntor"],
        label_visibility="collapsed",
    )
    st.divider()
    if st.button("🔄 Uppdatera data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("Data uppdateras automatiskt var 5:e minut")


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 1: Marknadsöversikt
# ══════════════════════════════════════════════════════════════════════════════

if page == "Marknadsöversikt":
    st.title("📊 Marknadsöversikt")

    latest = load_latest_list_rates()
    ref_rates = {r["series_key"]: r for r in load_reference_rates()}

    if not latest:
        st.warning("Inga listräntor insamlade ännu. Kör `python main.py collect` för att hämta data.")
        st.stop()

    # ── Referensräntor som metrics ────────────────────────────────────────────
    st.subheader("Referensräntor")
    col1, col2, col3, col4 = st.columns(4)
    for col, key, label, icon in [
        (col1, "policy_rate",   "Styrränta",       "🏦"),
        (col2, "stibor_3m",     "STIBOR 3M",       "📈"),
        (col3, "gov_bond_2y",   "Statsobligation 2 år", "📋"),
        (col4, "gov_bond_5y",   "Statsobligation 5 år", "📋"),
    ]:
        r = ref_rates.get(key)
        with col:
            if r:
                st.metric(f"{icon} {label}", f"{r['rate']:.2f}%", help=f"Datum: {r['rate_date']}")
            else:
                st.metric(f"{icon} {label}", "–")

    st.divider()

    # ── Marknadssammanfattning ────────────────────────────────────────────────
    st.subheader("Sammanfattning per bindningstid")
    summary = market_summary(latest)

    cols = st.columns(len(BINDING_PERIODS))
    for col, (pkey, plabel) in zip(cols, BINDING_PERIODS.items()):
        s = summary.get(pkey, {})
        with col:
            st.metric(plabel, f"{s.get('avg', 0):.2f}%",
                      help=f"Lägst: {s.get('min',0):.2f}%  |  Högst: {s.get('max',0):.2f}%")

    st.divider()

    # ── Heatmap: alla banker x alla perioder ──────────────────────────────────
    st.subheader("Listräntor – alla banker")
    banks = sorted({r["bank"] for r in latest})
    rows = []
    for bank in banks:
        bank_rates = {r["period_key"]: r["rate"] for r in latest if r["bank"] == bank}
        row = {"Bank": bank}
        for pk in PERIOD_ORDER:
            row[PERIOD_LABELS[pk]] = bank_rates.get(pk)
        rows.append(row)

    df_banks = pd.DataFrame(rows).set_index("Bank")

    fig_heat = go.Figure(data=go.Heatmap(
        z=df_banks.values,
        x=df_banks.columns.tolist(),
        y=df_banks.index.tolist(),
        colorscale="RdYlGn_r",
        text=[[f"{v:.2f}%" if v else "" for v in row] for row in df_banks.values],
        texttemplate="%{text}",
        showscale=True,
        colorbar=dict(title="Ränta (%)"),
    ))
    fig_heat.update_layout(
        height=350,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="Bindningstid",
        yaxis_title="Bank",
    )
    st.plotly_chart(fig_heat, use_container_width=True)

    # ── Stapeldiagram: jämförelse per period ──────────────────────────────────
    st.subheader("Bankjämförelse per bindningstid")
    selected_period = st.selectbox(
        "Välj bindningstid",
        options=PERIOD_ORDER,
        format_func=lambda k: PERIOD_LABELS[k],
        key="period_select_market",
    )
    filtered = [r for r in latest if r["period_key"] == selected_period]
    filtered.sort(key=lambda r: r["rate"])

    df_bar = pd.DataFrame(filtered)
    if not df_bar.empty:
        fig_bar = px.bar(
            df_bar, x="bank", y="rate",
            color="rate",
            color_continuous_scale="RdYlGn_r",
            labels={"bank": "Bank", "rate": "Ränta (%)"},
            text="rate",
        )
        fig_bar.update_traces(texttemplate="%{text:.2f}%", textposition="outside")
        fig_bar.update_layout(
            height=400,
            showlegend=False,
            coloraxis_showscale=False,
            yaxis=dict(range=[
                df_bar["rate"].min() - 0.1,
                df_bar["rate"].max() + 0.2,
            ]),
        )
        st.plotly_chart(fig_bar, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 2: Historiska trender
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Historiska trender":
    st.title("📈 Historiska trender")

    all_rates = load_list_rates()
    if not all_rates:
        st.warning("Inga listräntor insamlade ännu.")
        st.stop()

    df_all = pd.DataFrame(all_rates)
    df_all["rate_date"] = pd.to_datetime(df_all["rate_date"])

    col1, col2 = st.columns(2)
    with col1:
        selected_banks = st.multiselect(
            "Välj banker",
            options=sorted(df_all["bank"].unique()),
            default=sorted(df_all["bank"].unique())[:3],
        )
    with col2:
        selected_period_hist = st.selectbox(
            "Bindningstid",
            options=PERIOD_ORDER,
            format_func=lambda k: PERIOD_LABELS[k],
            index=2,  # default: 3 år
            key="period_hist",
        )

    df_filtered = df_all[
        (df_all["bank"].isin(selected_banks)) &
        (df_all["period_key"] == selected_period_hist)
    ].sort_values("rate_date")

    if df_filtered.empty:
        st.info("Ingen historik för valda banker/period ännu.")
    else:
        fig_line = px.line(
            df_filtered, x="rate_date", y="rate",
            color="bank",
            markers=True,
            labels={"rate_date": "Datum", "rate": "Ränta (%)", "bank": "Bank"},
            title=f"Listräntor – {PERIOD_LABELS[selected_period_hist]}",
        )
        fig_line.update_layout(height=450, legend_title_text="Bank")
        fig_line.update_yaxes(ticksuffix="%")
        st.plotly_chart(fig_line, use_container_width=True)

    st.divider()

    # ── Spridning (spread) mot styrränta ─────────────────────────────────────
    st.subheader("Bankernas marginal mot styrräntan")
    ref_history = load_reference_history("policy_rate", days=180)
    if ref_history and not df_all.empty:
        df_ref = pd.DataFrame(ref_history)
        df_ref["rate_date"] = pd.to_datetime(df_ref["rate_date"])
        df_ref = df_ref.rename(columns={"rate": "policy_rate"})

        df_spread = df_all[df_all["period_key"] == selected_period_hist].copy()
        df_spread = df_spread.merge(df_ref[["rate_date", "policy_rate"]], on="rate_date", how="left")
        df_spread["spread"] = df_spread["rate"] - df_spread["policy_rate"]
        df_spread = df_spread[df_spread["bank"].isin(selected_banks)].dropna(subset=["spread"])

        if not df_spread.empty:
            fig_spread = px.line(
                df_spread, x="rate_date", y="spread",
                color="bank",
                markers=True,
                labels={"rate_date": "Datum", "spread": "Marginal mot styrränta (pp)", "bank": "Bank"},
                title=f"Marginal mot styrräntan – {PERIOD_LABELS[selected_period_hist]}",
            )
            fig_spread.update_layout(height=400)
            fig_spread.update_yaxes(ticksuffix=" pp")
            st.plotly_chart(fig_spread, use_container_width=True)
    else:
        st.info("Hämta referensräntehistorik med `python main.py backfill` för att se marginalutveckling.")


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 3: Min lånesituation
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Min lånesituation":
    st.title("🏠 Min lånesituation")

    offers = load_my_offers()
    latest_list = {(r["bank"], r["period_key"]): r["rate"] for r in load_latest_list_rates()}
    ref_rates = {r["series_key"]: r["rate"] for r in load_reference_rates()}

    if not offers:
        st.info("Inga egna erbjudanden registrerade ännu.")
        st.markdown("Kör `python main.py add-offer` i terminalen för att lägga till ett erbjudande.")
        st.stop()

    df_offers = pd.DataFrame(offers)
    df_offers["offer_date"] = pd.to_datetime(df_offers["offer_date"])

    # Senaste erbjudandet
    latest_offer = df_offers.sort_values("offer_date").iloc[-1]
    list_rate = latest_list.get((latest_offer["bank"], latest_offer["period_key"]))
    policy = ref_rates.get("policy_rate")
    stibor = ref_rates.get("stibor_3m")

    st.subheader(f"Senaste erbjudande – {latest_offer['bank']}, {latest_offer['period_label']}")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Min ränta", f"{latest_offer['offered_rate']:.2f}%")
    with col2:
        if list_rate:
            disc = discount_vs_list(latest_offer["offered_rate"], list_rate)
            st.metric("Listränta", f"{list_rate:.2f}%",
                      delta=f"{disc:+.2f} pp rabatt",
                      delta_color="normal" if disc > 0 else "inverse")
        else:
            st.metric("Listränta", "–")
    with col3:
        if policy:
            sp = spread_vs_reference(latest_offer["offered_rate"], policy)
            st.metric("vs Styrränta", f"+{sp:.2f} pp", help=f"Styrränta: {policy:.2f}%")
        else:
            st.metric("vs Styrränta", "–")
    with col4:
        if stibor:
            sp = spread_vs_reference(latest_offer["offered_rate"], stibor)
            st.metric("vs STIBOR 3M", f"+{sp:.2f} pp", help=f"STIBOR 3M: {stibor:.2f}%")
        else:
            st.metric("vs STIBOR 3M", "–")
    with col5:
        loan = latest_offer.get("loan_amount")
        if loan:
            mc = monthly_cost(int(loan), latest_offer["offered_rate"])
            st.metric("Månadskostnad", f"{mc:,.0f} kr",
                      help=f"Lånebelopp: {int(loan):,} kr")
        else:
            st.metric("Månadskostnad", "–")

    st.divider()

    # ── Rabattutveckling ──────────────────────────────────────────────────────
    st.subheader("Rabattutveckling mot listränta")
    if list_rate:
        df_disc = df_offers.copy()
        df_disc["list_rate"] = df_disc.apply(
            lambda r: latest_list.get((r["bank"], r["period_key"]), None), axis=1
        )
        df_disc["discount"] = df_disc.apply(
            lambda r: discount_vs_list(r["offered_rate"], r["list_rate"])
            if r["list_rate"] else None, axis=1
        )
        df_disc = df_disc.dropna(subset=["discount"])

        if not df_disc.empty:
            fig_disc = px.bar(
                df_disc, x="offer_date", y="discount",
                color="discount",
                color_continuous_scale="RdYlGn",
                labels={"offer_date": "Datum", "discount": "Rabatt (pp)"},
                title="Rabatt mot listräntan per erbjudande",
                text="discount",
            )
            fig_disc.update_traces(texttemplate="%{text:.2f} pp", textposition="outside")
            fig_disc.update_layout(height=380, coloraxis_showscale=False)
            st.plotly_chart(fig_disc, use_container_width=True)

    # ── Marginalutveckling ────────────────────────────────────────────────────
    if policy or stibor:
        st.subheader("Din räntemarginal mot referensräntor")
        rows = []
        for _, o in df_offers.iterrows():
            if policy:
                rows.append({
                    "Datum": o["offer_date"],
                    "Marginal (pp)": spread_vs_reference(o["offered_rate"], policy),
                    "Referens": "Styrränta",
                })
            if stibor:
                rows.append({
                    "Datum": o["offer_date"],
                    "Marginal (pp)": spread_vs_reference(o["offered_rate"], stibor),
                    "Referens": "STIBOR 3M",
                })
        if rows:
            df_margin = pd.DataFrame(rows)
            fig_margin = px.line(
                df_margin, x="Datum", y="Marginal (pp)", color="Referens",
                markers=True,
                title="Din räntemarginal mot referensräntor över tid",
            )
            fig_margin.update_layout(height=380)
            fig_margin.update_yaxes(ticksuffix=" pp")
            st.plotly_chart(fig_margin, use_container_width=True)

    st.divider()

    # ── Besparingspotential ───────────────────────────────────────────────────
    st.subheader("Besparingspotential – marknadsjämförelse")
    loan_amount = latest_offer.get("loan_amount")
    if loan_amount and list_rate:
        competitors = [
            r for r in load_latest_list_rates()
            if r["period_key"] == latest_offer["period_key"]
            and r["bank"] != latest_offer["bank"]
        ]
        if competitors:
            comp_rows = []
            for c in sorted(competitors, key=lambda x: x["rate"]):
                sav = savings_vs_alternative(
                    latest_offer["offered_rate"], c["rate"], int(loan_amount)
                )
                comp_rows.append({
                    "Bank": c["bank"],
                    "Listränta": f"{c['rate']:.2f}%",
                    "Skillnad (pp)": sav["rate_diff_pp"],
                    "Besparing/år (kr)": sav["annual_savings_sek"],
                    "Besparing/mån (kr)": sav["monthly_savings_sek"],
                })
            df_comp = pd.DataFrame(comp_rows).sort_values("Skillnad (pp)", ascending=False)

            fig_sav = px.bar(
                df_comp, x="Bank", y="Besparing/år (kr)",
                color="Besparing/år (kr)",
                color_continuous_scale="RdYlGn",
                text="Besparing/år (kr)",
                title=f"Besparing/år vid byte från {latest_offer['bank']} (lånebelopp {int(loan_amount):,} kr)",
            )
            fig_sav.update_traces(texttemplate="%{text:,.0f} kr", textposition="outside")
            fig_sav.update_layout(height=400, coloraxis_showscale=False)
            st.plotly_chart(fig_sav, use_container_width=True)

            st.dataframe(df_comp.reset_index(drop=True), use_container_width=True)
    else:
        st.info("Lägg till lånebelopp i ditt erbjudande för att se besparingspotential.")

    # ── Alla erbjudanden ──────────────────────────────────────────────────────
    with st.expander("Visa alla registrerade erbjudanden"):
        st.dataframe(
            df_offers[["offer_date","bank","period_label","offered_rate",
                        "loan_amount","discount_vs_list","comment","source"]]
            .rename(columns={
                "offer_date": "Datum", "bank": "Bank", "period_label": "Bindningstid",
                "offered_rate": "Ränta (%)", "loan_amount": "Lånebelopp",
                "discount_vs_list": "Rabatt (pp)", "comment": "Kommentar",
                "source": "Källa",
            }),
            use_container_width=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 4: Referensräntor
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Referensräntor":
    st.title("📋 Referensräntor")

    ref_latest = load_reference_rates()
    if not ref_latest:
        st.warning("Inga referensräntor insamlade. Kör `python main.py backfill`.")
        st.stop()

    # Aktuella värden
    st.subheader("Aktuella värden")
    cols = st.columns(len(ref_latest))
    for col, r in zip(cols, ref_latest):
        with col:
            st.metric(r["series_label"], f"{r['rate']:.2f}%",
                      help=f"Datum: {r['rate_date']}")

    st.divider()

    # Historiska grafer
    st.subheader("Historisk utveckling")
    days_back = st.slider("Antal dagar bakåt", min_value=14, max_value=365, value=90, step=7)

    SERIES_TO_SHOW = [
        ("policy_rate", "Riksbankens styrränta"),
        ("stibor_3m", "STIBOR 3M"),
        ("gov_bond_2y", "Statsobligation 2 år"),
        ("gov_bond_5y", "Statsobligation 5 år"),
    ]

    rows_ref = []
    for key, label in SERIES_TO_SHOW:
        history = db.get_reference_rate_history(key, days=days_back)
        for h in history:
            rows_ref.append({
                "Datum": pd.to_datetime(h["rate_date"]),
                "Ränta (%)": h["rate"],
                "Serie": label,
            })

    if rows_ref:
        df_ref_hist = pd.DataFrame(rows_ref)
        fig_ref = px.line(
            df_ref_hist, x="Datum", y="Ränta (%)", color="Serie",
            markers=False,
            title="Referensräntor – historisk utveckling",
        )
        fig_ref.update_layout(height=480, legend_title_text="")
        fig_ref.update_yaxes(ticksuffix="%")
        st.plotly_chart(fig_ref, use_container_width=True)
    else:
        st.info(f"Ingen historik för de senaste {days_back} dagarna. Kör `python main.py backfill`.")


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 5: Varningar
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Varningar":
    st.title("⚠️ Varningar")

    warnings = load_warnings()

    if not warnings:
        st.success("✅ Inga aktiva varningar!")
        st.caption("Kör `python main.py warnings` för att kontrollera om nya varningar uppstått.")
        st.stop()

    SEV_COLOR = {"WARNING": "🔴", "INFO": "🟡"}
    SEV_LABEL = {"WARNING": "Varning", "INFO": "Information"}

    warnings_by_sev = {"WARNING": [], "INFO": []}
    for w in warnings:
        warnings_by_sev.setdefault(w["severity"], []).append(w)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("🔴 Varningar", len(warnings_by_sev.get("WARNING", [])))
    with col2:
        st.metric("🟡 Informationer", len(warnings_by_sev.get("INFO", [])))

    st.divider()

    for sev in ["WARNING", "INFO"]:
        group = warnings_by_sev.get(sev, [])
        if not group:
            continue
        st.subheader(f"{SEV_COLOR[sev]} {SEV_LABEL[sev]}er ({len(group)})")
        for w in group:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{w['category']}**  \n{w['message']}")
                with col2:
                    st.caption(f"Bank: {w['bank'] or '–'}")
                    st.caption(f"Period: {w['period_key'] or '–'}")
                    st.caption(f"Datum: {w['warning_date']}")


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 6: Mata in räntor manuellt
# ══════════════════════════════════════════════════════════════════════════════

elif page == "➕ Mata in räntor":
    st.title("➕ Mata in räntor")
    st.markdown("Ange räntor direkt från bankernas hemsidor eller appar.")

    tab1, tab2 = st.tabs(["📊 Listräntor", "🏠 Mitt erbjudande"])

    # ── Flik 1: Listräntor ────────────────────────────────────────────────────
    with tab1:
        st.subheader("Ange listränta för en bank")
        st.caption("Hämta räntorna från bankens hemsida och ange dem här.")

        with st.form("form_listrantor"):
            col1, col2 = st.columns(2)
            with col1:
                bank_val = st.selectbox("Bank", options=list(db.init_db() or []) or [
                    "SBAB", "Swedbank", "Handelsbanken", "SEB",
                    "Nordea", "Danske Bank", "Länsförsäkringar", "Skandia",
                ])
            with col2:
                rate_date_val = st.date_input("Datum", value=__import__('datetime').date.today())

            st.markdown("**Räntor (lämna blankt om okänd)**")
            c1, c2, c3, c4, c5 = st.columns(5)
            r_3m  = c1.text_input("3 mån",  placeholder="3.12")
            r_1ar = c2.text_input("1 år",   placeholder="3.08")
            r_2ar = c3.text_input("2 år",   placeholder="3.05")
            r_3ar = c4.text_input("3 år",   placeholder="3.01")
            r_5ar = c5.text_input("5 år",   placeholder="3.15")

            submitted = st.form_submit_button("💾 Spara", use_container_width=True, type="primary")

        if submitted:
            from storage.database import upsert_list_rate
            import datetime

            entries = {
                "3_man": ("3 månader", r_3m),
                "1_ar":  ("1 år",     r_1ar),
                "2_ar":  ("2 år",     r_2ar),
                "3_ar":  ("3 år",     r_3ar),
                "5_ar":  ("5 år",     r_5ar),
            }
            saved = 0
            errors = []
            for pk, (plabel, raw) in entries.items():
                if not raw.strip():
                    continue
                try:
                    rate_f = float(raw.strip().replace(",", "."))
                    if not 0 < rate_f < 25:
                        raise ValueError
                    upsert_list_rate(rate_date_val, bank_val, pk, plabel, rate_f, "Manuell inmatning")
                    saved += 1
                except ValueError:
                    errors.append(f"{plabel}: '{raw}' är inte ett giltigt tal")

            if saved:
                st.success(f"✅ {saved} räntor sparade för {bank_val} ({rate_date_val})")
                st.cache_data.clear()
            for e in errors:
                st.error(e)

        # Visa senaste inmatade
        st.divider()
        st.subheader("Senast inmatade listräntor")
        latest = db.get_latest_list_rates()
        if latest:
            import pandas as pd
            df_l = pd.DataFrame(latest)[["rate_date","bank","period_label","rate","source_url"]]
            df_l.columns = ["Datum","Bank","Bindningstid","Ränta (%)","Källa"]
            st.dataframe(df_l, use_container_width=True, hide_index=True)
        else:
            st.info("Inga listräntor inmatade ännu.")

    # ── Flik 2: Mitt erbjudande ───────────────────────────────────────────────
    with tab2:
        st.subheader("Registrera eget erbjudande")
        st.caption("Ange ett erbjudande du fått från en bank.")

        with st.form("form_erbjudande"):
            col1, col2, col3 = st.columns(3)
            with col1:
                e_bank = st.selectbox("Bank", [
                    "SBAB","Swedbank","Handelsbanken","SEB",
                    "Nordea","Danske Bank","Länsförsäkringar","Skandia",
                ], key="e_bank")
            with col2:
                e_period = st.selectbox("Bindningstid", list(BINDING_PERIODS.keys()),
                    format_func=lambda k: BINDING_PERIODS[k], key="e_period")
            with col3:
                e_date = st.date_input("Datum", value=__import__('datetime').date.today(), key="e_date")

            col4, col5 = st.columns(2)
            with col4:
                e_rate = st.text_input("Erbjuden ränta (%)", placeholder="2.95")
            with col5:
                e_loan = st.text_input("Lånebelopp (kr)", placeholder="3000000")

            e_comment = st.text_input("Kommentar", placeholder="Efter förhandling via telefon")
            e_source  = st.text_input("Källa", placeholder="Kundtjänst / app / möte")

            e_submit = st.form_submit_button("💾 Spara erbjudande", use_container_width=True, type="primary")

        if e_submit:
            from storage.database import insert_my_offer, get_latest_list_rates
            from analysis.calculator import discount_vs_list

            try:
                rate_f = float(e_rate.strip().replace(",", "."))
                loan_i = int(e_loan.strip().replace(" ", "").replace(",", "")) if e_loan.strip() else None
                ll = {(r["bank"], r["period_key"]): r["rate"] for r in get_latest_list_rates()}
                disc = discount_vs_list(rate_f, ll[(e_bank, e_period)]) if (e_bank, e_period) in ll else None
                insert_my_offer(
                    offer_date=e_date,
                    bank=e_bank,
                    period_key=e_period,
                    period_label=BINDING_PERIODS[e_period],
                    offered_rate=rate_f,
                    loan_amount=loan_i,
                    discount_vs_list=disc,
                    comment=e_comment or None,
                    source=e_source or None,
                )
                st.success(f"✅ Erbjudande från {e_bank} sparat!")
                if disc is not None:
                    color = "green" if disc > 0 else "red"
                    st.markdown(f"Din rabatt mot listräntan: **:{color}[{disc:+.2f} pp]**")
                if loan_i:
                    from analysis.calculator import monthly_cost
                    st.info(f"Räntekostnad: {monthly_cost(loan_i, rate_f):,.0f} kr/månad")
                st.cache_data.clear()
            except Exception as exc:
                st.error(f"Fel: {exc} – kontrollera att räntan är ett tal (ex: 2.95)")


# ── Footer ────────────────────────────────────────────────────────────────────

st.sidebar.divider()
st.sidebar.caption("Boränteagent Sverige  \nKör `python main.py run` för daglig uppdatering")

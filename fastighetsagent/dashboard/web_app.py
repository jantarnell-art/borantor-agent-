import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH
from storage.database import get_all_deals, get_deal_stats, init_db

st.set_page_config(
    page_title="Fastighetsagent",
    page_icon="\U0001f3e2",
    layout="wide",
    initial_sidebar_state="expanded",
)

_secrets = getattr(st, "secrets", {})
if "password" in _secrets:
    pwd = st.sidebar.text_input("Lösenord", type="password")
    if pwd != _secrets["password"]:
        st.warning("Ange lösenord för att fortsätta.")
        st.stop()


@st.cache_data(ttl=300)
def load_deals() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    init_db()
    deals = get_all_deals()
    if not deals:
        return pd.DataFrame()
    df = pd.DataFrame(deals)
    for col in ["artikel_datum", "kope_datum"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    df["extracted_at"] = pd.to_datetime(df["extracted_at"], errors="coerce")
    return df


@st.cache_data(ttl=300)
def load_stats() -> dict:
    if not DB_PATH.exists():
        return {}
    init_db()
    return get_deal_stats()


def fmt_msek(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    return f"{v:,.0f} MSEK"


def fmt_kvm(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    return f"{int(v):,} kvm".replace(",", " ")


def fmt_kr(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    return f"{int(v):,} kr/kvm".replace(",", " ")


def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    return f"{v:.1f}%"


st.sidebar.title("\U0001f3e2 Fastighetsagent")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigation",
    [
        "\U0001f4ca Marknadsöversikt",
        "\U0001f50d Senaste affärerna",
        "\U0001f4c8 Statistik & Trender",
        "\U0001f465 Aktörer",
        "\U0001f5c4️ Databas",
    ],
)

df = load_deals()
stats = load_stats()

if df.empty:
    st.info("Ingen data ännu. Kör `python main.py collect` för att samla in affärer.")
    st.stop()

# ─── PAGE 1: Marknadsöversikt ──────────────────────────────────────────────
if page == "\U0001f4ca Marknadsöversikt":
    st.title("\U0001f4ca Marknadsöversikt")

    total = len(df)
    vol = df["kopeskilling_msek"].sum()
    avg_da = df["da_krav_pct"].mean()
    avg_kvm = df["kr_per_kvm"].mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Totalt antal affärer", f"{total:,}")
    c2.metric("Total volym", fmt_msek(vol))
    c3.metric("Snitt DA-krav", fmt_pct(avg_da))
    c4.metric("Snitt kr/kvm", fmt_kr(avg_kvm))

    st.markdown("---")
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Volym per månad (MSEK)")
        df_m = df.copy()
        df_m["manad"] = df_m["extracted_at"].dt.to_period("M").astype(str)
        monthly = df_m.groupby("manad")["kopeskilling_msek"].sum().reset_index()
        monthly.columns = ["Månad", "MSEK"]
        if not monthly.empty:
            fig = px.bar(monthly.tail(18), x="Månad", y="MSEK",
                         color_discrete_sequence=["#1f77b4"])
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("Affärer per fastighetstyp")
        if stats.get("by_type"):
            type_df = pd.DataFrame(stats["by_type"])
            fig = px.pie(type_df, values="n", names="fastighetstyp",
                         color_discrete_sequence=px.colors.qualitative.Set3)
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Senaste 10 affärerna")
    cols_show = ["artikel_datum", "kopare", "saljare", "fastighetstyp", "ort",
                 "kopeskilling_msek", "kr_per_kvm", "da_krav_pct"]
    recent = df.head(10)[cols_show].copy()
    recent.columns = ["Datum", "Köpare", "Säljare", "Typ", "Ort", "MSEK", "kr/kvm", "DA %"]
    recent["MSEK"] = recent["MSEK"].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "–")
    recent["kr/kvm"] = recent["kr/kvm"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "–")
    recent["DA %"] = recent["DA %"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "–")
    st.dataframe(recent, use_container_width=True, hide_index=True)


# ─── PAGE 2: Senaste affärerna ─────────────────────────────────────────────
elif page == "\U0001f50d Senaste affärerna":
    st.title("\U0001f50d Senaste affärerna")

    with st.expander("Filter", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            types = ["Alla"] + sorted(df["fastighetstyp"].dropna().unique().tolist())
            sel_type = st.selectbox("Fastighetstyp", types)
        with f2:
            sources = ["Alla"] + sorted(df["kalla"].dropna().unique().tolist())
            sel_source = st.selectbox("Källa", sources)
        with f3:
            orter = ["Alla"] + sorted(df["ort"].dropna().unique().tolist())
            sel_ort = st.selectbox("Ort", orter)
        with f4:
            days_back = st.slider("Dagar tillbaka", 7, 365, 90)

    filt = df.copy()
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days_back)
    filt = filt[filt["extracted_at"] >= cutoff]
    if sel_type != "Alla":
        filt = filt[filt["fastighetstyp"] == sel_type]
    if sel_source != "Alla":
        filt = filt[filt["kalla"] == sel_source]
    if sel_ort != "Alla":
        filt = filt[filt["ort"] == sel_ort]

    st.markdown(f"**{len(filt)} affärer** matchar filtren")

    for _, row in filt.iterrows():
        cols = st.columns([3, 1, 1, 1, 1])
        with cols[0]:
            kopare = row.get("kopare") or "?"
            saljare = row.get("saljare") or "?"
            st.markdown(f"**{kopare}** ← {saljare}")
            loc = " ".join(filter(None, [row.get("fastighetstyp"), row.get("adress"), row.get("ort")]))
            st.caption(loc)
            if row.get("beskrivning"):
                st.caption(row["beskrivning"])
        with cols[1]:
            st.metric("Pris", fmt_msek(row.get("kopeskilling_msek")))
        with cols[2]:
            area = row.get("loa_kvm") or row.get("boa_kvm")
            st.metric("Area", fmt_kvm(area))
        with cols[3]:
            st.metric("kr/kvm", fmt_kr(row.get("kr_per_kvm")))
        with cols[4]:
            st.metric("DA-krav", fmt_pct(row.get("da_krav_pct")))
        kalla = row.get("kalla") or ""
        url = row.get("artikel_url") or "#"
        datum = str(row.get("artikel_datum", ""))[:10]
        st.caption(f"[{kalla}]({url}) · {datum}")
        st.divider()


# ─── PAGE 3: Statistik & Trender ──────────────────────────────────────────
elif page == "\U0001f4c8 Statistik & Trender":
    st.title("\U0001f4c8 Statistik & Trender")

    tab1, tab2, tab3 = st.tabs(["Priser per typ", "DA-krav", "Volym"])

    with tab1:
        st.subheader("Snitt kr/kvm per fastighetstyp")
        kvm_df = df[df["kr_per_kvm"].notna() & df["fastighetstyp"].notna()].copy()
        if not kvm_df.empty:
            agg = kvm_df.groupby("fastighetstyp")["kr_per_kvm"].agg(
                ["mean", "min", "max", "count"]
            ).reset_index()
            agg.columns = ["Typ", "Snitt kr/kvm", "Min", "Max", "Antal"]
            agg = agg.sort_values("Snitt kr/kvm", ascending=True)
            fig = px.bar(agg, x="Snitt kr/kvm", y="Typ", orientation="h",
                         text="Antal", color="Snitt kr/kvm",
                         color_continuous_scale="Blues")
            fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(agg.sort_values("Snitt kr/kvm", ascending=False),
                         hide_index=True, use_container_width=True)
        else:
            st.info("Inga kr/kvm-data tillgängliga ännu.")

    with tab2:
        st.subheader("DA-krav per fastighetstyp")
        da_df = df[df["da_krav_pct"].notna() & df["fastighetstyp"].notna()].copy()
        if not da_df.empty:
            fig = px.box(da_df, x="fastighetstyp", y="da_krav_pct",
                         labels={"fastighetstyp": "Typ", "da_krav_pct": "DA-krav (%)"},
                         color="fastighetstyp")
            fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("DA-krav över tid (snitt per månad)")
            da_df["manad"] = da_df["extracted_at"].dt.to_period("M").astype(str)
            da_trend = da_df.groupby("manad")["da_krav_pct"].mean().reset_index()
            da_trend.columns = ["Månad", "Snitt DA-krav (%)"]
            fig2 = px.line(da_trend, x="Månad", y="Snitt DA-krav (%)", markers=True)
            fig2.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Inga DA-krav-data tillgängliga ännu.")

    with tab3:
        st.subheader("Affärsvolym per månad")
        vol_df = df.copy()
        vol_df["manad"] = vol_df["extracted_at"].dt.to_period("M").astype(str)
        vol_monthly = vol_df.groupby("manad").agg(
            antal=("id", "count"),
            volym_msek=("kopeskilling_msek", "sum"),
        ).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=vol_monthly["manad"], y=vol_monthly["volym_msek"],
                             name="MSEK", yaxis="y"))
        fig.add_trace(go.Scatter(x=vol_monthly["manad"], y=vol_monthly["antal"],
                                 name="Antal affärer", yaxis="y2",
                                 mode="lines+markers", line=dict(color="orange")))
        fig.update_layout(
            yaxis=dict(title="Volym (MSEK)"),
            yaxis2=dict(title="Antal affärer", overlaying="y", side="right"),
            height=350, margin=dict(l=0, r=0, t=0, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)


# ─── PAGE 4: Aktörer ──────────────────────────────────────────────────────
elif page == "\U0001f465 Aktörer":
    st.title("\U0001f465 Aktörer – Köpare & Säljare")

    tab_k, tab_s = st.tabs(["Toppköpare", "Toppsäljare"])

    with tab_k:
        buyers = pd.DataFrame(stats.get("top_buyers", []))
        if not buyers.empty:
            buyers.columns = ["Köpare", "Antal förvärv", "Total MSEK"]
            buyers["Total MSEK"] = buyers["Total MSEK"].apply(
                lambda x: f"{x:,.0f}" if pd.notna(x) else "–"
            )
            fig = px.bar(buyers.head(15), x="Antal förvärv", y="Köpare",
                         orientation="h", color="Antal förvärv",
                         color_continuous_scale="Blues")
            fig.update_layout(height=450, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(buyers, use_container_width=True, hide_index=True)
        else:
            st.info("Inga köpardata ännu.")

    with tab_s:
        sellers = pd.DataFrame(stats.get("top_sellers", []))
        if not sellers.empty:
            sellers.columns = ["Säljare", "Antal försäljningar", "Total MSEK"]
            sellers["Total MSEK"] = sellers["Total MSEK"].apply(
                lambda x: f"{x:,.0f}" if pd.notna(x) else "–"
            )
            fig = px.bar(sellers.head(15), x="Antal försäljningar", y="Säljare",
                         orientation="h", color="Antal försäljningar",
                         color_continuous_scale="Reds")
            fig.update_layout(height=450, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(sellers, use_container_width=True, hide_index=True)
        else:
            st.info("Inga säljardata ännu.")


# ─── PAGE 5: Databas ──────────────────────────────────────────────────────
elif page == "\U0001f5c4️ Databas":
    st.title("\U0001f5c4️ Fullständig databas")

    search = st.text_input("Sök (köpare, säljare, ort, adress, typ...)", "")

    show_df = df.copy()
    if search:
        mask = (
            show_df["kopare"].str.contains(search, case=False, na=False)
            | show_df["saljare"].str.contains(search, case=False, na=False)
            | show_df["ort"].str.contains(search, case=False, na=False)
            | show_df["adress"].str.contains(search, case=False, na=False)
            | show_df["fastighetstyp"].str.contains(search, case=False, na=False)
            | show_df["region"].str.contains(search, case=False, na=False)
        )
        show_df = show_df[mask]

    display_cols = [
        "artikel_datum", "kopare", "saljare", "fastighetstyp",
        "ort", "region", "kopeskilling_msek", "loa_kvm", "boa_kvm",
        "kr_per_kvm", "da_krav_pct", "uthyrningsgrad_pct", "kalla",
    ]
    display_df = show_df[[c for c in display_cols if c in show_df.columns]].copy()
    display_df.columns = [
        "Datum", "Köpare", "Säljare", "Typ", "Ort", "Region",
        "MSEK", "LOA kvm", "BOA kvm", "kr/kvm", "DA %", "Uthyrn %", "Källa",
    ][:len(display_df.columns)]

    st.markdown(f"**{len(display_df)} affärer**")
    st.dataframe(display_df, use_container_width=True, hide_index=True, height=600)

    csv = display_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Ladda ner som CSV", csv, "fastighetsaffarer.csv", "text/csv"
    )

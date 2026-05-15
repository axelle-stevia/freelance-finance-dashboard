"""
dashboard.py
------------
Interface Streamlit — vue financière Q1 pour freelance.

Lancer avec : streamlit run dashboard.py
"""

import sys
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

sys.path.insert(0, ".")
from engine.data_loader import (
    load_invoices, load_statement, load_receipts,
    load_notes, load_client_config, build_summary
)

# ── Configuration de la page ──────────────────────────────────────
st.set_page_config(
    page_title="Freelance Finance Dashboard",
    page_icon="💼",
    layout="wide",
)

# ── CSS minimal ───────────────────────────────────────────────────
st.markdown("""
<style>
.alert-high   { background:#fff0f0; border-left:4px solid #e74c3c;
                padding:10px 14px; border-radius:4px; margin:6px 0;
                color:#1a1a1a; }
.alert-medium { background:#fffbea; border-left:4px solid #f39c12;
                padding:10px 14px; border-radius:4px; margin:6px 0;
                color:#1a1a1a; }
.alert-low    { background:#f0f7ff; border-left:4px solid #3498db;
                padding:10px 14px; border-radius:4px; margin:6px 0;
                color:#1a1a1a; }
.opp-card     { background:#f0fff4; border-left:4px solid #27ae60;
                padding:10px 14px; border-radius:4px; margin:6px 0;
                color:#1a1a1a; }
.reminder-card{ background:#fdf6ff; border-left:4px solid #9b59b6;
                padding:10px 14px; border-radius:4px; margin:6px 0;
                color:#1a1a1a; }
</style>
""", unsafe_allow_html=True)

# ── Chargement des données ────────────────────────────────────────
CLIENT = "shannon_q1_2025"
SHOEBOX = f"clients/{CLIENT}/shoebox"
CLIENT_FOLDER = f"clients/{CLIENT}"

@st.cache_data
def get_data():
    inv   = load_invoices(SHOEBOX)
    stmt  = load_statement(SHOEBOX, CLIENT_FOLDER)
    rec   = load_receipts(SHOEBOX)
    notes = load_notes(SHOEBOX)
    cfg   = load_client_config(CLIENT_FOLDER)
    summ  = build_summary(inv, stmt, rec)
    return inv, stmt, rec, notes, cfg, summ

inv_df, stmt_df, rec_df, notes, client_cfg, summary = get_data()

# ── En-tête ───────────────────────────────────────────────────────
client_name    = client_cfg.get("client_name", CLIENT)
fiscal_quarter = client_cfg.get("fiscal_quarter", "")
st.title("💼 Tableau de bord financier")
st.caption(f"{client_name} · {fiscal_quarter}")
st.divider()

# ══════════════════════════════════════════════════════════════════
# SECTION 1 : MÉTRIQUES CLÉS
# ══════════════════════════════════════════════════════════════════
st.subheader("Vue d'ensemble")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Revenus facturés",
              f"${summary['revenue']['total_invoiced']:,.0f}")
with col2:
    st.metric("Encaissé",
              f"${summary['revenue']['total_paid']:,.0f}")
with col3:
    st.metric("En attente",
              f"${summary['revenue']['total_unpaid']:,.0f}",
              delta=f"-${summary['revenue']['total_unpaid']:,.0f}",
              delta_color="inverse")
with col4:
    st.metric("Dépenses business",
              f"${summary['expenses']['total_expenses']:,.0f}")
with col5:
    st.metric("Net estimé Q1",
              f"${summary['net']:,.0f}")

st.divider()

# ══════════════════════════════════════════════════════════════════
# SECTION 2 : ALERTES
# ══════════════════════════════════════════════════════════════════
st.subheader("🚨 Alertes")

unpaid = inv_df[inv_df["status"] == "unpaid"]
dupes  = stmt_df["is_duplicate"].sum()
pers   = summary["expenses"]["personal_excluded"]

if unpaid.empty and dupes == 0 and pers == 0:
    st.success("Aucune alerte — tout est en ordre ✅")
else:
    for _, row in unpaid.iterrows():
        st.markdown(
            f'<div class="alert-high">🔴 <b>Facture impayée</b> — '
            f'{row["client"]} · <b>${row["amount"]:,.0f}</b> '
            f'· envoyée le {row["date_sent"]}</div>',
            unsafe_allow_html=True
        )
    if dupes > 0:
        dup_rows = stmt_df[stmt_df["is_duplicate"]]
        dup_list = ", ".join(dup_rows["description"].unique()[:3])
        st.markdown(
            f'<div class="alert-medium">🟡 <b>{dupes} transaction(s) dupliquée(s)</b> '
            f'détectée(s) dans le relevé — vérifier avec la banque<br>'
            f'<small>{dup_list}</small></div>',
            unsafe_allow_html=True
        )
    if pers > 0:
        pers_items = stmt_df[stmt_df["category"] == "personal"]["description"].unique()
        st.markdown(
            f'<div class="alert-low">🔵 <b>${pers:.2f} de dépenses personnelles</b> '
            f'sur la carte business — à transférer sur carte personnelle<br>'
            f'<small>{", ".join(pers_items)}</small></div>',
            unsafe_allow_html=True
        )

    # Remboursements reçus
    credits = stmt_df[stmt_df["type"] == "credit"]
    if not credits.empty:
        st.markdown(
            f'<div class="alert-low">✅ <b>{len(credits)} remboursement(s) reçus</b> '
            f'— total ${abs(credits["amount"].sum()):.2f} crédité</div>',
            unsafe_allow_html=True
        )

st.divider()

# ══════════════════════════════════════════════════════════════════
# SECTION 3 : REVENUS ET DÉPENSES (côte à côte)
# ══════════════════════════════════════════════════════════════════
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("📋 Factures")

    # Tableau factures avec couleur selon statut
    display_inv = inv_df[["client", "description", "amount", "date_sent", "status"]].copy()
    display_inv.columns = ["Client", "Description", "Montant", "Envoyée le", "Statut"]
    display_inv["Montant"] = display_inv["Montant"].apply(lambda x: f"${x:,.0f}")

    def color_status(val):
        if val == "paid":
            return "background-color: #d4edda; color: #155724"
        return "background-color: #f8d7da; color: #721c24"

    st.dataframe(
        display_inv.style.map(color_status, subset=["Statut"]),
        use_container_width=True,
        hide_index=True,
    )

    # Mini graphique revenus par client
    by_client = pd.DataFrame.from_dict(
        summary["by_client"], orient="index", columns=["Montant"]
    ).reset_index().rename(columns={"index": "Client"})

    fig_clients = px.bar(
        by_client.sort_values("Montant", ascending=True),
        x="Montant", y="Client", orientation="h",
        title="Revenus par client (Q1)",
        color_discrete_sequence=["#4C72B0"],
    )
    fig_clients.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=200)
    st.plotly_chart(fig_clients, use_container_width=True)

with col_right:
    st.subheader("💳 Dépenses par catégorie")

    by_cat = pd.DataFrame.from_dict(
        summary["by_category"], orient="index", columns=["Montant"]
    ).reset_index().rename(columns={"index": "Catégorie"})

    CATEGORY_FR = {
        "software": "Logiciels",
        "coworking": "Coworking",
        "transport": "Transport",
        "meals_entertainment": "Repas / Réceptions",
        "office_supplies": "Fournitures bureau",
        "other": "Autre",
    }
    by_cat["Catégorie"] = by_cat["Catégorie"].map(CATEGORY_FR).fillna(by_cat["Catégorie"])

    fig_pie = px.pie(
        by_cat, values="Montant", names="Catégorie",
        title=f"Total business : ${summary['expenses']['total_expenses']:,.0f}",
        hole=0.4,
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig_pie.update_traces(textinfo="label+percent")
    fig_pie.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=280)
    st.plotly_chart(fig_pie, use_container_width=True)

    # Reçus comptants
    if not rec_df.empty:
        st.caption("🧾 Reçus comptants inclus")
        display_rec = rec_df[["merchant", "date", "amount", "category"]].copy()
        display_rec.columns = ["Marchand", "Date", "Montant", "Catégorie"]
        display_rec["Montant"] = display_rec["Montant"].apply(lambda x: f"${x:.2f}")
        st.dataframe(display_rec, use_container_width=True, hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════════════════
# SECTION 4 : TRANSACTIONS DÉTAILLÉES
# ══════════════════════════════════════════════════════════════════
st.subheader("📊 Toutes les transactions du relevé")

# Filtres
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    show_dupes = st.checkbox("Afficher les doublons", value=False)
with col_f2:
    show_personal = st.checkbox("Afficher le personnel", value=True)
with col_f3:
    cat_filter = st.multiselect(
        "Filtrer par catégorie",
        options=sorted(stmt_df["category"].unique()),
        default=[],
    )

filtered = stmt_df.copy()
if not show_dupes:
    filtered = filtered[~filtered["is_duplicate"]]
if not show_personal:
    filtered = filtered[filtered["category"] != "personal"]
if cat_filter:
    filtered = filtered[filtered["category"].isin(cat_filter)]

display_stmt = filtered[["date", "description", "amount", "category", "type", "is_duplicate", "refund_for"]].copy()
display_stmt.columns = ["Date", "Description", "Montant", "Catégorie", "Type", "Doublon", "Remb. de"]

def style_transactions(row):
    if row["Doublon"]:
        return ["background-color: #fff3cd"] * len(row)
    if row["Type"] == "credit":
        return ["background-color: #d4edda"] * len(row)
    if row["Catégorie"] == "personal":
        return ["background-color: #f8d7da"] * len(row)
    return [""] * len(row)

st.dataframe(
    display_stmt.style.apply(style_transactions, axis=1),
    use_container_width=True,
    hide_index=True,
)
st.caption(f"🟡 Jaune = doublon · 🟢 Vert = remboursement · 🔴 Rouge = personnel")

st.divider()

# ══════════════════════════════════════════════════════════════════
# SECTION 5 : OPPORTUNITÉS ET RAPPELS (depuis notes.txt)
# ══════════════════════════════════════════════════════════════════
st.subheader("💡 Depuis vos notes")

col_opp, col_rem = st.columns(2)

with col_opp:
    st.markdown("**Opportunités business**")
    if notes["opportunities"]:
        for opp in notes["opportunities"]:
            st.markdown(f'<div class="opp-card">💡 {opp}</div>', unsafe_allow_html=True)
    else:
        st.caption("Aucune opportunité détectée dans les notes.")

with col_rem:
    st.markdown("**Rappels importants**")
    if notes["reminders"]:
        for rem in notes["reminders"]:
            st.markdown(f'<div class="reminder-card">🔔 {rem}</div>', unsafe_allow_html=True)

    st.markdown("**À faire**")
    if notes["todos"]:
        for todo in notes["todos"]:
            st.markdown(f'<div class="alert-high">☐ {todo}</div>', unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════════
# SECTION 6 : RÉCONCILIATION DES REMBOURSEMENTS
# ══════════════════════════════════════════════════════════════════
with st.expander("🔍 Détail — réconciliation des remboursements"):
    credits = stmt_df[stmt_df["type"] == "credit"]
    if credits.empty:
        st.info("Aucun remboursement dans cette période.")
    else:
        for _, credit in credits.iterrows():
            linked = credit["refund_for"]
            if linked:
                original = stmt_df[stmt_df["trans_id"] == linked]
                if not original.empty:
                    orig = original.iloc[0]
                    net = orig["amount"] + credit["amount"]
                    st.markdown(f"""
| | Date | Description | Montant |
|---|---|---|---|
| Débit original | {orig['date']} | {orig['description']} | ${orig['amount']:.2f} |
| Remboursement  | {credit['date']} | {credit['description']} | ${credit['amount']:.2f} |
| **Coût net**   | | | **${net:.2f}** |
""")
            else:
                st.markdown(f"- `{credit['date']}` {credit['description']} : **${credit['amount']:.2f}** *(débit original non trouvé)*")

st.caption("Généré par freelance-finance-dashboard · Données Q1 2025")
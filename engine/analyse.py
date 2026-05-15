"""
analyze.py
----------
Assemble toutes les sources de données et produit le résumé financier final.

Ce module est le "chef d'orchestre" : il appelle les 3 parsers,
fusionne les données et calcule les métriques finales.

Principe clé : chaque parser est indépendant (il ne sait pas que les autres existent).
C'est analyze.py qui fait le lien. Cela rend chaque module testable séparément.
"""

import json
import pandas as pd
from pathlib import Path

from engine.parse_invoices import load_invoices, get_summary as invoice_summary
from engine.parse_statement import parse_statement, get_summary as statement_summary
from engine.parse_receipts import load_receipts


def run_analysis(
    invoices_path: str,
    statement_path: str,
    receipts_folder: str,
    output_folder: str,
    config_path: str = "config/categories.json",
) -> dict:
    """
    Lance l'analyse complète d'un client.

    Paramètres :
      invoices_path   → chemin vers le .xlsx des factures
      statement_path  → chemin vers le PDF du relevé
      receipts_folder → dossier contenant les photos de reçus
      output_folder   → où sauvegarder les résultats
      config_path     → règles de catégorisation

    Retourne :
      Un dictionnaire complet avec toutes les métriques Q1.
    """
    output = Path(output_folder)
    output.mkdir(parents=True, exist_ok=True)

    print("\n" + "="*50)
    print("  ANALYSE FINANCIÈRE Q1 2025")
    print("="*50)

    # ── 1. REVENUS ────────────────────────────────────
    print("\n📋 ÉTAPE 1 : Lecture des factures...")
    invoices_df = load_invoices(invoices_path)
    inv_summary = invoice_summary(invoices_df)

    # Sauvegarder les données propres
    invoices_df.to_csv(output / "invoices_clean.csv", index=False)

    # ── 2. DÉPENSES (relevé bancaire) ─────────────────
    print("\n💳 ÉTAPE 2 : Lecture du relevé bancaire...")
    statement_df = parse_statement(statement_path, config_path)
    stmt_summary = statement_summary(statement_df) if not statement_df.empty else {}

    if not statement_df.empty:
        statement_df.to_csv(output / "statement_clean.csv", index=False)

    # ── 3. REÇUS COMPTANTS ────────────────────────────
    print("\n🧾 ÉTAPE 3 : Lecture des reçus...")
    receipts_df = load_receipts(receipts_folder)

    if not receipts_df.empty:
        receipts_df.to_csv(output / "receipts_clean.csv", index=False)
        total_receipts = receipts_df["amount"].dropna().sum()
    else:
        total_receipts = 0

    # ── 4. RÉSUMÉ FINAL ───────────────────────────────
    total_revenue = inv_summary.get("total_paid", 0)
    total_expenses = (
        stmt_summary.get("total_business_net", 0) + total_receipts
    )
    net_income = total_revenue + total_expenses  # expenses est négatif si dépenses

    summary = {
        "period": "Q1 2025 (Jan–Mar)",
        "revenue": {
            "total_invoiced": inv_summary.get("total_invoiced", 0),
            "total_collected": inv_summary.get("total_paid", 0),
            "total_outstanding": inv_summary.get("total_unpaid", 0),
            "unpaid_invoices": inv_summary.get("unpaid_invoices", []),
            "by_client": inv_summary.get("invoices_by_client", {}),
        },
        "expenses": {
            "total_card": abs(stmt_summary.get("total_business_net", 0)),
            "total_cash_receipts": round(total_receipts, 2),
            "total_personal_excluded": stmt_summary.get("total_personal", 0),
            "credits_received": abs(stmt_summary.get("total_credits", 0)),
            "duplicates_removed": stmt_summary.get("duplicates_found", 0),
            "by_category": stmt_summary.get("by_category", {}),
        },
        "alerts": build_alerts(inv_summary, stmt_summary),
    }

    # Sauvegarder le résumé en JSON
    with open(output / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n" + "="*50)
    print(f"  💰 Revenus collectés : ${total_revenue:,.2f}")
    print(f"  ⚠️  En attente       : ${inv_summary.get('total_unpaid', 0):,.2f}")
    print(f"  📤 Dépenses business : ${abs(total_expenses):,.2f}")
    print("="*50)
    print(f"\n✅ Résultats sauvegardés dans : {output_folder}")

    return summary


def build_alerts(inv_summary: dict, stmt_summary: dict) -> list:
    """
    Génère des alertes basées sur les anomalies détectées.

    Les alertes aident la freelance à agir rapidement
    sur les problèmes importants.
    """
    alerts = []

    # Factures impayées
    for inv in inv_summary.get("unpaid_invoices", []):
        alerts.append({
            "type": "unpaid_invoice",
            "severity": "high",
            "message": f"Facture impayée : {inv['client']} — ${inv['amount']:,.2f} (envoyée le {inv['date_sent']})"
        })

    # Doublons dans le relevé
    dupes = stmt_summary.get("duplicates_found", 0)
    if dupes > 0:
        alerts.append({
            "type": "duplicate_transactions",
            "severity": "medium",
            "message": f"{dupes} transaction(s) dupliquée(s) détectée(s) dans le relevé — vérifier avec la banque"
        })

    # Dépenses personnelles sur carte business
    personal = stmt_summary.get("total_personal", 0)
    if personal > 0:
        alerts.append({
            "type": "personal_expenses",
            "severity": "low",
            "message": f"${personal:.2f} de dépenses personnelles sur la carte business (Netflix, Petco) — à rembourser ou à exclure"
        })

    return alerts

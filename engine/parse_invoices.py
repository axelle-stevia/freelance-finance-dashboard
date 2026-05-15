"""
parse_invoices.py
-----------------
Lit le fichier invoices.xlsx d'un client et le nettoie.

Ce que ce module fait :
  1. Lit le fichier Excel (peu importe le client)
  2. Normalise les dates (formats inconsistants → YYYY-MM-DD)
  3. Détecte les factures payées vs impayées
  4. Retourne un DataFrame pandas propre

Pourquoi séparer ça dans un module ?
  → Si la structure du fichier Excel change, on ne modifie QUE ce fichier.
  → Le reste du programme ne sait pas d'où viennent les données.
"""

import pandas as pd
from pathlib import Path
from dateutil import parser as dateparser


def normalize_date(raw_date) -> str:
    """
    Convertit n'importe quel format de date en YYYY-MM-DD.

    Exemples de ce qu'on reçoit (le bazar réel !) :
      "Jan 18, 25"         → "2025-01-18"
      "February 15, 2025"  → "2025-02-15"
      "Mar 28 - 2025"      → "2025-03-28"
      "3/18/25"            → "2025-03-18"

    Pourquoi normaliser ?
      → Pour pouvoir comparer et trier des dates correctement.
      → "Jan 18" < "Feb 15" ne fonctionne pas en texte brut.
    """
    if pd.isna(raw_date) or str(raw_date).strip() == "":
        return None
    try:
        # dateutil.parser est très tolérant — il devine le format
        cleaned = str(raw_date).replace(" - ", " ").strip()
        return dateparser.parse(cleaned).strftime("%Y-%m-%d")
    except Exception:
        return None  # On ne plante pas, on signale juste que c'est invalide


def load_invoices(filepath: str) -> pd.DataFrame:
    """
    Charge et nettoie le fichier de factures.

    Paramètre :
      filepath → chemin vers le .xlsx (ex: "clients/shannon_q1_2025/shoebox/invoices.xlsx")

    Retourne :
      Un DataFrame pandas avec colonnes standardisées et données propres.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {filepath}")

    # Lecture du fichier Excel
    # engine="openpyxl" = bibliothèque pour lire les .xlsx modernes
    df = pd.read_excel(path, engine="openpyxl")

    # --- Nettoyage des noms de colonnes ---
    # On enlève les espaces cachés et on met en minuscules
    # Ex: " Date Sent " → "date_sent"
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
    )

    # --- Normalisation des dates ---
    df["date_sent"] = df["date_sent"].apply(normalize_date)
    df["date_paid"] = df["date_paid"].apply(normalize_date)

    # --- Statut de paiement ---
    # Si date_paid est vide → impayé
    df["status"] = df["date_paid"].apply(
        lambda d: "paid" if d is not None else "unpaid"
    )

    # --- Nettoyage des montants ---
    # S'assurer que "amount" est un nombre (float), pas du texte
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    # --- Ajout d'une colonne source pour la traçabilité ---
    # Utile si on fusionne plusieurs sources de données plus tard
    df["source"] = "invoice"

    print(f"✅ Factures chargées : {len(df)} entrées")
    print(f"   Payées : {(df['status'] == 'paid').sum()}")
    print(f"   Impayées : {(df['status'] == 'unpaid').sum()}")

    return df


def get_summary(df: pd.DataFrame) -> dict:
    """
    Calcule un résumé financier des factures.

    Retourne un dictionnaire avec les totaux clés.
    Un dictionnaire en Python = paires clé/valeur, comme un formulaire.
    """
    return {
        "total_invoiced": round(df["amount"].sum(), 2),
        "total_paid": round(df[df["status"] == "paid"]["amount"].sum(), 2),
        "total_unpaid": round(df[df["status"] == "unpaid"]["amount"].sum(), 2),
        "unpaid_invoices": df[df["status"] == "unpaid"][
            ["client", "description", "amount", "date_sent"]
        ].to_dict("records"),
        "invoices_by_client": df.groupby("client")["amount"]
            .sum()
            .round(2)
            .to_dict(),
    }

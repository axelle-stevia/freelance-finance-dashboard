"""
parse_statement.py
------------------
Lit un relevé de carte de crédit en PDF et le nettoie.

Défis à gérer :
  - Chaque banque a sa propre mise en page → ce parser vise les layouts tabulaires simples
  - Les doublons (même transaction deux fois)
  - Les crédits (remboursements) vs débits (achats)
  - La catégorisation des marchands
"""

import re
import json
import pdfplumber
import pandas as pd
from pathlib import Path


def load_categories(config_path: str = "config/categories.json") -> dict:
    """Charge les règles de catégorisation depuis le fichier config."""
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["categories"]


def categorize_regex(description: str, categories: dict) -> str:
    """Niveau 1 : Classification par règles regex. Retourne 'other' si aucune règle ne correspond."""
    desc_upper = description.upper()
    for category, keywords in categories.items():
        for keyword in keywords:
            if re.search(keyword, desc_upper):
                return category
    return "other"


def categorize(description: str, categories: dict, use_llm: bool = True) -> str:
    """
    Cascade de classification à 3 niveaux :

    Niveau 1 → Regex  : instantané, déterministe, fonctionne toujours
    Niveau 2 → LLM    : comprend le contexte si Ollama est lancé
    Niveau 3 → Fallback "other" : garantit que rien ne plante

    use_llm=False désactive le niveau 2 (utile pour les tests).
    """
    result = categorize_regex(description, categories)
    if result != "other":
        return result

    if use_llm:
        from engine.llm_classifier import classify_with_llm, is_ollama_available
        if is_ollama_available():
            llm_result = classify_with_llm(description)
            if llm_result:
                return llm_result

    return "other"


def detect_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Marque les transactions dupliquées.

    Une transaction est un doublon si :
      - Même date
      - Même description
      - Même montant
      - Apparaît plus d'une fois

    On garde la PREMIÈRE occurrence et marque les suivantes comme doublons.

    Pourquoi c'est important ?
      Les doublons faussent tous les totaux.
      Dans le relevé de ce client, on a trouvé 3 doublons !
    """
    duplicate_mask = df.duplicated(
        subset=["date", "description", "amount"],
        keep="first"  # garde la première, marque les autres
    )
    df["is_duplicate"] = duplicate_mask
    n_dupes = duplicate_mask.sum()
    if n_dupes > 0:
        print(f"⚠️  {n_dupes} doublon(s) détecté(s) dans le relevé")
    return df


def parse_statement(filepath: str, config_path: str = "config/categories.json") -> pd.DataFrame:
    """
    Extrait et nettoie les transactions d'un relevé PDF.

    Format attendu (typique des relevés en tableau) :
      TRANS_ID  DATE  DESCRIPTION  AMOUNT

    Retourne un DataFrame avec une ligne par transaction.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {filepath}")

    categories = load_categories(config_path)
    transactions = []

    # Pattern pour détecter une ligne de transaction
    # Exemple : "TXN-0103-001 Jan 03 GOOGLE *WORKSPACE $8.28"
    # Le $ devant le montant est optionnel, le montant peut être négatif (remboursement)
    line_pattern = re.compile(
        r"(TXN-[\w-]+)\s+"           # ID de transaction
        r"(\w{3}\s+\d{1,2})\s+"      # Date : "Jan 03"
        r"(.+?)\s+"                   # Description (tout le reste sauf le montant)
        r"(-?\$?[\d,]+\.\d{2})$"      # Montant (peut être négatif pour un remboursement)
    )

    with pdfplumber.open(path) as pdf:
        current_month_year = None

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                line = line.strip()

                # Détecter l'en-tête de mois pour reconstituer l'année
                month_match = re.match(r"^(January|February|March|April|May|June|"
                                       r"July|August|September|October|November|December)\s+(\d{4})", line)
                if month_match:
                    current_month_year = month_match.group(2)
                    continue

                # Détecter une ligne de transaction
                tx_match = line_pattern.match(line)
                if tx_match:
                    trans_id, date_str, description, amount_str = tx_match.groups()

                    # Nettoyer le montant : enlever $ et convertir en float
                    amount = float(amount_str.replace("$", "").replace(",", ""))

                    # Reconstituer la date complète avec l'année
                    year = current_month_year or "2025"
                    try:
                        from dateutil import parser as dp
                        full_date = dp.parse(f"{date_str} {year}").strftime("%Y-%m-%d")
                    except Exception:
                        full_date = date_str

                    transactions.append({
                        "trans_id": trans_id,
                        "date": full_date,
                        "description": description.strip(),
                        "amount": amount,
                        "source": "statement",
                    })

    if not transactions:
        print("⚠️  Aucune transaction trouvée — vérifier le format du PDF")
        return pd.DataFrame()

    df = pd.DataFrame(transactions)

    # Catégoriser chaque transaction
    df["category"] = df["description"].apply(
        lambda d: categorize(d, categories)
    )

    # Séparer débits et crédits
    # Un montant négatif = remboursement/crédit
    df["type"] = df["amount"].apply(
        lambda x: "credit" if x < 0 else "debit"
    )

    # Détecter les doublons
    df = detect_duplicates(df)

    print(f"✅ Relevé parsé : {len(df)} transactions")
    print(f"   Débits : {(df['type'] == 'debit').sum()}")
    print(f"   Crédits (remboursements) : {(df['type'] == 'credit').sum()}")
    print(f"   Catégorie 'personal' : {(df['category'] == 'personal').sum()}")

    return df


def get_summary(df: pd.DataFrame) -> dict:
    """Calcule les totaux par catégorie, en excluant les doublons et le personnel."""
    # Exclure les doublons et les dépenses personnelles pour le résumé business
    business_df = df[~df["is_duplicate"] & (df["category"] != "personal")]
    credits_df = df[df["type"] == "credit"]

    return {
        "total_spent_gross": round(df[~df["is_duplicate"] & (df["type"] == "debit")]["amount"].sum(), 2),
        "total_personal": round(df[df["category"] == "personal"]["amount"].sum(), 2),
        "total_credits": round(credits_df["amount"].sum(), 2),
        "total_business_net": round(business_df[business_df["type"] == "debit"]["amount"].sum()
                                    + credits_df["amount"].sum(), 2),
        "by_category": business_df[business_df["type"] == "debit"]
            .groupby("category")["amount"]
            .sum()
            .round(2)
            .to_dict(),
        "duplicates_found": df["is_duplicate"].sum(),
    }

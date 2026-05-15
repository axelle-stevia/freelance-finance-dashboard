"""
data_loader.py
--------------
Charge et nettoie toutes les sources de données d'un client.
Parse directement depuis les fichiers sources — pas de CSV intermédiaires.

Streamlit met en cache les résultats via @st.cache_data :
les fichiers sont parsés une seule fois par session, pas à chaque refresh.
"""

import re
import json
import pandas as pd
from pathlib import Path
from dateutil import parser as dateparser


def load_categories(config_path="config/categories.json"):
    """Charge les règles génériques — identiques pour tous les clients."""
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)["categories"]


def load_client_config(client_folder: str) -> dict:
    """
    Charge la config spécifique au client depuis son dossier.
    Si le fichier n'existe pas, retourne des valeurs par défaut vides.
    """
    path = Path(client_folder) / "client_config.json"
    if not path.exists():
        return {"client_name": "Unknown", "currency": "CAD",
                "known_personal_expenses": [], "known_clients": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def categorize(description: str, categories: dict,
               personal_keywords: list = None) -> str:
    """
    Classe une transaction.
    personal_keywords vient du client_config.json — dépenses
    personnelles spécifiques à ce client (Netflix, Petco...).
    """
    desc = description.upper()
    if personal_keywords:
        for kw in personal_keywords:
            if re.search(kw.upper(), desc):
                return "personal"
    for cat, keywords in categories.items():
        for kw in keywords:
            if re.search(kw, desc):
                return cat
    return "other"


def normalize_date(raw) -> str | None:
    if pd.isna(raw) or str(raw).strip() == "":
        return None
    try:
        return dateparser.parse(str(raw).replace(" - ", " ").strip()).strftime("%Y-%m-%d")
    except Exception:
        return None


# ── Factures ─────────────────────────────────────────────────────
def load_invoices(shoebox_path: str) -> pd.DataFrame:
    path = Path(shoebox_path) / "invoices.xlsx"
    if not path.exists():
        raise FileNotFoundError(f"invoices.xlsx introuvable dans {shoebox_path}")

    df = pd.read_excel(path, engine="openpyxl")
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df["date_sent"] = df["date_sent"].apply(normalize_date)
    df["date_paid"] = df["date_paid"].apply(normalize_date)
    df["status"]    = df["date_paid"].apply(
        lambda d: "unpaid" if pd.isna(d) or d is None else "paid"
    )
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df


# ── Relevé bancaire PDF ───────────────────────────────────────────
def load_statement(shoebox_path: str, client_folder: str = None, config_path="config/categories.json") -> pd.DataFrame:
    """
    Parse le PDF directement.
    Si le PDF est illisible → retourne un DataFrame vide avec un message clair.
    Le dashboard continue de fonctionner sans le relevé.
    """
    categories     = load_categories(config_path)
    client_cfg     = load_client_config(client_folder) if client_folder else {}
    personal_kwds  = client_cfg.get("known_personal_expenses", [])
    pdf_path       = Path(shoebox_path) / "Visa_Statement_Q12025.pdf"
    empty      = pd.DataFrame(columns=[
        "trans_id","date","description","amount",
        "category","type","is_duplicate","refund_for"
    ])

    if not pdf_path.exists():
        return empty

    try:
        import pdfplumber
        rows, year = [], "2025"
        line_re = re.compile(
            r"(TXN-[\w-]+)\s+(\w{3}\s+\d{1,2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})$"
        )
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for line in (page.extract_text() or "").split("\n"):
                    m = re.match(
                        r"^(January|February|March|April|May|June|July|"
                        r"August|September|October|November|December)\s+(\d{4})",
                        line.strip()
                    )
                    if m:
                        year = m.group(2)
                        continue
                    tx = line_re.match(line.strip())
                    if tx:
                        tid, date_str, desc, amt = tx.groups()
                        try:
                            full_date = dateparser.parse(f"{date_str} {year}").strftime("%Y-%m-%d")
                        except Exception:
                            full_date = date_str
                        rows.append({
                            "trans_id":    tid,
                            "date":        full_date,
                            "description": desc.strip(),
                            "amount":      float(amt.replace("$","").replace(",",""))
                        })

        if not rows:
            return empty

        df = pd.DataFrame(rows)

    except Exception:
        return empty

    df["amount"]       = pd.to_numeric(df["amount"], errors="coerce")
    df["category"]     = df["description"].apply(lambda d: categorize(d, categories, personal_kwds))
    df["type"]         = df["amount"].apply(lambda x: "credit" if x < 0 else "debit")
    df["is_duplicate"] = df.duplicated(subset=["date","description","amount"], keep="first")
    df                 = _reconcile_refunds(df)
    return df


# ── Reçus (OCR) ───────────────────────────────────────────────────
def load_receipts(shoebox_path: str) -> pd.DataFrame:
    """
    Lit les photos de reçus avec OCR si Tesseract est installé,
    sinon retourne un DataFrame vide.
    """
    receipts_dir = Path(shoebox_path) / "receipts"
    if not receipts_dir.exists():
        return pd.DataFrame()

    image_files = [
        f for f in receipts_dir.iterdir()
        if f.suffix.lower() in {".jpg",".jpeg",".png",".webp"}
    ]
    if not image_files:
        return pd.DataFrame()

    try:
        import pytesseract
        from PIL import Image
        pytesseract.get_tesseract_version()
    except Exception:
        # Tesseract non installé — on retourne un DataFrame vide proprement
        return pd.DataFrame(columns=["filename","merchant","date","amount","payment_method","category"])

    rows = []
    for img_path in sorted(image_files):
        try:
            text   = pytesseract.image_to_string(Image.open(img_path), lang="fra+eng")
            amounts = re.findall(r"TOTAL[^$\d]*\$?([\d,]+\.\d{2})", text, re.IGNORECASE)
            amount  = float(amounts[-1].replace(",","")) if amounts else None
            date    = None
            for pat in [r"\d{2}/\d{2}/\d{4}", r"\d{4}-\d{2}-\d{2}"]:
                m = re.search(pat, text)
                if m:
                    try:
                        date = dateparser.parse(m.group()).strftime("%Y-%m-%d")
                        break
                    except Exception:
                        pass
            lines    = [l.strip() for l in text.split("\n") if l.strip()]
            merchant = re.sub(r"[^a-zA-ZÀ-ÿ0-9\s\-'&]","", lines[0] if lines else "").strip()
            rows.append({
                "filename": img_path.name,
                "merchant": merchant or img_path.stem,
                "date":     date,
                "amount":   amount,
                "payment_method": (
                    "cash"       if re.search(r"COMPTANT|CASH", text, re.I) else
                    "e-transfer" if re.search(r"E-TRANSFER|VIREMENT", text, re.I) else
                    "card"
                ),
                "category": "office_supplies",
            })
        except Exception:
            continue

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Notes ─────────────────────────────────────────────────────────
def load_notes(shoebox_path: str) -> dict:
    notes_path = Path(shoebox_path) / "notes.txt"
    if not notes_path.exists():
        return {"todos": [], "opportunities": [], "reminders": []}

    text = notes_path.read_text(encoding="utf-8")
    todos, opps, reminders = [], [], []
    opp_signals      = ["might need","could be","upsell","follow up","new signage","motion graphic"]
    reminder_signals = ["renew","deadline","before","reminder","qualify","deduction"]

    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("=="):
            continue
        if line.startswith("[todo]"):
            todos.append(line.replace("[todo]","").strip())
        elif any(s in line.lower() for s in opp_signals):
            opps.append(re.sub(r"^[-–•]\s*","", line).strip())
        elif any(s in line.lower() for s in reminder_signals):
            reminders.append(re.sub(r"^[-–•]\s*","", line).strip())

    return {"todos": todos, "opportunities": opps, "reminders": reminders}


# ── Réconciliation remboursements ────────────────────────────────
def _reconcile_refunds(df: pd.DataFrame) -> pd.DataFrame:
    df["refund_for"] = None
    for idx, credit in df[df["type"] == "credit"].iterrows():
        kw = credit["description"].split()[0]
        matches = df[
            (df["type"] == "debit") &
            (df["description"].str.startswith(kw)) &
            (df["date"] < credit["date"])
        ]
        if not matches.empty:
            df.at[idx, "refund_for"] = df.at[matches.index[-1], "trans_id"]
    return df


# ── Résumé ────────────────────────────────────────────────────────
def build_summary(invoices_df, statement_df, receipts_df) -> dict:
    biz = statement_df[
        ~statement_df["is_duplicate"] &
        (statement_df["category"] != "personal") &
        (statement_df["type"] == "debit")
    ] if not statement_df.empty else pd.DataFrame(columns=["amount","category"])

    total_paid     = invoices_df[invoices_df["status"] == "paid"]["amount"].sum()
    total_card     = biz["amount"].sum() if not biz.empty else 0
    total_cash     = receipts_df["amount"].dropna().sum() if not receipts_df.empty else 0
    credits        = abs(statement_df[statement_df["type"]=="credit"]["amount"].sum()) if not statement_df.empty else 0
    total_expenses = total_card + total_cash - credits

    return {
        "revenue": {
            "total_invoiced": round(invoices_df["amount"].sum(), 2),
            "total_paid":     round(total_paid, 2),
            "total_unpaid":   round(invoices_df[invoices_df["status"]=="unpaid"]["amount"].sum(), 2),
        },
        "expenses": {
            "total_card":         round(total_card, 2),
            "total_cash":         round(total_cash, 2),
            "total_expenses":     round(total_expenses, 2),
            "personal_excluded":  round(statement_df[statement_df["category"]=="personal"]["amount"].sum(), 2) if not statement_df.empty else 0,
            "credits_received":   round(credits, 2),
            "duplicates_found":   int(statement_df["is_duplicate"].sum()) if not statement_df.empty else 0,
        },
        "net":         round(total_paid - total_expenses, 2),
        "by_category": biz.groupby("category")["amount"].sum().round(2).to_dict() if not biz.empty else {},
        "by_client":   invoices_df.groupby("client")["amount"].sum().round(2).to_dict(),
    }

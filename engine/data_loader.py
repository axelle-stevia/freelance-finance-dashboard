"""
data_loader.py
--------------
Charge et nettoie toutes les sources de données d'un client.
Parse directement depuis les fichiers sources — pas de CSV intermédiaires.

Classification en cascade :
  Étape 1 → personal    : mots-clés du client (client_config.json)
  Étape 2 → regex       : mots-clés business (config/categories.json)
  Étape 3 → LLM local   : Mistral via Ollama — pour les cas ambigus
  Étape 4 → "other"     : fallback si Ollama non disponible

Pourquoi conserver le regex ?
  Rapide, 0 dépendance, couvre ~90% des cas.
  Predictable — toujours le même résultat pour la même entrée.

Pourquoi ajouter le LLM ?
  Les cas que le regex ne couvre pas ("Istanbul Village", "Yango")
  sont gérés automatiquement sans modifier categories.json.
  Testable indépendamment via llm_classifier.py.
"""

import re
import json
import pandas as pd
from pathlib import Path
from dateutil import parser as dateparser


# ── Config ────────────────────────────────────────────────────────
def load_categories(config_path="config/categories.json") -> dict:
    """Charge les catégories depuis le fichier de config."""
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("categories", data.get("universal_categories", {}))

def load_client_config(client_folder: str) -> dict:
    path = Path(client_folder) / "client_config.json"
    if not path.exists():
        return {"client_name": "Unknown", "currency": "CAD",
                "known_personal_expenses": [], "known_clients": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Classification cascade ────────────────────────────────────────
def categorize(
    description: str,
    categories: dict,
    personal_keywords: list = None,
    use_llm: bool = True,
) -> str:
    """
    Cascade de classification :

    1. Personnel (client_config)  → priorité absolue, spécifique au client
    2. Regex (categories.json)    → rapide, couvre les cas évidents
    3. LLM local Mistral          → pour les cas ambigus non couverts
    4. Fallback "other"           → si Ollama non disponible

    use_llm=False pour désactiver le LLM (tests, Ollama non installé).
    """
    desc_upper = description.upper()

    # Étape 1 : personnel
    if personal_keywords:
        for kw in personal_keywords:
            if re.search(kw.upper(), desc_upper):
                return "personal"

# Étape 2 : regex
    for cat_name, cat_data in categories.items():
        # Compatible liste simple ["ADOBE"] ou dict {"keywords": ["ADOBE"]}
        if isinstance(cat_data, list):
            keywords = cat_data
        elif isinstance(cat_data, dict):
            keywords = cat_data.get("keywords", [])
        else:
            continue
        for kw in keywords:
            if re.search(kw, desc_upper):
                return cat_name

    # Étape 3 : LLM (seulement si regex a échoué)
    if use_llm:
        try:
            from engine.llm_classifier import classify_with_llm, is_ollama_available
            if is_ollama_available():
                result = classify_with_llm(description)
                if result:
                    return result
        except Exception:
            pass

    # Étape 4 : fallback
    return "other"


# ── Utilitaires ───────────────────────────────────────────────────
def normalize_date(raw) -> str | None:
    if pd.isna(raw) or str(raw).strip() == "":
        return None
    try:
        return dateparser.parse(str(raw).replace(" - ", " ").strip()).strftime("%Y-%m-%d")
    except Exception:
        return None


# ── Factures ──────────────────────────────────────────────────────
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


# ── Relevé bancaire ───────────────────────────────────────────────
def load_statement(
    shoebox_path: str,
    client_folder: str = None,
    config_path: str = "config/categories.json",
) -> pd.DataFrame:
    categories    = load_categories(config_path)
    personal_kwds = []
    if client_folder:
        cfg = load_client_config(client_folder)
        personal_kwds = cfg.get("known_personal_expenses", [])

    empty = pd.DataFrame(columns=[
        "trans_id","date","description","amount",
        "category","type","is_duplicate","refund_for"
    ])

    pdf_path = Path(shoebox_path) / "Visa_Statement_Q12025.pdf"
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
                            full_date = dateparser.parse(
                                f"{date_str} {year}"
                            ).strftime("%Y-%m-%d")
                        except Exception:
                            full_date = date_str
                        rows.append({
                            "trans_id": tid, "date": full_date,
                            "description": desc.strip(),
                            "amount": float(amt.replace("$","").replace(",",""))
                        })

        if not rows:
            return empty

        df = pd.DataFrame(rows)

    except Exception:
        return empty

    df["amount"]   = pd.to_numeric(df["amount"], errors="coerce")
    df["type"]     = df["amount"].apply(lambda x: "credit" if x < 0 else "debit")
    df["category"] = df["description"].apply(
        lambda d: categorize(d, categories, personal_kwds)
    )
    df["is_duplicate"] = df.duplicated(
        subset=["date","description","amount"], keep="first"
    )
    df = _reconcile_refunds(df)
    return df


# ── Reçus (EasyOCR → Tesseract → vide) ───────────────────────────
def load_receipts(shoebox_path: str) -> pd.DataFrame:
    receipts_dir = Path(shoebox_path) / "receipts"
    if not receipts_dir.exists():
        return pd.DataFrame()

    image_files = [
        f for f in receipts_dir.iterdir()
        if f.suffix.lower() in {".jpg",".jpeg",".png",".webp"}
    ]
    if not image_files:
        return pd.DataFrame()

    # Choisir le moteur OCR disponible
    ocr_engine = None
    try:
        import easyocr
        _reader   = easyocr.Reader(["fr","en"], gpu=False, verbose=False)
        ocr_engine = "easyocr"
    except ImportError:
        try:
            import pytesseract
            from PIL import Image
            pytesseract.get_tesseract_version()
            ocr_engine = "tesseract"
        except Exception:
            print("  ⚠️  EasyOCR et Tesseract non disponibles")
            print("     Installe EasyOCR : pip install easyocr")
            return pd.DataFrame(columns=[
                "filename","merchant","date","amount","payment_method","category"
            ])

    rows = []
    for img_path in sorted(image_files):
        try:
            if ocr_engine == "easyocr":
                results = _reader.readtext(str(img_path))
                text    = "\n".join([r[1] for r in results])
            else:
                from PIL import Image
                text = pytesseract.image_to_string(
                    Image.open(img_path), lang="fra+eng"
                )

            # ── Montant, date, marchand ──────────────────────────
            import re as _re

            text_lines = text.split("\n")

            # Montant : chercher la ligne contenant TOTAL ou TOIAL
            amount = None
            for i, tl in enumerate(text_lines):
                tl_up = tl.upper()
                if ("TOTAL" in tl_up or "TOIAL" in tl_up) and "SOUS" not in tl_up:
                    # Chercher sur cette ligne ET la suivante
                    search_lines = [tl]
                    if i + 1 < len(text_lines):
                        search_lines.append(text_lines[i + 1])
                    for sl in search_lines:
                        sl_clean = sl.replace("O","0").replace("o","0").replace("**","").replace("$","")
                        nums = _re.findall("[0-9]+[ ]*[.,][ ]*[0-9]{2}", sl_clean)
                        if nums:
                            try:
                                amount = float(nums[-1].replace(" ","").replace(",","."))
                                break
                            except Exception:
                                pass
                    if amount:
                        break
            # Date : forcer le format DD/MM/YYYY pour éviter l'inversion
            date = None
            found_date = _re.search("[0-9]{2}/[0-9]{2}/[0-9]{4}", text)
            if found_date:
                parts = found_date.group().split("/")
                try:
                    # parts[0]=jour, parts[1]=mois, parts[2]=annee
                    date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    pass
            if not date:
                found_ymd = _re.search("[0-9]{4}-[0-9]{2}-[0-9]{2}", text)
                if found_ymd:
                    date = found_ymd.group()

            # Marchand : premiers mots non-vides de la première ligne
            non_empty = [l.strip() for l in text_lines if l.strip()]
            # Joindre les 3 premières lignes pour reconstruire le nom complet
            raw_name = " ".join(non_empty[:3]).replace("**","").replace("*","")
            merchant = "".join(c for c in raw_name if c.isalnum() or c == " ").strip()
            # Prendre seulement les 4 premiers mots
            merchant = " ".join(merchant.split()[:4])

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
                "category":   "office_supplies",
                "ocr_engine": ocr_engine,
            })
        except Exception as e:
            print(f"  ⚠️  {img_path.name} — {e}")

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Notes ─────────────────────────────────────────────────────────
def load_notes(shoebox_path: str) -> dict:
    notes_path = Path(shoebox_path) / "notes.txt"
    if not notes_path.exists():
        return {"todos":[],"opportunities":[],"reminders":[]}

    text = notes_path.read_text(encoding="utf-8")
    todos, opps, reminders = [], [], []
    opp_kws = ["might need","could be","upsell","follow up","new signage","motion graphic"]
    rem_kws = ["renew","deadline","before","reminder","qualify","deduction"]

    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("=="):
            continue
        if line.startswith("[todo]"):
            todos.append(line.replace("[todo]","").strip())
        elif any(s in line.lower() for s in opp_kws):
            opps.append(line.lstrip("-–•• ").strip())
        elif any(s in line.lower() for s in rem_kws):
            reminders.append(line.lstrip("-–•• ").strip())

    return {"todos":todos,"opportunities":opps,"reminders":reminders}


# ── Réconciliation remboursements ─────────────────────────────────
def _reconcile_refunds(df: pd.DataFrame) -> pd.DataFrame:
    df["refund_for"] = None
    for idx, credit in df[df["type"]=="credit"].iterrows():
        kw = credit["description"].split()[0]
        matches = df[
            (df["type"]=="debit") &
            (df["description"].str.startswith(kw)) &
            (df["date"] < credit["date"])
        ]
        if not matches.empty:
            df.at[idx,"refund_for"] = df.at[matches.index[-1],"trans_id"]
    return df


# ── Résumé ────────────────────────────────────────────────────────
def build_summary(invoices_df, statement_df, receipts_df) -> dict:
    biz = statement_df[
        ~statement_df["is_duplicate"] &
        (statement_df["category"] != "personal") &
        (statement_df["type"] == "debit")
    ] if not statement_df.empty else pd.DataFrame(columns=["amount","category"])

    total_paid     = invoices_df[invoices_df["status"]=="paid"]["amount"].sum()
    total_card     = biz["amount"].sum() if not biz.empty else 0
    total_cash     = receipts_df["amount"].dropna().sum() if not receipts_df.empty else 0
    credits        = abs(statement_df[statement_df["type"]=="credit"]["amount"].sum()) \
                     if not statement_df.empty else 0
    total_expenses = total_card + total_cash - credits

    return {
        "revenue": {
            "total_invoiced": round(invoices_df["amount"].sum(), 2),
            "total_paid":     round(total_paid, 2),
            "total_unpaid":   round(
                invoices_df[invoices_df["status"]=="unpaid"]["amount"].sum(), 2
            ),
        },
        "expenses": {
            "total_card":        round(total_card, 2),
            "total_cash":        round(total_cash, 2),
            "total_expenses":    round(total_expenses, 2),
            "personal_excluded": round(
                statement_df[statement_df["category"]=="personal"]["amount"].sum(), 2
            ) if not statement_df.empty else 0,
            "credits_received":  round(credits, 2),
            "duplicates_found":  int(statement_df["is_duplicate"].sum())
                                 if not statement_df.empty else 0,
        },
        "net":         round(total_paid - total_expenses, 2),
        "by_category": biz.groupby("category")["amount"].sum().round(2).to_dict()
                       if not biz.empty else {},
        "by_client":   invoices_df.groupby("client")["amount"].sum().round(2).to_dict(),
    }
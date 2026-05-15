"""
parse_receipts.py
-----------------
Lit des photos de reçus et en extrait les informations clés.

Technologie : OCR (Optical Character Recognition)
  pytesseract = un pont Python vers Tesseract, le moteur OCR open-source de Google.
  L'OCR convertit une IMAGE en TEXTE. C'est imparfait — la qualité dépend
  de la netteté de la photo, de l'éclairage, de la police de caractères.

Ce qu'on extrait de chaque reçu :
  - Nom du marchand
  - Date
  - Montant total
  - Méthode de paiement (si lisible)
"""

import re
import pytesseract
from PIL import Image
from pathlib import Path
from dateutil import parser as dateparser
import pandas as pd


def extract_text_from_image(image_path: str) -> str:
    """
    Utilise l'OCR pour convertir une image en texte brut.

    PIL (Pillow) = bibliothèque Python pour manipuler des images.
    tesseract = le moteur OCR (lit les pixels, reconnaît les lettres).

    On configure le language sur "fra+eng" pour gérer
    les reçus francophones (comme Bureau en Gros).
    """
    img = Image.open(image_path)
    # lang="fra+eng" = essayer le français ET l'anglais
    text = pytesseract.image_to_string(img, lang="fra+eng")
    return text


def parse_amount(text: str) -> float | None:
    """
    Cherche le montant TOTAL dans le texte d'un reçu.

    Stratégie : chercher la ligne qui contient "TOTAL" ou "Total"
    puis capturer le nombre qui suit.

    Exemples :
      "TOTAL    $40.80"  → 40.80
      "Total: 14.94"    → 14.94
      "**TOTAL: $12.00**" → 12.00
    """
    # On cherche "TOTAL" (en ignorant la casse) suivi d'un montant
    matches = re.findall(
        r"TOTAL[^$\d]*\$?([\d,]+\.\d{2})",
        text,
        re.IGNORECASE
    )
    if matches:
        # Prendre le DERNIER montant (le vrai total, pas les sous-totaux)
        return float(matches[-1].replace(",", ""))
    return None


def parse_date(text: str) -> str | None:
    """
    Cherche une date dans le texte OCR.

    On cherche les patterns communs : DD/MM/YYYY, MM/DD/YYYY, etc.
    dateutil.parser essaie ensuite d'interpréter intelligemment.
    """
    # Chercher les patterns de date courants
    date_patterns = [
        r"\d{2}/\d{2}/\d{4}",   # 22/01/2025
        r"\d{4}-\d{2}-\d{2}",   # 2025-01-22
        r"\w+ \d{1,2},? \d{4}", # January 22, 2025
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return dateparser.parse(match.group()).strftime("%Y-%m-%d")
            except Exception:
                continue
    return None


def parse_merchant(text: str) -> str:
    """
    Extrait le nom du marchand — généralement la première ligne non-vide du reçu.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        # Nettoyer les caractères parasites de l'OCR
        merchant = re.sub(r"[^a-zA-Z0-9\s\-àâéèêëîïôùûü'&]", "", lines[0])
        return merchant.strip()
    return "Unknown"


def parse_receipt(image_path: str) -> dict:
    """
    Parse un seul reçu et retourne un dictionnaire avec ses données.

    C'est la fonction principale — elle orchestre les autres.
    """
    path = Path(image_path)
    print(f"  📄 Lecture : {path.name}")

    raw_text = extract_text_from_image(str(path))

    return {
        "filename": path.name,
        "merchant": parse_merchant(raw_text),
        "date": parse_date(raw_text),
        "amount": parse_amount(raw_text),
        "payment_method": "cash" if re.search(r"COMPTANT|CASH", raw_text, re.I) else
                          "e-transfer" if re.search(r"E-TRANSFER|VIREMENT", raw_text, re.I) else
                          "card",
        "raw_ocr": raw_text,  # On garde le texte brut pour le débogage
        "source": "receipt",
        "category": "office_supplies",  # Valeur par défaut — à améliorer
    }


def load_receipts(receipts_folder: str) -> pd.DataFrame:
    """
    Charge tous les reçus d'un dossier.

    Paramètre :
      receipts_folder → chemin vers le dossier contenant les images
                        (ex: "clients/shannon_q1_2025/shoebox/receipts/")

    Retourne :
      Un DataFrame avec une ligne par reçu.
    """
    folder = Path(receipts_folder)
    if not folder.exists():
        raise FileNotFoundError(f"Dossier introuvable : {receipts_folder}")

    # Extensions d'images supportées
    image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    image_files = [f for f in folder.iterdir() if f.suffix.lower() in image_extensions]

    if not image_files:
        print(f"⚠️  Aucune image trouvée dans {receipts_folder}")
        return pd.DataFrame()

    print(f"📸 {len(image_files)} reçu(s) trouvé(s) :")
    records = [parse_receipt(str(img)) for img in image_files]

    df = pd.DataFrame(records)
    print(f"✅ Reçus parsés : {len(df)} entrées")

    return df

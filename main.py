"""
main.py
-------
Point d'entrée du programme.

C'est ici qu'on lance tout. En Python, la convention est d'avoir un main.py
à la racine du projet qui est le "bouton START" de l'application.

Usage :
  python main.py

Pour un autre client, il suffit de changer les chemins dans la section
CLIENT CONFIGURATION ci-dessous.
"""

from engine.analyze import run_analysis

# ══════════════════════════════════════════════════════
#  CLIENT CONFIGURATION
#  → Modifier ces chemins pour chaque nouveau client
# ══════════════════════════════════════════════════════
CLIENT_FOLDER = "clients/shannon_q1_2025"

INVOICES_PATH = f"{CLIENT_FOLDER}/shoebox/invoices.xlsx"
STATEMENT_PATH = f"{CLIENT_FOLDER}/shoebox/Visa_Statement_Q12025.pdf"
RECEIPTS_FOLDER = f"{CLIENT_FOLDER}/shoebox/receipts/"
OUTPUT_FOLDER = f"{CLIENT_FOLDER}/output/"

CONFIG_PATH = "config/categories.json"
# ══════════════════════════════════════════════════════


if __name__ == "__main__":
    # "__main__" = ce bloc s'exécute seulement si tu lances ce fichier directement.
    # Si un autre fichier importait main.py, ce bloc serait ignoré.
    # C'est une convention Python importante !

    summary = run_analysis(
        invoices_path=INVOICES_PATH,
        statement_path=STATEMENT_PATH,
        receipts_folder=RECEIPTS_FOLDER,
        output_folder=OUTPUT_FOLDER,
        config_path=CONFIG_PATH,
    )

    # Afficher les alertes importantes
    if summary.get("alerts"):
        print("\n🚨 ALERTES :")
        for alert in summary["alerts"]:
            icon = "🔴" if alert["severity"] == "high" else "🟡" if alert["severity"] == "medium" else "🔵"
            print(f"  {icon} {alert['message']}")

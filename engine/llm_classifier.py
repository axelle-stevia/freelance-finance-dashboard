"""
llm_classifier.py
-----------------
Classification de transactions par LLM local (Ollama).

Pourquoi un LLM pour classifier ?
  Les règles regex dans categories.json sont bonnes pour les cas évidents :
  "ADOBE" → software, "NETFLIX" → personal.

  Mais certaines descriptions résistent aux règles :
  - "SQ *CAFE MYRIADE"     → SQ = Square (terminal de paiement) + café = meals
  - "LE PETIT DEP REST"    → REST = restaurant, pas évident
  - "VRBO COWORKING MTL"   → déjà géré, mais que faire pour "SPACES MTL" ?

  Un LLM comprend le CONTEXTE et la LANGUE NATURELLE.
  Il peut inférer qu'un "café" est un repas, qu'un "DEP" est une dépanneur, etc.

Architecture :
  Ce module est OPTIONNEL. Si Ollama n'est pas installé ou pas lancé,
  le programme continue sans lui (fallback vers "other").
  C'est ce qu'on appelle un "graceful degradation" — le programme ne plante pas,
  il fait de son mieux avec ce qu'il a.
"""

import json
import requests
from typing import Optional


OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"

VALID_CATEGORIES = {
    "software", "coworking", "transport",
    "meals_entertainment", "office_supplies", "personal", "other"
}


def is_ollama_available() -> bool:
    """
    Vérifie si Ollama est installé et en cours d'exécution.

    On envoie une requête simple à l'API locale.
    Si on reçoit une réponse → Ollama est là.
    Si on reçoit une erreur de connexion → Ollama n'est pas lancé.

    Pourquoi cette vérification ?
      Sans elle, le programme planterait avec une erreur cryptique si Ollama
      n'est pas installé. On préfère "échouer proprement" avec un message clair.
    """
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        return resp.status_code == 200
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False


def build_prompt(description: str, valid_categories: set) -> str:
    """
    Construit le prompt envoyé au LLM.

    Un "prompt" = l'instruction qu'on donne au LLM.
    La qualité du prompt détermine la qualité de la réponse.

    Bonnes pratiques pour un prompt de classification :
    1. Donner le contexte (carte de crédit d'une freelance)
    2. Lister les catégories possibles EXACTEMENT comme on veut qu'elles soient retournées
    3. Donner des exemples concrets (few-shot prompting)
    4. Être TRÈS explicite sur le format de sortie attendu
    5. Ajouter "rien d'autre" pour éviter les explications inutiles
    """
    cats = ", ".join(sorted(valid_categories))

    return f"""Tu es un assistant de comptabilité pour une freelance canadienne.
Classifie cette transaction de carte de crédit en UNE SEULE catégorie.

Catégories disponibles : {cats}

Définitions :
- software     : abonnements logiciels (Adobe, Canva, Google, Shopify, hébergement web)
- coworking    : espaces de travail partagés
- transport    : taxi, stationnement, transport en commun
- meals_entertainment : restaurants, cafés, repas d'affaires
- office_supplies : fournitures de bureau, impression, papeterie
- personal     : dépenses personnelles non-professionnelles (Netflix, animaux de compagnie)
- other        : ne correspond à aucune catégorie ci-dessus

Exemples :
"ADOBE *CREATIVE CL" → software
"SQ *CAFE MYRIADE" → meals_entertainment
"VRBO COWORKING MTL" → coworking
"WAYMO BUSINESS" → transport
"PETCO #4521" → personal
"AMAZON.CA *OFFICE" → office_supplies

Transaction à classifier : "{description}"

Réponds avec le nom de la catégorie SEULEMENT. Pas d'explication, pas de ponctuation."""


def classify_with_llm(
    description: str,
    model: str = OLLAMA_MODEL,
    timeout: int = 10,
) -> Optional[str]:
    """
    Envoie une description au LLM local et retourne la catégorie.

    Paramètres :
      description → le texte de la transaction (ex: "SQ *CAFE MYRIADE")
      model       → le modèle Ollama à utiliser (défaut: mistral)
      timeout     → secondes d'attente max (évite de bloquer indéfiniment)

    Retourne :
      La catégorie en string, ou None si quelque chose a échoué.

    Note sur "stream: False" :
      Ollama peut envoyer la réponse mot par mot (streaming) ou d'un coup.
      Pour la classification, on veut la réponse complète d'un coup → stream: False
    """
    prompt = build_prompt(description, VALID_CATEGORIES)

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0,    # 0 = réponses déterministes (pas aléatoires)
                    "num_predict": 20,   # max 20 tokens → on veut juste un mot
                }
            },
            timeout=timeout
        )
        response.raise_for_status()

        raw = response.json().get("response", "").strip().lower()

        # Nettoyer la réponse : enlever ponctuation, espaces
        clean = raw.strip(".,!?\"'").replace(" ", "_")

        # Vérifier que la réponse est une catégorie valide
        if clean in VALID_CATEGORIES:
            return clean

        # Parfois le LLM répond "meals entertainment" au lieu de "meals_entertainment"
        clean_spaced = raw.replace(" ", "_")
        if clean_spaced in VALID_CATEGORIES:
            return clean_spaced

        # Si la réponse n'est pas reconnue, on log et on retourne None
        print(f"  ⚠️  LLM a retourné une catégorie inconnue : '{raw}' pour '{description}'")
        return None

    except requests.exceptions.Timeout:
        print(f"  ⏱️  Ollama timeout pour : '{description}'")
        return None
    except requests.exceptions.ConnectionError:
        return None
    except Exception as e:
        print(f"  ❌ Erreur LLM inattendue : {e}")
        return None


def classify_batch(
    descriptions: list[str],
    verbose: bool = True,
) -> dict[str, str]:
    """
    Classifie une liste de descriptions d'un coup.

    Pourquoi un batch ?
      Au lieu d'appeler classify_with_llm() en boucle depuis l'extérieur,
      cette fonction gère :
      1. La vérification unique qu'Ollama est disponible (évite N vérifications)
      2. L'affichage de la progression
      3. Un fallback propre si Ollama n'est pas là

    Retourne un dictionnaire : {description: catégorie}
    """
    if not descriptions:
        return {}

    if not is_ollama_available():
        if verbose:
            print("  ℹ️  Ollama non disponible — classification LLM ignorée")
            print("     Pour l'activer : lancez 'ollama serve' dans un terminal")
        return {desc: "other" for desc in descriptions}

    if verbose:
        print(f"  🤖 Ollama disponible — classification de {len(descriptions)} transactions...")

    results = {}
    for i, desc in enumerate(descriptions, 1):
        category = classify_with_llm(desc)
        results[desc] = category or "other"

        if verbose and i % 5 == 0:
            print(f"     {i}/{len(descriptions)} traitées...")

    return results

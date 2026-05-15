# Notes de conception — Freelance Finance Dashboard

---

## Ce qu'on a choisi et pourquoi

**Streamlit plutôt que HTML/JavaScript**
Streamlit permet de construire une interface web en Python pur, sans écrire de HTML ou CSS. Pour un projet de 48h, ça permet de se concentrer sur la logique des données plutôt que sur le frontend. L'alternative aurait été plus flexible mais aurait pris trois fois plus de temps.

**Pas de fichiers CSV intermédiaires**
Les données sont parsées directement en mémoire à chaque lancement. Streamlit mémorise les résultats avec `@st.cache_data` — pas besoin d'écrire des fichiers temporaires sur le disque. On avait d'abord créé des CSV intermédiaires, puis on les a supprimés quand on a réalisé qu'ils n'étaient pas nécessaires.

**Regex d'abord, LLM ensuite**
La classification des transactions suit une cascade : règles regex → LLM local (Ollama + Mistral) → "other". Les regex couvrent environ 90% des cas rapidement et sans dépendance externe. Le LLM prend le relais pour les marchands inconnus comme "Istanbul Village" ou "Yango". Si Ollama n'est pas installé, le programme continue normalement sans planter.

**Configuration séparée par client**
`config/categories.json` contient les règles de catégorisation partagées entre tous les clients. `clients/<nom>/client_config.json` contient ce qui est spécifique à chaque client — nom, devise, dépenses personnelles à exclure. Cette séparation permet d'ajouter un nouveau client sans modifier une seule ligne de code.

**EasyOCR plutôt que Tesseract**
EasyOCR s'installe avec une seule commande pip, sans logiciel externe. Tesseract nécessite de télécharger et installer un exécutable séparément, ce qui complique l'installation sur Windows. EasyOCR gère aussi mieux les photos imparfaites comme des reçus froissés ou mal éclairés.

---

## Ce qu'on n'a pas pu faire et pourquoi

**Lire les reçus manuscrits**
EasyOCR est entraîné principalement sur du texte imprimé. L'écriture à la main sur papier ligné produit du bruit illisible. Les modèles spécialisés pour l'écriture manuscrite existent en open-source (TrOCR de Microsoft) mais sont lourds et lents sur CPU. On a préféré afficher un champ de saisie manuelle dans le dashboard plutôt que d'ajouter une dépendance lourde pour un seul reçu.

**Parser le relevé PDF de façon robuste pour toutes les banques**
Le parser PDF fonctionne pour le format fourni (National Credit Union). Un vrai client pourrait avoir un relevé Desjardins, TD, ou BMO avec une mise en page complètement différente. Construire un parser robuste multi-banques aurait nécessité des semaines de tests. Avec accès à une API comme Google Document AI, ce problème disparaît.

**Sauvegarder les saisies manuelles entre les sessions**
Les montants et noms de marchands entrés manuellement dans le dashboard disparaissent quand on ferme et relance l'application. Streamlit ne sauvegarde pas l'état par défaut. Une base de données SQLite locale aurait résolu ça, mais c'était hors scope pour ce projet.

**Classification parfaite sans LLM**
Les règles regex ne peuvent pas connaître tous les marchands à l'avance. "Le Petit Dép" ou "Café Myriade" nécessitent soit d'être ajoutés manuellement dans `categories.json`, soit d'utiliser le LLM. C'est le compromis fondamental entre une approche déterministe et une approche intelligente.

---

## Ce que j'aurais fait avec plus de temps

**LLM pour la classification — intégration complète**
Le code pour Ollama + Mistral est en place dans `engine/llm_classifier.py` et fonctionne quand Ollama est installé. Mais je n'ai pas eu le temps de le valider suffisamment sur des données réelles. Avec plus de temps, j'aurais testé le LLM sur l'ensemble des transactions, comparé ses résultats avec les regex, et ajusté le prompt. L'objectif était d'éliminer complètement le besoin de maintenir `categories.json` à la main — le LLM classifie "Istanbul Village" ou "Yango" sans qu'on lui dise quoi que ce soit.

**Boucle d'apprentissage**
Quand Shannon corrige une catégorie dans le dashboard, cette correction devrait alimenter automatiquement `categories.json` pour les prochains lancements. L'outil apprendrait de chaque utilisation au lieu de rester statique.
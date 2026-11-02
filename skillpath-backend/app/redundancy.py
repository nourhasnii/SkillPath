"""
Détection des compétences redondantes dans l'ontologie SkillPath.

Ce module analyse les compétences réellement présentes dans le graphe
(``CompetenceTechnique`` et ``CompetenceTransverse``, donc les individus
``onto:Competence`` via le client SPARQL) et repère les couples dont les
noms se ressemblent fortement au point d'être probablement redondants.

L'analyse est volontairement purement déterministe (aucune donnée inventée) :

1. normalisation du nom (identifiant ``comp_*`` ou libellé ``aNom``) :
   décomposition des accents, séparation camelCase, casse, ponctuation,
   suppression des mots vides et du préfixe de type, singularisation légère ;
2. indice de similarité combinant un coefficient de Dice sur les tokens
   normalisés et un ratio de caractères (``difflib``) ;
3. comparaison de toutes les paires (``combinations``) et conservation des
   couples dont le score atteint un seuil configurable.

Le module ne fusionne ni ne supprime jamais de compétence : il produit
uniquement des suggestions d'audit soumises à l'administrateur.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from itertools import combinations

from . import sparql_client as sp

# Seuil par défaut : au-delà de 75 % de similarité, le couple est jugé suspect.
DEFAULT_THRESHOLD = 0.75

# Compétences analysées (les deux sous-classes métier de onto:Competence).
COMPETENCY_CLASSES = ("CompetenceTechnique", "CompetenceTransverse")

# Pondération des deux mesures : la proximité de tokens prime (noms de métier),
# le ratio de caractères capte les fautes de frappe et les variantes.
TOKEN_WEIGHT = 0.6
CHARACTER_WEIGHT = 0.4

_STOPWORDS = {
    "de", "du", "des", "la", "le", "les", "un", "une", "et", "en", "a", "au",
    "aux", "the", "of", "and", "to", "for", "with",
}
_PREFIX_TOKENS = {"comp", "competence", "competences", "skill", "skills"}
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def _singularize(token: str) -> str:
    """Singularisation prudente : « skills » -> « skill », mais « analysis » intact."""
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def normalize_name(value: str | None) -> str:
    """Retourne la forme normalisée comparable d'un nom de compétence."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = _CAMEL_BOUNDARY.sub(" ", text)
    text = _ACRONYM_BOUNDARY.sub(" ", text)
    text = _NON_ALPHANUMERIC.sub(" ", text.lower())
    tokens = [
        _singularize(token)
        for token in text.split()
        if token and token not in _STOPWORDS and token not in _PREFIX_TOKENS
    ]
    return " ".join(tokens)


def _tokens(normalized: str) -> set[str]:
    return set(normalized.split())


def _breakdown(normalized_a: str, normalized_b: str) -> tuple[float, float]:
    """Retourne (coefficient de Dice sur les tokens, ratio de caractères)."""
    tokens_a = _tokens(normalized_a)
    tokens_b = _tokens(normalized_b)
    union = tokens_a | tokens_b
    dice = (2 * len(tokens_a & tokens_b) / (len(tokens_a) + len(tokens_b))) if union else 0.0
    if normalized_a == normalized_b:
        character_ratio = 1.0
    else:
        character_ratio = SequenceMatcher(None, normalized_a, normalized_b).ratio()
    return dice, character_ratio


def similarity(name_a: str | None, name_b: str | None) -> float:
    """Score de similarité dans [0, 1] entre deux noms de compétence."""
    normalized_a = normalize_name(name_a)
    normalized_b = normalize_name(name_b)
    if not normalized_a or not normalized_b:
        return 0.0
    dice, character_ratio = _breakdown(normalized_a, normalized_b)
    return round(TOKEN_WEIGHT * dice + CHARACTER_WEIGHT * character_ratio, 4)


def _explain(
    normalized_a: str,
    normalized_b: str,
    shared_tokens: list[str],
    dice: float,
    character_ratio: float,
    score: float,
) -> str:
    if normalized_a == normalized_b:
        return (
            f"Noms normalisés identiques (« {normalized_a} ») : "
            f"doublon très probable (score {score * 100:.0f} %)."
        )
    if shared_tokens:
        token_text = (
            f"tokens communs : {', '.join(shared_tokens)} "
            f"(Dice {dice * 100:.0f} %)"
        )
    else:
        token_text = f"aucun token commun (Dice {dice * 100:.0f} %)"
    return (
        f"Noms normalisés « {normalized_a} » et « {normalized_b} » ; "
        f"{token_text}, similarité de caractères {character_ratio * 100:.0f} % ; "
        f"score global {score * 100:.0f} %."
    )


def _competency_class(item: dict) -> str:
    class_name = item.get("class")
    if isinstance(class_name, str) and class_name:
        return class_name
    return "Competence"


def detect_redundant_competencies(threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Analyse les compétences de l'ontologie et retourne les couples suspects.

    :param threshold: seuil de similarité dans [0, 1] ; un couple est retenu
        lorsque son score est supérieur ou égal à ce seuil.
    """
    threshold = max(0.0, min(1.0, float(threshold)))
    candidates = [
        {
            "id": item["id"],
            "name": item.get("label") or item["id"],
            "class": _competency_class(item),
        }
        for item in sp.list_individuals("Competence", None, True)
    ]

    pairs: list[dict] = []
    for left, right in combinations(candidates, 2):
        score = similarity(left["name"], right["name"])
        if score < threshold:
            continue
        normalized_a = normalize_name(left["name"])
        normalized_b = normalize_name(right["name"])
        dice, character_ratio = _breakdown(normalized_a, normalized_b)
        shared = sorted(_tokens(normalized_a) & _tokens(normalized_b))
        pairs.append({
            "id_a": left["id"],
            "name_a": left["name"],
            "class_a": left["class"],
            "id_b": right["id"],
            "name_b": right["name"],
            "class_b": right["class"],
            "score": score,
            "explanation": _explain(
                normalized_a, normalized_b, shared, dice, character_ratio, score
            ),
        })

    pairs.sort(key=lambda pair: (-pair["score"], pair["id_a"], pair["id_b"]))
    return {
        "threshold": threshold,
        "total_competencies": len(candidates),
        "pair_count": len(pairs),
        "pairs": pairs,
    }

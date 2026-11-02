"""
Module TALN (traitement automatique du langage naturel) de SkillPath.

Il traduit une question en langue naturelle (français ou anglais) en une
requête SPARQL ``SELECT`` exécutable sur l'ontologie SkillPath, **sans aucun
appel à une API de type LLM**. Le pipeline est entièrement local :

1. **Analyse linguistique** avec *spaCy* (``fr_core_news_sm`` si le modèle est
   installé, sinon ``en_core_web_sm``, sinon un pipeline vide ``spacy.blank``) :
   découpage en tokens et repérage des groupes nominaux.
2. **Schéma** chargé depuis Fuseki (voir ``ontology_schema``) : classes et
   hiérarchie, propriétés d'objet (domaine / co-domaine) et propriétés de
   données. Rien n'est codé en dur : les types et les relations sont déduits du
   schéma.
3. **Lexique** (``lexicon.json``, FR + EN) : libellés, synonymes et lemmes
   verbaux reliant le vocabulaire naturel aux classes et propriétés, plus les
   modificateurs (négation, comptage, comparaison, transitivité…).
4. **Pipeline de détection** : modificateurs -> classe visée -> relation et son
   sens -> entité d'ancrage. L'ancrage est **résolu avec *rapidfuzz* en le
   restreignant au type attendu par la relation**, ce qui évite les confusions
   du type « Python » (compétence ``comp_Python``) contre « Mooc Python »
   (formation ``form_MoocPython``).
5. **Patrons SPARQL SELECT** : la question brute n'est jamais concaténée ; seuls
   des IRI validés issus de la résolution d'entités sont injectés, et seules des
   lectures (``SELECT``) sont possibles.

Repli (fallback) en cascade, dans cet ordre :

* **Paraphrases** : si aucune règle ne s'applique, la question est comparée à des
  formulations d'exemple avec *sentence-transformers* (petit modèle multilingue
  exécuté localement). Si le modèle est indisponible, on continue avec les
  règles seules.
* **Entité seule** : si aucune relation n'est reconnue mais qu'une entité de
  l'ontologie est identifiée, on renvoie tout ce que l'on sait d'elle
  (``Closest match: everything known about <entity>``).
* **Rien reconnu** : aucune supposition ; on propose des questions d'exemple
  construites à partir du schéma.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import json

import spacy
from rapidfuzz import fuzz
from spacy.matcher import Matcher

from . import ontology_schema as schema_module
from . import sparql_client as sp
from .redundancy import normalize_name

try:  # dépendance lourde : importée à la demande, jamais bloquante
    from sentence_transformers import SentenceTransformer
except Exception:  # noqa: BLE001 - dégradation contrôlée
    SentenceTransformer = None  # type: ignore[assignment]

#: Petit modèle multilingue exécuté localement pour le repli par paraphrase.
PARAPHRASE_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

#: Similarité minimale (cosinus) pour accepter une paraphrase.
PARAPHRASE_THRESHOLD = 0.62

#: Seuil minimal (0-100) de similarité floue pour accepter une résolution.
MATCH_THRESHOLD = 70

_RESOURCE_ID_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

#: Intentions dédiées (prioritaires) : elles exploitent le profil connecté.
DEDICATED_INTENTS = (
    "competences_manquantes_metier",
    "metiers_eligibles_profil",
    "profils_eligibles_metier",
    "formations_combler_ecarts",
    "parcours_optimal",
    "competences_acquises_profil",
)

#: Intentions génériques « lisibles » exposées par ``GET /nlp/examples``.
GENERIC_INTENT_FAMILIES = (
    "list_<Classe>",
    "relation_<Propriété>",
    "relation_negated_<Propriété>",
    "count_<Classe|relation_Propriété>",
    "numeric_filter_<Classe>",
    "detail_<Classe>",
    "common_<Propriété>",
    "transitive_<Propriété>",
)

SUPPORTED_INTENTS = DEDICATED_INTENTS + GENERIC_INTENT_FAMILIES

# ---------------------------------------------------------------------------
# Contrôle d'accès par rôle
# ---------------------------------------------------------------------------
# Le rôle et l'identifiant de profil proviennent exclusivement du jeton
# d'authentification vérifié (``auth_store``) ; ils ne sont jamais lus dans le
# corps de la requête ni dans le texte de la question.

#: Rôles reconnus par l'application (identiques à ``auth_store``).
ROLE_STUDENT = "STUDENT"
ROLE_PROFESSIONAL = "PROFESSIONAL"
ROLE_ADMIN = "ADMIN"

#: Tous les rôles, et le rôle réservé à l'administration.
ALL_ROLES = (ROLE_STUDENT, ROLE_PROFESSIONAL, ROLE_ADMIN)
ADMIN_ONLY = (ROLE_ADMIN,)

#: Rôles autorisés par **type de question**.
QUESTION_TYPES: dict[str, tuple[str, ...]] = {
    # Catalogue : formations, modules, durées, prérequis, métiers, compétences.
    "catalogue": ALL_ROLES,
    # Questions sur le profil connecté (« mes compétences », « mon parcours »).
    "own_profile": ALL_ROLES,
    # Profils d'autres personnes (compétences, formations, éligibilité…).
    "other_profile": ADMIN_ONLY,
    # Qualité des données (modules orphelins, compétences non couvertes…).
    "data_quality": ADMIN_ONLY,
    # Statistiques globales (comptages).
    "statistics": ADMIN_ONLY,
}

#: Intentions dédiées portant sur le profil connecté.
OWN_PROFILE_INTENTS = frozenset({
    "metiers_eligibles_profil",
    "formations_combler_ecarts",
    "parcours_optimal",
    "competences_acquises_profil",
    "competences_manquantes_metier",
})

#: Intentions dédiées portant sur d'autres profils (réservé à l'administration).
OTHER_PROFILE_INTENTS = frozenset({"profils_eligibles_metier"})

#: Propriétés d'objet décrivant des personnes (profils) et non le catalogue.
PROFILE_PROPERTIES = frozenset({
    "aAcquis", "vise", "aSuivi", "suitParcours", "aPasseEvaluation",
})

#: Classes dont les questions portent sur des profils (réservé à l'administration).
PROFILE_CLASSES = frozenset({"ProfilUtilisateur"})

_PROPERTY_INTENT_PREFIXES = ("relation_negated_", "relation_", "common_", "transitive_")
_CLASS_INTENT_PREFIXES = ("count_list_", "list_", "detail_", "numeric_filter_")

#: Message renvoyé à un rôle non autorisé (aucun SPARQL, aucune donnée).
RESTRICTED_ROLE_MESSAGE = "This question is reserved for administrators."


def _intent_property(intent: str) -> str | None:
    """Propriété visée par une intention de relation (``relation_enseigne``…)."""
    for prefix in _PROPERTY_INTENT_PREFIXES:
        if intent.startswith(prefix):
            return intent[len(prefix):]
    return None


def _intent_target_class(intent: str) -> str | None:
    """Classe visée par une intention de liste / détail / comptage de liste."""
    for prefix in _CLASS_INTENT_PREFIXES:
        if intent.startswith(prefix):
            return intent[len(prefix):]
    return None


def question_type(intent: str, plan: dict | None = None) -> str:
    """Type de question d'une intention (catalogue, profil, statistiques…)."""
    if intent in OTHER_PROFILE_INTENTS:
        return "other_profile"
    if intent in OWN_PROFILE_INTENTS:
        return "own_profile"
    if intent.startswith("count_"):
        return "statistics"
    if plan and plan.get("orphan_property"):
        return "data_quality"
    if _intent_target_class(intent) in PROFILE_CLASSES:
        return "other_profile"
    if _intent_property(intent) in PROFILE_PROPERTIES:
        return "other_profile"
    return "catalogue"


def intent_allowed_roles(intent: str, plan: dict | None = None) -> tuple[str, ...]:
    """Rôles autorisés à poser la question correspondant à ``intent``."""
    return QUESTION_TYPES[question_type(intent, plan)]


def is_intent_allowed(intent: str, role: str, plan: dict | None = None) -> bool:
    """Vrai si ``role`` peut poser la question correspondant à ``intent``."""
    return role in intent_allowed_roles(intent, plan)


#: Questions d'exemple « socle » et leur type de question (contrôle d'accès).
_BASE_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("Liste les compétences.", "catalogue"),
    ("Quelles formations enseignent Python ?", "catalogue"),
    ("Quels modules enseignent Cloud ?", "catalogue"),
    ("Quelles compétences enseigne le module Python Base ?", "catalogue"),
    ("Quels prérequis possède la formation Data Eng ?", "catalogue"),
    ("Quelles formations ont Python comme prérequis ?", "catalogue"),
    ("Tous les prérequis de la formation Data Eng ?", "catalogue"),
    ("Quelles compétences sont communes aux formations Data Eng et Master Cloud ?", "catalogue"),
    ("Quelles formations contiennent le module Python Base ?", "catalogue"),
    ("Quels modules ne sont associés à aucune formation ?", "data_quality"),
    ("Quelles formations durent moins de 25 heures ?", "catalogue"),
    ("Combien de formations enseignent Python ?", "statistics"),
    ("Quels métiers requièrent la compétence SQL ?", "catalogue"),
    ("Détails de la formation Data Eng.", "catalogue"),
)

#: Propriété de données utilisée par défaut pour une classe donnée.
_DEFAULT_DATA_PROPERTY = {
    "Formation": "aDureeHeures",
    "Metier": "aNiveau",
}


# ---------------------------------------------------------------------------
# Normalisation de texte
# ---------------------------------------------------------------------------


def _strip_accents(value: str) -> str:
    """Supprime les accents pour comparer les libellés sans diacritiques."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char))


def _norm_text(value: str) -> str:
    """Forme normalisée comparable : minuscules, sans accents ni ponctuation."""
    return " ".join(_NON_ALNUM.sub(" ", _strip_accents(value).lower()).split())


def _phrase_in(haystack: str, phrase: str) -> bool:
    """Vrai si ``phrase`` apparaît comme une suite de mots complète."""
    if not phrase:
        return False
    return f" {phrase} " in f" {haystack} "


# ---------------------------------------------------------------------------
# Lexique (lexicon.json)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _lexicon() -> dict:
    """Charge le lexique FR/EN depuis ``lexicon.json`` (jamais bloquant)."""
    path = Path(__file__).with_name("lexicon.json")
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {"classes": {}, "properties": {}, "modifiers": {}, "dedicated": {}}


def _lexicon_forms(entry: dict, extra: bool = True) -> list[str]:
    """Concatène libellés FR/EN (et synonymes) d'une entrée de lexique."""
    forms: list[str] = []
    labels = entry.get("labels") or {}
    if isinstance(labels, dict):
        for values in labels.values():
            forms.extend(values or [])
    if extra:
        forms.extend(entry.get("synonyms") or [])
    return [form for form in forms if isinstance(form, str) and form.strip()]


@lru_cache(maxsize=1)
def _class_phrase_index() -> tuple[tuple[str, str], ...]:
    """Couples (phrase normalisée, classe), du plus long au plus court."""
    items: list[tuple[str, str]] = []
    for klass, entry in (_lexicon().get("classes") or {}).items():
        for form in _lexicon_forms(entry):
            items.append((_norm_text(form), klass))
    items.sort(key=lambda item: (-len(item[0]), item[0]))
    return tuple(dict.fromkeys(items))


@lru_cache(maxsize=1)
def _property_phrase_index() -> tuple[tuple[str, str, str], ...]:
    """Couples (phrase normalisée, propriété, type), du plus long au plus court."""
    items: list[tuple[str, str, str]] = []
    for prop, entry in (_lexicon().get("properties") or {}).items():
        kind = entry.get("kind") or ("data" if prop.startswith("a") else "object")
        for form in _lexicon_forms(entry):
            items.append((_norm_text(form), prop, kind))
        for lemma in (entry.get("verb_lemmas") or {}).values():
            for form in lemma or []:
                items.append((_norm_text(form), prop, kind))
    items = [item for item in items if item[0]]
    items.sort(key=lambda item: (-len(item[0]), item[1]))
    return tuple(dict.fromkeys(items))


@lru_cache(maxsize=1)
def _modifier_index() -> dict[str, tuple[str, ...]]:
    """Formes normalisées par modificateur (négation, comptage, …)."""
    index: dict[str, tuple[str, ...]] = {}
    for name, entry in (_lexicon().get("modifiers") or {}).items():
        forms = (entry or {}).get("fr", []) + (entry or {}).get("en", [])
        index[name] = tuple(f for f in (_norm_text(form) for form in forms) if f)
    return index


@lru_cache(maxsize=1)
def _dedicated_index() -> dict[str, tuple[str, ...]]:
    """Formulations d'exemple par intention dédiée."""
    index: dict[str, tuple[str, ...]] = {}
    for name, entry in (_lexicon().get("dedicated") or {}).items():
        forms = (entry or {}).get("fr", []) + (entry or {}).get("en", [])
        index[name] = tuple(f for f in (_norm_text(form) for form in forms) if f)
    return index


def _class_label(name: str) -> str:
    """Premier libellé humain d'une classe (FR si possible, sinon la classe)."""
    entry = ((_lexicon().get("classes") or {}).get(name) or {})
    labels = entry.get("labels") or {}
    for language in ("fr", "en"):
        values = labels.get(language) or []
        if values:
            return values[0]
    return _schema().classes[name].label if _schema().has_class(name) else name


def _property_labels(name: str) -> list[str]:
    entry = ((_lexicon().get("properties") or {}).get(name) or {})
    return [form for form in _lexicon_forms(entry, extra=False) if form]


def _cue_tokens() -> frozenset[str]:
    """Tokens génériques (classes, propriétés, modificateurs) jamais traités
    comme des mentions d'entité : « formation », « module », « quelle »…"""
    tokens: set[str] = set()
    for phrase, _ in _class_phrase_index():
        tokens.update(phrase.split())
    for phrase, _, _ in _property_phrase_index():
        tokens.update(phrase.split())
    for forms in _modifier_index().values():
        for form in forms:
            tokens.update(form.split())
    tokens.update({
        "ne", "pas", "dans", "avec", "pour", "sur", "et", "ou", "est", "sont",
        "ont", "as", "que", "quoi", "qui", "dont", "me", "moi", "je", "ma",
        "mon", "mes", "my", "the", "of", "to", "for", "with", "is", "are",
    })
    return frozenset(token for token in tokens if token)


# ---------------------------------------------------------------------------
# Schéma de l'ontologie
# ---------------------------------------------------------------------------


def _schema():
    """Schéma de l'ontologie (chargé depuis Fuseki, mis en cache)."""
    return schema_module.get_schema()


@lru_cache(maxsize=1)
def _relations_index() -> dict[str, dict[str, frozenset[str]]]:
    """Domaine / co-domaine déduits des relations de ``sparql_client``.

    Sert de complément lorsque l'ontologie ne déclare pas ``rdfs:domain`` /
    ``rdfs:range`` sur une propriété.
    """
    index: dict[str, dict[str, set[str]]] = {}
    for entity_type, relations in sp.RELATIONS.items():
        for predicate, direction, target in relations.values():
            entry = index.setdefault(predicate, {"domains": set(), "ranges": set()})
            if direction == "outgoing":
                entry["domains"].add(entity_type)
                entry["ranges"].add(target)
            else:
                entry["domains"].add(target)
                entry["ranges"].add(entity_type)
    return {
        predicate: {
            "domains": frozenset(entry["domains"]),
            "ranges": frozenset(entry["ranges"]),
        }
        for predicate, entry in index.items()
    }


def _domains_ranges(prop: str) -> tuple[list[str], list[str]]:
    """Domaine et co-domaine d'une propriété (schéma Fuseki + relations connues)."""
    domains: set[str] = set()
    ranges: set[str] = set()
    info = _schema().property(prop)
    if info is not None:
        domains.update(info.domains)
        ranges.update(info.ranges)
    fallback = _relations_index().get(prop)
    if fallback:
        domains.update(fallback["domains"])
        ranges.update(fallback["ranges"])
    return sorted(domains), sorted(ranges)


# ---------------------------------------------------------------------------
# spaCy : tokenisation et groupes nominaux
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_pipeline():
    """Charge le meilleur pipeline spaCy disponible (FR, puis EN, puis vide)."""
    for model in ("fr_core_news_sm", "en_core_web_sm"):
        try:
            return spacy.load(model)
        except OSError:
            continue
    return spacy.blank("fr")


@lru_cache(maxsize=1)
def _duration_matcher() -> Matcher:
    """Matcher spaCy : un nombre suivi de « h » / « heure(s) »."""
    matcher = Matcher(_load_pipeline().vocab)
    matcher.add("DURATION", [[
        {"LIKE_NUM": True},
        {"LOWER": {"IN": ["h", "heure", "heures"]}},
    ]])
    return matcher


def _duration_value(question: str) -> int | None:
    """Extrait la borne numérique d'une contrainte de durée."""
    doc = _load_pipeline()(question)
    for _, start, _ in _duration_matcher()(doc):
        token = doc[start]
        if token.like_num:
            try:
                return int(token.text)
            except ValueError:
                continue
    fallback = re.search(
        r"(\d+)\s*(?:h\b|heures?\b)", _strip_accents(question).lower()
    )
    return int(fallback.group(1)) if fallback else None


def _first_number(question: str) -> int | None:
    """Premier entier présent dans la question (borne numérique)."""
    match = re.search(r"\b(\d+)\b", _norm_text(question))
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Détection des modificateurs, classes et propriétés
# ---------------------------------------------------------------------------


def _detect_modifiers(question_norm: str) -> set[str]:
    """Modificateurs présents dans la question (négation, comptage, etc.)."""
    found: set[str] = set()
    for name, phrases in _modifier_index().items():
        if any(_phrase_in(question_norm, phrase) for phrase in phrases):
            found.add(name)
    return found


def _detect_class_names(question_norm: str) -> list[str]:
    """Classes mentionnées, de la plus spécifique à la plus générale."""
    hits: list[tuple[int, str]] = []
    for phrase, klass in _class_phrase_index():
        if klass not in [name for _, name in hits] and _phrase_in(question_norm, phrase):
            hits.append((len(phrase), klass))
    return [name for _, name in hits]


def _question_lemmas(question: str) -> list[str]:
    """Lemmes normalisés des tokens de la question (analyse spaCy)."""
    lemmas: list[str] = []
    for token in _load_pipeline()(question):
        if token.is_space or token.is_punct:
            continue
        normalized = _norm_text(token.lemma_)
        if normalized:
            lemmas.append(normalized)
    return lemmas


@lru_cache(maxsize=1)
def _lemma_property_index() -> dict[str, tuple[tuple[str, str], ...]]:
    """Index lemme -> propriétés dont le lexique déclare ce lemme verbal.

    Permet de relier une forme fléchie (« enseignent ») au lemme du lexique
    (« enseigner »), donc à **toutes** les propriétés concernées : ici
    ``enseigne`` comme ``moduleEnseigne``.
    """
    index: dict[str, list[tuple[str, str]]] = {}
    for prop, entry in (_lexicon().get("properties") or {}).items():
        kind = entry.get("kind") or ("data" if prop.startswith("a") else "object")
        for lemma in (entry.get("verb_lemmas") or {}).values():
            for form in lemma or []:
                normalized = _norm_text(form)
                if normalized:
                    index.setdefault(normalized, []).append((prop, kind))
    return {lemma: tuple(dict.fromkeys(props)) for lemma, props in index.items()}


def _detect_properties(question_norm: str, question: str | None = None) -> list[tuple[str, str]]:
    """Propriétés mentionnées (nom, type), de la plus spécifique à la plus générale.

    La détection combine les formes du lexique (libellés, synonymes) et les
    **lemmes** produits par spaCy : une forme fléchie comme « enseignent » est
    reliée aux propriétés dont le lemme est « enseigner » (``enseigne`` et
    ``moduleEnseigne``).
    """
    hits: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for phrase, prop, kind in _property_phrase_index():
        if prop in seen or not _phrase_in(question_norm, phrase):
            continue
        seen.add(prop)
        hits.append((len(phrase), prop, kind))
    if question:
        for lemma in _question_lemmas(question):
            for prop, kind in _lemma_property_index().get(lemma, ()):
                if prop in seen:
                    continue
                seen.add(prop)
                hits.append((len(lemma), prop, kind))
    return [(prop, kind) for _, prop, kind in hits]


def _requested_class(question_norm: str) -> str | None:
    """Classe principalement demandée par la question.

    Heuristique : c'est la **première** classe mentionnée qui est visée, car la
    question commence par « quelles <classe> … ». Ce choix reste correct même
    quand une autre classe apparaît plus loin (« quels **modules** … aucune
    formation ») ou quand un groupe plus long arrive en fin de phrase
    (« familles de métiers »).
    """
    best: tuple[tuple[int, int], str] | None = None
    for phrase, klass in _class_phrase_index():
        if not _phrase_in(question_norm, phrase):
            continue
        key = (question_norm.find(phrase), -len(phrase))
        if best is None or key < best[0]:
            best = (key, klass)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Résolution d'entités (rapidfuzz, restreinte au type attendu)
# ---------------------------------------------------------------------------


def _entity_candidates(entity_type: str) -> list[dict]:
    """Individus de l'ontologie du type demandé, avec nom normalisé comparable."""
    return [
        {
            "id": item["id"],
            "label": item.get("label") or item["id"],
            "normalized": normalize_name(item.get("label") or item["id"]),
        }
        for item in sp.list_individuals(entity_type, None, True)
        if item.get("id")
    ]


def _is_generic(normalized: str) -> bool:
    tokens = normalized.split()
    return bool(tokens) and all(token in _cue_tokens() for token in tokens)


def _extract_mentions(question: str) -> list[dict]:
    """Mentions candidates : n-grammes de tokens + groupes nominaux spaCy."""
    doc = _load_pipeline()(question)
    tokens = [token.text for token in doc if not token.is_space and not token.is_punct]
    mentions: list[dict] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        normalized = normalize_name(raw)
        if not normalized or normalized in seen or _is_generic(normalized):
            return
        seen.add(normalized)
        mentions.append({"text": raw.strip(), "normalized": normalized})

    for size in range(1, min(4, len(tokens)) + 1):
        for index in range(len(tokens) - size + 1):
            add(" ".join(tokens[index:index + size]))

    if doc.has_annotation("DEP"):
        for chunk in doc.noun_chunks:
            add(chunk.text)

    return mentions


def _score_entities(question: str, entity_type: str) -> list[tuple[int, str, dict]]:
    """Candidats de ``entity_type`` scorés (score, texte de mention, candidat)."""
    candidates = _entity_candidates(entity_type)
    if not candidates:
        return []
    scored: list[tuple[int, str, dict]] = []
    for mention in _extract_mentions(question):
        for candidate in candidates:
            score = fuzz.token_set_ratio(mention["normalized"], candidate["normalized"])
            if score >= MATCH_THRESHOLD:
                scored.append((score, mention["text"], candidate))
    return scored


def resolve_entity(question: str, entity_type: str) -> dict | None:
    """Résout la meilleure mention vers un individu du type RDF demandé.

    Retourne ``None`` si aucune mention n'atteint le seuil de similarité.
    """
    scored = _score_entities(question, entity_type)
    if not scored:
        return None
    best: dict | None = None
    best_key: tuple[int, int, int] | None = None
    for score, text, candidate in scored:
        mention_tokens = len(normalize_name(text).split())
        # À score égal, on préfère la mention dont le nombre de tokens est le
        # plus proche du libellé ontologique (ex. « Data Eng » plutôt que
        # « Data » pour form_DataEng), puis la plus longue.
        key = (
            score,
            -abs(mention_tokens - len(candidate["normalized"].split())),
            len(text),
        )
        if best_key is None or key > best_key:
            best_key = key
            best = {
                "text": text,
                "id": candidate["id"],
                "label": candidate["label"],
                "type": entity_type,
                "score": score,
            }
    return best


def resolve_entities(question: str, entity_type: str, limit: int = 2) -> list[dict]:
    """Résout jusqu'à ``limit`` entités distinctes (pour « en commun »)."""
    scored = sorted(_score_entities(question, entity_type), key=lambda item: (-item[0], len(item[1])))
    results: dict[str, dict] = {}
    for score, text, candidate in scored:
        if candidate["id"] in results:
            continue
        results[candidate["id"]] = {
            "text": text,
            "id": candidate["id"],
            "label": candidate["label"],
            "type": entity_type,
            "score": score,
        }
        if len(results) >= limit:
            break
    return list(results.values())


def resolve_competences(text: str, per_mention: int = 3) -> list[dict]:
    """Résout un texte libre (« python, sql, cloud ») vers des compétences réelles.

    Le texte brut n'est jamais concaténé dans une requête SPARQL : il est
    découpé sur les séparateurs usuels, puis chaque segment est comparé aux
    libellés ``aNom`` / identifiants des individus ``onto:Competence`` réellement
    présents dans l'ontologie avec *rapidfuzz*. Seuls des individus existants
    sont proposés.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    candidates = _entity_candidates("Competence")
    if not candidates:
        return []

    results: dict[str, dict] = {}
    for segment in re.split(r"[,;\n/]+", text):
        mentions = _extract_mentions(segment)
        scored: list[tuple[int, dict, str]] = []
        for mention in mentions:
            for candidate in candidates:
                score = fuzz.token_set_ratio(mention["normalized"], candidate["normalized"])
                scored.append((score, candidate, mention["text"]))
        scored.sort(key=lambda item: (-item[0], len(item[2]), item[1]["id"]))
        for score, candidate, mention in scored[:max(1, per_mention)]:
            if score < MATCH_THRESHOLD:
                continue
            existing = results.get(candidate["id"])
            if existing is None or score > existing["score"]:
                results[candidate["id"]] = {
                    "iri": candidate["id"],
                    "label": candidate["label"],
                    "score": score,
                    "mention": mention,
                }
    return sorted(
        results.values(),
        key=lambda item: (-item["score"], item["label"].lower()),
    )


# ---------------------------------------------------------------------------
# Validation et construction d'IRI
# ---------------------------------------------------------------------------


def _iri(identifier: str) -> str:
    """IRI SPARQL d'un individu, uniquement si l'identifiant est valide."""
    if not _RESOURCE_ID_PATTERN.fullmatch(str(identifier or "")):
        raise sp.InvalidPayloadError(f"Identifiant d'entité invalide : {identifier}.")
    return f"<{sp.ONTOLOGY_NAMESPACE}{identifier}>"


def _validated_id(value: str) -> str:
    """Valide un identifiant fourni par l'appelant (profil, par ex.)."""
    if not _RESOURCE_ID_PATTERN.fullmatch(str(value or "")):
        raise sp.InvalidPayloadError("Identifiant de ressource invalide.")
    return value


def _class_pattern(var: str, class_name: str) -> str:
    """Motif SPARQL d'appartenance à une classe (sous-classes incluses)."""
    return (
        f"?{var} rdf:type ?{var}Class .\n"
        f"  ?{var}Class rdfs:subClassOf* onto:{class_name} .\n"
        f'  FILTER(STRSTARTS(STR(?{var}), "{sp.ONTOLOGY_NAMESPACE}"))\n'
        f"  FILTER(?{var}Class != owl:NamedIndividual)"
    )


# ---------------------------------------------------------------------------
# Planification (détection de l'intention + paramètres)
# ---------------------------------------------------------------------------


def _object_properties() -> list[str]:
    """Toutes les propriétés d'objet connues (schéma Fuseki + relations)."""
    return sorted(set(_schema().object_properties) | set(_relations_index()))


def _touches(prop: str, klass: str | None) -> bool:
    """Vrai si ``klass`` est le domaine ou le co-domaine de ``prop``."""
    if not klass:
        return False
    domains, ranges = _domains_ranges(prop)
    return klass in domains or klass in ranges


def _opposite(prop: str, klass: str) -> list[str]:
    """Côté de ``prop`` opposé à ``klass`` (sa cible si ``klass`` est son domaine)."""
    domains, ranges = _domains_ranges(prop)
    return ranges if klass in domains else domains


def _select_property(
    requested: str | None, others: list[str], detected: list[str]
) -> str | None:
    """Choisit la propriété d'objet qui relie la classe demandée au reste.

    Priorité : (1) les propriétés détectées dans la question qui touchent la
    classe demandée, en préférant celles dont le côté opposé correspond à une
    autre classe mentionnée ; (2) une propriété déduite du schéma reliant la
    classe demandée à une autre classe mentionnée (ex. « compétences communes
    aux **formations** X et Y » -> ``enseigne``) ; (3) à défaut, la première
    propriété détectée par le lexique.
    """
    fitting = [prop for prop in detected if _touches(prop, requested)]
    if others:
        # (1) propriété détectée reliant la classe demandée à une autre classe
        for prop in fitting:
            if set(_opposite(prop, requested)) & set(others):
                return prop
        # (2) propriété déduite du schéma reliant la classe demandée à une autre
        #     classe (ex. « compétences … le module X » -> ``moduleEnseigne``)
        if requested:
            for prop in _object_properties():
                if _touches(prop, requested) and set(_opposite(prop, requested)) & set(others):
                    return prop
    if fitting:
        return fitting[0]

    if not requested and detected:
        return detected[0]

    return detected[0] if detected else None


def _plan_relation(
    question: str, question_norm: str, prop: str, requested: str | None, mods: set[str]
) -> dict | None:
    """Construit un plan de type « relation » (directe ou inverse)."""
    domains, ranges = _domains_ranges(prop)
    if not domains and not ranges:
        return None

    labels = _property_labels(prop)
    reverse = any(
        _phrase_in(question_norm, f"comme {_norm_text(label)}") for label in labels
    )

    target = requested or (ranges or domains)[0]
    if reverse:
        role = "object"
    elif target in ranges:
        role = "subject"
    elif target in domains:
        role = "object"
    else:
        role = "subject"

    anchor_classes = domains if role == "subject" else ranges
    if not anchor_classes:
        return None

    if "common" in mods:
        for klass in anchor_classes:
            pair = resolve_entities(question, klass, limit=2)
            if len(pair) >= 2:
                return {
                    "kind": "common",
                    "property": prop,
                    "target_class": target,
                    "anchors": pair,
                    "intent": f"common_{prop}",
                }
        return None

    anchors: list[dict] = []
    for klass in anchor_classes:
        entity = resolve_entity(question, klass)
        if entity:
            anchors.append(entity)
            break

    if "transitive" in mods:
        if not anchors:
            return None
        return {
            "kind": "transitive",
            "property": prop,
            "target_class": target,
            "anchors": anchors,
            "intent": f"transitive_{prop}",
        }

    if not anchors:
        return None

    negated = "negation" in mods
    count = "count" in mods
    intent = f"relation_negated_{prop}" if negated else f"relation_{prop}"
    if count:
        intent = f"count_{intent}"
    return {
        "kind": "relation",
        "property": prop,
        "anchor_role": role,
        "target_class": target,
        "anchors": anchors,
        "negated": negated,
        "count": count,
        "intent": intent,
    }


def _plan_list(target_class: str, mods: set[str], orphan_property: str | None = None) -> dict:
    """Plan « lister les individus d'une classe » (comptage et exclusion gérés)."""
    count = "count" in mods and orphan_property is None
    return {
        "kind": "list",
        "target_class": target_class,
        "orphan_property": orphan_property,
        "count": count,
        "intent": (f"count_list_{target_class}" if count else f"list_{target_class}"),
    }


def _resolve_any_entity(question: str) -> dict | None:
    """Meilleure entité de l'ontologie, tous types confondus."""
    best: dict | None = None
    for entity_type in sp.ENTITY_CLASSES:
        entity = resolve_entity(question, entity_type)
        if entity and (best is None or entity["score"] > best["score"]):
            best = entity
    return best


def _orphan_property(requested: str | None) -> str | None:
    """Propriété de rattachement pour une classe « orpheline ».

    On privilégie la propriété dont la classe demandée est le **co-domaine**
    (ex. un module est *contenu* dans une formation via ``contientModule``).
    """
    if not requested:
        return None
    touching = [prop for prop in _object_properties() if _touches(prop, requested)]
    preferred = [
        prop for prop in touching if requested in _domains_ranges(prop)[1]
    ]
    ordered = preferred or touching
    return ordered[0] if ordered else None


def _plan(question: str, force_property: str | None = None) -> dict | None:
    """Détermine le plan de requête correspondant à la question (ou ``None``)."""
    question_norm = _norm_text(question)
    mods = _detect_modifiers(question_norm)
    requested = _requested_class(question_norm)
    others = [
        name for name in _detect_class_names(question_norm) if name != requested
    ]
    properties = _detect_properties(question_norm, question)
    object_props = [prop for prop, kind in properties if kind == "object"]
    data_props = [prop for prop, kind in properties if kind == "data"]

    # Repli par paraphrase : propriété imposée.
    if force_property:
        plan = _plan_relation(question, question_norm, force_property, requested, mods)
        if plan:
            return plan

    # Relation explicite, sinon déduite du schéma.
    property_name = _select_property(requested, others, object_props)
    if property_name:
        plan = _plan_relation(question, question_norm, property_name, requested, mods)
        if plan:
            return plan
        # Négation sans ancrage (« formations sans prérequis »).
        if "negation" in mods and requested:
            return _plan_list(requested, mods, orphan_property=property_name)

    # Filtre numérique sur une propriété de données.
    number = _first_number(question)
    if number is not None and ({"less", "more"} & mods) and requested:
        data_property = data_props[0] if data_props else _DEFAULT_DATA_PROPERTY.get(requested)
        if data_property:
            return {
                "kind": "numeric",
                "target_class": requested,
                "data_property": data_property,
                "operator": "<" if "less" in mods else ">",
                "value": number,
                "count": "count" in mods,
                "intent": f"numeric_filter_{requested}",
            }

    # Détails d'un individu précis.
    if "detail" in mods:
        entity = resolve_entity(question, requested) if requested else None
        entity = entity or _resolve_any_entity(question)
        if entity:
            return {
                "kind": "detail",
                "target_class": entity["type"],
                "anchors": [entity],
                "intent": f"detail_{entity['type']}",
            }

    # Liste simple, éventuellement « orpheline ».
    if "orphan" in mods and requested:
        orphan = _orphan_property(requested)
        if orphan:
            return _plan_list(requested, mods, orphan_property=orphan)
    if requested:
        return _plan_list(requested, mods)

    return None


# ---------------------------------------------------------------------------
# Construction des requêtes génériques
# ---------------------------------------------------------------------------


def _projection(plan: dict, rows: list[str]) -> str:
    """Projette ``COUNT`` ou la liste de variables selon le plan."""
    if plan.get("count"):
        return "SELECT (COUNT(DISTINCT ?item) AS ?count)"
    return "SELECT DISTINCT " + " ".join(rows)


def _build_generic(plan: dict) -> str:
    """Construit la requête SPARQL SELECT d'un plan générique."""
    prefixes = sp.COMMON_PREFIXES
    kind = plan["kind"]

    if kind == "list":
        lines = [f"  {_class_pattern('item', plan['target_class'])}"]
        if plan.get("orphan_property"):
            lines.append(
                f"  FILTER NOT EXISTS {{ ?holder onto:{plan['orphan_property']} ?item }}"
            )
        rows = ["?item"] if plan.get("count") else ["?item", "?nom"]
        if not plan.get("count"):
            lines.append("  OPTIONAL { ?item onto:aNom ?nom }")
        return prefixes + f"\n{_projection(plan, rows)} WHERE {{\n" + "\n".join(lines) + "\n}\n"

    if kind == "relation":
        anchor_iri = _iri(plan["anchors"][0]["id"])
        target = plan["target_class"]
        prop = plan["property"]
        lines: list[str] = []
        if plan["anchor_role"] == "object":
            lines.append(f"  {_class_pattern('item', target)}")
            if plan.get("negated"):
                lines.append(f"  FILTER NOT EXISTS {{ ?item onto:{prop} {anchor_iri} }}")
            else:
                lines.append(f"  ?item onto:{prop} {anchor_iri} .")
        else:
            lines.append(f"  {anchor_iri} onto:{prop} ?item .")
            lines.append(f"  {_class_pattern('item', target)}")
        rows = ["?item"] if plan.get("count") else ["?item", "?nom"]
        if not plan.get("count"):
            lines.append("  OPTIONAL { ?item onto:aNom ?nom }")
        return prefixes + f"\n{_projection(plan, rows)} WHERE {{\n" + "\n".join(lines) + "\n}\n"

    if kind == "numeric":
        lines = [
            f"  {_class_pattern('item', plan['target_class'])}",
            f"  ?item onto:{plan['data_property']} ?value .",
        ]
        rows = ["?item"] if plan.get("count") else ["?item", "?nom", "?value"]
        if not plan.get("count"):
            lines.append("  OPTIONAL { ?item onto:aNom ?nom }")
        lines.append(f"  FILTER(?value {plan['operator']} {int(plan['value'])})")
        return prefixes + f"\n{_projection(plan, rows)} WHERE {{\n" + "\n".join(lines) + "\n}\n"

    if kind == "detail":
        anchor_iri = _iri(plan["anchors"][0]["id"])
        return prefixes + (
            "\nSELECT ?propriete ?valeur WHERE {\n"
            f"  {anchor_iri} ?propriete ?valeur .\n"
            "}\n"
        )

    if kind == "common":
        prop = plan["property"]
        first = _iri(plan["anchors"][0]["id"])
        second = _iri(plan["anchors"][1]["id"])
        return prefixes + (
            "\nSELECT DISTINCT ?item ?nom WHERE {\n"
            f"  {first} onto:{prop} ?item .\n"
            f"  {second} onto:{prop} ?item .\n"
            "  OPTIONAL { ?item onto:aNom ?nom }\n"
            "}\n"
        )

    if kind == "transitive":
        prop = plan["property"]
        anchor_iri = _iri(plan["anchors"][0]["id"])
        return prefixes + (
            "\nSELECT DISTINCT ?item ?nom WHERE {\n"
            f"  {anchor_iri} onto:{prop}+ ?item .\n"
            "  OPTIONAL { ?item onto:aNom ?nom }\n"
            "}\n"
        )

    raise sp.InvalidPayloadError(f"Plan non supporté : {kind}.")


def _names(results: list[dict], *variables: str) -> str:
    """Concatène les libellés lisibles d'un jeu de résultats."""
    labels: list[str] = []
    for row in results:
        value = row.get("nom")
        if not value:
            for variable in variables:
                if row.get(variable):
                    value = row[variable]
                    break
        if value:
            labels.append(str(value))
    return ", ".join(labels)


def _build_message(plan: dict, results: list[dict]) -> str:
    """Résumé lisible en français du résultat d'une requête générique."""
    count = len(results)
    class_label = _class_label(plan.get("target_class", ""))
    property_name = plan.get("property") or plan.get("data_property") or ""
    property_label = (
        _property_labels(property_name)[0] if property_name and _property_labels(property_name)
        else property_name
    )
    anchor_label = plan["anchors"][0]["label"] if plan.get("anchors") else ""

    if plan.get("count"):
        value = results[0].get("count") if results else 0
        return f"{value} {class_label}(s) au total ({property_label or 'résultat'})."

    if plan["kind"] == "numeric":
        direction = "moins de" if plan["operator"] == "<" else "plus de"
        if count == 0:
            return (
                f"Aucun(e) {class_label} ne vérifie « {property_label} {direction} "
                f"{plan['value']} »."
            )
        return (
            f"{count} {class_label}(s) avec {property_label} {direction} {plan['value']} : "
            f"{_names(results, 'item')}."
        )

    if plan["kind"] == "list":
        if count == 0:
            return f"Aucun(e) {class_label} trouvé(e) dans l'ontologie."
        return f"{count} {class_label}(s) : {_names(results, 'item')}."

    if plan["kind"] == "relation":
        if plan.get("negated"):
            if count == 0:
                return f"Tous les {class_label}s sont liés à « {anchor_label} »."
            return (
                f"{count} {class_label}(s) ne sont pas liés à « {anchor_label} » via "
                f"{property_label} : {_names(results, 'item')}."
            )
        if count == 0:
            return f"Aucun(e) {class_label} lié(e) à « {anchor_label} » via {property_label}."
        return (
            f"{count} {class_label}(s) lié(s) à « {anchor_label} » via {property_label} : "
            f"{_names(results, 'item')}."
        )

    if plan["kind"] == "detail":
        return f"Détails de « {anchor_label} » : {count} propriété(s) renseignée(s)."

    if plan["kind"] == "common":
        labels = " et ".join(anchor["label"] for anchor in plan["anchors"])
        if count == 0:
            return f"Aucun élément commun à {labels} via {property_label}."
        return f"{count} élément(s) commun(s) à {labels} : {_names(results, 'item')}."

    if plan["kind"] == "transitive":
        if count == 0:
            return f"Aucun {property_label} (transitif) pour « {anchor_label} »."
        return (
            f"{count} {property_label} (transitif) pour « {anchor_label} » : "
            f"{_names(results, 'item')}."
        )

    return f"{count} résultat(s)."


def _entities_payload(plan: dict) -> list[dict]:
    """Entités résolues, au format attendu par l'interface."""
    payload = []
    for entity in plan.get("anchors") or []:
        payload.append({
            "text": entity["text"],
            "iri": sp.ONTOLOGY_NAMESPACE + entity["id"],
            "type": entity["type"],
            "score": round(entity["score"] / 100, 2),
        })
    return payload


def _run_plan(plan: dict, question: str) -> dict:
    """Exécute un plan générique et formate la réponse."""
    sparql = _build_generic(plan)
    results = sp.run_query(sparql)
    return {
        "question": question,
        "intent": plan["intent"],
        "entities": _entities_payload(plan),
        "sparql": sparql,
        "results": results,
        "message": _build_message(plan, results),
    }


# ---------------------------------------------------------------------------
# Intentions dédiées (profil connecté)
# ---------------------------------------------------------------------------


def _dedicated_intent(question_norm: str) -> str | None:
    """Détecte une intention dédiée (profil connecté), sinon ``None``."""
    if any(_phrase_in(question_norm, phrase) for phrase in (
        "combler", "comblent", "comble", "combler mes lacunes", "fill my gaps",
    )) and any(token in question_norm for token in ("lacune", "ecart", "manqu")):
        return "formations_combler_ecarts"
    if "parcours" in question_norm and any(
        token in question_norm for token in ("optimal", "meilleur", "recommande")
    ):
        return "parcours_optimal"
    if (
        any(token in question_norm for token in ("manqu", "lacune", "ecart"))
        and any(token in question_norm for token in ("competence", "skill"))
        and "formation" not in question_norm
    ):
        return "competences_manquantes_metier"
    if any(phrase in question_norm for phrase in (
        "mes competences", "my skills", "competences que je possede",
        "competences ai je", "skills i possess",
    )):
        return "competences_acquises_profil"
    if "profil" in question_norm and any(
        token in question_norm for token in ("eligible", "correspond", "qui peut")
    ):
        return "profils_eligibles_metier"
    if "metier" in question_norm and any(
        token in question_norm
        for token in ("accessible", "eligible", "puis je", "peux", "possible")
    ):
        return "metiers_eligibles_profil"

    # Formulations du lexique : on retient la plus spécifique (phrase la plus longue).
    best: tuple[int, str] | None = None
    for intent, phrases in _dedicated_index().items():
        if intent not in DEDICATED_INTENTS:
            continue
        for phrase in phrases:
            if _phrase_in(question_norm, phrase) and (best is None or len(phrase) > best[0]):
                best = (len(phrase), intent)
    return best[1] if best else None


def _need_profile(intent: str, question: str) -> dict:
    return {
        "question": question,
        "intent": intent,
        "entities": [],
        "sparql": "",
        "results": [],
        "message": (
            "Cette question porte sur votre profil : précisez le champ « profil » "
            "dans la requête pour que l'assistant puisse répondre."
        ),
    }


def _required_skills_query(metier_iri: str) -> str:
    return sp.SP_PREFIX + (
        "SELECT DISTINCT ?item ?nom WHERE {\n"
        f"  {metier_iri} sp:requiert ?item .\n"
        "  OPTIONAL { ?item sp:aNom ?nom }\n"
        "}\n"
    )


def _missing_skills_query(profil_id: str, metier_iri: str | None) -> str:
    if metier_iri is None:
        return sp.competences_manquantes_query(profil_id)
    return sp.SP_PREFIX + (
        "SELECT DISTINCT ?item ?nom WHERE {\n"
        f"  sp:{profil_id} sp:vise ?anyMetier .\n"
        f"  {metier_iri} sp:requiert ?item .\n"
        f"  FILTER NOT EXISTS {{ sp:{profil_id} sp:aAcquis ?item }}\n"
        "  OPTIONAL { ?item sp:aNom ?nom }\n"
        "}\n"
    )


def _profiles_for_metier_query(metier_iri: str) -> str:
    return sp.COMMON_PREFIXES + (
        "\nSELECT DISTINCT ?item ?nom WHERE {\n"
        f"  {_class_pattern('item', 'ProfilUtilisateur')}\n"
        f"  {metier_iri} sp:requiert ?any .\n"
        "  FILTER NOT EXISTS {\n"
        f"    {metier_iri} sp:requiert ?req .\n"
        "    FILTER NOT EXISTS { ?item sp:aAcquis ?req }\n"
        "  }\n"
        "  OPTIONAL { ?item sp:aNom ?nom }\n"
        "}\n"
    )


def _close_gaps_query(profil_id: str) -> str:
    return sp.SP_PREFIX + (
        "SELECT DISTINCT ?item ?nom WHERE {\n"
        "  ?item sp:enseigne ?comp .\n"
        f"  sp:{profil_id} sp:vise ?metier .\n"
        "  ?metier sp:requiert ?comp .\n"
        f"  FILTER NOT EXISTS {{ sp:{profil_id} sp:aAcquis ?comp }}\n"
        "  OPTIONAL { ?item sp:aNom ?nom }\n"
        "}\n"
    )


def _acquired_skills_query(profil_id: str) -> str:
    return sp.SP_PREFIX + (
        "SELECT DISTINCT ?item ?nom WHERE {\n"
        f"  {{ sp:{profil_id} sp:aAcquis ?item . }}\n"
        "  UNION\n"
        "  {\n"
        f"    sp:{profil_id} sp:aSuivi ?f .\n"
        "    { ?f sp:enseigne ?item . } UNION { ?f sp:contientModule ?m . ?m sp:moduleEnseigne ?item . }\n"
        "  }\n"
        "  OPTIONAL { ?item sp:aNom ?nom }\n"
        "}\n"
    )


def _run_dedicated(intent: str, question: str, profil: str | None) -> dict:
    """Exécute une intention dédiée (elle utilise le profil fourni)."""
    profil_id = _validated_id(profil) if profil else None
    metier = resolve_entity(question, "Metier")
    metier_iri = _iri(metier["id"]) if metier else None

    if intent == "competences_manquantes_metier":
        if profil_id is None and metier_iri is None:
            return _need_profile(intent, question)
        if profil_id is None:
            sparql = _required_skills_query(metier_iri)
        else:
            sparql = _missing_skills_query(profil_id, metier_iri)

    elif intent == "metiers_eligibles_profil":
        if profil_id is None:
            return _need_profile(intent, question)
        sparql = sp.metiers_accessibles_query(profil_id)

    elif intent == "profils_eligibles_metier":
        if metier_iri is None:
            return {
                "question": question,
                "intent": intent,
                "entities": [],
                "sparql": "",
                "results": [],
                "message": (
                    "Précisez le métier concerné (par exemple « métier Data Engineer ») "
                    "pour que l'assistant puisse lister les profils éligibles."
                ),
            }
        sparql = _profiles_for_metier_query(metier_iri)

    elif intent == "formations_combler_ecarts":
        if profil_id is None:
            return _need_profile(intent, question)
        sparql = _close_gaps_query(profil_id)

    elif intent == "parcours_optimal":
        if profil_id is None:
            return _need_profile(intent, question)
        sparql = sp.parcours_optimal_query(profil_id)

    elif intent == "competences_acquises_profil":
        if profil_id is None:
            return _need_profile(intent, question)
        sparql = _acquired_skills_query(profil_id)

    else:  # pragma: no cover - garde-fou
        return _unknown_response(question)

    results = sp.run_query(sparql)
    entities = (
        [{
            "text": metier["text"],
            "iri": sp.ONTOLOGY_NAMESPACE + metier["id"],
            "type": metier["type"],
            "score": round(metier["score"] / 100, 2),
        }]
        if metier
        else []
    )
    return {
        "question": question,
        "intent": intent,
        "entities": entities,
        "sparql": sparql,
        "results": results,
        "message": _dedicated_message(intent, results, metier, profil_id),
    }


def _dedicated_message(
    intent: str, results: list[dict], metier: dict | None, profil_id: str | None
) -> str:
    count = len(results)
    names = _names(results, "item", "metier", "formation", "competence")
    target = metier["label"] if metier else ""

    if intent == "competences_manquantes_metier":
        if profil_id is None:
            return f"Compétences requises pour « {target} » ({count}) : {names}."
        if count == 0:
            return f"Aucune compétence manquante pour le métier visé ({target or 'profil'})."
        return f"{count} compétence(s) manquante(s) : {names}."

    if intent == "metiers_eligibles_profil":
        if count == 0:
            return "Aucun métier du catalogue n'est encore entièrement couvert par ce profil."
        return f"{count} métier(s) accessible(s) avec ce profil : {names}."

    if intent == "profils_eligibles_metier":
        if count == 0:
            return f"Aucun profil du catalogue n'est éligible au métier « {target} »."
        return f"{count} profil(s) éligible(s) au métier « {target} » : {names}."

    if intent == "formations_combler_ecarts":
        if count == 0:
            return "Aucune formation du catalogue ne comble actuellement les écarts de ce profil."
        return f"{count} formation(s) comblent vos écarts : {names}."

    if intent == "parcours_optimal":
        if count == 0:
            return "Aucune formation n'est immédiatement accessible : des prérequis restent à suivre."
        return f"{count} formation(s) prioritaires pour votre parcours : {names}."

    if intent == "competences_acquises_profil":
        if count == 0:
            return "Aucune compétence acquise n'est enregistrée pour ce profil."
        return f"{count} compétence(s) acquise(s) : {names}."

    return f"{count} résultat(s)."


# ---------------------------------------------------------------------------
# Replis : paraphrase, entité seule, rien reconnu
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _paraphrase_model():
    """Charge (une fois) le petit modèle multilingue local, ou ``None``."""
    if SentenceTransformer is None:
        return None
    try:
        return SentenceTransformer(PARAPHRASE_MODEL_NAME)
    except Exception:  # noqa: BLE001 - modèle absent/hors ligne : règles seules
        return None


def _paraphrase_examples() -> tuple[list[str], list[str]]:
    """Formulations d'exemple et intention associée, pour le repli paraphrase."""
    texts: list[str] = []
    intents: list[str] = []

    for intent, phrases in _dedicated_index().items():
        for phrase in phrases:
            texts.append(phrase)
            intents.append(intent)

    schema = _schema()
    for klass in schema.class_names():
        label = _class_label(klass)
        texts.extend([f"liste des {label}", f"quels sont les {label}"])
        intents.extend([f"list_{klass}", f"list_{klass}"])

    for prop, kind in (
        (name, info.kind) for name, info in schema.object_properties.items()
    ):
        if kind != "object":
            continue
        domains, ranges = _domains_ranges(prop)
        labels = _property_labels(prop)
        if not domains or not ranges or not labels:
            continue
        verb = labels[0]
        texts.append(
            f"quelles {_class_label(domains[0])} {verb} une {_class_label(ranges[0])}"
        )
        intents.append(f"relation_{prop}")

    return texts, intents


@lru_cache(maxsize=1)
def _paraphrase_embeddings():
    """Embeddings normalisés des exemples de paraphrase (mis en cache)."""
    model = _paraphrase_model()
    if model is None:
        return None
    texts, _ = _paraphrase_examples()
    if not texts:
        return None
    try:
        return model.encode(texts, normalize_embeddings=True)
    except Exception:  # noqa: BLE001
        return None


def _paraphrase_intent(question: str) -> str | None:
    """Intention la plus proche via sentence-transformers (si disponible)."""
    model = _paraphrase_model()
    embeddings = _paraphrase_embeddings()
    if model is None or embeddings is None:
        return None
    _, intents = _paraphrase_examples()
    try:
        vector = model.encode([question], normalize_embeddings=True)[0]
    except Exception:  # noqa: BLE001
        return None
    scores = embeddings @ vector
    best_index = int(scores.argmax())
    if float(scores[best_index]) >= PARAPHRASE_THRESHOLD:
        return intents[best_index]
    return None


def _entity_detail_response(entity: dict, question: str) -> dict:
    """Repli « entité seule » : tout ce que l'on sait de l'entité résolue."""
    plan = {
        "kind": "detail",
        "target_class": entity["type"],
        "anchors": [entity],
        "intent": f"detail_{entity['type']}",
    }
    sparql = _build_generic(plan)
    results = sp.run_query(sparql)
    return {
        "question": question,
        "intent": plan["intent"],
        "entities": _entities_payload(plan),
        "sparql": sparql,
        "results": results,
        "message": f"Closest match: everything known about {entity['label']}.",
    }


def _example_entries() -> list[tuple[str, str]]:
    """(question d'exemple, type de question) : socle + une par classe du schéma."""
    entries: list[tuple[str, str]] = list(_BASE_EXAMPLES)
    for klass in _schema().class_names():
        kind = "other_profile" if klass in PROFILE_CLASSES else "catalogue"
        entries.append((f"Liste les {_class_label(klass)}s.", kind))
    return entries


def _schema_examples(role: str | None = None) -> list[str]:
    """Questions d'exemple visibles pour ``role`` (toutes si ``role`` est ``None``)."""
    examples: list[str] = []
    for example, kind in _example_entries():
        if role is not None and role not in QUESTION_TYPES.get(kind, ALL_ROLES):
            continue
        if example not in examples:
            examples.append(example)
    return examples


def _restricted_response(intent: str, question: str) -> dict:
    """Refus par rôle : aucun SPARQL généré, aucune donnée retournée."""
    return {
        "question": question,
        "intent": intent,
        "entities": [],
        "sparql": "",
        "results": [],
        "message": RESTRICTED_ROLE_MESSAGE,
    }


def _gate(
    intent: str, role: str | None, question: str, plan: dict | None = None
) -> dict | None:
    """Réponse de refus si ``role`` n'est pas autorisé, sinon ``None``.

    ``role`` à ``None`` signifie « pas de contrôle » (appel interne/historique) :
    toutes les intentions restent alors accessibles.
    """
    if role is None or is_intent_allowed(intent, role, plan):
        return None
    return _restricted_response(intent, question)


def _unknown_response(question: str, role: str | None = None) -> dict:
    """Repli « rien reconnu » : aucune supposition, exemples proposés."""
    suggestions = " ; ".join(_schema_examples(role))
    return {
        "question": question,
        "intent": "unknown",
        "entities": [],
        "sparql": "",
        "results": [],
        "message": (
            "Intention non reconnue : la question n'a pas pu être reliée à une "
            f"requête SPARQL connue. Questions d'exemple supportées : {suggestions}."
        ),
    }


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def detect_intent(question: str) -> tuple[str, dict]:
    """Détermine l'intention de la question et les paramètres associés.

    Retourne un couple ``(intention, indices)`` sans exécuter de requête.
    """
    question_norm = _norm_text(question)
    dedicated = _dedicated_intent(question_norm)
    if dedicated:
        return dedicated, {}
    plan = _plan(question)
    if plan:
        info = {
            key: plan[key]
            for key in ("kind", "target_class", "property", "data_property", "anchor_role")
            if key in plan
        }
        return plan["intent"], info
    return "unknown", {}


def analyze_question(
    question: str, profil: str | None = None, role: str | None = None
) -> dict:
    """Traduit une question en langage naturel en SPARQL puis exécute la requête.

    ``profil`` (optionnel) est l'identifiant du profil connecté ; il n'est jamais
    lu dans le texte de la question et sert uniquement aux intentions dédiées
    (« mes » compétences, parcours optimal…).

    ``role`` (optionnel) est le rôle vérifié de l'appelant (``STUDENT``,
    ``PROFESSIONAL`` ou ``ADMIN``). S'il est fourni et n'autorise pas l'intention
    détectée, aucune requête SPARQL n'est construite et aucune donnée n'est
    retournée : un message de refus est renvoyé. ``role`` à ``None`` désactive le
    contrôle (comportement historique).
    """
    question = (question or "").strip()
    if not question:
        return _unknown_response(question, role)

    question_norm = _norm_text(question)

    # 1. Intentions dédiées (prioritaires).
    dedicated = _dedicated_intent(question_norm)
    if dedicated:
        denied = _gate(dedicated, role, question)
        if denied:
            return denied
        return _run_dedicated(dedicated, question, profil)

    # 2. Règles génériques pilotées par le schéma.
    plan = _plan(question)
    if plan:
        denied = _gate(plan["intent"], role, question, plan)
        if denied:
            return denied
        return _run_plan(plan, question)

    # 3. Repli par paraphrase (sentence-transformers, local).
    paraphrase = _paraphrase_intent(question)
    if paraphrase:
        if paraphrase in DEDICATED_INTENTS:
            denied = _gate(paraphrase, role, question)
            if denied:
                return denied
            return _run_dedicated(paraphrase, question, profil)
        if paraphrase.startswith("relation_"):
            forced = _plan(question, force_property=paraphrase[len("relation_"):])
            if forced:
                denied = _gate(forced["intent"], role, question, forced)
                if denied:
                    return denied
                return _run_plan(forced, question)
        elif paraphrase.startswith("list_"):
            target = paraphrase[len("list_"):]
            if _schema().has_class(target):
                list_plan = _plan_list(target, _detect_modifiers(question_norm))
                denied = _gate(list_plan["intent"], role, question, list_plan)
                if denied:
                    return denied
                return _run_plan(list_plan, question)

    # 4. Repli « entité seule ».
    entity = _resolve_any_entity(question)
    if entity:
        denied = _gate(f"detail_{entity['type']}", role, question)
        if denied:
            return denied
        return _entity_detail_response(entity, question)

    # 5. Rien reconnu : aucune supposition.
    return _unknown_response(question, role)


def examples_payload(role: str | None = None) -> dict:
    """Questions d'exemple supportées, exposée par ``GET /nlp/examples``.

    ``role`` (optionnel) filtre les exemples pour ne montrer que ceux autorisés
    au rôle courant. ``None`` renvoie l'ensemble des exemples (comportement
    historique).
    """
    return {
        "examples": _schema_examples(role),
        "supported_intents": list(SUPPORTED_INTENTS),
    }

"""
Client SPARQL pour SkillPath.

Ce module centralise la connexion à Apache Jena Fuseki et l'exécution
des requêtes SPARQL. Il est utilisé par les endpoints FastAPI de main.py.

Pour le faire fonctionner :
1. Lance Fuseki sur ta machine (fuseki-server.bat) avec le dataset "skillpath"
   déjà chargé (comme tu l'as fait pour tester Q1, Q2, Q3 dans Protégé/Fuseki).
2. Vérifie que FUSEKI_URL ci-dessous correspond à ton endpoint réel
   (par défaut : http://localhost:3030/skillpath/sparql).
3. Lance ce backend avec : uvicorn app.main:app --reload
"""

import json
import math
import os
import re
from datetime import datetime
from urllib.error import URLError

from SPARQLWrapper import JSON, SPARQLWrapper
from SPARQLWrapper.SPARQLExceptions import SPARQLWrapperException

# URL de l'endpoint SPARQL de ton dataset Fuseki.
# Peut être surchargée via la variable d'environnement FUSEKI_URL,
# utile si tu déploies Fuseki ailleurs que sur ta machine locale.
FUSEKI_URL = os.environ.get("FUSEKI_URL", "http://localhost:3030/skillpath/sparql")
FUSEKI_UPDATE_URL = os.environ.get(
    "FUSEKI_UPDATE_URL",
    FUSEKI_URL.removesuffix("/sparql") + "/update",
)

ONTOLOGY_NAMESPACE = "http://www.skillpath.tn/onto#"
SP_PREFIX = f"PREFIX sp: <{ONTOLOGY_NAMESPACE}>\n"
ONTO_PREFIX = f"PREFIX onto: <{ONTOLOGY_NAMESPACE}>\n"
COMMON_PREFIXES = (
    ONTO_PREFIX
    + "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    + "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    + "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
    + "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
)


class FusekiError(RuntimeError):
    """Raised when a Fuseki request cannot be completed."""


class InvalidPayloadError(ValueError):
    """Raised when CRUD input cannot be represented in the SkillPath ontology."""


ENTITY_CLASSES = {
    "Competence": "Competence",
    "Formation": "Formation",
    "Module": "Module",
    "Metier": "Metier",
    "FamilleMetier": "FamilleMetier",
    "ProfilUtilisateur": "ProfilUtilisateur",
    "Niveau": "Niveau",
    "Parcours": "Parcours",
    "Evaluation": "Evaluation",
}
NON_MANAGEABLE_CLASSES = {"CompetenceManquante", "ProfilEligible", "ParcoursOptimal"}

DATATYPE_PROPERTIES = {
    "aCodeESCO": "xsd:string",
    "aDateDebut": "xsd:dateTime",
    "aDateEvaluation": "xsd:dateTime",
    "aDureeHeures": "xsd:integer",
    "aOrdreFormations": "xsd:string",
    "aNiveau": "xsd:integer",
    "aNom": "xsd:string",
    "aScore": "xsd:integer",
}

# Propriétés dont le domaine est déclaré dans l'ontologie : elles ne peuvent être
# posées que sur un individu dont la classe est celle indiquée (ou une sous-classe).
PROPERTY_DOMAINS = {
    "aDateDebut": "Formation",
    "aDureeHeures": "Formation",
    "aOrdreFormations": "Parcours",
}

# Each entry is (predicate, direction, target class).
RELATIONS = {
    "Competence": {
        "occupations_that_require": ("requiert", "incoming", "Metier"),
        "trainings_that_teach": ("enseigne", "incoming", "Formation"),
        # Inverse de sp:moduleEnseigne (Module -> Competence).
        "taught_by_modules": ("moduleEnseigne", "incoming", "Module"),
    },
    "Formation": {
        "enseigne": ("enseigne", "outgoing", "Competence"),
        "aPourPrerequis": ("aPourPrerequis", "outgoing", "Formation"),
        "contientModule": ("contientModule", "outgoing", "Module"),
    },
    "Module": {
        "moduleEnseigne": ("moduleEnseigne", "outgoing", "Competence"),
        "formations": ("contientModule", "incoming", "Formation"),
    },
    "Metier": {
        "requiert": ("requiert", "outgoing", "Competence"),
        "appartientA": ("appartientA", "outgoing", "FamilleMetier"),
        "necessiteNiveau": ("necessiteNiveau", "outgoing", "Niveau"),
    },
    "FamilleMetier": {
        "metiers": ("appartientA", "incoming", "Metier"),
    },
    "ProfilUtilisateur": {
        "aAcquis": ("aAcquis", "outgoing", "Competence"),
        "vise": ("vise", "outgoing", "Metier"),
        "aSuivi": ("aSuivi", "outgoing", "Formation"),
        "parcours": ("suitParcours", "outgoing", "Parcours"),
        "evaluations": ("aPasseEvaluation", "outgoing", "Evaluation"),
        # Niveau global du profil : au plus un seul par profil (propriété fonctionnelle).
        "niveau": ("aPourNiveau", "outgoing", "Niveau"),
    },
    "Niveau": {
        "metiers": ("necessiteNiveau", "incoming", "Metier"),
        "profils": ("aPourNiveau", "incoming", "ProfilUtilisateur"),
    },
    "Parcours": {
        "contientFormation": ("contientFormation", "outgoing", "Formation"),
    },
    "Evaluation": {
        "profils": ("aPasseEvaluation", "incoming", "ProfilUtilisateur"),
    },
}


def _literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _resource_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", value):
        raise InvalidPayloadError("Identifiant de ressource invalide.")
    return value


def _typed_literal(property_name: str, value: object) -> str:
    datatype = DATATYPE_PROPERTIES[property_name]
    if datatype == "xsd:integer":
        if isinstance(value, bool):
            raise InvalidPayloadError(f"La propriété {property_name} attend un entier.")
        lexical_value = str(value)
        if not re.fullmatch(r"-?\d+", lexical_value):
            raise InvalidPayloadError(f"La propriété {property_name} attend un entier.")
        lexical = str(int(lexical_value))
        return f"{_literal(lexical)}^^{datatype}"
    if isinstance(value, (dict, list)) or value is None:
        raise InvalidPayloadError(f"La propriété {property_name} attend une valeur simple.")
    lexical_value = str(value)
    if datatype == "xsd:dateTime":
        if "T" not in lexical_value:
            raise InvalidPayloadError(
                f"La propriété {property_name} attend une date ISO-8601 avec une heure."
            )
        try:
            date_value = datetime.fromisoformat(lexical_value.replace("Z", "+00:00"))
        except ValueError as error:
            raise InvalidPayloadError(
                f"La propriété {property_name} attend une date ISO-8601."
            ) from error
        lexical_value = date_value.isoformat(timespec="seconds")
    return f"{_literal(lexical_value)}^^{datatype}"


def run_query(query: str) -> list[dict]:
    """
    Exécute une requête SPARQL SELECT sur Fuseki et retourne une liste
    de dictionnaires (une entrée par ligne de résultat), avec des valeurs
    déjà nettoyées (URI complète -> juste le nom local après le '#').
    """
    sparql = SPARQLWrapper(FUSEKI_URL)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    try:
        results = sparql.query().convert()
    except (SPARQLWrapperException, URLError, TimeoutError, OSError) as error:
        raise FusekiError("Fuseki est indisponible ou a rejeté la requête SPARQL.") from error

    rows = []
    for binding in results["results"]["bindings"]:
        row = {}
        for var, val in binding.items():
            value = val["value"]
            # Simplifie les URI complètes en juste le nom local (après #)
            if val["type"] == "uri" and "#" in value:
                value = value.split("#")[-1]
            row[var] = value
        rows.append(row)
    return rows


def run_update(query: str) -> None:
    sparql = SPARQLWrapper(FUSEKI_UPDATE_URL)
    sparql.setQuery(query)
    sparql.setMethod("POST")
    try:
        sparql.query()
    except (SPARQLWrapperException, URLError, TimeoutError, OSError) as error:
        raise FusekiError("Fuseki est indisponible ou a rejeté la mise à jour SPARQL.") from error


def competences_manquantes_query(profil: str) -> str:
    """Requête Q1 — Compétences manquantes pour un profil, vis-à-vis du métier visé."""
    return SP_PREFIX + f"""
    SELECT ?competence WHERE {{
        sp:{profil} sp:vise ?metier .
        ?metier sp:requiert ?competence .
        FILTER NOT EXISTS {{ sp:{profil} sp:aAcquis ?competence }}
    }}
    """


def competences_manquantes(profil: str) -> list[dict]:
    """Q1 — Compétences manquantes pour un profil, vis-à-vis du métier qu'il vise."""
    return run_query(competences_manquantes_query(profil))


def competences_requises(metier: str) -> list[dict]:
    """Compétences demandées par un métier."""
    query = SP_PREFIX + f"""
    SELECT ?competence WHERE {{
        sp:{metier} sp:requiert ?competence .
    }}
    """
    return run_query(query)


def metiers_accessibles_query(profil: str) -> str:
    """Requête Q2 — Métiers déjà accessibles avec les compétences actuelles du profil."""
    return SP_PREFIX + f"""
    SELECT DISTINCT ?metier WHERE {{
        ?metier sp:requiert ?comp .
        FILTER NOT EXISTS {{
            ?metier sp:requiert ?c2 .
            FILTER NOT EXISTS {{ sp:{profil} sp:aAcquis ?c2 }}
        }}
    }}
    """


def metiers_accessibles(profil: str) -> list[dict]:
    """Q2 — Métiers déjà accessibles avec les compétences actuelles du profil."""
    return run_query(metiers_accessibles_query(profil))


def chaine_prerequis(formation: str) -> list[dict]:
    """Q3 — Chaîne complète de prérequis d'une formation (transitivité)."""
    query = SP_PREFIX + f"""
    SELECT ?prereq WHERE {{
        sp:{formation} sp:aPourPrerequis+ ?prereq .
    }}
    """
    return run_query(query)


def parcours_optimal_query(profil: str) -> str:
    """
    Requête Q4 (maison) — Formation(s) à suivre en priorité : enseigne une
    compétence manquante, et tous ses prérequis directs sont déjà suivis par
    le profil.
    """
    return SP_PREFIX + f"""
    SELECT DISTINCT ?formation WHERE {{
        ?formation sp:enseigne ?comp .
        sp:{profil} sp:vise ?metier .
        ?metier sp:requiert ?comp .
        FILTER NOT EXISTS {{ sp:{profil} sp:aAcquis ?comp }}

        FILTER NOT EXISTS {{
            ?formation sp:aPourPrerequis ?prereq .
            FILTER NOT EXISTS {{ sp:{profil} sp:aSuivi ?prereq }}
        }}
    }}
    """


def parcours_optimal(profil: str) -> list[dict]:
    """
    Q4 (maison) — Formation(s) à suivre en priorité : enseigne une compétence
    manquante, et tous ses prérequis directs sont déjà suivis par le profil.
    """
    return run_query(parcours_optimal_query(profil))


def formations_recommandees(profil: str, metier: str) -> list[dict]:
    """Formations enseignant une compétence manquante pour le métier choisi."""
    query = SP_PREFIX + f"""
    SELECT DISTINCT ?formation WHERE {{
        ?formation sp:enseigne ?competence .
        sp:{metier} sp:requiert ?competence .
        FILTER NOT EXISTS {{ sp:{profil} sp:aAcquis ?competence }}

        FILTER NOT EXISTS {{
            ?formation sp:aPourPrerequis ?prereq .
            FILTER NOT EXISTS {{ sp:{profil} sp:aSuivi ?prereq }}
        }}
    }}
    """
    return run_query(query)


def formations_et_prerequis() -> list[dict]:
    """Renvoie le catalogue, les compétences enseignées directement ou par module, et prérequis."""
    query = COMMON_PREFIXES + """
    SELECT DISTINCT ?formation ?competence ?prereq WHERE {
        ?formation rdf:type ?formationClass .
        ?formationClass rdfs:subClassOf* onto:Formation .
        FILTER(STRSTARTS(STR(?formation), "http://www.skillpath.tn/onto#"))
        OPTIONAL {
            {
                ?formation onto:enseigne ?competence .
            }
            UNION
            {
                ?formation onto:contientModule ?module .
                ?module onto:moduleEnseigne ?competence .
            }
        }
        OPTIONAL { ?formation onto:aPourPrerequis ?prereq . }
    }
    """
    return run_query(query)


def competences_partagees_metiers() -> list[dict]:
    """Renvoie les compétences et métiers reliés par ``requiert``."""
    query = COMMON_PREFIXES + """
    SELECT DISTINCT ?competence ?competenceName ?metier ?metierName WHERE {
        ?metier rdf:type ?metierClass .
        ?metierClass rdfs:subClassOf* onto:Metier .
        ?metier onto:requiert ?competence .
        ?competence rdf:type ?competenceClass .
        ?competenceClass rdfs:subClassOf* onto:Competence .
        FILTER(STRSTARTS(STR(?metier), "http://www.skillpath.tn/onto#"))
        FILTER(STRSTARTS(STR(?competence), "http://www.skillpath.tn/onto#"))
        OPTIONAL { ?competence onto:aNom ?competenceName . }
        OPTIONAL { ?metier onto:aNom ?metierName . }
    }
    """
    return run_query(query)


def competences_non_enseignees() -> list[dict]:
    """Renvoie les compétences techniques/transverses sans formation enseignante."""
    query = COMMON_PREFIXES + """
    SELECT DISTINCT ?competence ?competenceCategory ?competenceName WHERE {
        VALUES ?competenceCategory {
            onto:CompetenceTechnique
            onto:CompetenceTransverse
        }
        ?competence rdf:type ?competenceClass .
        ?competenceClass rdfs:subClassOf* ?competenceCategory .
        FILTER(STRSTARTS(STR(?competence), "http://www.skillpath.tn/onto#"))
        OPTIONAL { ?competence onto:aNom ?competenceName . }
        FILTER NOT EXISTS {
            {
                ?formation rdf:type ?formationClass .
                ?formationClass rdfs:subClassOf* onto:Formation .
                ?formation onto:enseigne ?competence .
            }
            UNION
            {
                ?formation rdf:type ?formationClass .
                ?formationClass rdfs:subClassOf* onto:Formation .
                ?formation onto:contientModule ?module .
                ?module onto:moduleEnseigne ?competence .
            }
        }
    }
    """
    return run_query(query)


def competences_par_categorie() -> list[dict]:
    """Nombre de compétences par catégorie déclarée (technique / transverse).

    ``?category`` est fixé par ``VALUES`` et ``?competenceClass`` est le type
    direct : une compétence n'apparaît donc qu'une fois par catégorie correspondante.
    """
    query = COMMON_PREFIXES + """
    SELECT ?category (COUNT(DISTINCT ?competence) AS ?total) WHERE {
        VALUES ?category { onto:CompetenceTechnique onto:CompetenceTransverse }
        ?competence rdf:type ?competenceClass .
        ?competenceClass rdfs:subClassOf* ?category .
        FILTER(STRSTARTS(STR(?competence), "http://www.skillpath.tn/onto#"))
    }
    GROUP BY ?category
    ORDER BY DESC(?total)
    """
    return run_query(query)


def metiers_par_famille() -> list[dict]:
    """Nombre de métiers rattachés à chaque famille de métiers (``appartientA``)."""
    query = COMMON_PREFIXES + """
    SELECT ?family ?familyName (COUNT(DISTINCT ?metier) AS ?total) WHERE {
        ?metier rdf:type ?metierClass .
        ?metierClass rdfs:subClassOf* onto:Metier .
        ?metier onto:appartientA ?family .
        FILTER(STRSTARTS(STR(?metier), "http://www.skillpath.tn/onto#"))
        OPTIONAL { ?family onto:aNom ?familyName . }
    }
    GROUP BY ?family ?familyName
    ORDER BY DESC(?total)
    """
    return run_query(query)


def profils_par_type() -> list[dict]:
    """Nombre de profils par type le plus spécifique.

    Un individu peut être typé à la fois ``ProfilUtilisateur`` et
    ``ProfilEtudiant`` (ou ``ProfilProfessionnel``). La clause
    ``FILTER NOT EXISTS`` écarte le type générique dès qu'un sous-type plus
    précis existe, de sorte qu'un profil n'est jamais compté deux fois et que
    la somme des segments reste égale au nombre réel de profils.
    """
    query = COMMON_PREFIXES + """
    SELECT ?profileClass (COUNT(DISTINCT ?profil) AS ?total) WHERE {
        ?profil rdf:type ?profileClass .
        ?profileClass rdfs:subClassOf* onto:ProfilUtilisateur .
        FILTER(STRSTARTS(STR(?profil), "http://www.skillpath.tn/onto#"))
        FILTER NOT EXISTS {
            ?profil rdf:type ?specificProfileClass .
            ?specificProfileClass rdfs:subClassOf+ ?profileClass .
        }
    }
    GROUP BY ?profileClass
    ORDER BY DESC(?total)
    """
    return run_query(query)


def formations_par_type() -> list[dict]:
    """Nombre de formations par type le plus spécifique (en ligne / présentielle).

    Une formation peut être typée ``Formation`` *et* ``FormationEnLigne`` :
    seul le type le plus précis est conservé afin d'éviter tout double comptage.
    """
    query = COMMON_PREFIXES + """
    SELECT ?formationClass (COUNT(DISTINCT ?formation) AS ?total) WHERE {
        ?formation rdf:type ?formationClass .
        ?formationClass rdfs:subClassOf* onto:Formation .
        FILTER(STRSTARTS(STR(?formation), "http://www.skillpath.tn/onto#"))
        FILTER NOT EXISTS {
            ?formation rdf:type ?specificFormationClass .
            ?specificFormationClass rdfs:subClassOf+ ?formationClass .
        }
    }
    GROUP BY ?formationClass
    ORDER BY DESC(?total)
    """
    return run_query(query)


def individus_par_classe() -> list[dict]:
    """Nombre d'individus RDF par classe racine de l'ontologie (pas de comptage de classes)."""
    query = COMMON_PREFIXES + """
    SELECT ?rootClass (COUNT(DISTINCT ?individual) AS ?total) WHERE {
        VALUES ?rootClass {
            onto:Competence onto:Metier onto:FamilleMetier onto:Formation
            onto:Module onto:ProfilUtilisateur onto:Evaluation onto:Parcours onto:Niveau
        }
        ?individual rdf:type ?individualClass .
        ?individualClass rdfs:subClassOf* ?rootClass .
        FILTER(STRSTARTS(STR(?individual), "http://www.skillpath.tn/onto#"))
    }
    GROUP BY ?rootClass
    ORDER BY DESC(?total)
    """
    return run_query(query)


def formations_meta() -> list[dict]:
    """Classe, durée, label et prérequis déclarés pour chaque formation.

    Renvoie une ligne par couple (classe, prérequis) : la durée est optionnelle
    dans l'ontologie, donc ``duree`` peut être absente.
    """
    query = COMMON_PREFIXES + """
    SELECT DISTINCT ?formation ?class ?duree ?prereq ?label WHERE {
        ?formation rdf:type ?class .
        ?class rdfs:subClassOf* onto:Formation .
        FILTER(STRSTARTS(STR(?formation), "http://www.skillpath.tn/onto#"))
        OPTIONAL { ?formation onto:aDureeHeures ?duree . }
        OPTIONAL { ?formation onto:aPourPrerequis ?prereq . }
        OPTIONAL { ?formation onto:aNom ?label . }
    }
    """
    return run_query(query)


def catalogue_formations() -> list[dict]:
    """Return real training metadata, taught competencies, and prerequisites."""
    query = COMMON_PREFIXES + """
    SELECT DISTINCT ?formation ?label ?class ?duration
                    ?competence ?competenceLabel ?prereq ?prereqLabel WHERE {
        ?formation rdf:type ?formationClass .
        ?formationClass rdfs:subClassOf* onto:Formation .
        FILTER(STRSTARTS(STR(?formation), "http://www.skillpath.tn/onto#"))
        OPTIONAL {
            ?formation rdf:type ?class .
            ?class rdfs:subClassOf* onto:Formation .
            FILTER(?class != onto:Formation && ?class != owl:NamedIndividual)
        }
        OPTIONAL { ?formation onto:aNom ?label . }
        OPTIONAL { ?formation onto:aDureeHeures ?duration . }
        OPTIONAL {
            {
                ?formation onto:enseigne ?competence .
            }
            UNION
            {
                ?formation onto:contientModule ?module .
                ?module onto:moduleEnseigne ?competence .
            }
            OPTIONAL { ?competence onto:aNom ?competenceLabel . }
        }
        OPTIONAL {
            ?formation onto:aPourPrerequis ?prereq .
            OPTIONAL { ?prereq onto:aNom ?prereqLabel . }
        }
    }
    """
    rows = run_query(query)
    catalogue: dict[str, dict] = {}
    for row in rows:
        identifier = row["formation"]
        training = catalogue.setdefault(identifier, {
            "id": identifier,
            "nom": row.get("label") or identifier,
            "type": row.get("class") or "Formation",
            "duree_heures": None,
            "competences_enseignees": {},
            "prerequis": {},
        })
        if row.get("class") and row["class"] != "Formation":
            training["type"] = row["class"]
        duration = row.get("duration")
        if duration not in (None, ""):
            try:
                training["duree_heures"] = int(duration)
            except (TypeError, ValueError):
                training["duree_heures"] = None
        if competence := row.get("competence"):
            training["competences_enseignees"][competence] = (
                row.get("competenceLabel") or competence
            )
        if prerequisite := row.get("prereq"):
            training["prerequis"][prerequisite] = (
                row.get("prereqLabel") or prerequisite
            )
    return [
        {
            **training,
            "competences_enseignees": [
                {"id": identifier, "label": label}
                for identifier, label in sorted(training["competences_enseignees"].items())
            ],
            "prerequis": [
                {"id": identifier, "label": label}
                for identifier, label in sorted(training["prerequis"].items())
            ],
        }
        for training in sorted(catalogue.values(), key=lambda item: item["id"])
    ]


def _ordered_path_formations(identifier: str) -> list[dict[str, str]]:
    formations = _related_entities(identifier, "contientFormation", "outgoing")
    rows = run_query(COMMON_PREFIXES + f"""
        SELECT ?order WHERE {{ {_entity_uri(identifier)} onto:aOrdreFormations ?order . }}
    """)
    if not rows:
        return formations
    try:
        ordered_ids = json.loads(rows[0]["order"])
    except (KeyError, json.JSONDecodeError) as error:
        raise FusekiError(
            f"L'ordre des formations du parcours '{identifier}' est invalide."
        ) from error
    if not isinstance(ordered_ids, list) or not all(
        isinstance(training, str) for training in ordered_ids
    ) or len(ordered_ids) != len(set(ordered_ids)):
        raise FusekiError(f"L'ordre des formations du parcours '{identifier}' est invalide.")
    by_id = {formation["id"]: formation for formation in formations}
    ordered = [by_id[training] for training in ordered_ids if training in by_id]
    ordered_set = {training["id"] for training in ordered}
    ordered.extend(sorted(
        (formation for formation in formations if formation["id"] not in ordered_set),
        key=lambda formation: formation["id"],
    ))
    return ordered


def relations_graphe() -> list[dict]:
    """Renvoie les relations entre individus qui composent le graphe SkillPath."""
    query = SP_PREFIX + """
    SELECT DISTINCT ?source ?relation ?target WHERE {
        VALUES ?relation {
            sp:aAcquis
            sp:requiert
            sp:enseigne
            sp:aPourPrerequis
        }
        ?source ?relation ?target .
    }
    """
    return run_query(query)


def profil_details(profil: str) -> dict:
    """Renvoie le détail complet d'un profil : compétences acquises, métier visé, formations suivies."""
    query = SP_PREFIX + f"""
    SELECT ?propriete ?valeur WHERE {{
        sp:{profil} ?propriete ?valeur .
    }}
    """
    rows = run_query(query)
    details: dict[str, list[str]] = {}
    for r in rows:
        prop = r["propriete"]
        details.setdefault(prop, []).append(r["valeur"])
    return details


def competences_effectives(profil: str) -> list[dict]:
    """Compétences réellement acquises par un profil (liens ``aAcquis`` et ``aSuivi``).

    ``aSuivi`` est la seule relation du modèle qui atteste qu'une formation a
    effectivement été suivie/terminée : elle est écrite par ``PUT /account/profile``
    (champ ``completed_trainings``) et ``PUT /account/parcours/{id}/progress``.
    Un parcours simplement enregistré (``suitParcours`` / ``contientFormation``) ou
    une formation seulement recommandée ne crée aucun ``aSuivi`` et n'est donc
    jamais comptée comme une acquisition.

    La requête combine en ``UNION`` les compétences déclarées directement
    (``aAcquis``) et celles enseignées — directement (``enseigne``) ou via un
    module (``contientModule`` / ``moduleEnseigne``) — par une formation suivie.
    ``source`` vaut ``"direct"`` ou ``"formation"``.
    """
    query = SP_PREFIX + f"""
    SELECT DISTINCT ?competence ?competenceLabel ?source ?formation ?formationLabel WHERE {{
        {{
            sp:{profil} sp:aAcquis ?competence .
            BIND("direct" AS ?source)
        }}
        UNION
        {{
            sp:{profil} sp:aSuivi ?formation .
            ?formation sp:enseigne ?competence .
            BIND("formation" AS ?source)
        }}
        UNION
        {{
            sp:{profil} sp:aSuivi ?formation .
            ?formation sp:contientModule ?module .
            ?module sp:moduleEnseigne ?competence .
            BIND("formation" AS ?source)
        }}
        OPTIONAL {{ ?competence sp:aNom ?competenceLabel . }}
        OPTIONAL {{ ?formation sp:aNom ?formationLabel . }}
    }}
    """
    return run_query(query)


def recommendations_query(profil: str) -> str:
    """Score une compétence non acquise à partir de liens de l'ontologie."""
    profil = _resource_id(profil)
    return COMMON_PREFIXES + f"""
    SELECT
        ?candidate
        (SAMPLE(COALESCE(STR(?candidateName), STRAFTER(STR(?candidate), "#"))) AS ?name)
        (SUM(?points) AS ?score)
        (GROUP_CONCAT(DISTINCT ?explanation; SEPARATOR="|||") AS ?explanations)
    WHERE {{
        onto:{profil} onto:aAcquis ?acquired .
        OPTIONAL {{ ?acquired onto:aNom ?acquiredName . }}
        ?candidate rdf:type ?candidateClass .
        ?candidateClass rdfs:subClassOf* onto:Competence .
        OPTIONAL {{ ?candidate onto:aNom ?candidateName . }}
        FILTER NOT EXISTS {{ onto:{profil} onto:aAcquis ?candidate . }}

        {{
            ?occupation rdf:type ?occupationClass .
            ?occupationClass rdfs:subClassOf* onto:Metier .
            ?occupation onto:requiert ?acquired, ?candidate .
            OPTIONAL {{ ?occupation onto:aNom ?contextName . }}
            BIND(2 AS ?points)
            BIND(CONCAT(
                "Related to ",
                COALESCE(STR(?acquiredName), STRAFTER(STR(?acquired), "#")),
                ": both required by ",
                COALESCE(STR(?contextName), STRAFTER(STR(?occupation), "#")),
                "."
            ) AS ?explanation)
        }}
        UNION
        {{
            ?training rdf:type ?trainingClass .
            ?trainingClass rdfs:subClassOf* onto:Formation .
            ?training onto:enseigne ?acquired, ?candidate .
            OPTIONAL {{ ?training onto:aNom ?contextName . }}
            BIND(1 AS ?points)
            BIND(CONCAT(
                "Related to ",
                COALESCE(STR(?acquiredName), STRAFTER(STR(?acquired), "#")),
                ": both taught by ",
                COALESCE(STR(?contextName), STRAFTER(STR(?training), "#")),
                "."
            ) AS ?explanation)
        }}
        UNION
        {{
            ?training rdf:type ?trainingClass .
            ?trainingClass rdfs:subClassOf* onto:Formation .
            ?training onto:contientModule ?module .
            ?module onto:moduleEnseigne ?acquired, ?candidate .
            OPTIONAL {{ ?module onto:aNom ?contextName . }}
            BIND(1 AS ?points)
            BIND(CONCAT(
                "Related to ",
                COALESCE(STR(?acquiredName), STRAFTER(STR(?acquired), "#")),
                ": both taught by module ",
                COALESCE(STR(?contextName), STRAFTER(STR(?module), "#")),
                "."
            ) AS ?explanation)
        }}
        UNION
        {{
            ?occupation1 rdf:type ?occupationClass1 .
            ?occupationClass1 rdfs:subClassOf* onto:Metier .
            ?occupation1 onto:requiert ?acquired ;
                onto:appartientA ?family .
            ?occupation2 rdf:type ?occupationClass2 .
            ?occupationClass2 rdfs:subClassOf* onto:Metier .
            ?occupation2 onto:requiert ?candidate ;
                onto:appartientA ?family .
            OPTIONAL {{ ?family onto:aNom ?contextName . }}
            BIND(1 AS ?points)
            BIND(CONCAT(
                "Related to ",
                COALESCE(STR(?acquiredName), STRAFTER(STR(?acquired), "#")),
                ": occupations share the ",
                COALESCE(STR(?contextName), STRAFTER(STR(?family), "#")),
                " family."
            ) AS ?explanation)
        }}
    }}
    GROUP BY ?candidate
    ORDER BY DESC(?score) LCASE(?name) STR(?candidate)
    LIMIT 5
    """


def recommendations_teachings_query(competence_ids: list[str]) -> str:
    """Retourne les formations et modules qui enseignent les compétences données."""
    identifiers = [_resource_id(identifier) for identifier in competence_ids]
    if not identifiers:
        return ""
    values = " ".join(f"onto:{identifier}" for identifier in identifiers)
    return COMMON_PREFIXES + f"""
    SELECT DISTINCT ?competence ?name ?type ?duration WHERE {{
        VALUES ?competence {{ {values} }}
        {{
            ?resource rdf:type ?resourceClass .
            ?resourceClass rdfs:subClassOf* onto:Formation .
            ?resource onto:enseigne ?competence .
            BIND("Training" AS ?type)
        }}
        UNION
        {{
            ?resource rdf:type ?resourceClass .
            ?resourceClass rdfs:subClassOf* onto:Module .
            ?resource onto:moduleEnseigne ?competence .
            BIND("Module" AS ?type)
        }}
        OPTIONAL {{ ?resource onto:aNom ?resourceName . }}
        BIND(COALESCE(STR(?resourceName), STRAFTER(STR(?resource), "#")) AS ?name)
        OPTIONAL {{ ?resource onto:aDureeHeures ?duration . }}
    }}
    ORDER BY ?competence ?type LCASE(?name)
    """


def recommendations_for_profile(profil: str) -> list[dict]:
    """Top-five recommendations for the acquired skills on a profile."""
    rows = run_query(recommendations_query(profil))
    if not rows:
        return []

    competence_ids = [row["candidate"] for row in rows]
    teachings = run_query(recommendations_teachings_query(competence_ids))
    teachings_by_competence: dict[str, list[dict]] = {
        identifier: [] for identifier in competence_ids
    }
    seen_teachings: set[tuple[str, str, str, int | None]] = set()
    for row in teachings:
        raw_duration = row.get("duration")
        duration = int(raw_duration) if raw_duration not in (None, "") else None
        teaching = (
            row["competence"],
            row["type"],
            row["name"],
            duration,
        )
        if teaching in seen_teachings:
            continue
        seen_teachings.add(teaching)
        teachings_by_competence[row["competence"]].append({
            "name": row["name"],
            "type": row["type"],
            "duration_hours": duration,
        })

    return [
        {
            "competence": row["name"],
            "score": int(row["score"]),
            "explanations": [
                explanation
                for explanation in row.get("explanations", "").split("|||")
                if explanation
            ],
            "teachings": teachings_by_competence[row["candidate"]],
        }
        for row in rows
    ]


def career_bridges_query(profil: str) -> str:
    """All non-target occupations and their required skills, compared to a profile."""
    profil = _resource_id(profil)
    return COMMON_PREFIXES + f"""
        SELECT DISTINCT ?occupation ?occupationName ?family ?familyName
            ?competence ?competenceName ?covered WHERE {{
            ?occupation rdf:type ?occupationClass .
            ?occupationClass rdfs:subClassOf* onto:Metier .
            ?occupation onto:requiert ?competence .
            FILTER NOT EXISTS {{ onto:{profil} onto:vise ?occupation }}
            OPTIONAL {{ ?occupation onto:aNom ?occupationName . }}
            OPTIONAL {{
                ?occupation onto:appartientA ?family .
                OPTIONAL {{ ?family onto:aNom ?familyName . }}
            }}
            OPTIONAL {{ ?competence onto:aNom ?competenceName . }}
            BIND(
                EXISTS {{ onto:{profil} onto:aAcquis ?competence }}
                AS ?covered
            )
        }}
        ORDER BY LCASE(?occupationName) LCASE(?competenceName)
    """


def career_bridge_trainings_query(competence_ids: list[str]) -> str:
    """Training courses and contained modules that teach these competencies."""
    identifiers = [_resource_id(identifier) for identifier in competence_ids]
    if not identifiers:
        return ""
    values = " ".join(f"onto:{identifier}" for identifier in identifiers)
    return COMMON_PREFIXES + f"""
        SELECT DISTINCT ?competence ?training ?trainingName ?trainingDuration
            ?module ?moduleName ?moduleDuration WHERE {{
            VALUES ?competence {{ {values} }}
            ?training rdf:type ?trainingClass .
            ?trainingClass rdfs:subClassOf* onto:Formation .
            {{
                ?training onto:enseigne ?competence .
                OPTIONAL {{
                    ?training onto:contientModule ?module .
                    ?module onto:moduleEnseigne ?competence .
                }}
            }}
            UNION
            {{
                ?training onto:contientModule ?module .
                ?module onto:moduleEnseigne ?competence .
            }}
            OPTIONAL {{ ?training onto:aNom ?trainingName . }}
            OPTIONAL {{ ?training onto:aDureeHeures ?trainingDuration . }}
            OPTIONAL {{ ?module onto:aNom ?moduleName . }}
            OPTIONAL {{ ?module onto:aDureeHeures ?moduleDuration . }}
        }}
        ORDER BY ?competence LCASE(?trainingName) LCASE(?moduleName)
    """


def career_bridges_for_profile(profil: str) -> list[dict]:
    """Return occupations ranked by overlap with directly acquired profile skills."""
    profil = _resource_id(profil)
    rows = run_query(career_bridges_query(profil))
    if not rows:
        return []

    occupations: dict[str, dict] = {}
    for row in rows:
        occupation_id = row["occupation"]
        occupation = occupations.setdefault(occupation_id, {
            "occupationId": occupation_id,
            "occupation": row.get("occupationName") or occupation_id,
            "family": None,
            "competences": {},
        })
        family_name = row.get("familyName") or row.get("family")
        if family_name and (
            occupation["family"] is None or family_name < occupation["family"]
        ):
            occupation["family"] = family_name
        if competence_id := row.get("competence"):
            competence_name = row.get("competenceName") or competence_id
            covered = row.get("covered", "").lower() == "true"
            previous = occupation["competences"].get(competence_id)
            if previous is None or (covered and not previous["covered"]):
                occupation["competences"][competence_id] = {
                    "name": competence_name,
                    "covered": covered,
                }

    missing_ids = sorted({
        competence_id
        for occupation in occupations.values()
        for competence_id, competence in occupation["competences"].items()
        if not competence["covered"]
    })
    teaching_rows = (
        run_query(career_bridge_trainings_query(missing_ids)) if missing_ids else []
    )
    trainings_by_competence: dict[str, list[dict]] = {
        competence_id: [] for competence_id in missing_ids
    }
    training_index: dict[tuple[str, str], dict] = {}
    for row in teaching_rows:
        competence_id = row["competence"]
        training_id = row["training"]
        key = (competence_id, training_id)
        training = training_index.get(key)
        if training is None:
            training = {
                "id": training_id,
                "name": row.get("trainingName") or training_id,
                "durationHours": _diagnostic_duration(row.get("trainingDuration")),
                "modules": [],
            }
            training_index[key] = training
            trainings_by_competence[competence_id].append(training)
        module_id = row.get("module")
        if module_id and not any(
            module["id"] == module_id for module in training["modules"]
        ):
            training["modules"].append({
                "id": module_id,
                "name": row.get("moduleName") or module_id,
                "durationHours": _diagnostic_duration(row.get("moduleDuration")),
            })

    results = []
    for occupation in occupations.values():
        competences = occupation["competences"]
        covered = sorted(
            competence["name"]
            for competence in competences.values()
            if competence["covered"]
        )
        missing = sorted(
            (
                competence_id,
                competence["name"],
            )
            for competence_id, competence in competences.items()
            if not competence["covered"]
        )
        if not competences:
            continue
        results.append({
            "occupationId": occupation["occupationId"],
            "occupation": occupation["occupation"],
            "family": occupation["family"],
            "percent": round(len(covered) / len(competences) * 100),
            "coveredNames": covered,
            "missingNames": [name for _, name in missing],
            "trainings": [
                {
                    "competence": name,
                    "trainings": trainings_by_competence.get(competence_id, []),
                }
                for competence_id, name in missing
            ],
        })
    results.sort(key=lambda result: (-result["percent"], result["occupation"].casefold()))
    return results


# --------------------------------------------------------------------------
# Évaluation automatique et niveau global du profil (étudiant / professionnel).
# Le niveau n'est jamais saisi par un administrateur : il est déduit du score
# de l'évaluation automatique, et il n'existe qu'un seul niveau par profil.
# --------------------------------------------------------------------------

NIVEAU_DEBUTANT = "niv_Debutant"
NIVEAU_INTERMEDIAIRE = "niv_Intermediaire"
NIVEAU_AVANCE = "niv_Avance"


def niveau_pour_score(score: int) -> str:
    """Niveau global correspondant à un score de préparation (0-100)."""
    if score < 50:
        return NIVEAU_DEBUTANT
    if score < 80:
        return NIVEAU_INTERMEDIAIRE
    return NIVEAU_AVANCE


def _niveau_from_row(row: dict) -> dict:
    raw_value = row.get("value")
    try:
        value = int(raw_value) if raw_value not in (None, "") else None
    except (TypeError, ValueError):
        value = None
    return {
        "id": row["niveau"],
        "label": row.get("label") or row["niveau"],
        "value": value,
    }


def niveau_profil(profil: str) -> dict | None:
    """Niveau global déclaré pour un profil (au plus un ``aPourNiveau``)."""
    rows = run_query(COMMON_PREFIXES + f"""
        SELECT ?niveau ?label ?value WHERE {{
            {_entity_uri(profil)} onto:aPourNiveau ?niveau .
            OPTIONAL {{ ?niveau onto:aNom ?label . }}
            OPTIONAL {{ ?niveau onto:aNiveau ?value . }}
        }}
        LIMIT 1
    """)
    return _niveau_from_row(rows[0]) if rows else None


def niveau_requis_metier(metier: str) -> dict | None:
    """Niveau exigé par un métier (``sp:necessiteNiveau``), ou ``None``."""
    rows = run_query(COMMON_PREFIXES + f"""
        SELECT ?niveau ?label ?value WHERE {{
            {_entity_uri(metier)} onto:necessiteNiveau ?niveau .
            OPTIONAL {{ ?niveau onto:aNom ?label . }}
            OPTIONAL {{ ?niveau onto:aNiveau ?value . }}
        }}
        LIMIT 1
    """)
    return _niveau_from_row(rows[0]) if rows else None


def definir_niveau_profil(profil: str, niveau_id: str) -> None:
    """Remplace le niveau du profil : une seule valeur ``aPourNiveau`` au final.

    Seul le triplet ``<profil> sp:aPourNiveau ?`` est supprimé puis réécrit ;
    aucune autre donnée du profil n'est touchée.
    """
    profil = _resource_id(profil)
    niveau_id = _resource_id(niveau_id)
    run_update(COMMON_PREFIXES + f"""
        DELETE {{ {_entity_uri(profil)} onto:aPourNiveau ?ancien . }}
        INSERT {{ {_entity_uri(profil)} onto:aPourNiveau {_entity_uri(niveau_id)} . }}
        WHERE {{ OPTIONAL {{ {_entity_uri(profil)} onto:aPourNiveau ?ancien . }} }}
    """)


def evaluations_profil(profil: str) -> list[dict]:
    """Évaluations réellement passées par un profil (les plus récentes d'abord)."""
    profil = _resource_id(profil)
    prefix = f"eval_{profil}_"
    rows = run_query(COMMON_PREFIXES + f"""
        SELECT ?evaluation ?label ?score ?date WHERE {{
            {_entity_uri(profil)} onto:aPasseEvaluation ?evaluation .
            OPTIONAL {{ ?evaluation onto:aNom ?label . }}
            OPTIONAL {{ ?evaluation onto:aScore ?score . }}
            OPTIONAL {{ ?evaluation onto:aDateEvaluation ?date . }}
        }}
    """)
    evaluations = []
    for row in rows:
        identifier = row["evaluation"]
        raw_score = row.get("score")
        try:
            score = int(raw_score) if raw_score not in (None, "") else None
        except (TypeError, ValueError):
            score = None
        evaluations.append({
            "id": identifier,
            "label": row.get("label") or identifier,
            "score": score,
            "date": row.get("date"),
            "occupation": (
                identifier[len(prefix):] if identifier.startswith(prefix) else None
            ),
        })
    evaluations.sort(key=lambda item: item.get("date") or "", reverse=True)
    return evaluations


def diagnostic_competences_query(profil: str, metier: str) -> str:
    """Compétences requises, leurs noms et leur statut d'acquisition."""
    profil = _resource_id(profil)
    metier = _resource_id(metier)
    return COMMON_PREFIXES + f"""
        SELECT DISTINCT ?competence ?name ?mastered WHERE {{
            onto:{metier} onto:requiert ?competence .
            OPTIONAL {{ ?competence onto:aNom ?competenceName . }}
            BIND(
                COALESCE(
                    STR(?competenceName),
                    STRAFTER(STR(?competence), "#")
                ) AS ?name
            )
            BIND(
                EXISTS {{ onto:{profil} onto:aAcquis ?competence }}
                || EXISTS {{
                    onto:{profil} onto:aSuivi ?training .
                    ?training onto:enseigne ?competence .
                }}
                || EXISTS {{
                    onto:{profil} onto:aSuivi ?training .
                    ?training onto:contientModule ?module .
                    ?module onto:moduleEnseigne ?competence .
                }}
                AS ?mastered
            )
        }}
        ORDER BY LCASE(?name) STR(?competence)
    """


def diagnostic_suggestions_query(competence_ids: list[str]) -> str:
    """Trainings teaching missing skills and modules they contain."""
    identifiers = [_resource_id(identifier) for identifier in competence_ids]
    if not identifiers:
        return ""
    values = " ".join(f"onto:{identifier}" for identifier in identifiers)
    return COMMON_PREFIXES + f"""
        SELECT DISTINCT ?competence ?training ?trainingName ?trainingDuration
            ?module ?moduleName ?moduleDuration WHERE {{
            VALUES ?competence {{ {values} }}
            ?training onto:enseigne ?competence .
            OPTIONAL {{ ?training onto:aNom ?trainingName . }}
            OPTIONAL {{ ?training onto:aDureeHeures ?trainingDuration . }}
            OPTIONAL {{
                ?training onto:contientModule ?module .
                OPTIONAL {{ ?module onto:aNom ?moduleName . }}
                OPTIONAL {{ ?module onto:aDureeHeures ?moduleDuration . }}
            }}
        }}
        ORDER BY ?competence LCASE(?trainingName) LCASE(?moduleName)
    """


def _diagnostic_duration(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        duration = int(float(value))
    except (TypeError, ValueError):
        return None
    return duration if duration >= 0 else None


def _diagnostic_level(value: int | None) -> str | None:
    return {1: "Beginner", 2: "Intermediate", 3: "Advanced"}.get(value)


def evaluation_diagnostic(
    profil: str,
    metier: str | None,
    score: int | None = None,
) -> dict:
    """Build the template-based explanation from the profile's live SPARQL facts."""
    profil = _resource_id(profil)
    if metier is None:
        return {
            "strengths": [],
            "gaps": [],
            "levelReason": "No target occupation is available for this evaluation.",
            "nextLevel": None,
            "competencesToNextLevel": 0,
            "requiredLevelGap": None,
            "suggestions": [],
        }

    metier = _resource_id(metier)
    rows = run_query(diagnostic_competences_query(profil, metier))
    strengths = [row["name"] for row in rows if row.get("mastered", "").lower() == "true"]
    missing_rows = [row for row in rows if row.get("mastered", "").lower() != "true"]
    gaps = [row["name"] for row in missing_rows]
    total = len(rows)
    mastered = len(strengths)
    readiness = score if score is not None else (round(mastered / total * 100) if total else 0)

    required_level = niveau_requis_metier(metier)
    required_value = required_level.get("value") if required_level else None
    user_level_value = 1 if readiness < 50 else 2 if readiness < 80 else 3
    required_level_name = (
        _diagnostic_level(required_value)
        or (required_level.get("label") if required_level else None)
    )
    user_level_name = _diagnostic_level(user_level_value)
    required_level_gap = None
    if (
        required_level_name
        and required_value is not None
        and required_value > user_level_value
    ):
        required_level_gap = f"Required: {required_level_name}, yours: {user_level_name}"

    if readiness < 50:
        level_range, current_level = "0-49%", "Beginner"
        next_level, threshold = "Intermediate", 0.5
    elif readiness < 80:
        level_range, current_level = "50-79%", "Intermediate"
        next_level, threshold = "Advanced", 0.8
    else:
        level_range, current_level = "80-100%", "Advanced"
        next_level, threshold = None, None

    if total == 0:
        level_reason = "No required competences are defined for this occupation."
        next_level = None
        competences_to_next_level = 0
    else:
        level_reason = (
            f"Readiness {readiness}% is in the {level_range} range -> {current_level}"
        )
        competences_to_next_level = (
            max(0, math.ceil(threshold * total) - mastered)
            if threshold is not None
            else 0
        )

    missing_ids = [row["competence"] for row in missing_rows]
    suggestion_rows = (
        run_query(diagnostic_suggestions_query(missing_ids)) if missing_ids else []
    )
    suggestions_by_competence: dict[str, dict] = {
        row["competence"]: {
            "competence": row["name"],
            "trainings": [],
        }
        for row in missing_rows
    }
    training_index: dict[tuple[str, str], dict] = {}
    for row in suggestion_rows:
        competence = row["competence"]
        training_id = row["training"]
        suggestion = suggestions_by_competence[competence]
        key = (competence, training_id)
        training = training_index.get(key)
        if training is None:
            training = {
                "id": training_id,
                "name": row.get("trainingName") or training_id,
                "durationHours": _diagnostic_duration(row.get("trainingDuration")),
                "modules": [],
            }
            training_index[key] = training
            suggestion["trainings"].append(training)
        module_id = row.get("module")
        if module_id and not any(module["id"] == module_id for module in training["modules"]):
            training["modules"].append({
                "id": module_id,
                "name": row.get("moduleName") or module_id,
                "durationHours": _diagnostic_duration(row.get("moduleDuration")),
            })

    return {
        "strengths": strengths,
        "gaps": gaps,
        "levelReason": level_reason,
        "nextLevel": next_level,
        "competencesToNextLevel": competences_to_next_level,
        "requiredLevelGap": required_level_gap,
        "suggestions": list(suggestions_by_competence.values()),
    }


def remplacer_evaluation(
    profil: str,
    evaluation_id: str,
    nom: str,
    score: int,
    date_iso: str,
) -> None:
    """Crée ou remplace l'évaluation d'un profil pour un métier donné.

    La réexécution ne supprime que les triplets ayant cette évaluation pour
    sujet, et le lien ``<profil> sp:aPasseEvaluation <évaluation>`` : aucune
    autre évaluation ni aucune autre donnée du profil n'est modifiée.
    """
    profil = _resource_id(profil)
    evaluation_id = _resource_id(evaluation_id)
    evaluation_uri = _entity_uri(evaluation_id)
    run_update(COMMON_PREFIXES + f"""
        DELETE {{ {evaluation_uri} ?propriete ?valeur . }}
        WHERE {{ {evaluation_uri} ?propriete ?valeur . }}
    """)
    run_update(COMMON_PREFIXES + f"""
        DELETE WHERE {{ {_entity_uri(profil)} onto:aPasseEvaluation {evaluation_uri} . }}
    """)
    triples = [
        f"{evaluation_uri} rdf:type onto:EvaluationTechnique .",
        f"{evaluation_uri} rdf:type owl:NamedIndividual .",
        f"{evaluation_uri} onto:aNom {_typed_literal('aNom', nom)} .",
        f"{evaluation_uri} onto:aScore {_typed_literal('aScore', score)} .",
        f"{evaluation_uri} onto:aDateEvaluation {_typed_literal('aDateEvaluation', date_iso)} .",
        f"{_entity_uri(profil)} onto:aPasseEvaluation {evaluation_uri} .",
    ]
    run_update(COMMON_PREFIXES + "INSERT DATA { " + " ".join(triples) + " }")


def _entity_uri(identifier: str) -> str:
    return f"<{ONTOLOGY_NAMESPACE}{_resource_id(identifier)}>"


def _normalise_properties(entity_type: str, properties: object) -> dict[str, list[object]]:
    if not isinstance(properties, dict):
        raise InvalidPayloadError("'properties' doit être un objet.")
    base_class = ENTITY_CLASSES[entity_type]
    normalized: dict[str, list[object]] = {}
    for name, value in properties.items():
        if name not in DATATYPE_PROPERTIES:
            raise InvalidPayloadError(f"Propriété inconnue ou non modifiable : {name}.")
        domain = PROPERTY_DOMAINS.get(name)
        if domain is not None and base_class != domain:
            raise InvalidPayloadError(
                f"La propriété {name} n'est valide que pour {domain} (domaine ontologique)."
            )
        values = value if isinstance(value, list) else [value]
        normalized[name] = values
        for item in values:
            _typed_literal(name, item)
    return normalized


def entity_classes(entity_type: str) -> list[str]:
    if entity_type not in ENTITY_CLASSES:
        raise InvalidPayloadError(f"Type d'entité inconnu : {entity_type}.")
    base_class = ENTITY_CLASSES[entity_type]
    rows = run_query(COMMON_PREFIXES + f"""
        SELECT DISTINCT ?class WHERE {{
            ?class rdfs:subClassOf+ onto:{base_class} .
            FILTER(STRSTARTS(STR(?class), "http://www.skillpath.tn/onto#"))
        }}
    """)
    subclasses = sorted({
        row["class"]
        for row in rows
        if row["class"] not in NON_MANAGEABLE_CLASSES and row["class"] != base_class
    })
    return [base_class, *subclasses]


def _validate_entity_class(entity_type: str, entity_class: object | None) -> str:
    base_class = ENTITY_CLASSES[entity_type]
    if entity_class is None:
        return base_class
    if not isinstance(entity_class, str) or entity_class not in entity_classes(entity_type):
        raise InvalidPayloadError(f"La classe '{entity_class}' n'est pas valide pour {entity_type}.")
    return entity_class


def _normalise_relations(entity_type: str, relations: object) -> dict[str, list[str]]:
    if not isinstance(relations, dict):
        raise InvalidPayloadError("'relations' doit être un objet.")
    allowed = RELATIONS[entity_type]
    normalized: dict[str, list[str]] = {}
    for name, value in relations.items():
        if name not in allowed:
            raise InvalidPayloadError(f"Relation inconnue pour {entity_type} : {name}.")
        values = value if isinstance(value, list) else [value]
        normalized[name] = list(dict.fromkeys(_resource_id(item) for item in values))
    return normalized


def _property_triples(identifier: str, properties: dict[str, list[object]]) -> list[str]:
    subject = _entity_uri(identifier)
    return [
        f"{subject} onto:{name} {_typed_literal(name, value)} ."
        for name, values in properties.items()
        for value in values
    ]


def _relation_triples(
    entity_type: str, identifier: str, relations: dict[str, list[str]]
) -> list[str]:
    triples = []
    for name, targets in relations.items():
        predicate, direction, _ = RELATIONS[entity_type][name]
        for target in targets:
            target_uri = _entity_uri(target)
            if direction == "incoming":
                triples.append(f"{target_uri} onto:{predicate} {_entity_uri(identifier)} .")
            else:
                triples.append(f"{_entity_uri(identifier)} onto:{predicate} {target_uri} .")
    return triples


def _entity_is_typed(identifier: str, class_name: str) -> bool:
    """True si l'individu est typé (directement ou via une sous-classe) class_name."""
    query = COMMON_PREFIXES + f"""
    SELECT ?id WHERE {{
        BIND({_entity_uri(identifier)} AS ?id)
        ?id rdf:type ?assertedType .
        ?assertedType rdfs:subClassOf* onto:{class_name} .
    }}
    LIMIT 1
    """
    return bool(run_query(query))


def _ensure_related_entities_exist(entity_type: str, relations: dict[str, list[str]]) -> None:
    for relation_name, identifiers in relations.items():
        expected_type = RELATIONS[entity_type][relation_name][2]
        for identifier in identifiers:
            # Un Module n'est jamais une Formation : il ne peut pas être un prérequis,
            # même si les données le typent aussi comme sous-classe de Formation.
            if expected_type == "Formation" and _entity_is_typed(identifier, "Module"):
                raise InvalidPayloadError(
                    f"La ressource '{identifier}' est un Module : un Module ne peut pas être "
                    "un prérequis de formation."
                )
            if not _entity_is_typed(identifier, expected_type):
                raise InvalidPayloadError(
                    f"La ressource '{identifier}' n'existe pas comme {expected_type}."
                )


def _reject_self_prerequisite(
    entity_type: str, identifier: str, relations: dict[str, list[str]]
) -> None:
    if entity_type == "Formation" and identifier in relations.get("aPourPrerequis", []):
        raise InvalidPayloadError("Une formation ne peut pas être son propre prérequis.")


def list_individuals(
    entity_type: str, search: str | None = None, include_class: bool = False
) -> list[dict[str, str]]:
    if entity_type not in ENTITY_CLASSES:
        raise InvalidPayloadError(f"Type d'entité inconnu : {entity_type}.")
    class_name = ENTITY_CLASSES[entity_type]
    search_filter = ""
    if search:
        search_literal = _literal(search.lower())
        search_filter = f"""
            FILTER(
                CONTAINS(LCASE(STR(?id)), {search_literal})
                || CONTAINS(LCASE(STR(?label)), {search_literal})
            )
        """
    # Les listes de Formations ne doivent jamais exposer un Module, même si les
    # données typent un Module comme sous-classe de Formation.
    exclusion_filter = ""
    if entity_type == "Formation":
        exclusion_filter = """
            FILTER NOT EXISTS {
                ?id rdf:type ?moduleType .
                ?moduleType rdfs:subClassOf* onto:Module .
            }
        """
    rows = run_query(COMMON_PREFIXES + f"""
        SELECT DISTINCT ?id ?label ?assertedType WHERE {{
            ?id rdf:type ?assertedType .
            ?assertedType rdfs:subClassOf* onto:{class_name} .
            FILTER(STRSTARTS(STR(?id), "http://www.skillpath.tn/onto#"))
            FILTER(?assertedType != owl:NamedIndividual)
            {exclusion_filter}
            OPTIONAL {{ ?id onto:aNom ?label . }}
            {search_filter}
        }}
    """)
    entities: dict[str, dict[str, object]] = {}
    for row in rows:
        identifier = row["id"]
        entity = entities.setdefault(identifier, {"id": identifier, "label": identifier, "classes": set()})
        if row.get("label"):
            entity["label"] = row["label"]
        if row.get("assertedType") and row["assertedType"] != class_name:
            entity["classes"].add(row["assertedType"])
    result = []
    for entity in entities.values():
        item = {"id": str(entity["id"]), "label": str(entity["label"])}
        classes = sorted(entity["classes"])
        if include_class and classes:
            item["class"] = classes[0]
        result.append(item)
    return result


def _related_entities(identifier: str, predicate: str, direction: str) -> list[dict[str, str]]:
    entity_uri = _entity_uri(identifier)
    pattern = (
        f"?id onto:{predicate} {entity_uri} ."
        if direction == "incoming"
        else f"{entity_uri} onto:{predicate} ?id ."
    )
    rows = run_query(COMMON_PREFIXES + f"""
        SELECT DISTINCT ?id ?label WHERE {{
            {pattern}
            OPTIONAL {{ ?id onto:aNom ?label . }}
        }}
    """)
    return [
        {"id": row["id"], "label": row.get("label") or row["id"]}
        for row in rows
    ]


def get_entity_detail(entity_type: str, identifier: str) -> dict | None:
    if entity_type not in ENTITY_CLASSES:
        raise InvalidPayloadError(f"Type d'entité inconnu : {entity_type}.")
    entity_uri = _entity_uri(identifier)
    rows = run_query(COMMON_PREFIXES + f"""
        SELECT ?property ?value WHERE {{
            {entity_uri} ?property ?value .
        }}
    """)
    if not rows:
        return None

    class_rows = run_query(COMMON_PREFIXES + f"""
        SELECT DISTINCT ?class WHERE {{
            {entity_uri} rdf:type ?class .
            ?class rdfs:subClassOf* onto:{ENTITY_CLASSES[entity_type]} .
            FILTER(?class != onto:{ENTITY_CLASSES[entity_type]})
        }}
    """)
    entity_class = next(
        (row["class"] for row in class_rows if row["class"] not in NON_MANAGEABLE_CLASSES),
        ENTITY_CLASSES[entity_type],
    )

    relation_predicates = {
        predicate
        for entity_relations in RELATIONS.values()
        for predicate, _, _ in entity_relations.values()
    }
    properties: dict[str, list[str]] = {}
    for row in rows:
        property_name = row["property"]
        if property_name not in relation_predicates and property_name != "type":
            properties.setdefault(property_name, []).append(row["value"])

    relations: dict[str, list[dict[str, str]]] = {}
    for name, (predicate, direction, _) in RELATIONS[entity_type].items():
        relations[name] = _related_entities(identifier, predicate, direction)
    if entity_type == "ProfilUtilisateur":
        relations["parcours"] = [
            {
                **path,
                "formations": _ordered_path_formations(path["id"]),
            }
            for path in relations["parcours"]
        ]

    label_values = properties.get("aNom", [])
    return {
        "id": identifier,
        "type": entity_type,
        "class": entity_class,
        "label": label_values[0] if label_values else identifier,
        "properties": properties,
        "relations": relations,
    }


def get_stats() -> dict[str, int]:
    count_queries = [
        ("competences", "Competence"),
        ("metiers", "Metier"),
        ("formations", "Formation"),
        ("profils", "ProfilUtilisateur"),
        ("modules", "Module"),
        ("parcours", "Parcours"),
        ("evaluations", "Evaluation"),
    ]
    subqueries = "\n".join(
        f"""
        {{ SELECT (COUNT(DISTINCT ?{key}Item) AS ?{key}) WHERE {{
            ?{key}Item rdf:type ?{key}Type .
            ?{key}Type rdfs:subClassOf* onto:{class_name} .
            FILTER(STRSTARTS(STR(?{key}Item), "http://www.skillpath.tn/onto#"))
        }} }}
        """
        for key, class_name in count_queries
    )
    rows = run_query(COMMON_PREFIXES + f"SELECT * WHERE {{ {subqueries} }}")
    if not rows:
        return {key: 0 for key, _ in count_queries}
    return {key: int(rows[0].get(key, 0)) for key, _ in count_queries}


def create_entity(
    entity_type: str,
    identifier: str,
    properties: object,
    relations: object,
    entity_class: object | None = None,
) -> None:
    if entity_type not in ENTITY_CLASSES:
        raise InvalidPayloadError(f"Type d'entité inconnu : {entity_type}.")
    identifier = _resource_id(identifier)
    selected_class = _validate_entity_class(entity_type, entity_class)
    existing = run_query(COMMON_PREFIXES + f"""
        SELECT ?id WHERE {{ BIND({_entity_uri(identifier)} AS ?id) ?id ?p ?o . }}
        LIMIT 1
    """)
    if existing:
        raise InvalidPayloadError(f"L'identifiant '{identifier}' existe déjà.")
    normalized_properties = _normalise_properties(entity_type, properties)
    normalized_relations = _normalise_relations(entity_type, relations)
    _reject_self_prerequisite(entity_type, identifier, normalized_relations)
    _ensure_related_entities_exist(entity_type, normalized_relations)
    triples = [
        f"{_entity_uri(identifier)} rdf:type onto:{ENTITY_CLASSES[entity_type]} .",
        f"{_entity_uri(identifier)} rdf:type onto:{selected_class} .",
        f"{_entity_uri(identifier)} rdf:type owl:NamedIndividual .",
        *_property_triples(identifier, normalized_properties),
        *_relation_triples(entity_type, identifier, normalized_relations),
    ]
    run_update(COMMON_PREFIXES + "INSERT DATA { " + " ".join(triples) + " }")


def update_entity(
    entity_type: str,
    identifier: str,
    properties: object,
    relations: object,
    entity_class: object | None = None,
) -> None:
    if entity_type not in ENTITY_CLASSES:
        raise InvalidPayloadError(f"Type d'entité inconnu : {entity_type}.")
    identifier = _resource_id(identifier)
    normalized_properties = _normalise_properties(entity_type, properties)
    normalized_relations = _normalise_relations(entity_type, relations)
    _reject_self_prerequisite(entity_type, identifier, normalized_relations)
    selected_class = (
        _validate_entity_class(entity_type, entity_class)
        if entity_class is not None
        else None
    )
    if not normalized_properties and not normalized_relations and selected_class is None:
        raise InvalidPayloadError("Au moins une propriété ou relation doit être fournie.")
    _ensure_related_entities_exist(entity_type, normalized_relations)
    entity_uri = _entity_uri(identifier)

    if selected_class is not None:
        base_class = ENTITY_CLASSES[entity_type]
        run_update(COMMON_PREFIXES + f"""
            DELETE {{ {entity_uri} rdf:type ?oldClass . }}
            INSERT {{
                {entity_uri} rdf:type onto:{base_class} .
                {entity_uri} rdf:type onto:{selected_class} .
            }}
            WHERE {{
                OPTIONAL {{
                    {entity_uri} rdf:type ?oldClass .
                    ?oldClass rdfs:subClassOf+ onto:{base_class} .
                }}
            }}
        """)

    for name, values in normalized_properties.items():
        if values:
            new_triples = " ".join(
                f"{entity_uri} onto:{name} {_typed_literal(name, value)} ."
                for value in values
            )
            update = f"""
                DELETE {{ {entity_uri} onto:{name} ?oldValue . }}
                INSERT {{ {new_triples} }}
                WHERE {{ OPTIONAL {{ {entity_uri} onto:{name} ?oldValue . }} }}
            """
        else:
            update = f"DELETE WHERE {{ {entity_uri} onto:{name} ?oldValue . }}"
        run_update(COMMON_PREFIXES + update)

    for name, targets in normalized_relations.items():
        predicate, direction, _ = RELATIONS[entity_type][name]
        if direction == "incoming":
            old_pattern = f"?oldSubject onto:{predicate} {entity_uri} ."
            new_triples = " ".join(
                f"{_entity_uri(target)} onto:{predicate} {entity_uri} ."
                for target in targets
            )
        else:
            old_pattern = f"{entity_uri} onto:{predicate} ?oldValue ."
            new_triples = " ".join(
                f"{entity_uri} onto:{predicate} {_entity_uri(target)} ."
                for target in targets
            )
        if new_triples:
            update = f"""
                DELETE {{ {old_pattern} }}
                INSERT {{ {new_triples} }}
                WHERE {{ OPTIONAL {{ {old_pattern} }} }}
            """
        else:
            update = f"DELETE WHERE {{ {old_pattern} }}"
        run_update(COMMON_PREFIXES + update)


def add_followed_trainings(identifier: str, training_ids: list[str]) -> None:
    """Append followed-trainings links without deleting other profile relations."""
    identifier = _resource_id(identifier)
    normalized = _normalise_relations("ProfilUtilisateur", {"aSuivi": training_ids})
    _ensure_related_entities_exist("ProfilUtilisateur", normalized)
    triples = _relation_triples("ProfilUtilisateur", identifier, normalized)
    if triples:
        run_update(COMMON_PREFIXES + "INSERT DATA { " + " ".join(triples) + " }")


def delete_entity(identifier: str) -> int:
    entity_uri = _entity_uri(identifier)
    dependencies = run_query(COMMON_PREFIXES + f"""
        SELECT (COUNT(*) AS ?count) WHERE {{
            ?source ?predicate {entity_uri} .
            FILTER(?source != {entity_uri})
        }}
    """)
    dependency_count = int(dependencies[0]["count"]) if dependencies else 0
    if dependency_count:
        return dependency_count
    run_update(COMMON_PREFIXES + f"DELETE WHERE {{ {entity_uri} ?predicate ?value . }}")
    return 0

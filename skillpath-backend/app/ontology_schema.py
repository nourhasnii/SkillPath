"""
Schéma de l'ontologie SkillPath, chargé depuis Fuseki puis mis en cache.

Le module TALN a besoin de connaître, sans les coder en dur :

* les classes de l'ontologie et leur hiérarchie (``rdfs:subClassOf``) ;
* les propriétés d'objet avec leur domaine et leur co-domaine ;
* les propriétés de données.

Tout est récupéré une seule fois au démarrage via SPARQL, converti en objets
immuables, puis conservé en mémoire (``get_schema``). Si Fuseki est injoignable,
un schéma de repli est construit à partir des constantes déjà présentes dans
``sparql_client`` (``ENTITY_CLASSES`` / ``RELATIONS`` / ``DATATYPE_PROPERTIES``)
afin que l'assistant continue de fonctionner en mode dégradé.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from . import sparql_client as sp


@dataclass(frozen=True)
class ClassInfo:
    """Classe RDF de l'ontologie."""

    name: str
    label: str = ""
    superclasses: tuple[str, ...] = ()
    subclasses: tuple[str, ...] = ()


@dataclass(frozen=True)
class PropertyInfo:
    """Propriété d'objet ou de donnée."""

    name: str
    kind: str  # "object" | "data"
    label: str = ""
    domains: tuple[str, ...] = ()
    ranges: tuple[str, ...] = ()


@dataclass(frozen=True)
class OntologySchema:
    """Instantané immuable du schéma de l'ontologie."""

    classes: dict[str, ClassInfo]
    object_properties: dict[str, PropertyInfo]
    data_properties: dict[str, PropertyInfo]
    source: str = "fuseki"

    # -- interrogations -------------------------------------------------

    def class_names(self) -> list[str]:
        return sorted(self.classes)

    def has_class(self, name: str) -> bool:
        return name in self.classes

    def property(self, name: str) -> PropertyInfo | None:
        return self.object_properties.get(name) or self.data_properties.get(name)

    def ancestors(self, name: str) -> list[str]:
        """Classe et tous ses ancêtres (transitivement)."""
        seen: list[str] = []
        stack = [name]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.append(current)
            info = self.classes.get(current)
            if info:
                stack.extend(info.superclasses)
        return seen

    def is_subclass_of(self, child: str, parent: str) -> bool:
        """Vrai si ``child`` est ``parent`` ou une de ses sous-classes."""
        return parent in self.ancestors(child)


_SCHEMA_LOCK = threading.Lock()
_SCHEMA: OntologySchema | None = None


def _load_from_fuseki() -> OntologySchema:
    """Lit classes, hiérarchie, propriétés d'objet et de données depuis Fuseki."""
    namespace = sp.ONTOLOGY_NAMESPACE

    class_rows = sp.run_query(sp.COMMON_PREFIXES + f"""
    SELECT DISTINCT ?class ?super ?label WHERE {{
        ?class rdf:type owl:Class .
        FILTER(STRSTARTS(STR(?class), "{namespace}"))
        OPTIONAL {{
            ?class rdfs:subClassOf ?super .
            FILTER(STRSTARTS(STR(?super), "{namespace}"))
        }}
        OPTIONAL {{ ?class rdfs:label ?label . }}
    }}
    """)

    supers: dict[str, set[str]] = {}
    labels: dict[str, str] = {}
    for row in class_rows:
        name = row.get("class")
        if not name:
            continue
        supers.setdefault(name, set())
        if row.get("super"):
            supers[name].add(row["super"])
        if row.get("label") and name not in labels:
            labels[name] = row["label"]

    if not supers:
        raise sp.FusekiError("Le schéma de l'ontologie n'a retourné aucune classe.")

    subclasses: dict[str, set[str]] = {name: set() for name in supers}
    for child, parents in supers.items():
        for parent in parents:
            subclasses.setdefault(parent, set()).add(child)

    classes = {
        name: ClassInfo(
            name=name,
            label=labels.get(name, name),
            superclasses=tuple(sorted(parents)),
            subclasses=tuple(sorted(subclasses.get(name, set()))),
        )
        for name, parents in supers.items()
    }

    def load_properties(owl_type: str, kind: str) -> dict[str, PropertyInfo]:
        rows = sp.run_query(sp.COMMON_PREFIXES + f"""
        SELECT DISTINCT ?property ?domain ?range ?label WHERE {{
            ?property rdf:type owl:{owl_type} .
            FILTER(STRSTARTS(STR(?property), "{namespace}"))
            OPTIONAL {{
                ?property rdfs:domain ?domain .
                FILTER(STRSTARTS(STR(?domain), "{namespace}"))
            }}
            OPTIONAL {{
                ?property rdfs:range ?range .
                FILTER(STRSTARTS(STR(?range), "{namespace}"))
            }}
            OPTIONAL {{ ?property rdfs:label ?label . }}
        }}
        """)
        domains: dict[str, set[str]] = {}
        ranges: dict[str, set[str]] = {}
        property_labels: dict[str, str] = {}
        for row in rows:
            name = row.get("property")
            if not name:
                continue
            domains.setdefault(name, set())
            ranges.setdefault(name, set())
            if row.get("domain"):
                domains[name].add(row["domain"])
            if row.get("range"):
                ranges[name].add(row["range"])
            if row.get("label") and name not in property_labels:
                property_labels[name] = row["label"]
        return {
            name: PropertyInfo(
                name=name,
                kind=kind,
                label=property_labels.get(name, name),
                domains=tuple(sorted(domains[name])),
                ranges=tuple(sorted(ranges[name])),
            )
            for name in domains
        }

    object_properties = load_properties("ObjectProperty", "object")
    data_properties = load_properties("DatatypeProperty", "data")
    if not object_properties and not data_properties:
        raise sp.FusekiError("Le schéma de l'ontologie n'a retourné aucune propriété.")

    return OntologySchema(
        classes=classes,
        object_properties=object_properties,
        data_properties=data_properties,
        source="fuseki",
    )


def fallback_schema() -> OntologySchema:
    """Schéma minimal reconstruit à partir des constantes de ``sparql_client``."""
    classes = {
        name: ClassInfo(name=name, label=name) for name in sp.ENTITY_CLASSES
    }
    object_properties: dict[str, PropertyInfo] = {}
    for entity_type, relations in sp.RELATIONS.items():
        for predicate, direction, target in relations.values():
            domain = entity_type if direction == "outgoing" else target
            range_ = target if direction == "outgoing" else entity_type
            current = object_properties.get(predicate) or PropertyInfo(
                name=predicate, kind="object", label=predicate
            )
            object_properties[predicate] = PropertyInfo(
                name=predicate,
                kind="object",
                label=current.label,
                domains=tuple(sorted(set(current.domains) | {domain})),
                ranges=tuple(sorted(set(current.ranges) | {range_})),
            )
    data_properties = {
        name: PropertyInfo(name=name, kind="data", label=name)
        for name in sp.DATATYPE_PROPERTIES
    }
    return OntologySchema(
        classes=classes,
        object_properties=object_properties,
        data_properties=data_properties,
        source="fallback",
    )


def get_schema(*, force: bool = False) -> OntologySchema:
    """Retourne le schéma mis en cache, en le chargeant au premier appel."""
    global _SCHEMA
    if _SCHEMA is not None and not force:
        return _SCHEMA
    with _SCHEMA_LOCK:
        if _SCHEMA is not None and not force:
            return _SCHEMA
        try:
            _SCHEMA = _load_from_fuseki()
        except Exception:  # noqa: BLE001 - mode dégradé volontaire
            _SCHEMA = fallback_schema()
        return _SCHEMA


def reset_schema() -> None:
    """Vide le cache du schéma (utilisé par les tests)."""
    global _SCHEMA
    _SCHEMA = None

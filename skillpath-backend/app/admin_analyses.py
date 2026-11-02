"""Ontology-backed reports used by the SkillPath administration dashboard."""

import re

from . import sparql_client as sp

COMPETENCY_CATEGORY_LABELS = {
    "CompetenceTechnique": "Technical competencies",
    "CompetenceTransverse": "Transversal competencies",
}

PROFILE_TYPE_LABELS = {
    "ProfilEtudiant": "Students",
    "ProfilProfessionnel": "Professionals",
    "ProfilUtilisateur": "Other profiles",
}

TRAINING_TYPE_LABELS = {
    "FormationEnLigne": "Online trainings",
    "FormationPresentielle": "In-person trainings",
    "Formation": "Unclassified trainings",
    # Module is a subclass of Formation in the ontology, so module individuals
    # legitimately appear in the trainings distribution.
    "ModuleTechnique": "Technical modules",
    "ModuleTransverse": "Transversal modules",
}

ROOT_CLASS_LABELS = {
    "Competence": "Competencies",
    "Metier": "Occupations",
    "FamilleMetier": "Occupation families",
    "Formation": "Trainings",
    "Module": "Modules",
    "ProfilUtilisateur": "Profiles",
    "Evaluation": "Evaluations",
    "Parcours": "Learning paths",
    "Niveau": "Levels",
}


def _humanize(identifier: str) -> str:
    """Turn an ontology local name into a readable label without exposing IRIs."""
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", identifier).replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else identifier


def _count(row: dict) -> int:
    try:
        return int(row.get("total") or 0)
    except (TypeError, ValueError):
        return 0


def _segments(rows: list[dict], key_field: str, labels: dict[str, str]) -> list[dict]:
    """Normalize aggregated SPARQL rows into labelled distribution segments."""
    segments = []
    for row in rows:
        key = row.get(key_field)
        if not key:
            continue
        segments.append({
            "key": key,
            "label": labels.get(key) or _humanize(key),
            "count": _count(row),
        })
    segments.sort(key=lambda segment: (-segment["count"], segment["label"].casefold()))
    return segments


def occupations_by_family() -> list[dict]:
    """Occupations per job family, plus the ones without a declared family."""
    segments = []
    for row in sp.metiers_par_famille():
        family_id = row.get("family")
        if not family_id:
            continue
        segments.append({
            "key": family_id,
            "label": row.get("familyName") or _humanize(family_id),
            "count": _count(row),
        })

    total_occupations = sp.get_stats().get("metiers", 0)
    unassigned = total_occupations - sum(segment["count"] for segment in segments)
    if unassigned > 0:
        segments.append({
            "key": "__unassigned__",
            "label": "No family declared",
            "count": unassigned,
        })

    segments.sort(key=lambda segment: (-segment["count"], segment["label"].casefold()))
    return segments


def repository_overview() -> list[dict]:
    """Individuals per ontology root class, using the real class/individual counts."""
    segments = []
    for row in sp.individus_par_classe():
        class_name = row.get("rootClass")
        if not class_name:
            continue
        segments.append({
            "key": class_name,
            "label": ROOT_CLASS_LABELS.get(class_name) or _humanize(class_name),
            "count": _count(row),
        })
    segments.sort(key=lambda segment: (-segment["count"], segment["label"].casefold()))
    return segments


def dashboard_analytics() -> dict:
    """Aggregated knowledge-base analytics for the administration dashboard.

    Every value is computed from real individuals and relationships stored in
    Fuseki. Nothing is estimated or padded: a category with no individual is
    simply absent from its distribution.
    """
    return {
        "competencyDistribution": _segments(
            sp.competences_par_categorie(), "category", COMPETENCY_CATEGORY_LABELS
        ),
        "occupationsByFamily": occupations_by_family(),
        "profilesDistribution": _segments(
            sp.profils_par_type(), "profileClass", PROFILE_TYPE_LABELS
        ),
        "trainingsDistribution": _segments(
            sp.formations_par_type(), "formationClass", TRAINING_TYPE_LABELS
        ),
        "repositoryOverview": repository_overview(),
    }


def shared_competencies() -> dict:
    """List each competency required by at least two distinct occupations."""
    grouped: dict[str, dict] = {}
    for row in sp.competences_partagees_metiers():
        competency_id = row["competence"]
        competency = grouped.setdefault(
            competency_id,
            {
                "id": competency_id,
                "name": row.get("competenceName") or competency_id,
                "occupations": {},
            },
        )
        occupation_id = row["metier"]
        competency["occupations"][occupation_id] = {
            "id": occupation_id,
            "name": row.get("metierName") or occupation_id,
        }

    competencies = []
    for competency in grouped.values():
        occupations = sorted(
            competency["occupations"].values(),
            key=lambda occupation: (occupation["name"].casefold(), occupation["id"]),
        )
        if len(occupations) < 2:
            continue
        competencies.append({
            "id": competency["id"],
            "name": competency["name"],
            "occupation_count": len(occupations),
            "occupations": occupations,
        })

    competencies.sort(key=lambda competency: (competency["name"].casefold(), competency["id"]))
    return {"total_competencies": len(competencies), "competencies": competencies}


def untaught_competencies() -> dict:
    """List technical and transversal competencies no catalogue training teaches."""
    competencies_by_id: dict[str, dict[str, str]] = {}
    for row in sp.competences_non_enseignees():
        competency_id = row["competence"]
        category = row["competenceCategory"]
        competencies_by_id[competency_id] = {
            "id": competency_id,
            "name": row.get("competenceName") or competency_id,
            "class": category,
        }

    competencies = sorted(
        competencies_by_id.values(),
        key=lambda competency: (competency["name"].casefold(), competency["id"]),
    )
    return {"total_competencies": len(competencies), "competencies": competencies}

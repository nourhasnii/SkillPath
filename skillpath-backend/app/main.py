"""
SkillPath — Backend API

Couche "Back-end" du schéma d'architecture officiel du projet :

    Front-end --(question)--> API IA --(SPARQL)--> API Fuseki --> Back-end (ce fichier) --> Fuseki --> Protégé/OWL

Ce backend expose les analyses validées manuellement dans Fuseki, sous forme de
routes REST/JSON, ainsi qu'un module TALN local (``app/nlp.py``) qui traduit une
question en langage naturel en requête SPARQL SELECT (sans aucune API de type
LLM), via ``POST /nlp/query`` et ``GET /nlp/examples``.

Lancer en local :
    uvicorn app.main:app --reload --port 8000

Puis ouvrir : http://localhost:8000/docs (interface Swagger auto-générée)
"""

import os
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import auth_store
from . import learning_path_generator
from . import nlp
from . import sparql_client as sp
from .admin_seeder import seed_admin_account
from .auth import (
    account_router,
    admin_router,
    get_current_account,
    require_admin,
)
from .auth import (
    router as auth_router,
)
from .auth_store import Account

BACKEND_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(BACKEND_ENV_FILE, override=False)


def initialize_auth_database() -> None:
    print("SkillPath startup: initializing authentication store.", flush=True)
    auth_store.initialize_store()
    print("SkillPath startup: running Admin seeder.", flush=True)
    seed_admin_account()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    initialize_auth_database()
    yield


app = FastAPI(
    title="SkillPath API",
    description="Analyseur intelligent d'écarts de compétences — Backend RDFLib/SPARQL sur Fuseki",
    version="0.1.0",
    lifespan=lifespan,
)

allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(auth_router)
app.include_router(account_router)
app.include_router(admin_router)


@app.middleware("http")
async def validate_request_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Origine de requête interdite."})
        if request.cookies.get("skillpath_session") and not origin:
            return JSONResponse(
                status_code=403,
                content={"detail": "En-tête Origin requis pour une requête authentifiée."},
            )
    return await call_next(request)

@app.exception_handler(sp.FusekiError)
async def fuseki_error_handler(_, error: sp.FusekiError):
    return JSONResponse(status_code=502, content={"detail": str(error)})


@app.get("/")
def root():
    return {
        "projet": "SkillPath",
        "endpoints": [
            "/api/profile/{profil}",
            "/me/recommendations",
            "/me/career-bridges",
            "/profils/{profil}",
            "/profils/{profil}/competences-manquantes",
            "/profils/{profil}/metiers-accessibles",
            "/profils/{profil}/parcours-optimal",
            "/formations/{formation}/chaine-prerequis",
            "/nlp/query",
            "/nlp/examples",
        ],
    }


@app.post("/nlp/query")
def nlp_query(
    body: Any = Body(None),
    account: Account = Depends(get_current_account),
):
    """Traduit une question en langage naturel en SPARQL SELECT et l'exécute.

    La question brute n'est jamais injectée dans la requête : seuls des patrons
    SELECT et des IRI validés de l'ontologie sont utilisés. Une entité non
    résolue renvoie une réponse 200 avec un message explicite plutôt qu'un
    SPARQL invalide.

    Le rôle et l'identifiant de profil proviennent **exclusivement du jeton
    d'authentification vérifié** : tout champ ``profil`` ou ``role`` présent
    dans le corps de la requête est ignoré. Le profil du jeton sert aux
    intentions dédiées (« mes » compétences, parcours optimal…). Si le rôle
    connecté n'est pas autorisé pour l'intention détectée, aucun SPARQL n'est
    généré et aucune donnée n'est retournée.
    """
    if not isinstance(body, dict) or not isinstance(body.get("question"), str):
        raise HTTPException(
            status_code=400,
            detail="Le corps doit contenir un champ 'question' de type texte.",
        )
    try:
        return nlp.analyze_question(
            body["question"], account.profile_iri, account.role
        )
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error


@app.get("/nlp/examples")
def nlp_examples(account: Account = Depends(get_current_account)):
    """Questions d'exemple autorisées pour le rôle connecté."""
    return nlp.examples_payload(account.role)


@app.get("/me/recommendations")
def me_recommendations(account: Account = Depends(get_current_account)):
    """Recommendations based only on the authenticated student's/professional's profile."""
    if account.role not in {"STUDENT", "PROFESSIONAL"} or not account.profile_iri:
        raise HTTPException(
            status_code=403,
            detail="Les recommandations sont réservées aux profils étudiants et professionnels.",
        )
    return sp.recommendations_for_profile(account.profile_iri)


def _guard(rows, not_found_msg):
    """Petite aide : si aucune ligne n'est retournée, ce n'est pas forcément une erreur
    (ça peut vouloir dire 'aucune compétence manquante'), donc on renvoie une liste vide
    proprement plutôt qu'une erreur 404 — sauf si le profil/formation lui-même est inconnu."""
    return rows


def _validate_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", value):
        raise HTTPException(status_code=400, detail=f"Identifiant {label} invalide.")
    return value


def _entity_type(value: str) -> str:
    if value not in sp.ENTITY_CLASSES:
        raise HTTPException(status_code=404, detail=f"Type d'entité '{value}' inconnu.")
    return value


def _crud_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Le corps doit être un objet JSON.")
    unexpected = set(payload) - {"id", "class", "properties", "relations"}
    if unexpected:
        raise HTTPException(
            status_code=400,
            detail=f"Champ(s) non reconnu(s) : {', '.join(sorted(unexpected))}.",
        )
    return payload


def _crud_failure(error: sp.InvalidPayloadError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


# --------------------------------------------------------------------------
# Smart Profile — vue et édition des relations OWL d'un ProfilUtilisateur.
# Ces routes sont déclarées AVANT les routes CRUD génériques `/api/{entity_type}`
# afin que `/api/profile/{id}` ne soit pas intercepté comme un type d'entité.
# --------------------------------------------------------------------------

PROFILE_PATCH_FIELDS = frozenset({
    "target_occupation",
    "skills_add",
    "skills_remove",
    "trainings_add",
    "trainings_remove",
})


def _profile_identifier_list(payload: dict, field: str) -> list[str]:
    values = payload.get(field, [])
    if (
        not isinstance(values, list)
        or len(values) > 200
        or not all(isinstance(value, str) for value in values)
    ):
        raise HTTPException(
            status_code=400,
            detail=f"'{field}' doit être une liste de 200 identifiants maximum.",
        )
    return [_validate_identifier(value, field) for value in values]


def _profile_view(profile_id: str) -> dict:
    """Vue consolidée d'un profil, strictement dérivée des assertions de l'ontologie."""
    detail = sp.get_entity_detail("ProfilUtilisateur", profile_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"Profil '{profile_id}' introuvable dans l'ontologie.",
        )

    relations = detail.get("relations", {})
    target = relations.get("vise") or []
    skills = relations.get("aAcquis") or []
    trainings = relations.get("aSuivi") or []
    paths = relations.get("parcours") or []
    evaluations = relations.get("evaluations") or []

    def reference(item: dict) -> dict:
        return {"id": item["id"], "label": item.get("label") or item["id"]}

    def sort_key(item: dict) -> tuple[str, str]:
        return (str(item.get("label") or item["id"]).lower(), item["id"])

    ordered_targets = sorted(target, key=sort_key)
    ordered_paths = sorted(paths, key=sort_key)
    path = ordered_paths[0] if ordered_paths else None

    score = 0
    missing: list[str] = []
    for key, present in (
        ("target_occupation", bool(ordered_targets)),
        ("skills", bool(skills)),
        ("trainings", bool(trainings)),
        ("parcours_or_evaluation", bool(paths) or bool(evaluations)),
    ):
        if present:
            score += 25
        else:
            missing.append(key)

    return {
        "id": detail["id"],
        "label": detail["label"],
        "types": [detail["class"]],
        "target_occupation": reference(ordered_targets[0]) if ordered_targets else None,
        "skills_acquired": [reference(item) for item in sorted(skills, key=sort_key)],
        "trainings_followed": [reference(item) for item in sorted(trainings, key=sort_key)],
        "parcours": (
            {
                "id": path["id"],
                "label": path.get("label") or path["id"],
                "formations": [reference(item) for item in path.get("formations", [])],
            }
            if path
            else None
        ),
        "evaluations": [reference(item) for item in sorted(evaluations, key=sort_key)],
        "completeness": {"score": score, "missing": missing},
    }


@app.get("/api/profile/{profile_id}")
def api_profile(profile_id: str, account: Account = Depends(get_current_account)):
    """Vue Smart Profile : métier visé, compétences, formations suivies, parcours, évaluations."""
    profile_id = _validate_identifier(profile_id, "profil")
    _assert_profile_access(account, profile_id)
    return _profile_view(profile_id)


@app.patch("/api/profile/{profile_id}")
def api_profile_patch(
    profile_id: str,
    body: Any = Body(None),
    account: Account = Depends(get_current_account),
):
    """Mise à jour partielle : métier visé, ajout/retrait de compétences et de formations.

    Chaque cible est vérifiée par ``sp.update_entity`` contre le type RDF attendu
    (``Metier``, ``Competence``, ``Formation``) : une cible d'un autre type est
    rejetée en 400 plutôt qu'écrite dans le graphe.
    """
    profile_id = _validate_identifier(profile_id, "profil")
    _assert_profile_access(account, profile_id)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Le corps doit être un objet JSON.")
    unexpected = set(body) - PROFILE_PATCH_FIELDS
    if unexpected:
        raise HTTPException(
            status_code=400,
            detail=f"Champ(s) non reconnu(s) : {', '.join(sorted(unexpected))}.",
        )

    current = _profile_view(profile_id)
    relations: dict[str, list[str]] = {}
    if "target_occupation" in body:
        target = body["target_occupation"]
        if target is None or target == "":
            relations["vise"] = []
        elif isinstance(target, str):
            relations["vise"] = [_validate_identifier(target, "métier")]
        else:
            raise HTTPException(
                status_code=400,
                detail="'target_occupation' doit être un identifiant de métier ou null.",
            )
    if "skills_add" in body or "skills_remove" in body:
        additions = set(_profile_identifier_list(body, "skills_add"))
        removals = set(_profile_identifier_list(body, "skills_remove"))
        current_skills = {item["id"] for item in current["skills_acquired"]}
        relations["aAcquis"] = sorted((current_skills | additions) - removals)
    if "trainings_add" in body or "trainings_remove" in body:
        additions = set(_profile_identifier_list(body, "trainings_add"))
        removals = set(_profile_identifier_list(body, "trainings_remove"))
        current_trainings = {item["id"] for item in current["trainings_followed"]}
        relations["aSuivi"] = sorted((current_trainings | additions) - removals)

    if not relations:
        raise HTTPException(status_code=400, detail="Aucune modification fournie.")
    try:
        sp.update_entity("ProfilUtilisateur", profile_id, {}, relations)
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error
    return _profile_view(profile_id)


@app.post("/api/profile/resolve-skills")
def api_resolve_skills(
    body: Any = Body(None),
    _: Account = Depends(get_current_account),
):
    """Résout un texte libre en compétences réelles de l'ontologie (spaCy + rapidfuzz).

    Le texte fourni n'est jamais concaténé dans une requête SPARQL : il sert
    uniquement d'entrée au matching flou local contre les ``aNom`` des individus
    ``onto:Competence``. Aucune donnée n'est inventée.
    """
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        raise HTTPException(
            status_code=400,
            detail="Le corps doit contenir un champ 'text' de type texte.",
        )
    text = body["text"].strip()
    if not text:
        raise HTTPException(status_code=400, detail="Le champ 'text' ne peut pas être vide.")
    if len(text) > 500:
        raise HTTPException(
            status_code=400,
            detail="Le champ 'text' ne peut pas dépasser 500 caractères.",
        )
    try:
        candidates = nlp.resolve_competences(text)
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error
    return {"text": text, "candidates": candidates}


@app.get("/api/stats")
def api_stats(_: Account = Depends(get_current_account)):
    return sp.get_stats()


@app.get("/api/{entity_type}")
def api_list(
    entity_type: str,
    search: str | None = None,
    include_class: bool = False,
    account: Account = Depends(get_current_account),
):
    entity_type = _entity_type(entity_type)
    if entity_type == "ProfilUtilisateur" and account.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Les profils sont accessibles uniquement à l'administration.")
    try:
        return sp.list_individuals(entity_type, search, include_class)
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error


@app.get("/api/{entity_type}/classes")
def api_entity_classes(entity_type: str, _: Account = Depends(get_current_account)):
    entity_type = _entity_type(entity_type)
    try:
        return sp.entity_classes(entity_type)
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error


@app.get("/api/{entity_type}/{identifier}")
def api_detail(
    entity_type: str,
    identifier: str,
    account: Account = Depends(get_current_account),
):
    entity_type = _entity_type(entity_type)
    if entity_type == "ProfilUtilisateur" and account.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Les profils sont accessibles uniquement à l'administration.")
    identifier = _validate_identifier(identifier, entity_type)
    try:
        detail = sp.get_entity_detail(entity_type, identifier)
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error
    if detail is None:
        raise HTTPException(status_code=404, detail=f"{entity_type} '{identifier}' introuvable.")
    return detail


@app.post("/api/{entity_type}", status_code=201)
def api_create(
    entity_type: str,
    body: Any = Body(None),
    _: Account = Depends(require_admin),
):
    entity_type = _entity_type(entity_type)
    payload = _crud_payload(body)
    identifier = payload.get("id")
    if not isinstance(identifier, str):
        raise HTTPException(status_code=400, detail="Le champ 'id' est obligatoire.")
    identifier = _validate_identifier(identifier, entity_type)
    try:
        sp.create_entity(
            entity_type,
            identifier,
            payload.get("properties", {}),
            payload.get("relations", {}),
            payload.get("class"),
        )
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error
    return {"id": identifier, "type": entity_type}


@app.put("/api/{entity_type}/{identifier}")
def api_update(
    entity_type: str,
    identifier: str,
    body: Any = Body(None),
    _: Account = Depends(require_admin),
):
    entity_type = _entity_type(entity_type)
    identifier = _validate_identifier(identifier, entity_type)
    payload = _crud_payload(body)
    try:
        if sp.get_entity_detail(entity_type, identifier) is None:
            raise HTTPException(
                status_code=404,
                detail=f"{entity_type} '{identifier}' introuvable.",
            )
        sp.update_entity(
            entity_type,
            identifier,
            payload.get("properties", {}),
            payload.get("relations", {}),
            payload.get("class"),
        )
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error
    return {"id": identifier, "type": entity_type}


@app.delete("/api/{entity_type}/{identifier}")
def api_delete(
    entity_type: str,
    identifier: str,
    _: Account = Depends(require_admin),
):
    entity_type = _entity_type(entity_type)
    identifier = _validate_identifier(identifier, entity_type)
    try:
        if sp.get_entity_detail(entity_type, identifier) is None:
            raise HTTPException(
                status_code=404,
                detail=f"{entity_type} '{identifier}' introuvable.",
            )
        dependencies = sp.delete_entity(identifier)
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error
    if dependencies:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Suppression impossible : {identifier} est référencé par "
                f"{dependencies} assertion(s) de l'ontologie."
            ),
        )
    return {"id": identifier, "deleted": True}


def _assert_profile_access(account: Account, profile_id: str) -> None:
    if account.role != "ADMIN" and account.profile_iri != profile_id:
        raise HTTPException(status_code=403, detail="Ce profil n'appartient pas à votre compte.")


def _formations_index() -> dict[str, Any]:
    """Indexe le graphe des formations : compétences enseignées, prérequis, métadonnées.

    Une seule lecture du graphe alimente à la fois l'analyse d'écarts et le
    parcours d'apprentissage, ce qui évite de multiplier les requêtes SPARQL.
    """
    course_skills: dict[str, set[str]] = {}
    course_prereqs: dict[str, set[str]] = {}
    for row in sp.formations_et_prerequis():
        course = row["formation"]
        course_skills.setdefault(course, set())
        if competence := row.get("competence"):
            course_skills[course].add(competence)
        if prereq := row.get("prereq"):
            course_prereqs.setdefault(course, set()).add(prereq)

    skill_courses: dict[str, set[str]] = {}
    for course, skills in course_skills.items():
        for skill in skills:
            skill_courses.setdefault(skill, set()).add(course)

    course_meta: dict[str, dict[str, Any]] = {}
    for course in course_skills:
        course_meta[course] = {
            "classes": set(),
            "duree": None,
            "label": course,
        }
    for row in sp.formations_meta():
        course = row["formation"]
        entry = course_meta.setdefault(
            course, {"classes": set(), "duree": None, "label": course}
        )
        class_name = row.get("class")
        if class_name and class_name not in {"Formation", "NamedIndividual"}:
            entry["classes"].add(class_name)
        if row.get("label"):
            entry["label"] = row["label"]
        raw_duration = row.get("duree")
        if raw_duration not in (None, ""):
            try:
                duration = int(float(raw_duration))
                entry["duree"] = duration if duration >= 0 else None
            except (TypeError, ValueError):
                entry["duree"] = None

    return {
        "course_skills": course_skills,
        "course_prereqs": course_prereqs,
        "skill_courses": skill_courses,
        "course_meta": course_meta,
    }


def _course_type(index: dict[str, Any], course: str) -> str:
    classes = sorted(index["course_meta"].get(course, {}).get("classes", set()))
    return classes[0] if classes else "Formation"


def _course_duration(index: dict[str, Any], course: str) -> int | None:
    return index["course_meta"].get(course, {}).get("duree")


def _acquisition_breakdown(profil: str) -> dict[str, Any]:
    """Répartit les compétences acquises : déclarées vs déduites d'une formation suivie.

    Seules les formations réellement suivies/terminées (relation ``aSuivi``)
    comptent comme preuve d'acquisition. Une formation simplement enregistrée
    dans un parcours ou recommandée par l'analyse n'est jamais prise en compte.
    Les compétences déclarées directement (``aAcquis``) restent dans
    ``competences_declarees`` et sont exclues de ``competences_via_formation``.
    """
    declared: set[str] = set()
    via_formation: dict[str, dict[str, str]] = {}
    for row in sp.competences_effectives(profil):
        competence = row.get("competence")
        formation = row.get("formation")
        if not competence:
            continue
        if row.get("source") == "direct" or not formation:
            declared.add(competence)
            continue
        via_formation.setdefault(competence, {})[formation] = (
            row.get("formationLabel") or formation
        )
    return {
        "acquired": declared | set(via_formation),
        "competences_declarees": sorted(declared),
        "competences_via_formation": [
            {
                "competence": competence,
                "formation": formation,
                "formation_label": label,
            }
            for competence in sorted(via_formation)
            if competence not in declared
            for formation, label in sorted(via_formation[competence].items())
        ],
    }


def _learning_steps(
    index: dict[str, Any],
    ordered_courses: list[str] | tuple[str, ...],
    required: set[str],
    acquired: set[str],
    followed: set[str],
) -> list[dict]:
    course_skills: dict[str, set[str]] = index["course_skills"]
    prerequisites: dict[str, set[str]] = index["course_prereqs"]
    selected_courses = set(ordered_courses)
    depth: dict[str, int] = {}
    for course in ordered_courses:
        dependencies = prerequisites.get(course, set()) & selected_courses
        depth[course] = 1 + max(
            (depth[dependency] for dependency in dependencies if dependency in depth),
            default=-1,
        )

    phases = ("fondation", "intermediaire", "avance")
    completed = set(followed)
    steps = []
    for position, course in enumerate(ordered_courses, start=1):
        declared_prerequisites = sorted(prerequisites.get(course, set()))
        metadata = index["course_meta"].get(course, {})
        steps.append({
            "ordre": position,
            "formation": course,
            "label": metadata.get("label") or course,
            "type": _course_type(index, course),
            "duree_heures": _course_duration(index, course),
            "prerequis": declared_prerequisites,
            "prerequis_satisfaits": sorted(set(declared_prerequisites) & completed),
            "competences_couvertes": sorted(course_skills.get(course, set()) & (required - acquired)),
            "deja_suivie": course in followed,
            "statut": "terminee" if course in followed else "a_suivre",
            "phase": phases[min(depth.get(course, 0), len(phases) - 1)],
        })
        completed.add(course)
    return steps


def _personalized_training_order(
    required: set[str],
    acquired: set[str],
    index: dict[str, Any],
    followed: set[str],
) -> list[str]:
    """Build the original single personalized roadmap using greedy skill coverage."""
    catalogue = set(index["course_meta"])
    prerequisites: dict[str, set[str]] = index["course_prereqs"]
    teaching: dict[str, set[str]] = index["course_skills"]
    closure_cache: dict[str, tuple[str, ...] | None] = {}

    def prerequisite_closure(
        training: str, visiting: frozenset[str] = frozenset()
    ) -> tuple[str, ...] | None:
        if training in followed:
            return ()
        if training not in catalogue or training in visiting:
            return None
        if training in closure_cache:
            return closure_cache[training]
        result: list[str] = []
        next_visiting = visiting | {training}
        for prerequisite in sorted(prerequisites.get(training, set())):
            closure = prerequisite_closure(prerequisite, next_visiting)
            if closure is None:
                closure_cache[training] = None
                return None
            result.extend(course for course in closure if course not in result)
        result.append(training)
        closure_cache[training] = tuple(result)
        return closure_cache[training]

    missing = required - acquired
    selected: list[str] = []
    covered: set[str] = set()
    available = catalogue - followed
    while missing - covered:
        choices = []
        for training in available:
            closure = prerequisite_closure(training)
            if closure is None:
                continue
            additional = {
                skill
                for course in closure
                for skill in teaching.get(course, set())
            } & (missing - covered)
            if not additional:
                continue
            durations = [_course_duration(index, course) for course in closure]
            duration = sum(value for value in durations if value is not None) if all(
                value is not None for value in durations
            ) else None
            choices.append((training, closure, additional, duration))

        if not choices:
            break
        _, closure, additional, _ = min(
            choices,
            key=lambda choice: (
                -len(choice[2]),
                choice[3] is None,
                choice[3] if choice[3] is not None else float("inf"),
                len(choice[1]),
                choice[0],
            ),
        )
        selected.extend(course for course in closure if course not in selected)
        covered.update(additional)

    completed = set(followed)
    remaining = set(selected)
    ordered: list[str] = []
    while remaining:
        ready = sorted(
            course for course in remaining
            if prerequisites.get(course, set()) <= completed
        )
        if not ready:
            break
        course = ready[0]
        remaining.remove(course)
        completed.add(course)
        ordered.append(course)
    return ordered


@app.get("/analyse")
def analyse(
    profil: str,
    metier: str,
    account: Account = Depends(get_current_account),
):
    profil = _validate_identifier(profil, "profil")
    metier = _validate_identifier(metier, "métier")
    _assert_profile_access(account, profil)

    details = sp.profil_details(profil)
    if not details:
        raise HTTPException(status_code=404, detail=f"Profil '{profil}' introuvable dans l'ontologie.")

    index = _formations_index()
    required = sorted({row["competence"] for row in sp.competences_requises(metier)})
    acquisition = _acquisition_breakdown(profil)
    acquired = acquisition["acquired"]
    followed = set(details.get("aSuivi", []))
    # Compétences qu'une formation déjà suivie enseigne : elles sont « en cours »
    # plutôt que réellement absentes, sans inventer de niveau de maîtrise.
    covered_by_followed = {
        skill for course in followed for skill in index["course_skills"].get(course, set())
    }
    acquired_required = [skill for skill in required if skill in acquired]
    missing = [skill for skill in required if skill not in acquired]
    in_progress = [skill for skill in missing if skill in covered_by_followed]
    match_score = round(len(acquired_required) / len(required) * 100) if required else 0
    trainings = sorted({
        row["formation"] for row in sp.formations_recommandees(profil, metier)
    })

    competences = []
    for skill in required:
        courses = sorted(index["skill_courses"].get(skill, set()))
        if skill in acquired:
            statut, priorite = "acquise", "aucune"
        elif skill in covered_by_followed:
            statut, priorite = "en_cours", "basse"
        elif courses:
            statut, priorite = "manquante", "moyenne"
        else:
            # Aucune formation du catalogue ne couvre cette compétence : c'est
            # le cas le plus bloquant, donc la priorité la plus élevée.
            statut, priorite = "manquante", "haute"
        competences.append({
            "id": skill,
            "label": skill,
            "statut": statut,
            "priorite": priorite,
            "formations_recommandees": courses,
        })

    return {
        "profil": profil,
        "metier": metier,
        "competences_requises": required,
        "competences_acquises": acquired_required,
        "competences_declarees": acquisition["competences_declarees"],
        "competences_via_formation": acquisition["competences_via_formation"],
        "competences_manquantes": missing,
        "competences_en_cours": in_progress,
        "match_score": match_score,
        "formations_recommandees": trainings,
        "competences": competences,
    }


@app.get("/learning-path")
def learning_path(
    profil: str,
    metier: str,
    account: Account = Depends(get_current_account),
):
    """Return one deterministic, prerequisite-valid personalized roadmap."""
    profil = _validate_identifier(profil, "profil")
    metier = _validate_identifier(metier, "métier")
    _assert_profile_access(account, profil)

    details = sp.profil_details(profil)
    if not details:
        raise HTTPException(status_code=404, detail=f"Profil '{profil}' introuvable dans l'ontologie.")
    if sp.get_entity_detail("Metier", metier) is None:
        raise HTTPException(status_code=404, detail=f"Métier '{metier}' introuvable dans l'ontologie.")

    index = _formations_index()
    required = sorted({row["competence"] for row in sp.competences_requises(metier)})
    acquisition = _acquisition_breakdown(profil)
    acquired = acquisition["acquired"]
    followed = set(details.get("aSuivi", []))
    missing = set(required) - acquired
    acquired_required = [skill for skill in required if skill in acquired]
    ordered = _personalized_training_order(set(required), acquired, index, followed)
    steps = _learning_steps(index, ordered, set(required), acquired, followed)
    completed_steps = [
        {
            **_learning_steps(index, [course], set(required), acquired, followed)[0],
            "ordre": 0,
            "phase": "terminee",
        }
        for course in sorted(followed)
        if index["course_skills"].get(course, set()) & set(required)
        and course in index["course_meta"]
    ]
    covered = {
        skill for step in steps for skill in step["competences_couvertes"]
    }
    durations = [step["duree_heures"] for step in steps]
    duration = (
        sum(value for value in durations if value is not None)
        if all(value is not None for value in durations)
        else None
    )
    total_steps = len(steps) + len(completed_steps)
    return {
        "profil": profil,
        "metier": metier,
        "competences_requises": required,
        "competences_acquises": acquired_required,
        "competences_declarees": acquisition["competences_declarees"],
        "competences_via_formation": acquisition["competences_via_formation"],
        "competences_manquantes": sorted(missing),
        "competences_en_cours": sorted(
            skill for skill in missing
            if any(skill in index["course_skills"].get(course, set()) for course in followed)
        ),
        "match_score": round(len(acquired_required) / len(required) * 100) if required else 0,
        "etapes": steps,
        "etapes_terminees": completed_steps,
        "competences_couvertes": sorted(covered),
        "competences_non_couvertes": sorted(missing - covered),
        "competences_sans_formation": sorted(
            skill for skill in missing if not index["skill_courses"].get(skill)
        ),
        "competences_bloquees_prerequis": [],
        "progression": {
            "total": total_steps,
            "terminees": len(completed_steps),
            "pourcentage": round(len(completed_steps) / total_steps * 100) if total_steps else 0,
            "heures_restantes": duration,
            "duree_disponible": duration is not None,
        },
    }


@app.get("/parcours-optimal")
def parcours_optimal(
    profil: str,
    metier: str,
    max_duration_hours: int | None = Query(default=None, ge=0),
    account: Account = Depends(get_current_account),
):
    profil = _validate_identifier(profil, "profil")
    metier = _validate_identifier(metier, "métier")
    _assert_profile_access(account, profil)

    details = sp.profil_details(profil)
    if not details:
        raise HTTPException(status_code=404, detail=f"Profil '{profil}' introuvable dans l'ontologie.")
    if sp.get_entity_detail("Metier", metier) is None:
        raise HTTPException(status_code=404, detail=f"Métier '{metier}' introuvable dans l'ontologie.")

    index = _formations_index()
    required = sorted({row["competence"] for row in sp.competences_requises(metier)})
    acquisition = _acquisition_breakdown(profil)
    acquired = acquisition["acquired"]
    followed = set(details.get("aSuivi", []))
    acquired_required = [skill for skill in required if skill in acquired]
    missing = set(required) - acquired
    match_score = round(len(acquired_required) / len(required) * 100) if required else 0
    catalogue = learning_path_generator.generate_learning_path_candidates(
        required,
        acquired,
        index["course_skills"],
        index["course_prereqs"],
        {
            course: metadata["duree"]
            for course, metadata in index["course_meta"].items()
        },
        index["course_meta"],
        followed,
        max_duration_hours,
    )
    candidates = []
    for candidate in catalogue["candidates"]:
        candidates.append({
            **candidate,
            "id": f"candidate-{candidate['rank']}",
            "training_count": len(candidate["training_ids"]),
            "etapes": _learning_steps(
                index,
                candidate["training_ids"],
                set(required),
                acquired,
                followed,
            ),
        })
    best_candidate = candidates[0]
    etapes = best_candidate["etapes"]

    # 5) Formations déjà suivies qui couvrent une compétence du métier visé.
    etapes_terminees = [
        {
            **_learning_steps(index, [course], set(required), acquired, followed)[0],
            "ordre": 0,
            "phase": "terminee",
        }
        for course in sorted(followed)
        if index["course_skills"].get(course, set()) & set(required)
    ]

    covered_by_path = set(best_candidate["covered_competencies"])
    completed_recommendations = sum(
        step["formation"] in followed for step in etapes
    )
    total_recommendations = len(etapes)

    return {
        "profil": profil,
        "metier": metier,
        "competences_requises": required,
        "competences_acquises": acquired_required,
        "competences_declarees": acquisition["competences_declarees"],
        "competences_via_formation": acquisition["competences_via_formation"],
        "competences_manquantes": sorted(missing),
        "competences_en_cours": sorted(
            skill for skill in missing
            if any(skill in index["course_skills"].get(course, set()) for course in followed)
        ),
        "match_score": match_score,
        "etapes": etapes,
        "etapes_terminees": etapes_terminees,
        "competences_couvertes": sorted(covered_by_path),
        "competences_non_couvertes": best_candidate["uncovered_competencies"],
        # Compétence sans formation : aucune formation du catalogue (suivie ou non,
        # disponible ou non) ne l'enseigne, et non « aucune recommandation restante ».
        "competences_sans_formation": sorted(
            skill for skill in missing if not index["skill_courses"].get(skill)
        ),
        "competences_bloquees_prerequis": catalogue["prerequisite_blocked_competencies"],
        "candidates": candidates,
        "max_duration_hours": max_duration_hours,
        "progression": {
            "total": total_recommendations,
            "terminees": completed_recommendations,
            "pourcentage": (
                round(completed_recommendations / total_recommendations * 100)
                if total_recommendations
                else 0
            ),
            "heures_restantes": best_candidate["duration_hours"],
            "duree_disponible": best_candidate["duration_available"],
        },
    }


@app.get("/graph")
def get_graph(account: Account = Depends(get_current_account)):
    type_prefixes = {
        "profil_": "profile",
        "comp_": "skill",
        "met_": "job",
        "form_": "training",
    }
    nodes: dict[str, dict[str, str]] = {}
    edges = []

    for relation in sp.relations_graphe():
        if account.role != "ADMIN" and (
            relation["source"].startswith("profil_")
            or relation["target"].startswith("profil_")
        ):
            if account.profile_iri not in {relation["source"], relation["target"]}:
                continue
        elif account.role != "ADMIN" and relation["source"].startswith("profil_"):
            continue
        source = relation["source"]
        target = relation["target"]
        for identifier in (source, target):
            prefix = next((value for value in type_prefixes if identifier.startswith(value)), None)
            if prefix is not None:
                nodes[identifier] = {
                    "id": identifier,
                    "label": identifier.removeprefix(prefix),
                    "type": type_prefixes[prefix],
                }
        edges.append({
            "id": f"{source}:{relation['relation']}:{target}",
            "from": source,
            "to": target,
            "relation": relation["relation"],
        })

    return {
        "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
        "edges": edges,
    }


@app.get("/profils/{profil}")
def get_profil(profil: str, account: Account = Depends(get_current_account)):
    profil = _validate_identifier(profil, "profil")
    _assert_profile_access(account, profil)
    details = sp.profil_details(profil)
    if not details:
        raise HTTPException(status_code=404, detail=f"Profil '{profil}' introuvable dans l'ontologie.")
    return {"profil": profil, "assertions": details}


@app.put("/profils/{profil}")
def follow_profile_trainings(
    profil: str,
    body: Any = Body(None),
    account: Account = Depends(get_current_account),
):
    profil = _validate_identifier(profil, "profil")
    _assert_profile_access(account, profil)
    if account.role == "ADMIN":
        raise HTTPException(status_code=403, detail="Aucun profil métier modifiable pour ce compte.")
    if not isinstance(body, dict) or set(body) != {"formations_suivies"}:
        raise HTTPException(
            status_code=400,
            detail="Le corps doit contenir uniquement 'formations_suivies'.",
        )
    trainings = body["formations_suivies"]
    if (
        not isinstance(trainings, list)
        or len(trainings) > 200
        or not all(isinstance(training, str) for training in trainings)
    ):
        raise HTTPException(
            status_code=400,
            detail="'formations_suivies' doit être une liste de 200 identifiants de formation maximum.",
        )
    requested = {
        _validate_identifier(training, "formation")
        for training in trainings
    }
    profile = sp.get_entity_detail("ProfilUtilisateur", profil)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Profil '{profil}' introuvable.")
    current = {
        training["id"]
        for training in profile["relations"].get("aSuivi", [])
    }
    followed = sorted(current | requested)
    try:
        sp.add_followed_trainings(profil, sorted(requested))
    except sp.InvalidPayloadError as error:
        raise _crud_failure(error) from error
    return {"profil": profil, "formations_suivies": followed}


@app.get("/dashboard")
def public_dashboard_stats():
    stats = sp.get_stats()
    return {
        "competences": stats["competences"],
        "formations": stats["formations"],
        "metiers": stats["metiers"],
    }


@app.get("/formations")
def public_training_catalogue():
    return sp.catalogue_formations()


@app.get("/formations/{formation}")
def public_training_detail(formation: str):
    formation = _validate_identifier(formation, "formation")
    item = next(
        (item for item in sp.catalogue_formations() if item["id"] == formation),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail=f"Formation '{formation}' introuvable.")
    training = {**item}
    detail = sp.get_entity_detail("Formation", formation)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Formation '{formation}' introuvable.")
    training["modules"] = [
        {"id": module["id"], "label": module["label"]}
        for module in detail["relations"].get("contientModule", [])
    ]
    return training


@app.get("/modules/{module}")
def public_module_detail(module: str):
    module = _validate_identifier(module, "module")
    detail = sp.get_entity_detail("Module", module)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Module '{module}' introuvable.")
    return {
        "id": module,
        "nom": detail["label"],
        "competences_enseignees": [
            {"id": competence["id"], "label": competence["label"]}
            for competence in detail["relations"].get("moduleEnseigne", [])
        ],
    }


@app.get("/profils/{profil}/competences-manquantes")
def get_competences_manquantes(
    profil: str, account: Account = Depends(get_current_account)
):
    profil = _validate_identifier(profil, "profil")
    _assert_profile_access(account, profil)
    """Équivalent de la requête Q1 du rapport."""
    rows = sp.competences_manquantes(profil)
    return {
        "profil": profil,
        "competences_manquantes": [r["competence"] for r in rows],
        "nombre": len(rows),
    }


@app.get("/profils/{profil}/metiers-accessibles")
def get_metiers_accessibles(
    profil: str, account: Account = Depends(get_current_account)
):
    profil = _validate_identifier(profil, "profil")
    _assert_profile_access(account, profil)
    """Équivalent de la requête Q2 du rapport."""
    rows = sp.metiers_accessibles(profil)
    return {
        "profil": profil,
        "metiers_accessibles": [r["metier"] for r in rows],
        "nombre": len(rows),
    }


@app.get("/profils/{profil}/parcours-optimal")
def get_parcours_optimal(
    profil: str, account: Account = Depends(get_current_account)
):
    profil = _validate_identifier(profil, "profil")
    _assert_profile_access(account, profil)
    """Formation(s) recommandée(s) en priorité pour ce profil."""
    rows = sp.parcours_optimal(profil)
    return {
        "profil": profil,
        "parcours_recommande": [r["formation"] for r in rows],
        "nombre": len(rows),
    }


@app.get("/formations/{formation}/chaine-prerequis")
def get_chaine_prerequis(
    formation: str, _: Account = Depends(get_current_account)
):
    formation = _validate_identifier(formation, "formation")
    """Équivalent de la requête Q3 du rapport (transitivité de aPourPrerequis)."""
    rows = sp.chaine_prerequis(formation)
    return {
        "formation": formation,
        "chaine_prerequis": [r["prereq"] for r in rows],
        "nombre": len(rows),
    }


# --------------------------------------------------------------------------
# Évaluation automatique et niveau global (étudiant / professionnel).
# Le profil provient exclusivement du jeton d'authentification : aucun
# identifiant de profil n'est accepté dans le corps de la requête. L'admin
# n'utilise pas ces fonctionnalités (403).
# --------------------------------------------------------------------------


def _learner_account(account: Account = Depends(get_current_account)) -> Account:
    """Réserve la route aux profils étudiant / professionnel connectés."""
    if account.role == "ADMIN" or not account.profile_iri:
        raise HTTPException(
            status_code=403,
            detail="Fonctionnalité réservée aux profils étudiant et professionnel.",
        )
    return account


def _target_occupation(profile: dict | None) -> dict | None:
    """Métier visé par le profil (relation ``vise``), ou ``None``."""
    if not profile:
        return None
    targets = profile.get("relations", {}).get("vise") or []
    return targets[0] if targets else None


@app.post("/me/evaluations/generate")
def generate_evaluation(account: Account = Depends(_learner_account)):
    """Génère (ou remplace) l'évaluation automatique du profil connecté.

    Le score de préparation est le pourcentage de compétences requises par le
    métier visé que le profil a réellement acquises (même règle d'acquisition
    que l'analyse d'écarts). Le niveau global en est déduit automatiquement.
    """
    profil = account.profile_iri
    profile = sp.get_entity_detail("ProfilUtilisateur", profil)
    if profile is None:
        raise HTTPException(status_code=503, detail="Le profil SkillPath associé est indisponible.")
    occupation = _target_occupation(profile)
    if occupation is None:
        raise HTTPException(status_code=400, detail="Choose a target occupation first")

    metier = occupation["id"]
    occupation_name = occupation.get("label") or metier
    required = sorted({row["competence"] for row in sp.competences_requises(metier)})
    required_level = sp.niveau_requis_metier(metier)

    # Métier sans compétence requise : aucun score calculable, aucun niveau modifié.
    if not required:
        return {
            "score": 0,
            "date": None,
            "level": sp.niveau_profil(profil),
            "requiredLevel": required_level,
            "masteredCount": 0,
            "missingCount": 0,
            "occupationName": occupation_name,
            "message": "No required competences defined for this occupation",
            "diagnostic": sp.evaluation_diagnostic(profil, metier, 0),
        }

    acquired = _acquisition_breakdown(profil)["acquired"]
    mastered = [skill for skill in required if skill in acquired]
    score = round(len(mastered) / len(required) * 100)
    now = datetime.now().isoformat(timespec="seconds")
    sp.remplacer_evaluation(
        profil,
        f"eval_{profil}_{metier}",
        f"Evaluation {occupation_name}",
        score,
        now,
    )
    sp.definir_niveau_profil(profil, sp.niveau_pour_score(score))
    return {
        "score": score,
        "date": now,
        "level": sp.niveau_profil(profil),
        "requiredLevel": required_level,
        "masteredCount": len(mastered),
        "missingCount": len(required) - len(mastered),
        "occupationName": occupation_name,
        "diagnostic": sp.evaluation_diagnostic(profil, metier, score),
    }


@app.get("/me/evaluations")
def list_my_evaluations(account: Account = Depends(_learner_account)):
    """Évaluations du profil connecté (une par métier déjà évalué)."""
    evaluations = sp.evaluations_profil(account.profile_iri)
    for evaluation in evaluations:
        evaluation["diagnostic"] = sp.evaluation_diagnostic(
            account.profile_iri,
            evaluation.get("occupation"),
            evaluation.get("score"),
        )
    return evaluations


@app.get("/me/career-bridges")
def me_career_bridges(account: Account = Depends(_learner_account)):
    """Compare the authenticated profile's acquired skills with other occupations."""
    return sp.career_bridges_for_profile(account.profile_iri)

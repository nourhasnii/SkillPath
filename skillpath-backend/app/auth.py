import json
import os
import re
import smtplib
import sqlite3
import ssl
import uuid
from email.message import EmailMessage
from enum import Enum
from typing import Annotated
from urllib.parse import urlencode

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import admin_analyses, auth_store, redundancy
from . import sparql_client as sp
from .auth_store import Account

router = APIRouter(prefix="/auth", tags=["authentication"])
account_router = APIRouter(tags=["account"])
admin_router = APIRouter(prefix="/admin", tags=["administration"])

PASSWORD_HASHER = PasswordHasher(type=Type.ID)
SESSION_LIFETIME_SECONDS = 8 * 60 * 60
RESET_LIFETIME_SECONDS = 30 * 60
SESSION_COOKIE = "skillpath_session"
SESSION_COOKIE_PATH = "/"
RESET_SUCCESS_MESSAGE = (
    "If an account exists for this address, a password reset email has been sent."
)
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}$")


class PublicRole(str, Enum):
    STUDENT = "STUDENT"
    PROFESSIONAL = "PROFESSIONAL"


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    experience: str = Field(default="", max_length=5000)
    target_occupation: str | None = Field(default=None, max_length=120)
    acquired_competences: list[str] | None = Field(default=None, max_length=200)
    completed_trainings: list[str] | None = Field(default=None, max_length=200)


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=6, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    password_confirmation: str = Field(min_length=12, max_length=128)
    profile_type: PublicRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Adresse email invalide.")
        return normalized

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Le nom complet doit contenir au moins deux caractères.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        validate_new_password(value)
        return value

    @model_validator(mode="after")
    def confirm_password(self):
        if self.password != self.password_confirmation:
            raise ValueError("La confirmation du mot de passe ne correspond pas.")
        return self


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=6, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Adresse email invalide.")
        return normalized


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=6, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Adresse email invalide.")
        return normalized


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=128)
    password_confirmation: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        validate_new_password(value)
        return value

    @model_validator(mode="after")
    def confirm_password(self):
        if self.password != self.password_confirmation:
            raise ValueError("La confirmation du mot de passe ne correspond pas.")
        return self


class AdminRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in {"STUDENT", "PROFESSIONAL", "ADMIN"}:
            raise ValueError("Rôle invalide.")
        return value


class LearningPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trainings: list[str] = Field(min_length=1, max_length=100)

    @field_validator("trainings")
    @classmethod
    def unique_trainings(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Une formation ne peut apparaître qu'une fois dans le parcours.")
        return value


class LearningProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed_trainings: list[str] = Field(max_length=100)


def validate_new_password(password: str) -> None:
    if len(password.encode("utf-8")) > 128:
        raise ValueError("Le mot de passe est trop long.")
    if len(set(password)) < 4:
        raise ValueError("Choisissez un mot de passe moins prévisible.")


def public_account(account: Account) -> dict:
    return {
        "id": account.id,
        "email": account.email,
        "full_name": account.full_name,
        "role": account.role,
        "profile_iri": account.profile_iri,
        "experience": account.experience,
    }


def cookie_secure() -> bool:
    configured = os.environ.get("AUTH_COOKIE_SECURE")
    if configured is not None:
        return configured.strip().lower() in {"1", "true", "yes"}
    return os.environ.get("ENVIRONMENT", "development").lower() == "production"


def set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        max_age=SESSION_LIFETIME_SECONDS,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path=SESSION_COOKIE_PATH,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path=SESSION_COOKIE_PATH,
    )


def get_current_account(request: Request) -> Account:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentification requise.")
    account = auth_store.account_for_session(raw_token)
    if account is None:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée.")
    return account


def require_admin(account: Annotated[Account, Depends(get_current_account)]) -> Account:
    if account.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Accès réservé à l'administration.")
    return account


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def login_rate_limit_enabled() -> bool:
    return os.environ.get("ENVIRONMENT", "production").strip().lower() != "development"


def smtp_is_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def send_reset_email(email: str, token: str) -> None:
    host = os.environ.get("SMTP_HOST")
    sender = os.environ.get("SMTP_FROM")
    if not host or not sender:
        raise RuntimeError("SMTP_HOST et SMTP_FROM doivent être configurés pour le reset.")

    base_url = os.environ.get("FRONTEND_BASE_URL", "http://localhost:4200").rstrip("/")
    reset_link = f"{base_url}/reset-password?{urlencode({'token': token})}"
    message = EmailMessage()
    message["Subject"] = "Réinitialiser votre mot de passe SkillPath"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "Une demande de réinitialisation a été faite pour votre compte SkillPath.\n\n"
        f"Utilisez ce lien à usage unique dans les 30 minutes : {reset_link}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email."
    )

    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    use_ssl = os.environ.get("SMTP_USE_SSL", "").lower() in {"1", "true", "yes"}
    use_starttls = os.environ.get("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}
    timeout = float(os.environ.get("SMTP_TIMEOUT_SECONDS", "10"))
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context()) as client:
            if username:
                client.login(username, password or "")
            client.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=timeout) as client:
        client.ehlo()
        if use_starttls:
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if username:
            client.login(username, password or "")
        client.send_message(message)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegistrationRequest, response: Response):
    profile_iri = f"profil_{uuid.uuid4().hex}"
    role_class = {
        PublicRole.STUDENT: "ProfilEtudiant",
        PublicRole.PROFESSIONAL: "ProfilProfessionnel",
    }[body.profile_type]
    password_hash = PASSWORD_HASHER.hash(body.password)

    try:
        account = auth_store.create_account(
            body.email, body.full_name, password_hash, body.profile_type.value, profile_iri
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Cette adresse email est déjà utilisée.") from error

    try:
        sp.create_entity(
            "ProfilUtilisateur",
            profile_iri,
            {"aNom": body.full_name},
            {},
            role_class,
        )
    except (sp.FusekiError, sp.InvalidPayloadError):
        auth_store.delete_account(account.id)
        raise

    raw_session = auth_store.create_session(account.id, SESSION_LIFETIME_SECONDS)
    set_session_cookie(response, raw_session)
    return public_account(account)


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    rate_limit_enabled = login_rate_limit_enabled()
    bucket: str | None = None
    if rate_limit_enabled:
        client_ip = request.client.host if request.client else "unknown"
        bucket = auth_store.login_bucket(body.email, client_ip)
        if auth_store.login_is_blocked(bucket):
            raise HTTPException(
                status_code=429,
                detail="Trop de tentatives. Réessayez dans quelques minutes.",
            )

    row = auth_store.account_by_email(body.email)
    if row is None or not verify_password(row["password_hash"], body.password):
        if bucket is not None:
            auth_store.record_login_failure(bucket)
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")
    if bucket is not None:
        auth_store.clear_login_failures(bucket)

    account = auth_store.account_from_row(row)
    if account.role != "ADMIN" and not account.profile_iri:
        raise HTTPException(status_code=403, detail="Le profil associé au compte est indisponible.")
    raw_session = auth_store.create_session(account.id, SESSION_LIFETIME_SECONDS)
    set_session_cookie(response, raw_session)
    return public_account(account)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response):
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        auth_store.revoke_session(raw_token)
    clear_session_cookie(response)


@router.get("/me")
def who_am_i(account: Annotated[Account, Depends(get_current_account)]):
    return public_account(account)


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, request: Request):
    if login_rate_limit_enabled():
        client_ip = request.client.host if request.client else "unknown"
        buckets = (
            auth_store.login_bucket(body.email, client_ip),
            auth_store.login_bucket("password-reset", client_ip),
        )
        if any(auth_store.login_is_blocked(bucket) for bucket in buckets):
            raise HTTPException(
                status_code=429,
                detail="Trop de demandes. Réessayez dans quelques minutes.",
            )
        for bucket in buckets:
            auth_store.record_login_failure(bucket)

    if not smtp_is_configured():
        raise HTTPException(
            status_code=503,
            detail="La livraison email de réinitialisation n'est pas configurée.",
        )
    row = auth_store.account_by_email(body.email)
    if row is not None:
        token = auth_store.new_reset_token()
        auth_store.store_reset_token(row["id"], token, RESET_LIFETIME_SECONDS)
        try:
            send_reset_email(body.email, token)
        except (OSError, smtplib.SMTPException, RuntimeError) as error:
            auth_store.delete_reset_tokens(row["id"])
            raise HTTPException(
                status_code=503,
                detail="Le service email est indisponible. Réessayez plus tard.",
            ) from error
    return {"message": RESET_SUCCESS_MESSAGE}


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest):
    account_id = auth_store.update_password_from_reset(
        body.token, PASSWORD_HASHER.hash(body.password)
    )
    if account_id is None:
        raise HTTPException(status_code=400, detail="Le lien est invalide ou a expiré.")
    return {"message": "Mot de passe modifié. Connectez-vous avec votre nouveau mot de passe."}


@account_router.get("/account/profile")
def get_account_profile(account: Annotated[Account, Depends(get_current_account)]):
    profile = sp.get_entity_detail("ProfilUtilisateur", account.profile_iri) if account.profile_iri else None
    if account.role != "ADMIN" and profile is None:
        raise HTTPException(status_code=503, detail="Le profil SkillPath associé est indisponible.")
    # Niveau global du profil et niveau exigé par le métier visé (facultatif).
    level = sp.niveau_profil(account.profile_iri) if profile is not None else None
    required_level = None
    if profile is not None:
        targets = profile.get("relations", {}).get("vise") or []
        if targets:
            required_level = sp.niveau_requis_metier(targets[0]["id"])
    return {
        **public_account(account),
        "profile": profile,
        "level": level,
        "requiredLevel": required_level,
    }


@account_router.put("/account/profile")
def update_account_profile(
    body: ProfileUpdate,
    account: Annotated[Account, Depends(get_current_account)],
):
    if account.role == "ADMIN" or not account.profile_iri:
        raise HTTPException(status_code=403, detail="Aucun profil métier modifiable pour ce compte.")
    relations: dict[str, list[str]] = {}
    if body.target_occupation is not None:
        if body.target_occupation:
            relations["vise"] = [body.target_occupation]
        else:
            relations["vise"] = []
    if body.acquired_competences is not None:
        relations["aAcquis"] = body.acquired_competences
    if body.completed_trainings is not None:
        relations["aSuivi"] = body.completed_trainings
    try:
        sp.update_entity(
            "ProfilUtilisateur",
            account.profile_iri,
            {"aNom": [body.full_name]},
            relations,
        )
    except sp.InvalidPayloadError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return public_account(auth_store.update_account_profile(account.id, body.full_name, body.experience))


@account_router.post("/account/parcours", status_code=status.HTTP_201_CREATED)
def save_learning_path(
    body: LearningPathRequest,
    account: Annotated[Account, Depends(get_current_account)],
):
    if account.role == "ADMIN" or not account.profile_iri:
        raise HTTPException(status_code=403, detail="Cette action nécessite un profil étudiant ou professionnel.")
    try:
        profile = sp.get_entity_detail("ProfilUtilisateur", account.profile_iri)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profil introuvable dans l'ontologie.")
        catalogue: dict[str, set[str]] = {}
        prerequisites: dict[str, set[str]] = {}
        for row in sp.formations_et_prerequis():
            training = row["formation"]
            catalogue.setdefault(training, set())
            if competence := row.get("competence"):
                catalogue[training].add(competence)
            if prereq := row.get("prereq"):
                prerequisites.setdefault(training, set()).add(prereq)
        completed = {
            item["id"] for item in profile.get("relations", {}).get("aSuivi", [])
        }
        for training in body.trainings:
            if training not in catalogue:
                raise HTTPException(
                    status_code=400,
                    detail=f"La formation '{training}' n'appartient pas au catalogue.",
                )
            unmet = sorted(prerequisites.get(training, set()) - completed)
            if unmet:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Ordre invalide : suivez d'abord "
                        f"{', '.join(unmet)} avant '{training}'."
                    ),
                )
            completed.add(training)
    except sp.InvalidPayloadError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    # Nom affiché généré par le serveur : "Learning path: <Métier> - <Profil>".
    # Le hash n'apparaît que dans l'identifiant (path_id), jamais dans le libellé.
    occupation = next(
        (
            item["label"]
            for item in profile.get("relations", {}).get("vise", [])
            if item.get("label")
        ),
        "",
    )
    profile_name = next(
        (value for value in profile.get("properties", {}).get("aNom", []) if value),
        "",
    ) or account.full_name
    path_name = "Learning path: " + " - ".join(
        part for part in (occupation, profile_name) if part
    )

    path_id = f"parc_{uuid.uuid4().hex}"
    try:
        sp.create_entity(
            "Parcours",
            path_id,
            {
                "aNom": path_name,
                "aOrdreFormations": json.dumps(body.trainings, separators=(",", ":")),
            },
            {"contientFormation": body.trainings},
            "ParcoursIndividualise",
        )
        existing_paths = [
            item["id"] for item in profile.get("relations", {}).get("parcours", [])
        ]
        sp.update_entity(
            "ProfilUtilisateur",
            account.profile_iri,
            {},
            {"parcours": [*existing_paths, path_id]},
        )
    except sp.InvalidPayloadError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"id": path_id, "label": path_name, "formations": body.trainings}


@account_router.put("/account/parcours/{path_id}/progress")
def update_learning_progress(
    path_id: str,
    body: LearningProgressRequest,
    account: Annotated[Account, Depends(get_current_account)],
):
    if account.role == "ADMIN" or not account.profile_iri:
        raise HTTPException(status_code=403, detail="Cette action nécessite un profil étudiant ou professionnel.")
    try:
        details = sp.get_entity_detail("ProfilUtilisateur", account.profile_iri)
        paths = (details or {}).get("relations", {}).get("parcours", [])
        owned_path = next((path for path in paths if path["id"] == path_id), None)
        if owned_path is None:
            raise HTTPException(status_code=404, detail="Parcours introuvable pour ce profil.")
        included = {item["id"] for item in owned_path.get("formations", [])}
        if not set(body.completed_trainings) <= included:
            raise HTTPException(status_code=400, detail="Une formation ne fait pas partie de ce parcours.")
        current_followed = {
            item["id"] for item in (details or {}).get("relations", {}).get("aSuivi", [])
        }
        sp.update_entity(
            "ProfilUtilisateur",
            account.profile_iri,
            {},
            {"aSuivi": sorted(current_followed | set(body.completed_trainings))},
        )
    except sp.InvalidPayloadError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"path_id": path_id, "completed_trainings": sorted(body.completed_trainings)}


@admin_router.get("/users")
def admin_list_users(_: Annotated[Account, Depends(require_admin)]):
    return [public_account(account) for account in auth_store.list_accounts()]


@admin_router.put("/users/{account_id}/role")
def admin_update_role(
    account_id: str,
    body: AdminRoleUpdate,
    actor: Annotated[Account, Depends(require_admin)],
):
    target = auth_store.account_by_id(account_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    if target.id == actor.id and body.role != "ADMIN":
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas retirer votre propre rôle ADMIN.")
    if target.role != body.role:
        auth_store.set_account_role(account_id, body.role)
        auth_store.revoke_account_sessions(account_id)
    updated = auth_store.account_by_id(account_id)
    return public_account(updated) if updated else {"id": account_id, "role": body.role}


@admin_router.get("/dashboard/analytics")
def admin_dashboard_analytics(_: Annotated[Account, Depends(require_admin)]):
    """Agrégats de la base de connaissances (Fuseki) pour le tableau de bord d'administration."""
    return admin_analyses.dashboard_analytics()


@admin_router.get("/redundant-competencies")
def admin_redundant_competencies(
    _: Annotated[Account, Depends(require_admin)],
    threshold: float = Query(redundancy.DEFAULT_THRESHOLD, ge=0.0, le=1.0),
):
    """Analyse les compétences de l'ontologie et retourne les couples redondants."""
    return redundancy.detect_redundant_competencies(threshold)


@admin_router.get("/shared-competencies")
def admin_shared_competencies(_: Annotated[Account, Depends(require_admin)]):
    """Compétences requises par au moins deux métiers."""
    return admin_analyses.shared_competencies()


@admin_router.get("/untaught-competencies")
def admin_untaught_competencies(_: Annotated[Account, Depends(require_admin)]):
    """Compétences techniques/transverses sans formation dans le catalogue."""
    return admin_analyses.untaught_competencies()


def admin_password_hash(password: str) -> str:
    validate_new_password(password)
    return PASSWORD_HASHER.hash(password)

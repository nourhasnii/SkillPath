import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

_test_database = tempfile.TemporaryDirectory(prefix="skillpath-auth-tests-")
os.environ["AUTH_DATABASE_PATH"] = os.path.join(_test_database.name, "auth.sqlite3")
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:4200,http://127.0.0.1:4200"
os.environ["ENVIRONMENT"] = "test"
os.environ.pop("AUTH_COOKIE_SECURE", None)

from fastapi.testclient import TestClient

from app import admin_analyses, auth_store, nlp, ontology_schema, sparql_client
from app.auth import PASSWORD_HASHER
from app.main import app, initialize_auth_database


class AuthenticationApiTests(unittest.TestCase):
    def setUp(self):
        self.client_context = TestClient(app)
        with redirect_stdout(StringIO()):
            self.client = self.client_context.__enter__()
        with auth_store.connect() as connection:
            connection.execute("DELETE FROM login_attempts")
            connection.execute("DELETE FROM password_reset_tokens")
            connection.execute("DELETE FROM auth_sessions")
            connection.execute("DELETE FROM accounts")

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    @staticmethod
    def registration_payload(**overrides):
        return {
            "full_name": "Test Learner",
            "email": "learner@example.test",
            "password": "Secure-test-password-42",
            "password_confirmation": "Secure-test-password-42",
            "profile_type": "STUDENT",
            **overrides,
        }

    def login_admin(self):
        auth_store.create_admin(
            "admin@example.test",
            "Test Administrator",
            PASSWORD_HASHER.hash("Admin-test-password-89"),
        )
        response = self.client.post("/auth/login", json={
            "email": "admin@example.test",
            "password": "Admin-test-password-89",
        })
        self.assertEqual(response.status_code, 200)

    def test_registration_creates_profile_without_exposing_credentials(self):
        with patch.object(sparql_client, "create_entity") as create_profile:
            response = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(response.status_code, 201)
        account = response.json()
        self.assertEqual(account["role"], "STUDENT")
        self.assertTrue(account["profile_iri"].startswith("profil_"))
        self.assertNotIn("password", account)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        create_profile.assert_called_once()
        self.assertEqual(create_profile.call_args.args[2], {"aNom": "Test Learner"})

        row = auth_store.account_by_email("learner@example.test")
        self.assertIsNotNone(row)
        self.assertNotEqual(row["password_hash"], "Secure-test-password-42")

    def test_registration_rejects_duplicate_email_and_admin_role(self):
        with patch.object(sparql_client, "create_entity"):
            first = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
            duplicate = self.client.post(
                "/auth/register",
                json=self.registration_payload(full_name="Another Learner"),
                headers={"Origin": "http://localhost:4200"},
            )
            admin = self.client.post(
                "/auth/register",
                json=self.registration_payload(email="admin@example.test", profile_type="ADMIN"),
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(admin.status_code, 422)

    def test_login_logout_and_anonymous_api_access(self):
        with patch.object(sparql_client, "create_entity"):
            self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        self.client.cookies.clear()

        anonymous = self.client.get("/api/stats")
        login = self.client.post("/auth/login", json={
            "email": "learner@example.test",
            "password": "Secure-test-password-42",
        })
        current = self.client.get("/auth/me")
        with patch.object(sparql_client, "get_stats", return_value={"competences": 0}):
            protected = self.client.get("/api/stats")
        logout = self.client.post(
            "/auth/logout",
            headers={"Origin": "http://localhost:4200"},
        )
        after_logout = self.client.get("/auth/me")

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(protected.status_code, 200)
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(after_logout.status_code, 401)

    def test_recommendations_use_the_authenticated_profile(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        expected = [{
            "competence": "Docker",
            "score": 2,
            "explanations": ["Related to Linux: both required by DevOps."],
            "teachings": [],
        }]
        with patch.object(
            sparql_client,
            "recommendations_for_profile",
            return_value=expected,
        ) as recommend:
            response = self.client.get("/me/recommendations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        recommend.assert_called_once_with(profile_id)

    def test_recommendations_are_not_available_to_admin_accounts(self):
        self.login_admin()
        with patch.object(sparql_client, "recommendations_for_profile") as recommend:
            response = self.client.get("/me/recommendations")

        self.assertEqual(response.status_code, 403)
        recommend.assert_not_called()

    def test_career_bridges_use_the_authenticated_profile(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        expected = [{
            "occupationId": "met_devops",
            "occupation": "DevOps Engineer",
            "family": "Technology",
            "percent": 50,
            "coveredNames": ["Python"],
            "missingNames": ["Docker"],
            "trainings": [{"competence": "Docker", "trainings": []}],
        }]
        with patch.object(
            sparql_client,
            "career_bridges_for_profile",
            return_value=expected,
        ) as bridges:
            response = self.client.get("/me/career-bridges")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        bridges.assert_called_once_with(profile_id)

    def test_career_bridges_are_not_available_to_admin_accounts(self):
        self.login_admin()
        with patch.object(sparql_client, "career_bridges_for_profile") as bridges:
            response = self.client.get("/me/career-bridges")

        self.assertEqual(response.status_code, 403)
        bridges.assert_not_called()

    def test_development_login_is_not_rate_limited(self):
        auth_store.create_admin(
            "dev-rate-limit@example.test",
            "Development Admin",
            PASSWORD_HASHER.hash("Valid-development-password-2026!"),
        )
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
            failures = [
                self.client.post("/auth/login", json={
                    "email": "dev-rate-limit@example.test",
                    "password": "wrong-password",
                })
                for _ in range(10)
            ]
            successful_login = self.client.post(
                "/auth/login",
                json={
                    "email": "dev-rate-limit@example.test",
                    "password": "Valid-development-password-2026!",
                },
            )

        self.assertTrue(all(response.status_code == 401 for response in failures))
        self.assertEqual(successful_login.status_code, 200)

    def test_development_registration_is_not_rate_limited(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
            with patch.object(sparql_client, "create_entity"):
                registrations = [
                    self.client.post(
                        "/auth/register",
                        json=self.registration_payload(
                            email=f"development-{index}@example.test"
                        ),
                        headers={"Origin": "http://localhost:4200"},
                    )
                    for index in range(10)
                ]

        self.assertTrue(all(response.status_code == 201 for response in registrations))

    def test_development_forgot_password_is_not_rate_limited(self):
        auth_store.create_admin(
            "dev-reset@example.test",
            "Development Admin",
            PASSWORD_HASHER.hash("Valid-development-password-2026!"),
        )
        with patch.dict(os.environ, {
            "ENVIRONMENT": "development",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_FROM": "noreply@example.test",
        }):
            with patch("app.auth.send_reset_email"):
                responses = [
                    self.client.post(
                        "/auth/forgot-password",
                        json={"email": "dev-reset@example.test"},
                    )
                    for _ in range(10)
                ]

        self.assertTrue(all(response.status_code == 200 for response in responses))

    def test_login_rate_limit_remains_enabled_outside_development(self):
        auth_store.create_admin(
            "production-rate-limit@example.test",
            "Production Admin",
            PASSWORD_HASHER.hash("Valid-production-password-2026!"),
        )
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            failures = [
                self.client.post("/auth/login", json={
                    "email": "production-rate-limit@example.test",
                    "password": "wrong-password",
                })
                for _ in range(8)
            ]
            blocked = self.client.post("/auth/login", json={
                "email": "production-rate-limit@example.test",
                "password": "Valid-production-password-2026!",
            })

        self.assertTrue(all(response.status_code == 401 for response in failures))
        self.assertEqual(blocked.status_code, 429)

    def test_password_reset_revokes_existing_session(self):
        with patch.object(sparql_client, "create_entity"):
            self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        self.client.cookies.clear()

        with patch.dict(os.environ, {"SMTP_HOST": "smtp.example.test", "SMTP_FROM": "noreply@example.test"}):
            with patch("app.auth.send_reset_email") as send_email:
                forgotten = self.client.post(
                    "/auth/forgot-password",
                    json={"email": "learner@example.test"},
                )
                reset_token = send_email.call_args.args[1]
                reset = self.client.post("/auth/reset-password", json={
                    "token": reset_token,
                    "password": "A-different-password-73",
                    "password_confirmation": "A-different-password-73",
                })

        self.assertEqual(forgotten.status_code, 200)
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        login = self.client.post("/auth/login", json={
            "email": "learner@example.test",
            "password": "A-different-password-73",
        })
        self.assertEqual(login.status_code, 200)

    def test_non_admin_cannot_manage_users_or_repository(self):
        with patch.object(sparql_client, "create_entity"):
            self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )

        users = self.client.get("/admin/users")
        repository_write = self.client.post(
            "/api/Parcours",
            json={"id": "parc_test", "properties": {"aNom": "Test"}},
            headers={"Origin": "http://localhost:4200"},
        )

        self.assertEqual(users.status_code, 403)
        self.assertEqual(repository_write.status_code, 403)

    def test_bootstrapped_admin_can_access_user_management(self):
        auth_store.create_admin(
            "admin@example.test",
            "Test Administrator",
            PASSWORD_HASHER.hash("Admin-test-password-89"),
        )
        login = self.client.post("/auth/login", json={
            "email": "admin@example.test",
            "password": "Admin-test-password-89",
        })

        users = self.client.get("/admin/users")

        self.assertEqual(login.status_code, 200)
        self.assertEqual(users.status_code, 200)
        self.assertEqual(users.json()[0]["role"], "ADMIN")

    def test_admin_dashboard_analytics_is_derived_from_ontology_counts(self):
        self.login_admin()

        with patch.object(sparql_client, "competences_par_categorie", return_value=[
            {"category": "CompetenceTechnique", "total": "4"},
            {"category": "CompetenceTransverse", "total": "2"},
        ]), patch.object(sparql_client, "metiers_par_famille", return_value=[
            {"family": "FamilleIT", "familyName": "Famille IT", "total": "3"},
        ]), patch.object(sparql_client, "profils_par_type", return_value=[
            {"profileClass": "ProfilEtudiant", "total": "2"},
            {"profileClass": "ProfilProfessionnel", "total": "1"},
        ]), patch.object(sparql_client, "formations_par_type", return_value=[
            {"formationClass": "FormationEnLigne", "total": "3"},
        ]), patch.object(sparql_client, "individus_par_classe", return_value=[
            {"rootClass": "Competence", "total": "6"},
        ]), patch.object(sparql_client, "get_stats", return_value={"metiers": 4}):
            response = self.client.get("/admin/dashboard/analytics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["competencyDistribution"], [
            {"key": "CompetenceTechnique", "label": "Technical competencies", "count": 4},
            {"key": "CompetenceTransverse", "label": "Transversal competencies", "count": 2},
        ])
        self.assertEqual(payload["profilesDistribution"][0], {
            "key": "ProfilEtudiant", "label": "Students", "count": 2,
        })
        self.assertEqual(payload["trainingsDistribution"], [
            {"key": "FormationEnLigne", "label": "Online trainings", "count": 3},
        ])
        self.assertEqual(payload["repositoryOverview"], [
            {"key": "Competence", "label": "Competencies", "count": 6},
        ])
        # 4 occupations declared, 3 attached to a family -> 1 without a family.
        self.assertEqual(payload["occupationsByFamily"], [
            {"key": "FamilleIT", "label": "Famille IT", "count": 3},
            {"key": "__unassigned__", "label": "No family declared", "count": 1},
        ])

    def test_admin_dashboard_analytics_requires_an_admin_session(self):
        anonymous = self.client.get("/admin/dashboard/analytics")

        with patch.object(sparql_client, "create_entity"):
            self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        learner = self.client.get("/admin/dashboard/analytics")

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(learner.status_code, 403)

    def test_admin_can_access_dashboard_statistics_and_entity_crud(self):
        auth_store.create_admin(
            "admin@example.test",
            "Test Administrator",
            PASSWORD_HASHER.hash("Admin-test-password-89"),
        )
        login = self.client.post("/auth/login", json={
            "email": "admin@example.test",
            "password": "Admin-test-password-89",
        })
        self.assertEqual(login.status_code, 200)

        with patch.object(sparql_client, "get_stats", return_value={"competences": 3}), \
                patch.object(sparql_client, "list_individuals", return_value=[]) as list_items:
            stats = self.client.get("/api/stats")
            items = self.client.get("/api/Competence")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.json(), {"competences": 3})
        self.assertEqual(items.status_code, 200)
        list_items.assert_called_once_with("Competence", None, False)

        payload = {"id": "comp_admin_test", "properties": {"aNom": "Admin test"}}
        with patch.object(sparql_client, "create_entity") as create_entity:
            created = self.client.post(
                "/api/Competence",
                json=payload,
                headers={"Origin": "http://localhost:4200"},
            )
        self.assertEqual(created.status_code, 201)
        create_entity.assert_called_once_with(
            "Competence", "comp_admin_test", {"aNom": "Admin test"}, {}, None
        )

        detail = {
            "id": "comp_admin_test",
            "type": "Competence",
            "properties": {},
            "relations": {},
        }
        with patch.object(sparql_client, "get_entity_detail", return_value=detail), \
                patch.object(sparql_client, "update_entity") as update_entity:
            updated = self.client.put(
                "/api/Competence/comp_admin_test",
                json={"properties": {"aNom": "Updated by admin"}},
                headers={"Origin": "http://localhost:4200"},
            )
        self.assertEqual(updated.status_code, 200)
        update_entity.assert_called_once_with(
            "Competence", "comp_admin_test", {"aNom": "Updated by admin"}, {}, None
        )

        with patch.object(sparql_client, "get_entity_detail", return_value=detail), \
                patch.object(sparql_client, "delete_entity", return_value=0) as delete_entity:
            deleted = self.client.delete(
                "/api/Competence/comp_admin_test",
                headers={"Origin": "http://localhost:4200"},
            )
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        delete_entity.assert_called_once_with("comp_admin_test")

    def test_public_catalogue_and_dashboard_endpoints_return_live_data(self):
        catalogue = [{
            "id": "form_online",
            "nom": "Online training",
            "type": "FormationEnLigne",
            "duree_heures": 8,
            "competences_enseignees": [{"id": "comp_python", "label": "Python"}],
            "prerequis": [{"id": "form_intro", "label": "Introduction"}],
        }]
        detail = {
            "relations": {
                "contientModule": [{"id": "mod_python", "label": "Python module"}]
            }
        }
        module_detail = {
            "label": "Python module",
            "relations": {
                "moduleEnseigne": [{"id": "comp_python", "label": "Python"}]
            },
        }
        with (
            patch.object(sparql_client, "get_stats", return_value={
                "competences": 4, "formations": 3, "metiers": 2,
                "profils": 1, "modules": 1, "parcours": 0, "evaluations": 0,
            }),
            patch.object(sparql_client, "catalogue_formations", return_value=catalogue),
            patch.object(sparql_client, "get_entity_detail", side_effect=[detail, module_detail]),
        ):
            dashboard = self.client.get("/dashboard")
            trainings = self.client.get("/formations")
            training = self.client.get("/formations/form_online")
            module = self.client.get("/modules/mod_python")

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json(), {"competences": 4, "formations": 3, "metiers": 2})
        self.assertEqual(trainings.json(), catalogue)
        self.assertEqual(training.json()["modules"], [{"id": "mod_python", "label": "Python module"}])
        self.assertEqual(
            module.json()["competences_enseignees"],
            [{"id": "comp_python", "label": "Python"}],
        )

    def test_follow_training_appends_only_to_the_authenticated_profiles_followed_list(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        self.assertEqual(registration.status_code, 201)
        profile_id = registration.json()["profile_iri"]
        current_profile = {
            "relations": {
                "aSuivi": [{"id": "form_existing", "label": "Existing training"}]
            }
        }
        with (
            patch.object(sparql_client, "get_entity_detail", return_value=current_profile),
            patch.object(sparql_client, "add_followed_trainings") as append_followed,
        ):
            response = self.client.put(
                f"/profils/{profile_id}",
                json={"formations_suivies": ["form_new"]},
                headers={"Origin": "http://localhost:4200"},
            )
            forbidden = self.client.put(
                "/profils/profil_someone_else",
                json={"formations_suivies": ["form_new"]},
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["formations_suivies"],
            ["form_existing", "form_new"],
        )
        append_followed.assert_called_once_with(profile_id, ["form_new"])
        self.assertEqual(forbidden.status_code, 403)

    def test_training_creation_rejects_module_as_prerequisite(self):
        self.login_admin()
        with patch.object(sparql_client, "run_query", return_value=[]):
            response = self.client.post(
                "/api/Formation",
                json={
                    "id": "form_invalid_prerequisite",
                    "properties": {"aNom": "Invalid prerequisite"},
                    "relations": {"aPourPrerequis": ["mod_python"]},
                },
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("mod_python", response.json()["detail"])
        self.assertIn("Formation", response.json()["detail"])

    def test_training_creation_rejects_non_competence_in_teaches(self):
        self.login_admin()
        with patch.object(sparql_client, "run_query", return_value=[]):
            response = self.client.post(
                "/api/Formation",
                json={
                    "id": "form_invalid_teaches",
                    "properties": {"aNom": "Invalid teaches relation"},
                    "relations": {"enseigne": ["form_not_a_competence"]},
                },
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("form_not_a_competence", response.json()["detail"])
        self.assertIn("Competence", response.json()["detail"])

    def test_training_update_rejects_itself_as_prerequisite(self):
        self.login_admin()
        detail = {
            "id": "form_self_prerequisite",
            "type": "Formation",
            "properties": {"aNom": ["Self prerequisite"]},
            "relations": {},
        }
        with patch.object(sparql_client, "get_entity_detail", return_value=detail):
            response = self.client.put(
                "/api/Formation/form_self_prerequisite",
                json={"relations": {"aPourPrerequis": ["form_self_prerequisite"]}},
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("propre prérequis", response.json()["detail"])

    def test_training_creation_rejects_module_even_when_it_looks_like_a_formation(self):
        self.login_admin()

        def fake_run_query(query):
            # Le module est typé Module (et, par erreur, comme Formation) dans les données.
            if "onto:Module" in query:
                return [{"id": "http://www.skillpath.tn/onto#mod_python"}]
            return []

        with patch.object(sparql_client, "run_query", side_effect=fake_run_query):
            response = self.client.post(
                "/api/Formation",
                json={
                    "id": "form_module_prerequisite",
                    "properties": {"aNom": "Module as prerequisite"},
                    "relations": {"aPourPrerequis": ["mod_python"]},
                },
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("mod_python", response.json()["detail"])
        self.assertIn("Module", response.json()["detail"])

    def test_formation_option_list_never_contains_a_module(self):
        with patch.object(sparql_client, "run_query", return_value=[]) as run:
            sparql_client.list_individuals("Formation", include_class=True)

        query = run.call_args.args[0]
        self.assertIn("rdfs:subClassOf* onto:Formation", query)
        self.assertIn("FILTER NOT EXISTS", query)
        self.assertIn("onto:Module", query)

    def test_module_option_list_is_strictly_typed_as_module(self):
        with patch.object(sparql_client, "run_query", return_value=[]) as run:
            sparql_client.list_individuals("Module")

        query = run.call_args.args[0]
        self.assertIn("rdfs:subClassOf* onto:Module", query)
        self.assertNotIn("FILTER NOT EXISTS", query)
        self.assertNotIn("onto:Formation", query)

    def test_training_duration_and_start_date_are_stored_as_typed_literals(self):
        self.login_admin()
        with patch.object(sparql_client, "run_query", return_value=[]):
            with patch.object(sparql_client, "run_update") as run_update:
                response = self.client.post(
                    "/api/Formation",
                    json={
                        "id": "form_typed_properties",
                        "properties": {
                            "aNom": "Typed properties",
                            "aDureeHeures": "12",
                            "aDateDebut": "2026-10-28T10:00",
                        },
                        "relations": {},
                    },
                    headers={"Origin": "http://localhost:4200"},
                )

        self.assertEqual(response.status_code, 201)
        update_query = run_update.call_args.args[0]
        self.assertIn('"12"^^xsd:integer', update_query)
        self.assertIn('"2026-10-28T10:00:00"^^xsd:dateTime', update_query)

    def test_startup_seeder_creates_admin_without_ontology_profile(self):
        password = "Local-dev-admin-password-2026!"
        output = StringIO()
        with patch.dict(os.environ, {
            "ENVIRONMENT": "development",
            "SKILLPATH_ADMIN_PASSWORD": password,
        }), redirect_stdout(output):
            initialize_auth_database()

        output_lines = output.getvalue().splitlines()
        self.assertIn(
            "Admin seeder: development password loaded from "
            "SKILLPATH_ADMIN_PASSWORD (value redacted).",
            output_lines,
        )
        self.assertIn("Admin seeder: Argon2id hash generated and verified.", output_lines)
        self.assertIn("Admin créé avec succès", output_lines)
        self.assertIn("Email : nour.hasni02@gmail.com", output_lines)
        account = auth_store.account_by_email("nour.hasni02@gmail.com")
        self.assertIsNotNone(account)
        self.assertEqual(account["role"], "ADMIN")
        self.assertIsNone(account["profile_iri"])
        self.assertEqual(PASSWORD_HASHER.type.name, "ID")
        self.assertTrue(account["password_hash"].startswith("$argon2id$"))
        self.assertNotEqual(account["password_hash"], password)
        self.assertTrue(PASSWORD_HASHER.verify(account["password_hash"], password))
        self.assertNotIn(password, output.getvalue())

        login = self.client.post("/auth/login", json={
            "email": "nour.hasni02@gmail.com",
            "password": password,
        })
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["role"], "ADMIN")

    def test_startup_seeder_updates_existing_admin_credentials(self):
        old_password = "Existing-admin-password-2026!"
        original_account = auth_store.create_admin(
            "nour.hasni02@gmail.com",
            "Existing Account",
            PASSWORD_HASHER.hash(old_password),
        )
        old_login = self.client.post("/auth/login", json={
            "email": "nour.hasni02@gmail.com",
            "password": old_password,
        })
        self.assertEqual(old_login.status_code, 200)

        password = "Updated-dev-admin-password-2026!"
        output = StringIO()
        with patch.dict(os.environ, {
            "ENVIRONMENT": "development",
            "SKILLPATH_ADMIN_PASSWORD": password,
        }), redirect_stdout(output):
            initialize_auth_database()

        updated_account = auth_store.account_by_email("nour.hasni02@gmail.com")
        self.assertIn("Admin mis à jour avec succès", output.getvalue())
        self.assertIn("Email : nour.hasni02@gmail.com", output.getvalue())
        self.assertEqual(updated_account["id"], original_account.id)
        self.assertEqual(updated_account["full_name"], "Nour Hasni")
        self.assertEqual(updated_account["role"], "ADMIN")
        self.assertIsNone(updated_account["profile_iri"])
        self.assertTrue(updated_account["password_hash"].startswith("$argon2id$"))
        self.assertTrue(PASSWORD_HASHER.verify(updated_account["password_hash"], password))
        self.assertIn(
            "Admin seeder: Argon2id hash generated and verified.",
            output.getvalue(),
        )
        self.assertNotIn(password, output.getvalue())
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

        updated_login = self.client.post("/auth/login", json={
            "email": "nour.hasni02@gmail.com",
            "password": password,
        }, headers={"Origin": "http://localhost:4200"})
        self.assertEqual(updated_login.status_code, 200)

    def test_startup_seeder_is_disabled_outside_development(self):
        with patch.dict(os.environ, {
            "ENVIRONMENT": "production",
            "SKILLPATH_ADMIN_PASSWORD": "Local-dev-admin-password-2026!",
        }):
            initialize_auth_database()

        self.assertIsNone(auth_store.account_by_email("nour.hasni02@gmail.com"))

    def test_application_lifespan_runs_and_logs_admin_seeder(self):
        from app.main import app

        output = StringIO()
        with patch("app.main.auth_store.initialize_store") as initialize_store:
            with patch("app.main.seed_admin_account") as seed_admin:
                context = TestClient(app)
                with redirect_stdout(output):
                    context.__enter__()
                    context.__exit__(None, None, None)

        initialize_store.assert_called_once()
        seed_admin.assert_called_once()
        self.assertIn("SkillPath startup: initializing authentication store.", output.getvalue())
        self.assertIn("SkillPath startup: running Admin seeder.", output.getvalue())

    def test_student_cannot_analyze_or_optimize_another_profiles_data(self):
        with patch.object(sparql_client, "create_entity"):
            self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )

        response = self.client.get(
            "/analyse",
            params={"profil": "profil_someone_else", "metier": "met_test"},
        )
        optimal_path = self.client.get(
            "/learning-path",
            params={"profil": "profil_someone_else", "metier": "met_test"},
        )
        generated_candidates = self.client.get(
            "/parcours-optimal",
            params={"profil": "profil_someone_else", "metier": "met_test"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(optimal_path.status_code, 403)
        self.assertEqual(generated_candidates.status_code, 403)

    def test_account_can_save_a_path_and_only_complete_its_trainings(self):
        with patch.object(sparql_client, "create_entity"):
            self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )

        catalogue = [
            {"formation": "form_cloud"},
            {"formation": "form_advanced", "prereq": "form_cloud"},
        ]
        with patch.object(sparql_client, "create_entity") as create_path:
            with patch.object(
                sparql_client,
                "get_entity_detail",
                return_value={"relations": {"parcours": []}},
            ):
                with patch.object(
                    sparql_client, "formations_et_prerequis", return_value=catalogue
                ):
                    with patch.object(sparql_client, "update_entity") as link_path:
                        invalid_order = self.client.post(
                            "/account/parcours",
                            json={"trainings": ["form_advanced", "form_cloud"]},
                            headers={"Origin": "http://localhost:4200"},
                        )
                        saved = self.client.post(
                            "/account/parcours",
                            json={"trainings": ["form_cloud", "form_advanced"]},
                            headers={"Origin": "http://localhost:4200"},
                        )

        self.assertEqual(invalid_order.status_code, 400)
        self.assertEqual(saved.status_code, 201)
        path_id = saved.json()["id"]
        create_path.assert_called_once()
        self.assertEqual(
            create_path.call_args.args[2]["aOrdreFormations"],
            '["form_cloud","form_advanced"]',
        )
        link_path.assert_called_once()

        profile_detail = {
            "relations": {
                "parcours": [{
                    "id": path_id,
                    "formations": [{"id": "form_cloud", "label": "Cloud"}],
                }],
                "aSuivi": [],
            }
        }
        with patch.object(sparql_client, "get_entity_detail", return_value=profile_detail):
            with patch.object(sparql_client, "update_entity") as update_progress:
                complete = self.client.put(
                    f"/account/parcours/{path_id}/progress",
                    json={"completed_trainings": ["form_cloud"]},
                    headers={"Origin": "http://localhost:4200"},
                )
                invalid = self.client.put(
                    f"/account/parcours/{path_id}/progress",
                    json={"completed_trainings": ["form_other"]},
                    headers={"Origin": "http://localhost:4200"},
                )

        self.assertEqual(complete.status_code, 200)
        self.assertEqual(complete.json()["completed_trainings"], ["form_cloud"])
        self.assertEqual(invalid.status_code, 400)
        update_progress.assert_called_once()

    def test_parcours_creation_rejects_start_date_property(self):
        # sp:aDateDebut a pour domaine Formation : elle est interdite sur un Parcours.
        self.login_admin()
        with patch.object(sparql_client, "run_query", return_value=[]):
            response = self.client.post(
                "/api/Parcours",
                json={
                    "id": "parc_invalid_start_date",
                    "properties": {
                        "aNom": "Invalid parcours",
                        "aDateDebut": "2026-10-28T10:00",
                    },
                    "relations": {},
                },
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("aDateDebut", response.json()["detail"])
        self.assertIn("Formation", response.json()["detail"])

    def test_generated_learning_path_is_named_after_occupation_and_profile_name(self):
        with patch.object(sparql_client, "create_entity"):
            self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )

        profile_detail = {
            "id": "profil_test",
            "properties": {"aNom": ["Ahmed Ben Ali"]},
            "relations": {
                "vise": [{"id": "met_cloud", "label": "Cloud Engineer"}],
                "parcours": [],
            },
        }
        catalogue = [{"formation": "form_cloud"}]
        with patch.object(sparql_client, "get_entity_detail", return_value=profile_detail):
            with patch.object(sparql_client, "formations_et_prerequis", return_value=catalogue):
                with patch.object(sparql_client, "create_entity") as create_path:
                    with patch.object(sparql_client, "update_entity"):
                        saved = self.client.post(
                            "/account/parcours",
                            json={"trainings": ["form_cloud"]},
                            headers={"Origin": "http://localhost:4200"},
                        )

        self.assertEqual(saved.status_code, 201)
        expected_name = "Learning path: Cloud Engineer - Ahmed Ben Ali"
        self.assertEqual(saved.json()["label"], expected_name)
        # Le libellé est le nom lisible : le hash reste confiné dans l'identifiant.
        self.assertEqual(create_path.call_args.args[2]["aNom"], expected_name)
        self.assertNotIn("parc_", create_path.call_args.args[2]["aNom"])
        self.assertTrue(create_path.call_args.args[1].startswith("parc_"))

    def test_optimal_paths_are_separate_from_the_personalized_single_path(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        details = {"aAcquis": ["comp_acquired"], "aSuivi": []}
        catalogue = [
            {"formation": "form_foundation"},
            {
                "formation": "form_advanced",
                "competence": "comp_missing",
                "prereq": "form_foundation",
            },
        ]
        metadata = [
            {"formation": "form_foundation", "label": "Foundation", "duree": "2"},
            {"formation": "form_advanced", "label": "Advanced", "duree": "4"},
        ]
        effective = [{"competence": "comp_acquired", "source": "direct"}]
        with (
            patch.object(sparql_client, "profil_details", return_value=details),
            patch.object(sparql_client, "competences_effectives", return_value=effective),
        ):
            with patch.object(sparql_client, "get_entity_detail", return_value={}):
                with patch.object(sparql_client, "formations_et_prerequis", return_value=catalogue):
                    with patch.object(sparql_client, "formations_meta", return_value=metadata):
                        with patch.object(
                            sparql_client,
                            "competences_requises",
                            return_value=[
                                {"competence": "comp_acquired"},
                                {"competence": "comp_missing"},
                            ],
                        ):
                            with patch.object(sparql_client, "formations_recommandees", return_value=[]):
                                optimal = self.client.get(
                                    "/parcours-optimal",
                                    params={"profil": profile_id, "metier": "met_test"},
                                )
                                personalized = self.client.get(
                                    "/learning-path",
                                    params={"profil": profile_id, "metier": "met_test"},
                                )
                                skill_gap = self.client.get(
                                    "/analyse",
                                    params={"profil": profile_id, "metier": "met_test"},
                                )

        self.assertEqual(optimal.status_code, 200)
        path = optimal.json()
        self.assertEqual(path["competences_acquises"], ["comp_acquired"])
        self.assertEqual(path["competences_manquantes"], ["comp_missing"])
        self.assertEqual(
            path["candidates"][0]["training_ids"],
            ["form_foundation", "form_advanced"],
        )
        self.assertEqual(path["candidates"][0]["duration_hours"], 6)
        self.assertEqual(personalized.status_code, 200)
        personalized_path = personalized.json()
        self.assertNotIn("candidates", personalized_path)
        self.assertEqual(
            [step["formation"] for step in personalized_path["etapes"]],
            ["form_foundation", "form_advanced"],
        )
        self.assertEqual(personalized_path["competences_non_couvertes"], [])
        self.assertEqual(skill_gap.status_code, 200)
        self.assertEqual(skill_gap.json()["competences_manquantes"], ["comp_missing"])

    def test_optimal_report_separates_acquired_skills_completed_trainings_and_recommendations(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        details = {
            "aAcquis": ["comp_Python"],
            "aSuivi": ["form_MoocPython"],
        }
        catalogue = [
            {"formation": "form_MoocPython", "competence": "comp_Python"},
            {"formation": "form_foundation"},
            {
                "formation": "form_SQL",
                "competence": "comp_SQL",
                "prereq": "form_foundation",
            },
        ]
        metadata = [
            {"formation": "form_MoocPython", "label": "Python MOOC"},
            {"formation": "form_foundation", "label": "Foundation"},
            {"formation": "form_SQL", "label": "SQL"},
        ]
        effective = [{"competence": "comp_Python", "source": "direct"}]
        with (
            patch.object(sparql_client, "profil_details", return_value=details),
            patch.object(sparql_client, "competences_effectives", return_value=effective),
        ):
            with patch.object(sparql_client, "get_entity_detail", return_value={}):
                with patch.object(sparql_client, "formations_et_prerequis", return_value=catalogue):
                    with patch.object(sparql_client, "formations_meta", return_value=metadata):
                        with patch.object(
                            sparql_client,
                            "competences_requises",
                            return_value=[
                                {"competence": "comp_Python"},
                                {"competence": "comp_SQL"},
                            ],
                        ):
                            response = self.client.get(
                                "/parcours-optimal",
                                params={"profil": profile_id, "metier": "met_test"},
                            )

        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["competences_acquises"], ["comp_Python"])
        self.assertEqual(report["competences_manquantes"], ["comp_SQL"])
        self.assertEqual(report["competences_sans_formation"], [])
        self.assertEqual(
            report["etapes_terminees"][0]["formation"],
            "form_MoocPython",
        )
        self.assertEqual(
            [step["formation"] for step in report["etapes"]],
            ["form_foundation", "form_SQL"],
        )
        self.assertEqual(
            report["progression"],
            {
                "total": 2,
                "terminees": 0,
                "pourcentage": 0,
                "heures_restantes": None,
                "duree_disponible": False,
            },
        )

    def test_optimal_report_recomputes_per_occupation_and_counts_only_real_missing_skill_links(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        details = {
            "aAcquis": [
                "comp_Cloud",
                "comp_Git",
                "comp_Java",
                "comp_Kubernetes",
                "comp_SQL",
            ],
            "aSuivi": ["form_MoocML", "form_MoocPython"],
        }
        effective = [
            {"competence": "comp_Cloud", "source": "direct"},
            {"competence": "comp_Git", "source": "direct"},
            {"competence": "comp_Java", "source": "direct"},
            {"competence": "comp_Kubernetes", "source": "direct"},
            {"competence": "comp_SQL", "source": "direct"},
        ]
        catalogue = [
            {"formation": "form_FormationJava", "competence": "_comp_Communication"},
            {"formation": "form_FormationJava", "competence": "comp_Java"},
            {"formation": "form_MoocDocker", "competence": "comp_Docker"},
            {"formation": "form_FormationDevOps", "competence": "comp_Docker",
             "prereq": "form_MoocDocker"},
            {"formation": "form_FormationDevOps", "competence": "comp_Kubernetes"},
        ]
        occupation_skills = {
            "met_BackendDeveloper": [
                "_comp_Communication",
                "comp_Docker",
                "comp_Git",
                "comp_Java",
                "comp_SQL",
            ],
            "met_DevOps": [
                "_comp_Communication",
                "comp_Cloud",
                "comp_Docker",
                "comp_Git",
                "comp_Kubernetes",
            ],
        }
        with (
            patch.object(sparql_client, "profil_details", return_value=details),
            patch.object(sparql_client, "competences_effectives", return_value=effective),
        ):
            with patch.object(sparql_client, "get_entity_detail", return_value={}):
                with patch.object(sparql_client, "formations_et_prerequis", return_value=catalogue):
                    with patch.object(sparql_client, "formations_meta", return_value=[]):
                        with patch.object(
                            sparql_client,
                            "competences_requises",
                            side_effect=lambda occupation: [
                                {"competence": skill}
                                for skill in occupation_skills[occupation]
                            ],
                        ):
                            backend = self.client.get(
                                "/parcours-optimal",
                                params={
                                    "profil": profile_id,
                                    "metier": "met_BackendDeveloper",
                                },
                            )
                            devops = self.client.get(
                                "/parcours-optimal",
                                params={"profil": profile_id, "metier": "met_DevOps"},
                            )

        self.assertEqual(backend.status_code, 200)
        self.assertEqual(devops.status_code, 200)
        backend_report = backend.json()
        devops_report = devops.json()
        self.assertEqual(backend_report["competences_requises"], occupation_skills["met_BackendDeveloper"])
        self.assertEqual(devops_report["competences_requises"], occupation_skills["met_DevOps"])
        self.assertEqual(
            backend_report["competences_acquises"],
            ["comp_Git", "comp_Java", "comp_SQL"],
        )
        self.assertEqual(
            devops_report["competences_acquises"],
            ["comp_Cloud", "comp_Git", "comp_Kubernetes"],
        )
        expected_missing = ["_comp_Communication", "comp_Docker"]
        self.assertEqual(backend_report["competences_manquantes"], expected_missing)
        self.assertEqual(devops_report["competences_manquantes"], expected_missing)

        for report in (backend_report, devops_report):
            candidate = report["candidates"][0]
            self.assertEqual(candidate["covered_competencies"], expected_missing)
            self.assertEqual(candidate["uncovered_competencies"], [])
            self.assertEqual(candidate["coverage_ratio"], 1.0)
            taught_by_training = {
                "form_FormationJava": {"_comp_Communication", "comp_Java"},
                "form_MoocDocker": {"comp_Docker"},
                "form_FormationDevOps": {"comp_Docker", "comp_Kubernetes"},
            }
            for step in candidate["etapes"]:
                self.assertTrue(
                    set(step["competences_couvertes"])
                    <= taught_by_training[step["formation"]]
                )
                self.assertEqual(
                    set(step["competences_couvertes"]),
                    taught_by_training[step["formation"]]
                    & set(report["competences_manquantes"]),
                )
        self.assertEqual(
            [step["formation"] for step in backend_report["etapes"]],
            ["form_FormationJava", "form_MoocDocker"],
        )
        self.assertEqual(
            [step["formation"] for step in devops_report["etapes"]],
            ["form_FormationJava", "form_MoocDocker"],
        )

    def test_professional_profile_is_persisted_and_retrievable_after_relogin(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(
                    full_name="Grace Hopper",
                    email="professional@example.test",
                    profile_type="PROFESSIONAL",
                ),
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(registration.status_code, 201)
        profile_iri = registration.json()["profile_iri"]
        self.assertEqual(registration.json()["role"], "PROFESSIONAL")

        experience = "Ten years in software engineering and cloud platforms."
        payload = {
            "full_name": "Grace Hopper",
            "experience": experience,
            "target_occupation": "met_DataEngineer",
            "acquired_competences": ["comp_Python", "comp_SQL"],
            "completed_trainings": [],
        }
        with patch.object(sparql_client, "update_entity") as update_profile:
            saved = self.client.put(
                "/account/profile",
                json=payload,
                headers={"Origin": "http://localhost:4200"},
            )

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["experience"], experience)
        update_profile.assert_called_once()
        self.assertEqual(update_profile.call_args.args[0], "ProfilUtilisateur")
        self.assertEqual(update_profile.call_args.args[1], profile_iri)
        self.assertEqual(
            update_profile.call_args.args[3]["vise"], ["met_DataEngineer"]
        )
        self.assertEqual(
            update_profile.call_args.args[3]["aAcquis"], ["comp_Python", "comp_SQL"]
        )

        detail = {
            "id": profile_iri,
            "type": "ProfilUtilisateur",
            "class": "ProfilProfessionnel",
            "label": "Grace Hopper",
            "properties": {"aNom": ["Grace Hopper"]},
            "relations": {
                "aAcquis": [
                    {"id": "comp_Python", "label": "Python"},
                    {"id": "comp_SQL", "label": "SQL"},
                ],
                "vise": [{"id": "met_DataEngineer", "label": "Data Engineer"}],
                "aSuivi": [],
                "parcours": [],
                "evaluations": [],
            },
        }
        with patch.object(sparql_client, "get_entity_detail", return_value=detail):
            fetched = self.client.get("/account/profile")

        self.assertEqual(fetched.status_code, 200)
        body = fetched.json()
        self.assertEqual(body["role"], "PROFESSIONAL")
        self.assertEqual(body["profile_iri"], profile_iri)
        self.assertEqual(
            body["profile"]["relations"]["vise"][0]["id"], "met_DataEngineer"
        )
        self.assertEqual(
            [item["id"] for item in body["profile"]["relations"]["aAcquis"]],
            ["comp_Python", "comp_SQL"],
        )

        # A fresh login must expose the same persisted profile and experience.
        self.client.cookies.clear()
        relogin = self.client.post(
            "/auth/login",
            json={
                "email": "professional@example.test",
                "password": "Secure-test-password-42",
            },
        )

        self.assertEqual(relogin.status_code, 200)
        self.assertEqual(relogin.json()["experience"], experience)
        self.assertEqual(relogin.json()["profile_iri"], profile_iri)

        with patch.object(sparql_client, "get_entity_detail", return_value=detail):
            refetched = self.client.get("/account/profile")
        self.assertEqual(refetched.status_code, 200)
        self.assertEqual(refetched.json()["experience"], experience)

    def test_admin_can_access_analysis_reports_but_others_cannot(self):
        with patch.object(sparql_client, "create_entity"):
            self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        forbidden = self.client.get("/admin/redundant-competencies")
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(self.client.get("/admin/shared-competencies").status_code, 403)
        self.assertEqual(self.client.get("/admin/untaught-competencies").status_code, 403)
        self.client.cookies.clear()

        auth_store.create_admin(
            "admin@example.test",
            "Test Administrator",
            PASSWORD_HASHER.hash("Admin-test-password-89"),
        )
        login = self.client.post("/auth/login", json={
            "email": "admin@example.test",
            "password": "Admin-test-password-89",
        })
        self.assertEqual(login.status_code, 200)

        items = [
            {"id": "comp_Python", "label": "comp_Python", "class": "CompetenceTechnique"},
            {"id": "comp_PythonProg", "label": "Python", "class": "CompetenceTechnique"},
            {"id": "comp_Kubernetes", "label": "comp_Kubernetes", "class": "CompetenceTechnique"},
        ]
        with patch.object(sparql_client, "list_individuals", return_value=items) as list_items:
            response = self.client.get(
                "/admin/redundant-competencies",
                params={"threshold": 0.75},
            )

        self.assertEqual(response.status_code, 200)
        list_items.assert_called_once_with("Competence", None, True)
        body = response.json()
        self.assertEqual(body["threshold"], 0.75)
        self.assertEqual(body["total_competencies"], 3)
        self.assertEqual(body["pair_count"], 1)
        pair = body["pairs"][0]
        self.assertEqual({pair["id_a"], pair["id_b"]}, {"comp_Python", "comp_PythonProg"})
        self.assertEqual(pair["score"], 1.0)
        self.assertTrue(pair["explanation"])

        with (
            patch.object(admin_analyses, "shared_competencies") as shared_report,
            patch.object(admin_analyses, "untaught_competencies") as untaught_report,
        ):
            shared_report.return_value = {"total_competencies": 0, "competencies": []}
            untaught_report.return_value = {"total_competencies": 0, "competencies": []}
            shared = self.client.get("/admin/shared-competencies")
            untaught = self.client.get("/admin/untaught-competencies")

        self.assertEqual(shared.status_code, 200)
        self.assertEqual(shared.json(), {"total_competencies": 0, "competencies": []})
        self.assertEqual(untaught.status_code, 200)
        self.assertEqual(untaught.json(), {"total_competencies": 0, "competencies": []})

    def test_skill_gap_analysis_remains_available(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]

        with (
            patch.object(sparql_client, "profil_details", return_value={"aAcquis": ["comp_Python"]}),
            patch.object(
                sparql_client,
                "competences_effectives",
                return_value=[{"competence": "comp_Python", "source": "direct"}],
            ),
            patch.object(
                sparql_client,
                "formations_et_prerequis",
                return_value=[{"formation": "form_Python", "competence": "comp_Python"}],
            ),
            patch.object(sparql_client, "formations_meta", return_value=[]),
            patch.object(
                sparql_client,
                "competences_requises",
                return_value=[{"competence": "comp_Python"}, {"competence": "comp_SQL"}],
            ),
            patch.object(sparql_client, "formations_recommandees", return_value=[]),
        ):
            response = self.client.get(
                "/analyse",
                params={"profil": profile_id, "metier": "met_BackendDeveloper"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["competences_requises"], ["comp_Python", "comp_SQL"])
        self.assertEqual(body["competences_acquises"], ["comp_Python"])
        self.assertEqual(body["match_score"], 50)

    def test_analyse_separates_declared_skills_from_followed_training_skills(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        effective = [
            {"competence": "comp_Python", "source": "direct"},
            {
                "competence": "comp_SQL",
                "source": "formation",
                "formation": "form_MoocSQL",
                "formationLabel": "MOOC SQL",
            },
        ]
        with (
            patch.object(
                sparql_client,
                "profil_details",
                return_value={"aAcquis": ["comp_Python"], "aSuivi": ["form_MoocSQL"]},
            ),
            patch.object(sparql_client, "competences_effectives", return_value=effective),
            patch.object(
                sparql_client,
                "formations_et_prerequis",
                return_value=[
                    {"formation": "form_MoocPython", "competence": "comp_Python"},
                    {"formation": "form_MoocSQL", "competence": "comp_SQL"},
                ],
            ),
            patch.object(sparql_client, "formations_meta", return_value=[]),
            patch.object(
                sparql_client,
                "competences_requises",
                return_value=[{"competence": "comp_Python"}, {"competence": "comp_SQL"}],
            ),
            patch.object(sparql_client, "formations_recommandees", return_value=[]),
        ):
            response = self.client.get(
                "/analyse",
                params={"profil": profile_id, "metier": "met_test"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["competences_acquises"], ["comp_Python", "comp_SQL"])
        self.assertEqual(body["competences_declarees"], ["comp_Python"])
        self.assertEqual(
            body["competences_via_formation"],
            [
                {
                    "competence": "comp_SQL",
                    "formation": "form_MoocSQL",
                    "formation_label": "MOOC SQL",
                }
            ],
        )
        self.assertEqual(body["competences_manquantes"], [])
        self.assertEqual(body["match_score"], 100)

    def test_effective_acquisition_query_unions_a_acquis_and_followed_trainings(self):
        with patch.object(sparql_client, "run_query", return_value=[]) as run:
            sparql_client.competences_effectives("profil_test")

        query = run.call_args.args[0]
        self.assertIn("sp:aAcquis", query)
        self.assertIn("sp:aSuivi", query)
        self.assertIn("UNION", query)
        self.assertIn("sp:enseigne", query)
        self.assertIn("sp:contientModule", query)
        self.assertIn("sp:moduleEnseigne", query)
        # Une formation simplement enregistrée dans un parcours ne doit jamais
        # être interprétée comme une acquisition.
        self.assertNotIn("suitParcours", query)
        self.assertNotIn("contientFormation", query)

    def test_saved_training_is_not_counted_as_an_acquired_skill(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        with (
            patch.object(
                sparql_client,
                "profil_details",
                return_value={"aAcquis": [], "aSuivi": []},
            ),
            # Le profil a bien enregistré un parcours contenant form_Saved,
            # mais aucune relation aSuivi : la requête effective ne renvoie rien.
            patch.object(sparql_client, "competences_effectives", return_value=[]),
            patch.object(
                sparql_client,
                "formations_et_prerequis",
                return_value=[{"formation": "form_Saved", "competence": "comp_Saved"}],
            ),
            patch.object(sparql_client, "formations_meta", return_value=[]),
            patch.object(
                sparql_client,
                "competences_requises",
                return_value=[{"competence": "comp_Saved"}],
            ),
            patch.object(sparql_client, "formations_recommandees", return_value=[]),
        ):
            response = self.client.get(
                "/analyse",
                params={"profil": profile_id, "metier": "met_test"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["competences_acquises"], [])
        self.assertEqual(body["competences_declarees"], [])
        self.assertEqual(body["competences_via_formation"], [])
        self.assertEqual(body["competences_manquantes"], ["comp_Saved"])

    def test_duplicate_effective_acquisitions_are_deduplicated_across_sources(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        effective = [
            {"competence": "comp_Python", "source": "direct"},
            {"competence": "comp_Python", "source": "direct"},
            {
                "competence": "comp_Python",
                "source": "formation",
                "formation": "form_A",
                "formationLabel": "Formation A",
            },
            {
                "competence": "comp_SQL",
                "source": "formation",
                "formation": "form_B",
                "formationLabel": "Formation B",
            },
            {
                "competence": "comp_SQL",
                "source": "formation",
                "formation": "form_B",
                "formationLabel": "Formation B",
            },
        ]
        with (
            patch.object(
                sparql_client,
                "profil_details",
                return_value={"aAcquis": ["comp_Python"], "aSuivi": ["form_A", "form_B"]},
            ),
            patch.object(sparql_client, "competences_effectives", return_value=effective),
            patch.object(
                sparql_client,
                "formations_et_prerequis",
                return_value=[
                    {"formation": "form_A", "competence": "comp_Python"},
                    {"formation": "form_B", "competence": "comp_SQL"},
                ],
            ),
            patch.object(sparql_client, "formations_meta", return_value=[]),
            patch.object(
                sparql_client,
                "competences_requises",
                return_value=[{"competence": "comp_Python"}, {"competence": "comp_SQL"}],
            ),
            patch.object(sparql_client, "formations_recommandees", return_value=[]),
        ):
            response = self.client.get(
                "/analyse",
                params={"profil": profile_id, "metier": "met_test"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["competences_declarees"], ["comp_Python"])
        self.assertEqual(
            body["competences_via_formation"],
            [
                {
                    "competence": "comp_SQL",
                    "formation": "form_B",
                    "formation_label": "Formation B",
                }
            ],
        )
        self.assertEqual(body["competences_acquises"], ["comp_Python", "comp_SQL"])

    def test_optimal_path_reports_missing_skills_no_catalogue_training_teaches(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        with (
            patch.object(
                sparql_client,
                "profil_details",
                return_value={"aAcquis": ["comp_Python"], "aSuivi": []},
            ),
            patch.object(
                sparql_client,
                "competences_effectives",
                return_value=[{"competence": "comp_Python", "source": "direct"}],
            ),
            patch.object(sparql_client, "get_entity_detail", return_value={}),
            patch.object(
                sparql_client,
                "formations_et_prerequis",
                return_value=[{"formation": "form_MoocSQL", "competence": "comp_SQL"}],
            ),
            patch.object(sparql_client, "formations_meta", return_value=[]),
            patch.object(
                sparql_client,
                "competences_requises",
                return_value=[
                    {"competence": "comp_Python"},
                    {"competence": "comp_SQL"},
                    {"competence": "comp_NoCourse"},
                ],
            ),
        ):
            response = self.client.get(
                "/parcours-optimal",
                params={"profil": profile_id, "metier": "met_test"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["competences_manquantes"], ["comp_NoCourse", "comp_SQL"])
        # comp_SQL est enseignée par une formation du catalogue, comp_NoCourse non.
        self.assertEqual(body["competences_sans_formation"], ["comp_NoCourse"])

    def test_profile_without_remaining_gap_returns_a_valid_empty_path(self):
        with patch.object(sparql_client, "create_entity"):
            registration = self.client.post(
                "/auth/register",
                json=self.registration_payload(),
                headers={"Origin": "http://localhost:4200"},
            )
        profile_id = registration.json()["profile_iri"]
        with (
            patch.object(
                sparql_client,
                "profil_details",
                return_value={"aAcquis": [], "aSuivi": ["form_MoocPython"]},
            ),
            patch.object(
                sparql_client,
                "competences_effectives",
                return_value=[
                    {
                        "competence": "comp_Python",
                        "source": "formation",
                        "formation": "form_MoocPython",
                        "formationLabel": "MOOC Python",
                    }
                ],
            ),
            patch.object(sparql_client, "get_entity_detail", return_value={}),
            patch.object(
                sparql_client,
                "formations_et_prerequis",
                return_value=[{"formation": "form_MoocPython", "competence": "comp_Python"}],
            ),
            patch.object(sparql_client, "formations_meta", return_value=[]),
            patch.object(
                sparql_client,
                "competences_requises",
                return_value=[{"competence": "comp_Python"}],
            ),
            patch.object(sparql_client, "formations_recommandees", return_value=[]),
        ):
            optimal = self.client.get(
                "/parcours-optimal",
                params={"profil": profile_id, "metier": "met_test"},
            )
            personalized = self.client.get(
                "/learning-path",
                params={"profil": profile_id, "metier": "met_test"},
            )

        self.assertEqual(optimal.status_code, 200)
        self.assertEqual(personalized.status_code, 200)
        optimal_body = optimal.json()
        self.assertEqual(optimal_body["competences_manquantes"], [])
        self.assertEqual(optimal_body["competences_sans_formation"], [])
        self.assertEqual(optimal_body["etapes"], [])
        self.assertEqual(
            optimal_body["candidates"][0]["training_ids"],
            [],
        )
        self.assertEqual(optimal_body["candidates"][0]["covered_competencies"], [])
        # Aucun parcours n'est fabriqué quand l'écart est déjà couvert.
        self.assertEqual(
            [step["formation"] for step in optimal_body["etapes"]],
            [],
        )
        personalized_body = personalized.json()
        self.assertEqual(personalized_body["competences_manquantes"], [])
        self.assertEqual(personalized_body["etapes"], [])
        self.assertEqual(personalized_body["competences_non_couvertes"], [])

    def test_redundant_competencies_threshold_is_validated(self):
        auth_store.create_admin(
            "admin@example.test",
            "Test Administrator",
            PASSWORD_HASHER.hash("Admin-test-password-89"),
        )
        self.client.post("/auth/login", json={
            "email": "admin@example.test",
            "password": "Admin-test-password-89",
        })

        invalid = self.client.get("/admin/redundant-competencies", params={"threshold": 2})
        self.assertEqual(invalid.status_code, 422)

    def test_untrusted_origin_cannot_perform_mutations(self):
        response = self.client.post(
            "/auth/register",
            json=self.registration_payload(),
            headers={"Origin": "https://untrusted.example"},
        )
        self.assertEqual(response.status_code, 403)


#: Individus simulés pour les tests d'accès par rôle de l'assistant sémantique.
_NLP_INDIVIDUALS = {
    "Metier": [{"id": "met_DataEngineer", "label": "Data Engineer", "class": "Metier"}],
    "Competence": [
        {"id": "comp_Python", "label": "Python", "class": "CompetenceTechnique"},
        {"id": "comp_SQL", "label": "SQL", "class": "CompetenceTechnique"},
    ],
    "Formation": [
        {"id": "form_MoocPython", "label": "Mooc Python", "class": "FormationEnLigne"},
    ],
    "Module": [
        {"id": "mod_PythonBase", "label": "Python Base", "class": "ModuleTechnique"},
    ],
    "ProfilUtilisateur": [
        {"id": "profil_other", "label": "Autre Profil", "class": "ProfilUtilisateur"},
    ],
}


def _nlp_individuals(entity_type, _search=None, _include_class=False):
    return _NLP_INDIVIDUALS.get(entity_type, [])


class SemanticAssistantRoleTests(unittest.TestCase):
    """Contrôle d'accès par rôle sur l'assistant sémantique (``/nlp``).

    Le rôle et le profil sont lus dans le jeton d'authentification vérifié ;
    tout ce qui est envoyé dans le corps de la requête (``role``, ``profil``) est
    ignoré.
    """

    OTHER_PROFILE_QUESTION = "Quels profils sont éligibles pour le métier Data Engineer ?"
    CATALOGUE_QUESTION = "Liste les compétences."
    STATISTICS_QUESTION = "Combien de formations enseignent Python ?"

    def setUp(self):
        self.client_context = TestClient(app)
        with redirect_stdout(StringIO()):
            self.client = self.client_context.__enter__()
        with auth_store.connect() as connection:
            connection.execute("DELETE FROM login_attempts")
            connection.execute("DELETE FROM password_reset_tokens")
            connection.execute("DELETE FROM auth_sessions")
            connection.execute("DELETE FROM accounts")
        for patcher in (
            patch.object(nlp, "_schema", return_value=ontology_schema.fallback_schema()),
            patch.object(sparql_client, "list_individuals", side_effect=_nlp_individuals),
            patch.object(sparql_client, "run_query", return_value=[]),
            patch.object(nlp, "_paraphrase_intent", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    @staticmethod
    def registration_payload(**overrides):
        return {
            "full_name": "Test Learner",
            "email": "learner@example.test",
            "password": "Secure-test-password-42",
            "password_confirmation": "Secure-test-password-42",
            "profile_type": "STUDENT",
            **overrides,
        }

    def register_student(self, email="learner@example.test"):
        with patch.object(sparql_client, "create_entity"):
            response = self.client.post(
                "/auth/register",
                json=self.registration_payload(email=email),
                headers={"Origin": "http://localhost:4200"},
            )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def login_admin(self):
        auth_store.create_admin(
            "admin@example.test",
            "Test Administrator",
            PASSWORD_HASHER.hash("Admin-test-password-89"),
        )
        response = self.client.post("/auth/login", json={
            "email": "admin@example.test",
            "password": "Admin-test-password-89",
        })
        self.assertEqual(response.status_code, 200)

    def ask(self, question, **extra):
        return self.client.post(
            "/nlp/query",
            json={"question": question, **extra},
            headers={"Origin": "http://localhost:4200"},
        )

    def test_student_asking_about_another_profile_is_refused(self):
        self.register_student()

        response = self.ask(self.OTHER_PROFILE_QUESTION)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["message"], nlp.RESTRICTED_ROLE_MESSAGE)
        self.assertEqual(payload["sparql"], "")
        self.assertEqual(payload["results"], [])

    def test_student_statistics_question_is_refused(self):
        self.register_student()

        payload = self.ask(self.STATISTICS_QUESTION).json()

        self.assertEqual(payload["message"], nlp.RESTRICTED_ROLE_MESSAGE)
        self.assertEqual(payload["sparql"], "")
        self.assertEqual(payload["results"], [])

    def test_student_asking_a_catalogue_question_is_allowed(self):
        self.register_student()

        response = self.ask(self.CATALOGUE_QUESTION)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotEqual(payload["message"], nlp.RESTRICTED_ROLE_MESSAGE)
        self.assertEqual(payload["intent"], "list_Competence")
        self.assertIn("onto:Competence", payload["sparql"])

    def test_admin_can_ask_profile_and_catalogue_questions(self):
        self.login_admin()

        profile_payload = self.ask(self.OTHER_PROFILE_QUESTION).json()
        catalogue_payload = self.ask(self.CATALOGUE_QUESTION).json()

        self.assertNotEqual(profile_payload["message"], nlp.RESTRICTED_ROLE_MESSAGE)
        self.assertEqual(profile_payload["intent"], "profils_eligibles_metier")
        self.assertNotEqual(profile_payload["sparql"], "")
        self.assertNotEqual(catalogue_payload["message"], nlp.RESTRICTED_ROLE_MESSAGE)
        self.assertEqual(catalogue_payload["intent"], "list_Competence")

    def test_forged_role_and_profile_in_the_request_body_are_ignored(self):
        self.register_student()

        payload = self.ask(
            self.OTHER_PROFILE_QUESTION, role="ADMIN", profil="profil_other"
        ).json()

        # Le rôle « ADMIN » forgé dans le corps n'accorde aucun droit : le rôle
        # réel de la session (STUDENT) reste seul pris en compte.
        self.assertEqual(payload["message"], nlp.RESTRICTED_ROLE_MESSAGE)
        self.assertEqual(payload["sparql"], "")
        self.assertEqual(payload["results"], [])
        self.assertNotIn("profil_other", payload["sparql"])

    def test_examples_are_filtered_by_role(self):
        self.register_student()
        student_examples = self.client.get("/nlp/examples").json()["examples"]
        self.client.cookies.clear()

        self.login_admin()
        admin_examples = self.client.get("/nlp/examples").json()["examples"]

        self.assertIn("Liste les compétences.", student_examples)
        self.assertNotIn(self.STATISTICS_QUESTION, student_examples)
        self.assertNotIn(
            "Quels modules ne sont associés à aucune formation ?", student_examples
        )
        self.assertIn(self.STATISTICS_QUESTION, admin_examples)
        self.assertIn(
            "Quels modules ne sont associés à aucune formation ?", admin_examples
        )

    def test_semantic_assistant_requires_authentication(self):
        response = self.client.post(
            "/nlp/query",
            json={"question": self.CATALOGUE_QUESTION},
            headers={"Origin": "http://localhost:4200"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/nlp/examples").status_code, 401)


class AutomaticEvaluationTests(unittest.TestCase):
    """Évaluation automatique et niveau global (étudiant / professionnel).

    Le profil est lu exclusivement dans le jeton d'authentification : aucune
    route n'accepte d'identifiant de profil dans le corps de la requête, et
    l'administrateur n'a pas accès à ces fonctionnalités.
    """

    TARGET = "met_cloud"

    def setUp(self):
        self.client_context = TestClient(app)
        with redirect_stdout(StringIO()):
            self.client = self.client_context.__enter__()
        with auth_store.connect() as connection:
            connection.execute("DELETE FROM login_attempts")
            connection.execute("DELETE FROM password_reset_tokens")
            connection.execute("DELETE FROM auth_sessions")
            connection.execute("DELETE FROM accounts")

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    @staticmethod
    def registration_payload(**overrides):
        return {
            "full_name": "Test Learner",
            "email": "learner@example.test",
            "password": "Secure-test-password-42",
            "password_confirmation": "Secure-test-password-42",
            "profile_type": "PROFESSIONAL",
            **overrides,
        }

    def register(self, **overrides):
        with patch.object(sparql_client, "create_entity"):
            response = self.client.post(
                "/auth/register",
                json=self.registration_payload(**overrides),
                headers={"Origin": "http://localhost:4200"},
            )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def login_admin(self):
        auth_store.create_admin(
            "admin@example.test",
            "Test Administrator",
            PASSWORD_HASHER.hash("Admin-test-password-89"),
        )
        response = self.client.post("/auth/login", json={
            "email": "admin@example.test",
            "password": "Admin-test-password-89",
        })
        self.assertEqual(response.status_code, 200)

    @staticmethod
    def profile_with(target=TARGET, label="Cloud Engineer"):
        relations = {} if target is None else {"vise": [{"id": target, "label": label}]}
        return {
            "id": "profil_x",
            "properties": {"aNom": ["Test Learner"]},
            "relations": relations,
        }

    def generate(self):
        return self.client.post(
            "/me/evaluations/generate",
            headers={"Origin": "http://localhost:4200"},
        )

    def test_generate_requires_a_target_occupation(self):
        self.register()

        with patch.object(
            sparql_client, "get_entity_detail", return_value=self.profile_with(target=None)
        ):
            response = self.generate()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Choose a target occupation first")

    def test_generate_computes_score_level_and_counts(self):
        account = self.register()
        profil = account["profile_iri"]

        with patch.object(sparql_client, "get_entity_detail", return_value=self.profile_with()), \
                patch.object(sparql_client, "competences_requises", return_value=[
                    {"competence": "comp_a"}, {"competence": "comp_b"},
                ]), \
                patch.object(sparql_client, "competences_effectives", return_value=[
                    {"competence": "comp_a", "source": "direct"},
                ]), \
                patch.object(sparql_client, "niveau_requis_metier", return_value={
                    "id": "niv_Avance", "label": "Avancé", "value": 3,
                }), \
                patch.object(sparql_client, "niveau_profil", return_value={
                    "id": "niv_Intermediaire", "label": "Intermédiaire", "value": 2,
                }), \
                patch.object(sparql_client, "evaluation_diagnostic", return_value={
                    "strengths": ["Python"],
                    "gaps": ["Cloud"],
                    "levelReason": "Readiness 50% is in the 50-79% range -> Intermediate",
                    "nextLevel": "Advanced",
                    "competencesToNextLevel": 1,
                    "requiredLevelGap": "Required: Advanced, yours: Intermediate",
                    "suggestions": [],
                }), \
                patch.object(sparql_client, "remplacer_evaluation") as replace, \
                patch.object(sparql_client, "definir_niveau_profil") as set_level:
            response = self.generate()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score"], 50)
        self.assertEqual(payload["masteredCount"], 1)
        self.assertEqual(payload["missingCount"], 1)
        self.assertEqual(payload["occupationName"], "Cloud Engineer")
        self.assertEqual(
            payload["level"], {"id": "niv_Intermediaire", "label": "Intermédiaire", "value": 2}
        )
        self.assertEqual(
            payload["requiredLevel"], {"id": "niv_Avance", "label": "Avancé", "value": 3}
        )
        self.assertEqual(payload["diagnostic"]["strengths"], ["Python"])
        self.assertEqual(payload["diagnostic"]["gaps"], ["Cloud"])
        self.assertEqual(payload["diagnostic"]["nextLevel"], "Advanced")
        self.assertEqual(payload["diagnostic"]["competencesToNextLevel"], 1)
        self.assertIsNotNone(payload["date"])
        # Une seule évaluation par (profil, métier) et niveau déduit du score (50 -> Intermédiaire).
        replace.assert_called_once()
        self.assertEqual(replace.call_args.args[0], profil)
        self.assertEqual(replace.call_args.args[1], f"eval_{profil}_{self.TARGET}")
        self.assertEqual(replace.call_args.args[2], "Evaluation Cloud Engineer")
        self.assertEqual(replace.call_args.args[3], 50)
        set_level.assert_called_once_with(profil, "niv_Intermediaire")

    def test_generate_without_required_competences_leaves_the_level_unchanged(self):
        self.register()

        with patch.object(sparql_client, "get_entity_detail", return_value=self.profile_with()), \
                patch.object(sparql_client, "competences_requises", return_value=[]), \
                patch.object(sparql_client, "niveau_requis_metier", return_value=None), \
                patch.object(sparql_client, "niveau_profil", return_value={
                    "id": "niv_Debutant", "label": "Débutant", "value": 1,
                }), \
                patch.object(sparql_client, "evaluation_diagnostic", return_value={
                    "strengths": [],
                    "gaps": [],
                    "levelReason": "No required competences are defined for this occupation.",
                    "nextLevel": None,
                    "competencesToNextLevel": 0,
                    "requiredLevelGap": None,
                    "suggestions": [],
                }), \
                patch.object(sparql_client, "remplacer_evaluation") as replace, \
                patch.object(sparql_client, "definir_niveau_profil") as set_level:
            response = self.generate()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score"], 0)
        self.assertEqual(
            payload["message"], "No required competences defined for this occupation"
        )
        self.assertEqual(payload["masteredCount"], 0)
        self.assertEqual(payload["missingCount"], 0)
        self.assertEqual(payload["level"]["id"], "niv_Debutant")
        replace.assert_not_called()
        set_level.assert_not_called()

    def test_level_thresholds(self):
        self.assertEqual(sparql_client.niveau_pour_score(0), "niv_Debutant")
        self.assertEqual(sparql_client.niveau_pour_score(49), "niv_Debutant")
        self.assertEqual(sparql_client.niveau_pour_score(50), "niv_Intermediaire")
        self.assertEqual(sparql_client.niveau_pour_score(79), "niv_Intermediaire")
        self.assertEqual(sparql_client.niveau_pour_score(80), "niv_Avance")
        self.assertEqual(sparql_client.niveau_pour_score(100), "niv_Avance")

    def test_admin_is_forbidden_on_evaluation_endpoints(self):
        self.login_admin()

        generated = self.generate()
        listed = self.client.get("/me/evaluations")

        self.assertEqual(generated.status_code, 403)
        self.assertEqual(listed.status_code, 403)

    def test_evaluation_endpoints_require_authentication(self):
        generated = self.generate()
        listed = self.client.get("/me/evaluations")

        self.assertEqual(generated.status_code, 401)
        self.assertEqual(listed.status_code, 401)

    def test_me_evaluations_returns_only_the_connected_profiles_evaluations(self):
        account = self.register()
        stored = [{
            "id": "eval_profil_x_met_cloud",
            "label": "Evaluation Cloud Engineer",
            "score": 50,
            "date": "2026-10-31T10:00:00",
            "occupation": "met_cloud",
        }]
        diagnostic = {
            "strengths": ["Python"],
            "gaps": ["Cloud"],
            "levelReason": "Readiness 50% is in the 50-79% range -> Intermediate",
            "nextLevel": "Advanced",
            "competencesToNextLevel": 1,
            "requiredLevelGap": None,
            "suggestions": [],
        }

        with patch.object(sparql_client, "evaluations_profil", return_value=stored) as listing, \
                patch.object(sparql_client, "evaluation_diagnostic", return_value=diagnostic) as get_diagnostic:
            response = self.client.get("/me/evaluations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{**stored[0], "diagnostic": diagnostic}])
        listing.assert_called_once()
        get_diagnostic.assert_called_once_with(account["profile_iri"], "met_cloud", 50)

    def test_profile_endpoint_exposes_level_and_required_level(self):
        self.register()

        with patch.object(sparql_client, "get_entity_detail", return_value=self.profile_with()), \
                patch.object(sparql_client, "niveau_profil", return_value={
                    "id": "niv_Avance", "label": "Avancé", "value": 3,
                }), \
                patch.object(sparql_client, "niveau_requis_metier", return_value={
                    "id": "niv_Intermediaire", "label": "Intermédiaire", "value": 2,
                }):
            payload = self.client.get("/account/profile").json()

        self.assertEqual(payload["level"], {"id": "niv_Avance", "label": "Avancé", "value": 3})
        self.assertEqual(
            payload["requiredLevel"],
            {"id": "niv_Intermediaire", "label": "Intermédiaire", "value": 2},
        )

    def test_repeated_generation_reuses_the_same_evaluation_individual(self):
        account = self.register()
        profil = account["profile_iri"]

        with patch.object(sparql_client, "get_entity_detail", return_value=self.profile_with()), \
                patch.object(sparql_client, "competences_requises", return_value=[
                    {"competence": "comp_a"},
                ]), \
                patch.object(sparql_client, "competences_effectives", return_value=[
                    {"competence": "comp_a", "source": "direct"},
                ]), \
                patch.object(sparql_client, "niveau_requis_metier", return_value=None), \
                patch.object(sparql_client, "niveau_profil", return_value=None), \
                patch.object(sparql_client, "evaluation_diagnostic", return_value={
                    "strengths": ["Python"],
                    "gaps": [],
                    "levelReason": "Readiness 100% is in the 80-100% range -> Advanced",
                    "nextLevel": None,
                    "competencesToNextLevel": 0,
                    "requiredLevelGap": None,
                    "suggestions": [],
                }), \
                patch.object(sparql_client, "remplacer_evaluation") as replace, \
                patch.object(sparql_client, "definir_niveau_profil") as set_level:
            first = self.generate().json()
            second = self.generate().json()

        self.assertEqual(replace.call_count, 2)
        self.assertEqual(
            replace.call_args_list[0].args[1], replace.call_args_list[1].args[1]
        )
        self.assertEqual(replace.call_args_list[0].args[1], f"eval_{profil}_{self.TARGET}")
        # Score 100 -> niveau Avancé : une seule valeur aPourNiveau écrite à chaque passage.
        set_level.assert_called_with(profil, "niv_Avance")
        self.assertEqual(first["score"], 100)
        self.assertEqual(second["score"], 100)

    def test_replacement_writes_typed_literals_and_a_single_link(self):
        with patch.object(sparql_client, "run_update") as update:
            sparql_client.remplacer_evaluation(
                "profil_x",
                "eval_profil_x_met_cloud",
                "Evaluation Cloud Engineer",
                50,
                "2026-10-31T10:00:00",
            )

        statements = [call.args[0] for call in update.call_args_list]
        self.assertEqual(len(statements), 3)
        evaluation_uri = "<http://www.skillpath.tn/onto#eval_profil_x_met_cloud>"
        profile_uri = "<http://www.skillpath.tn/onto#profil_x>"
        # 1) seuls les triplets de cette évaluation sont supprimés ; 2) seul le lien du profil l'est.
        self.assertIn(f"DELETE {{ {evaluation_uri} ?propriete ?valeur . }}", statements[0])
        self.assertIn(f"DELETE WHERE {{ {profile_uri} onto:aPasseEvaluation {evaluation_uri} . }}", statements[1])
        insert = statements[2]
        self.assertIn("rdf:type onto:EvaluationTechnique", insert)
        self.assertIn('"50"^^xsd:integer', insert)
        self.assertIn('"2026-10-31T10:00:00"^^xsd:dateTime', insert)
        self.assertIn(f"{profile_uri} onto:aPasseEvaluation {evaluation_uri} .", insert)

    def test_defining_a_level_replaces_the_previous_single_value(self):
        with patch.object(sparql_client, "run_update") as update:
            sparql_client.definir_niveau_profil("profil_x", "niv_Avance")

        statement = update.call_args.args[0]
        profile_uri = "<http://www.skillpath.tn/onto#profil_x>"
        self.assertIn(f"DELETE {{ {profile_uri} onto:aPourNiveau ?ancien . }}", statement)
        self.assertIn(
            f"INSERT {{ {profile_uri} onto:aPourNiveau <http://www.skillpath.tn/onto#niv_Avance> . }}",
            statement,
        )

    def test_evaluations_are_read_with_their_occupation_and_integer_score(self):
        rows = [{
            "evaluation": "eval_profil_x_met_cloud",
            "label": "Evaluation Cloud Engineer",
            "score": "50",
            "date": "2026-10-31T10:00:00",
        }]

        with patch.object(sparql_client, "run_query", return_value=rows):
            evaluations = sparql_client.evaluations_profil("profil_x")

        self.assertEqual(evaluations, [{
            "id": "eval_profil_x_met_cloud",
            "label": "Evaluation Cloud Engineer",
            "score": 50,
            "date": "2026-10-31T10:00:00",
            "occupation": "met_cloud",
        }])


if __name__ == "__main__":
    unittest.main()

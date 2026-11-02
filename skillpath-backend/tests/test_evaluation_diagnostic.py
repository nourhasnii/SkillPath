import unittest
from unittest.mock import patch

from app import sparql_client as sp


class EvaluationDiagnosticTests(unittest.TestCase):
    def test_partial_readiness_has_named_strengths_gaps_and_training_modules(self):
        skill_rows = [
            {"competence": "comp_python", "name": "Python", "mastered": "true"},
            {"competence": "comp_cloud", "name": "Cloud", "mastered": "false"},
        ]
        teaching_rows = [
            {
                "competence": "comp_cloud",
                "training": "form_cloud",
                "trainingName": "Cloud Foundations",
                "trainingDuration": "12",
                "module": "mod_storage",
                "moduleName": "Storage Module",
                "moduleDuration": "3",
            },
            {
                "competence": "comp_cloud",
                "training": "form_cloud",
                "trainingName": "Cloud Foundations",
                "trainingDuration": "12",
                "module": "mod_network",
                "moduleName": "Networking Module",
            },
        ]
        required_level = {"id": "niv_Avance", "label": "Advanced", "value": 3}
        with patch.object(sp, "run_query", side_effect=[skill_rows, teaching_rows]) as query, \
                patch.object(sp, "niveau_requis_metier", return_value=required_level):
            diagnostic = sp.evaluation_diagnostic("profil_student", "met_cloud", 50)

        self.assertEqual(diagnostic["strengths"], ["Python"])
        self.assertEqual(diagnostic["gaps"], ["Cloud"])
        self.assertEqual(
            diagnostic["levelReason"],
            "Readiness 50% is in the 50-79% range -> Intermediate",
        )
        self.assertEqual(diagnostic["nextLevel"], "Advanced")
        self.assertEqual(diagnostic["competencesToNextLevel"], 1)
        self.assertEqual(
            diagnostic["requiredLevelGap"],
            "Required: Advanced, yours: Intermediate",
        )
        self.assertEqual(diagnostic["suggestions"], [{
            "competence": "Cloud",
            "trainings": [{
                "id": "form_cloud",
                "name": "Cloud Foundations",
                "durationHours": 12,
                "modules": [
                    {"id": "mod_storage", "name": "Storage Module", "durationHours": 3},
                    {"id": "mod_network", "name": "Networking Module", "durationHours": None},
                ],
            }],
        }])
        self.assertEqual(query.call_count, 2)

    def test_zero_readiness_keeps_all_gaps_and_calculates_intermediate_threshold(self):
        skills = [
            {"competence": f"comp_{name.lower()}", "name": name, "mastered": "false"}
            for name in ("Python", "Cloud", "Linux")
        ]
        with patch.object(sp, "run_query", side_effect=[skills, []]), \
                patch.object(sp, "niveau_requis_metier", return_value=None):
            diagnostic = sp.evaluation_diagnostic("profil_student", "met_cloud", 0)

        self.assertEqual(diagnostic["strengths"], [])
        self.assertEqual(diagnostic["gaps"], ["Python", "Cloud", "Linux"])
        self.assertEqual(diagnostic["nextLevel"], "Intermediate")
        self.assertEqual(diagnostic["competencesToNextLevel"], 2)
        self.assertEqual(len(diagnostic["suggestions"]), 3)
        self.assertTrue(all(not item["trainings"] for item in diagnostic["suggestions"]))

    def test_full_readiness_has_no_gaps_or_next_level(self):
        skills = [
            {"competence": "comp_python", "name": "Python", "mastered": "true"},
            {"competence": "comp_cloud", "name": "Cloud", "mastered": "true"},
        ]
        with patch.object(sp, "run_query", return_value=skills) as query, \
                patch.object(sp, "niveau_requis_metier", return_value=None):
            diagnostic = sp.evaluation_diagnostic("profil_student", "met_cloud", 100)

        self.assertEqual(diagnostic["strengths"], ["Python", "Cloud"])
        self.assertEqual(diagnostic["gaps"], [])
        self.assertEqual(diagnostic["levelReason"], "Readiness 100% is in the 80-100% range -> Advanced")
        self.assertIsNone(diagnostic["nextLevel"])
        self.assertEqual(diagnostic["competencesToNextLevel"], 0)
        self.assertEqual(diagnostic["suggestions"], [])
        query.assert_called_once()

    def test_diagnostic_queries_are_sparql_and_only_select_missing_training_teaching(self):
        status_query = sp.diagnostic_competences_query("profil_student", "met_cloud")
        suggestions_query = sp.diagnostic_suggestions_query(["comp_cloud"])

        self.assertIn("onto:met_cloud onto:requiert ?competence", status_query)
        self.assertIn("onto:profil_student onto:aAcquis ?competence", status_query)
        self.assertIn("onto:moduleEnseigne ?competence", status_query)
        self.assertIn("?training onto:enseigne ?competence", suggestions_query)
        self.assertIn("?training onto:contientModule ?module", suggestions_query)
        self.assertIn("VALUES ?competence { onto:comp_cloud }", suggestions_query)
        self.assertNotIn("UPDATE", status_query.upper())
        self.assertNotIn("UPDATE", suggestions_query.upper())


if __name__ == "__main__":
    unittest.main()

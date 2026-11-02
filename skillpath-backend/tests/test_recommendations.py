import unittest
from unittest.mock import patch

from app import sparql_client as sp


class RecommendationsTests(unittest.TestCase):
    def test_scoring_query_uses_profile_relations_and_excludes_acquired_skills(self):
        query = sp.recommendations_query("profil_student")

        self.assertIn("onto:profil_student onto:aAcquis ?acquired", query)
        self.assertIn("onto:requiert ?acquired, ?candidate", query)
        self.assertIn("onto:enseigne ?acquired, ?candidate", query)
        self.assertIn("onto:moduleEnseigne ?acquired, ?candidate", query)
        self.assertIn("onto:appartientA ?family", query)
        self.assertIn("FILTER NOT EXISTS { onto:profil_student onto:aAcquis ?candidate", query)
        self.assertIn("SUM(?points)", query)
        self.assertIn("LIMIT 5", query)

    def test_invalid_profile_identifier_is_rejected(self):
        with self.assertRaises(sp.InvalidPayloadError):
            sp.recommendations_query("profile> ?other")

    def test_returns_named_recommendations_and_their_teachings(self):
        candidate_rows = [
            {
                "candidate": "comp_Docker",
                "name": "Docker",
                "score": "4",
                "explanations": "Related to Linux: both required by DevOps.|||Related to Linux: both taught by DevOps Bootcamp.",
            },
            {
                "candidate": "comp_Cloud",
                "name": "Cloud",
                "score": "1",
                "explanations": "Related to Linux: occupations share the Infrastructure family.",
            },
        ]
        teaching_rows = [
            {
                "competence": "comp_Docker",
                "name": "Docker fundamentals",
                "type": "Training",
                "duration": "8",
            },
            {
                "competence": "comp_Docker",
                "name": "Containers module",
                "type": "Module",
            },
        ]
        with patch.object(sp, "run_query", side_effect=[candidate_rows, teaching_rows]) as query:
            recommendations = sp.recommendations_for_profile("profil_student")

        self.assertEqual(len(recommendations), 2)
        self.assertEqual(recommendations[0], {
            "competence": "Docker",
            "score": 4,
            "explanations": [
                "Related to Linux: both required by DevOps.",
                "Related to Linux: both taught by DevOps Bootcamp.",
            ],
            "teachings": [
                {
                    "name": "Docker fundamentals",
                    "type": "Training",
                    "duration_hours": 8,
                },
                {
                    "name": "Containers module",
                    "type": "Module",
                    "duration_hours": None,
                },
            ],
        })
        self.assertEqual(query.call_count, 2)
        self.assertIn("VALUES ?competence { onto:comp_Docker onto:comp_Cloud }", query.call_args_list[1].args[0])

    def test_no_candidates_skips_teaching_query(self):
        with patch.object(sp, "run_query", return_value=[]) as query:
            self.assertEqual(sp.recommendations_for_profile("profil_student"), [])
        query.assert_called_once()


class CareerBridgesTests(unittest.TestCase):
    def test_query_uses_profile_acquisitions_and_excludes_target(self):
        query = sp.career_bridges_query("profil_student")

        self.assertIn("FILTER NOT EXISTS { onto:profil_student onto:vise ?occupation }", query)
        self.assertIn("EXISTS { onto:profil_student onto:aAcquis ?competence }", query)
        self.assertIn("?occupation onto:requiert ?competence", query)
        self.assertIn("onto:appartientA ?family", query)

    def test_ranks_competence_overlap_and_attaches_training_modules(self):
        occupations = [
            {
                "occupation": "met_devops",
                "occupationName": "DevOps Engineer",
                "family": "fam_technology",
                "familyName": "Technology",
                "competence": "comp_python",
                "competenceName": "Python",
                "covered": "true",
            },
            {
                "occupation": "met_devops",
                "occupationName": "DevOps Engineer",
                "family": "fam_technology",
                "familyName": "Technology",
                "competence": "comp_docker",
                "competenceName": "Docker",
                "covered": "false",
            },
            {
                "occupation": "met_analyst",
                "occupationName": "Data Analyst",
                "competence": "comp_python",
                "competenceName": "Python",
                "covered": "true",
            },
        ]
        teachings = [{
            "competence": "comp_docker",
            "training": "form_docker",
            "trainingName": "Docker Fundamentals",
            "trainingDuration": "8",
            "module": "mod_containers",
            "moduleName": "Containers",
            "moduleDuration": "2",
        }]
        with patch.object(sp, "run_query", side_effect=[occupations, teachings]) as query:
            results = sp.career_bridges_for_profile("profil_student")

        self.assertEqual(
            [(item["occupation"], item["percent"]) for item in results],
            [("Data Analyst", 100), ("DevOps Engineer", 50)],
        )
        self.assertEqual(results[0]["family"], None)
        self.assertEqual(results[1]["family"], "Technology")
        self.assertEqual(results[1]["coveredNames"], ["Python"])
        self.assertEqual(results[1]["missingNames"], ["Docker"])
        self.assertEqual(results[1]["trainings"], [{
            "competence": "Docker",
            "trainings": [{
                "id": "form_docker",
                "name": "Docker Fundamentals",
                "durationHours": 8,
                "modules": [{
                    "id": "mod_containers",
                    "name": "Containers",
                    "durationHours": 2,
                }],
            }],
        }])
        self.assertEqual(query.call_count, 2)

    def test_no_missing_skills_skips_training_query(self):
        occupations = [{
            "occupation": "met_devops",
            "occupationName": "DevOps",
            "competence": "comp_python",
            "competenceName": "Python",
            "covered": "true",
        }]
        with patch.object(sp, "run_query", return_value=occupations) as query:
            results = sp.career_bridges_for_profile("profil_student")

        self.assertEqual(results[0]["percent"], 100)
        self.assertEqual(results[0]["missingNames"], [])
        self.assertEqual(results[0]["trainings"], [])
        query.assert_called_once()


if __name__ == "__main__":
    unittest.main()

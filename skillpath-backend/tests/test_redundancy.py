import unittest
from unittest.mock import patch

from app import redundancy, sparql_client


class NormalizeNameTests(unittest.TestCase):
    def test_strips_type_prefix_and_splits_camel_case(self):
        self.assertEqual(redundancy.normalize_name("comp_DataPipeline"), "data pipeline")
        self.assertEqual(redundancy.normalize_name("comp_MachineLearning"), "machine learning")

    def test_removes_accents_stopwords_and_plural(self):
        self.assertEqual(redundancy.normalize_name("Gestion des projets"), "gestion projet")
        self.assertEqual(redundancy.normalize_name("Competence en Python"), "python")

    def test_empty_name_normalizes_to_empty(self):
        self.assertEqual(redundancy.normalize_name(""), "")
        self.assertEqual(redundancy.normalize_name(None), "")


class SimilarityTests(unittest.TestCase):
    def test_duplicate_names_score_one(self):
        self.assertEqual(redundancy.similarity("Python", "python"), 1.0)
        self.assertEqual(redundancy.similarity("Gestion de projet", "Gestion des projets"), 1.0)

    def test_identifier_and_label_of_the_same_skill_are_duplicates(self):
        self.assertEqual(redundancy.similarity("comp_Python", "Python"), 1.0)

    def test_similar_skills_reach_the_threshold(self):
        self.assertEqual(redundancy.similarity("Machine Learning", "MachineLearning"), 1.0)
        self.assertGreaterEqual(
            redundancy.similarity("Version Control System", "Version Control Systems"),
            redundancy.DEFAULT_THRESHOLD,
        )

    def test_unrelated_skills_stay_below_the_threshold(self):
        self.assertLess(redundancy.similarity("Docker", "Kubernetes"), redundancy.DEFAULT_THRESHOLD)
        self.assertLess(redundancy.similarity("SQL", "Spark"), redundancy.DEFAULT_THRESHOLD)
        self.assertLess(redundancy.similarity("Java", "Git"), redundancy.DEFAULT_THRESHOLD)


class DetectRedundantCompetenciesTests(unittest.TestCase):
    def _items(self):
        return [
            {"id": "comp_Python", "label": "comp_Python", "class": "CompetenceTechnique"},
            {"id": "comp_PythonProg", "label": "Python", "class": "CompetenceTechnique"},
            {"id": "comp_Docker", "label": "comp_Docker", "class": "CompetenceTechnique"},
            {"id": "comp_GestionProjet", "label": "Gestion de projet", "class": "CompetenceTransverse"},
            {"id": "comp_GestionProjets", "label": "Gestion des projets", "class": "CompetenceTransverse"},
        ]

    def test_detects_duplicate_pairs_across_both_competency_classes(self):
        with patch.object(sparql_client, "list_individuals", return_value=self._items()) as list_items:
            report = redundancy.detect_redundant_competencies()

        self.assertEqual(report["total_competencies"], 5)
        self.assertEqual(report["pair_count"], 2)
        pair_keys = {(pair["id_a"], pair["id_b"]) for pair in report["pairs"]}
        self.assertIn(("comp_GestionProjet", "comp_GestionProjets"), pair_keys)
        self.assertIn(("comp_Python", "comp_PythonProg"), pair_keys)
        classes = {pair["class_a"] for pair in report["pairs"]} | {
            pair["class_b"] for pair in report["pairs"]
        }
        self.assertEqual(classes, {"CompetenceTechnique", "CompetenceTransverse"})
        self.assertTrue(all(pair["score"] >= report["threshold"] for pair in report["pairs"]))
        self.assertTrue(all(pair["explanation"] for pair in report["pairs"]))
        list_items.assert_called_once_with("Competence", None, True)

    def test_unrelated_skills_are_not_reported(self):
        with patch.object(sparql_client, "list_individuals", return_value=self._items()):
            report = redundancy.detect_redundant_competencies()

        ids = {identifier for pair in report["pairs"] for identifier in (pair["id_a"], pair["id_b"])}
        self.assertNotIn("comp_Docker", ids)

    def test_threshold_filters_candidate_pairs(self):
        with patch.object(sparql_client, "list_individuals", return_value=self._items()):
            strict = redundancy.detect_redundant_competencies(0.99)
            permissive = redundancy.detect_redundant_competencies(0.0)

        self.assertLess(strict["pair_count"], permissive["pair_count"])
        self.assertEqual(strict["pair_count"], 2)
        self.assertEqual(permissive["pair_count"], 10)

    def test_result_sorted_by_descending_score(self):
        items = [
            {"id": "comp_A", "label": "Data Engineering", "class": "CompetenceTechnique"},
            {"id": "comp_B", "label": "Data Engineer", "class": "CompetenceTechnique"},
            {"id": "comp_C", "label": "Data", "class": "CompetenceTechnique"},
        ]
        with patch.object(sparql_client, "list_individuals", return_value=items):
            report = redundancy.detect_redundant_competencies(0.0)

        scores = [pair["score"] for pair in report["pairs"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()

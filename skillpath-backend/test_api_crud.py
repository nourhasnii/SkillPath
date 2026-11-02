import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import Graph, URIRef
from rdflib.plugins.sparql.parser import parseUpdate

from app import sparql_client as sp


class CrudOntologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ontology_path = Path(__file__).parent.parent / "ontology" / "SkillPath.owl"
        cls.graph = Graph().parse(str(ontology_path))

    @classmethod
    def query_ontology(cls, query: str) -> list[dict[str, str]]:
        rows = []
        for result in cls.graph.query(query):
            row = {}
            for name, value in result.asdict().items():
                text = str(value)
                if isinstance(value, URIRef) and "#" in text:
                    text = text.rsplit("#", 1)[-1]
                row[str(name)] = text
            rows.append(row)
        return rows

    def test_list_search_and_optional_class_preserve_api_shape(self):
        with patch.object(sp, "run_query", side_effect=self.query_ontology):
            result = sp.list_individuals("Competence", "python")
            classified = sp.list_individuals("Competence", include_class=True)

        self.assertEqual(result, [{"id": "comp_Python", "label": "comp_Python"}])
        self.assertEqual(set(result[0]), {"id", "label"})
        python = next(item for item in classified if item["id"] == "comp_Python")
        self.assertEqual(python["class"], "CompetenceTechnique")

    def test_profile_detail_includes_paths_and_evaluations(self):
        with patch.object(sp, "run_query", side_effect=self.query_ontology):
            detail = sp.get_entity_detail("ProfilUtilisateur", "profil_Ahmed")
            evaluated_profile = sp.get_entity_detail("ProfilUtilisateur", "profil_Sami")

        self.assertIsNotNone(detail)
        self.assertEqual(
            [item["id"] for item in detail["relations"]["parcours"]],
            ["parc_StandardData"],
        )
        self.assertEqual(
            {item["id"] for item in detail["relations"]["parcours"][0]["formations"]},
            {"form_MasterCloud", "form_MoocPython"},
        )
        self.assertEqual(detail["relations"]["evaluations"], [])
        self.assertEqual(
            [item["id"] for item in evaluated_profile["relations"]["evaluations"]],
            ["eval_TechniqueDevOps"],
        )

    def test_competence_incoming_relations_are_returned(self):
        with patch.object(sp, "run_query", side_effect=self.query_ontology):
            detail = sp.get_entity_detail("Competence", "comp_Cloud")

        self.assertIsNotNone(detail)
        self.assertTrue(detail["relations"]["occupations_that_require"])
        self.assertTrue(detail["relations"]["trainings_that_teach"])

    def test_public_training_catalogue_uses_real_taught_skills_and_prerequisites(self):
        with patch.object(sp, "run_query", side_effect=self.query_ontology):
            catalogue = sp.catalogue_formations()

        by_id = {training["id"]: training for training in catalogue}
        self.assertIn("form_MoocPython", by_id)
        python_training = by_id["form_MoocPython"]
        self.assertIn(
            "comp_Python",
            {competence["id"] for competence in python_training["competences_enseignees"]},
        )
        self.assertIsInstance(python_training["prerequis"], list)
        self.assertIn("nom", python_training)
        self.assertIn("type", python_training)
        self.assertIn("duree_heures", python_training)

    def test_type_only_individual_is_not_reported_missing(self):
        with patch.object(sp, "run_query", side_effect=self.query_ontology):
            detail = sp.get_entity_detail("Competence", "comp_Cloud")

        self.assertIsNotNone(detail)
        self.assertEqual(detail["class"], "CompetenceTechnique")

    def test_create_generates_valid_insert_and_checks_real_relation_target(self):
        updates: list[str] = []
        with (
            patch.object(sp, "run_query", side_effect=self.query_ontology),
            patch.object(sp, "run_update", side_effect=updates.append),
        ):
            sp.create_entity(
                "Parcours",
                "parc_Test",
                {"aNom": 'A "quoted" path'},
                {"contientFormation": ["form_MoocPython"]},
                "ParcoursStandard",
            )

        self.assertEqual(len(updates), 1)
        parseUpdate(updates[0])
        self.assertIn('A \\"quoted\\" path', updates[0])
        self.assertIn("rdf:type onto:ParcoursStandard", updates[0])

    def test_create_preserves_prefixed_identifier_in_exact_ontology_iri(self):
        updates: list[str] = []
        with (
            patch.object(sp, "run_query", return_value=[]),
            patch.object(sp, "run_update", side_effect=updates.append),
        ):
            sp.create_entity(
                "Formation",
                "form_TestCloud",
                {"aNom": "Test Cloud"},
                {},
                "Formation",
            )

        self.assertEqual(len(updates), 1)
        parseUpdate(updates[0])
        self.assertIn(
            "<http://www.skillpath.tn/onto#form_TestCloud> rdf:type",
            updates[0],
        )
        self.assertNotIn(
            "<http://www.skillpath.tn/onto#_form_TestCloud>",
            updates[0],
        )

    def test_followed_training_is_appended_without_removing_existing_links(self):
        updates: list[str] = []
        with (
            patch.object(sp, "run_query", side_effect=self.query_ontology),
            patch.object(sp, "run_update", side_effect=updates.append),
        ):
            sp.add_followed_trainings("profil_Ahmed", ["form_MoocPython"])

        self.assertEqual(len(updates), 1)
        parseUpdate(updates[0])
        self.assertIn("INSERT DATA", updates[0])
        self.assertIn(
            "<http://www.skillpath.tn/onto#form_MoocPython>",
            updates[0],
        )
        self.assertNotIn("DELETE", updates[0])

    def test_saved_path_order_is_persisted_and_restored(self):
        updates: list[str] = []
        with (
            patch.object(sp, "run_query", side_effect=self.query_ontology),
            patch.object(sp, "run_update", side_effect=updates.append),
        ):
            sp.create_entity(
                "Parcours",
                "parc_Ordered",
                {
                    "aNom": "Ordered path",
                    "aOrdreFormations": '["form_MoocPython","form_MasterCloud"]',
                },
                {"contientFormation": ["form_MasterCloud", "form_MoocPython"]},
                "ParcoursIndividualise",
            )

        self.assertIn("onto:aOrdreFormations", updates[0])
        self.assertIn(
            r'[\"form_MoocPython\",\"form_MasterCloud\"]',
            updates[0],
        )

        def ordered_path_query(query: str) -> list[dict[str, str]]:
            if "SELECT ?order" in query:
                return [{"order": '["form_MoocPython","form_MasterCloud"]'}]
            if "onto:contientFormation ?id" in query:
                return [
                    {"id": "form_MasterCloud", "label": "Master cloud"},
                    {"id": "form_MoocPython", "label": "MOOC Python"},
                ]
            return []

        with patch.object(sp, "run_query", side_effect=ordered_path_query):
            trainings = sp._ordered_path_formations("parc_Ordered")

        self.assertEqual(
            [training["id"] for training in trainings],
            ["form_MoocPython", "form_MasterCloud"],
        )

    def test_inferred_classes_are_not_crud_entity_types(self):
        self.assertNotIn("CompetenceManquante", sp.ENTITY_CLASSES)
        self.assertNotIn("ProfilEligible", sp.ENTITY_CLASSES)
        self.assertNotIn("ParcoursOptimal", sp.ENTITY_CLASSES)


if __name__ == "__main__":
    unittest.main()

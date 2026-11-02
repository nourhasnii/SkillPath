import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import RDF, RDFS, Graph, URIRef

from app import admin_analyses
from app import sparql_client as sp

ONTOLOGY = URIRef("http://www.skillpath.tn/onto#")


class AdminAnalysisSparqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ontology_path = Path(__file__).resolve().parents[2] / "ontology" / "SkillPath.owl"
        with ontology_path.open("rb") as ontology_file:
            cls.graph = Graph().parse(ontology_file, format="xml")

    @classmethod
    def evaluate_query(cls, query: str) -> list[dict[str, str]]:
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

    @classmethod
    def local_id(cls, uri: URIRef) -> str:
        return str(uri).rsplit("#", 1)[-1]

    @classmethod
    def has_type_under(cls, individual: URIRef, parent_name: str) -> bool:
        parent = ONTOLOGY + parent_name
        for asserted_type in cls.graph.objects(individual, RDF.type):
            if asserted_type == parent or parent in cls.graph.transitive_objects(
                asserted_type, RDFS.subClassOf
            ):
                return True
        return False

    def test_shared_competency_query_matches_real_occupation_relationships(self):
        required_by: dict[URIRef, set[URIRef]] = {}
        for occupation, _, competency in self.graph.triples(
            (None, ONTOLOGY + "requiert", None)
        ):
            if self.has_type_under(occupation, "Metier") and self.has_type_under(
                competency, "Competence"
            ):
                required_by.setdefault(competency, set()).add(occupation)
        expected = {
            self.local_id(competency): {
                self.local_id(occupation) for occupation in occupations
            }
            for competency, occupations in required_by.items()
            if len(occupations) >= 2
        }

        with patch.object(sp, "run_query", side_effect=self.evaluate_query):
            report = admin_analyses.shared_competencies()

        actual = {
            item["id"]: {occupation["id"] for occupation in item["occupations"]}
            for item in report["competencies"]
        }
        self.assertEqual(actual, expected)
        self.assertEqual(report["total_competencies"], len(expected))
        self.assertTrue(all(
            item["occupation_count"] == len(item["occupations"])
            for item in report["competencies"]
        ))

    def test_untaught_competency_query_matches_real_training_and_module_coverage(self):
        categories = ("CompetenceTechnique", "CompetenceTransverse")
        competency_categories = {}
        for individual in set(self.graph.subjects(RDF.type, None)):
            for category in categories:
                if self.has_type_under(individual, category):
                    competency_categories[self.local_id(individual)] = category

        taught = {
            competency
            for formation in self.graph.subjects(RDF.type, ONTOLOGY + "Formation")
            for competency in self.graph.objects(formation, ONTOLOGY + "enseigne")
        }
        for formation in self.graph.subjects(RDF.type, ONTOLOGY + "Formation"):
            for module in self.graph.objects(formation, ONTOLOGY + "contientModule"):
                taught.update(self.graph.objects(module, ONTOLOGY + "moduleEnseigne"))
        expected = {
            competency_id: category
            for competency_id, category in competency_categories.items()
            if URIRef(str(ONTOLOGY) + competency_id) not in taught
        }

        with patch.object(sp, "run_query", side_effect=self.evaluate_query):
            report = admin_analyses.untaught_competencies()

        actual = {item["id"]: item["class"] for item in report["competencies"]}
        self.assertEqual(actual, expected)
        self.assertEqual(report["total_competencies"], len(expected))


if __name__ == "__main__":
    unittest.main()

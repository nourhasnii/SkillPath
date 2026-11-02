import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import Graph, RDF, URIRef

from app import learning_path_generator
from app import sparql_client as sp

ONTOLOGY = URIRef("http://www.skillpath.tn/onto#")


class LearningPathGeneratorTests(unittest.TestCase):
    def test_generates_alternative_combinations_and_ranks_by_duration(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"python", "sql"},
            set(),
            {
                "combined": {"python", "sql"},
                "python-course": {"python"},
                "sql-course": {"sql"},
            },
            {},
            {"combined": 10, "python-course": 3, "sql-course": 4},
            {"combined", "python-course", "sql-course"},
            set(),
        )

        self.assertEqual(len(report["candidates"]), 2)
        self.assertEqual(
            report["candidates"][0]["training_ids"],
            ("python-course", "sql-course"),
        )
        self.assertEqual(
            report["candidates"][0]["covered_competencies"],
            ("python", "sql"),
        )
        self.assertIn("2/2 missing competencies", report["candidates"][0]["ranking_explanation"])

    def test_includes_transitive_prerequisites_in_valid_order_and_coverage(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"python", "docker", "sql"},
            set(),
            {
                "foundation": {"python"},
                "middle": {"docker"},
                "advanced": {"sql"},
            },
            {
                "middle": {"foundation"},
                "advanced": {"middle"},
            },
            {"foundation": 2, "middle": 3, "advanced": 5},
            {"foundation", "middle", "advanced"},
            set(),
        )

        candidate = report["candidates"][0]
        self.assertEqual(candidate["training_ids"], ("foundation", "middle", "advanced"))
        self.assertEqual(candidate["covered_competencies"], ("docker", "python", "sql"))
        self.assertTrue(candidate["prerequisites_valid"])

    def test_orders_independent_training_before_a_newly_ready_advanced_training(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"advanced-skill", "independent-skill"},
            set(),
            {
                "deep-base": set(),
                "deep-middle": set(),
                "deep-advanced": {"advanced-skill"},
                "z-independent": {"independent-skill"},
            },
            {
                "deep-middle": {"deep-base"},
                "deep-advanced": {"deep-middle"},
            },
            {},
            {"deep-base", "deep-middle", "deep-advanced", "z-independent"},
            set(),
        )

        self.assertEqual(
            report["candidates"][0]["training_ids"],
            ("deep-base", "z-independent", "deep-middle", "deep-advanced"),
        )

    def test_followed_prerequisite_is_satisfied_without_marking_skills_acquired(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"python", "sql"},
            {"python"},
            {"advanced": {"sql"}, "foundation": {"python"}},
            {"advanced": {"foundation"}},
            {"advanced": 4, "foundation": 2},
            {"advanced", "foundation"},
            {"foundation"},
        )

        candidate = report["candidates"][0]
        self.assertEqual(candidate["training_ids"], ("advanced",))
        self.assertEqual(report["acquired_competencies"], ["python"])
        self.assertEqual(candidate["covered_competencies"], ("sql",))

    def test_maximum_duration_excludes_unknown_and_over_budget_paths(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"long-skill", "short-skill"},
            set(),
            {
                "long": {"long-skill"},
                "short": {"short-skill"},
                "unknown": {"long-skill"},
            },
            {},
            {"long": 8, "short": 3, "unknown": None},
            {"long", "short", "unknown"},
            set(),
            max_duration_hours=4,
        )

        self.assertEqual(report["candidates"][0]["training_ids"], ("short",))
        self.assertEqual(report["candidates"][0]["uncovered_competencies"], ("long-skill",))

    def test_unknown_durations_remain_available_without_a_duration_constraint(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"python"},
            set(),
            {"python-course": {"python"}},
            {},
            {"python-course": None},
            {"python-course"},
            set(),
        )

        self.assertEqual(report["candidates"][0]["training_ids"], ("python-course",))
        self.assertIsNone(report["candidates"][0]["duration_hours"])
        self.assertFalse(report["candidates"][0]["duration_available"])

    def test_equal_coverage_and_duration_prunes_paths_with_more_trainings(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"python", "sql"},
            set(),
            {
                "combined": {"python", "sql"},
                "python-course": {"python"},
                "sql-course": {"sql"},
            },
            {},
            {"combined": 7, "python-course": 3, "sql-course": 4},
            {"combined", "python-course", "sql-course"},
            set(),
        )

        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["candidates"][0]["training_ids"], ("combined",))
        self.assertEqual(report["candidates"][0]["duration_hours"], 7)
        self.assertEqual(report["candidates"][0]["coverage_ratio"], 1.0)

    def test_candidate_ranking_prefers_more_coverage_before_duration(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"skill-a", "skill-b", "skill-c"},
            set(),
            {
                "two-skills": {"skill-a", "skill-b"},
                "one-skill": {"skill-c"},
            },
            {},
            {"two-skills": 4, "one-skill": 1},
            {"two-skills", "one-skill"},
            set(),
            max_duration_hours=4,
        )

        self.assertEqual(
            report["candidates"][0]["covered_competencies"],
            ("skill-a", "skill-b"),
        )
        self.assertEqual(report["candidates"][0]["coverage_ratio"], round(2 / 3, 4))

    def test_reports_missing_catalogue_coverage_and_cycle_blocked_trainings(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"unavailable", "cycle-skill"},
            set(),
            {"cyclic": {"cycle-skill"}, "other": set()},
            {"cyclic": {"other"}, "other": {"cyclic"}},
            {"cyclic": 1, "other": 1},
            {"cyclic", "other"},
            set(),
        )

        self.assertEqual(report["catalogue_unavailable_competencies"], ["unavailable"])
        self.assertEqual(report["prerequisite_blocked_competencies"], ["cycle-skill"])
        self.assertEqual(report["candidates"][0]["training_ids"], ())
        self.assertEqual(
            report["candidates"][0]["uncovered_competencies"],
            ("cycle-skill", "unavailable"),
        )

    def test_required_skills_already_acquired_produce_an_empty_valid_path(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"python"},
            {"python"},
            {},
            {},
            {},
            set(),
            set(),
        )

        self.assertEqual(report["missing_competencies"], [])
        self.assertEqual(report["candidates"][0]["training_ids"], ())
        self.assertEqual(report["candidates"][0]["coverage_ratio"], 1.0)

    def test_followed_training_is_not_recommended_or_reported_as_missing_from_catalogue(self):
        report = learning_path_generator.generate_learning_path_candidates(
            {"python"},
            set(),
            {"completed-course": {"python"}},
            {},
            {"completed-course": 2},
            {"completed-course"},
            {"completed-course"},
        )

        self.assertEqual(report["catalogue_unavailable_competencies"], [])
        self.assertEqual(report["candidates"][0]["training_ids"], ())
        self.assertEqual(report["candidates"][0]["uncovered_competencies"], ("python",))


class TrainingCatalogueQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ontology_path = Path(__file__).resolve().parents[2] / "ontology" / "SkillPath.owl"
        with ontology_path.open("rb") as ontology_file:
            cls.graph = Graph().parse(ontology_file, format="xml")

    @classmethod
    def evaluate_query(cls, query: str, graph: Graph | None = None) -> list[dict[str, str]]:
        rows = []
        for result in (graph or cls.graph).query(query):
            row = {}
            for name, value in result.asdict().items():
                text = str(value)
                if isinstance(value, URIRef) and "#" in text:
                    text = text.rsplit("#", 1)[-1]
                row[str(name)] = text
            rows.append(row)
        return rows

    def test_training_catalogue_query_includes_real_courses_and_prerequisites(self):
        expected_trainings = {
            str(training).rsplit("#", 1)[-1]
            for training in self.graph.subjects(RDF.type, ONTOLOGY + "Formation")
        }
        with patch.object(sp, "run_query", side_effect=self.evaluate_query):
            rows = sp.formations_et_prerequis()

        self.assertEqual({row["formation"] for row in rows}, expected_trainings)
        self.assertTrue(any(row.get("competence") for row in rows))
        self.assertTrue(any(row.get("prereq") for row in rows))

    def test_checked_in_java_training_does_not_claim_communication_without_an_ontology_link(self):
        with patch.object(sp, "run_query", side_effect=self.evaluate_query):
            rows = sp.formations_et_prerequis()

        java_skills = {
            row["competence"]
            for row in rows
            if row["formation"] == "form_FormationJava" and row.get("competence")
        }
        self.assertEqual(java_skills, {"comp_Java"})
        self.assertNotIn("_comp_Communication", java_skills)
        self.assertNotIn("comp_Communication", java_skills)

    def test_catalogue_query_includes_direct_and_module_taught_skills(self):
        module_graph = Graph()
        for triple in self.graph:
            module_graph.add(triple)
        module_graph.remove((
            ONTOLOGY + "form_MoocPython",
            ONTOLOGY + "enseigne",
            ONTOLOGY + "comp_Python",
        ))

        with patch.object(
            sp,
            "run_query",
            side_effect=lambda query: self.evaluate_query(query, module_graph),
        ):
            rows = sp.formations_et_prerequis()

        taught_by_python_mooc = {
            row["competence"]
            for row in rows
            if row["formation"] == "form_MoocPython" and row.get("competence")
        }
        self.assertIn("comp_Python", taught_by_python_mooc)
        self.assertIn(
            ONTOLOGY + "mod_PythonBase",
            set(self.graph.objects(ONTOLOGY + "form_MoocPython", ONTOLOGY + "contientModule")),
        )

    def test_python_is_acquired_and_taught_by_a_real_catalogue_training(self):
        profile = ONTOLOGY + "profil_Sara"
        self.assertIn(
            ONTOLOGY + "comp_Python",
            set(self.graph.objects(profile, ONTOLOGY + "aAcquis")),
        )
        self.assertIn(
            ONTOLOGY + "form_MoocPython",
            set(self.graph.objects(profile, ONTOLOGY + "aSuivi")),
        )
        with patch.object(sp, "run_query", side_effect=self.evaluate_query):
            rows = sp.formations_et_prerequis()
        course_skills: dict[str, set[str]] = {}
        for row in rows:
            course_skills.setdefault(row["formation"], set())
            if skill := row.get("competence"):
                course_skills[row["formation"]].add(skill)

        report = learning_path_generator.generate_learning_path_candidates(
            {"comp_Python"},
            {"comp_Python"},
            course_skills,
            {},
            {},
            course_skills,
            {"form_MoocPython"},
        )
        self.assertEqual(report["missing_competencies"], [])
        self.assertEqual(report["catalogue_unavailable_competencies"], [])
        self.assertEqual(report["candidates"][0]["training_ids"], ())


if __name__ == "__main__":
    unittest.main()

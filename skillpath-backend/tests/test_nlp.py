"""Tests du moteur TALN (``app.nlp``) reconstruit.

Couvre, comme demandé :

* une question par **type de question** (liste, relation directe et inverse,
  négation, comparaison numérique, comptage, détail, éléments communs,
  prérequis transitifs) ;
* une question par **famille de classes** (compétences, formations, modules,
  métiers, familles, niveaux, profils, parcours, évaluations) ;
* les cas limites : faute de frappe, négation, filtre numérique, nom ambigu,
  paraphrase, question « entité seule », question incompréhensible et tentative
  d'injection ``'; DROP`` qui ne doit jamais produire de requête à partir du
  texte brut.

Le pipeline est exécuté hors ligne : le schéma est le schéma de repli, les
individus et les résultats SPARQL sont simulés, et le repli par paraphrase est
désactivé par défaut (un test dédié vérifie son branchement).
"""

import unittest
from unittest.mock import patch

from app import nlp, ontology_schema, sparql_client

#: Individus simulés, alignés sur les libellés réels de l'ontologie.
INDIVIDUALS = {
    "Competence": [
        {"id": "comp_Python", "label": "Python", "class": "CompetenceTechnique"},
        {"id": "comp_SQL", "label": "SQL", "class": "CompetenceTechnique"},
        {"id": "comp_Cloud", "label": "Cloud", "class": "CompetenceTechnique"},
        {"id": "comp_Communication", "label": "Communication", "class": "CompetenceTransverse"},
    ],
    "Formation": [
        {"id": "form_MoocPython", "label": "Mooc Python", "class": "FormationEnLigne"},
        {"id": "form_DataEng", "label": "Data Eng", "class": "FormationEnLigne"},
        {"id": "form_MasterCloud", "label": "Master Cloud", "class": "FormationEnLigne"},
    ],
    "Module": [
        {"id": "mod_PythonBase", "label": "Python Base", "class": "ModuleTechnique"},
        {"id": "mod_CloudIntro", "label": "Cloud Intro", "class": "ModuleTechnique"},
    ],
    "Metier": [
        {"id": "met_DataEngineer", "label": "Data Engineer", "class": "Metier"},
        {"id": "met_DataAnalyst", "label": "Data Analyst", "class": "Metier"},
    ],
    "FamilleMetier": [
        {"id": "fam_Data", "label": "Data", "class": "FamilleMetier"},
    ],
    "Niveau": [
        {"id": "niv_Avance", "label": "Avance", "class": "Niveau"},
    ],
    "Parcours": [
        {"id": "parc_Data", "label": "Parcours Data", "class": "Parcours"},
    ],
    "Evaluation": [
        {"id": "eval_Data", "label": "Examen Data", "class": "Evaluation"},
    ],
    "ProfilUtilisateur": [
        {"id": "profil_abc", "label": "Amine", "class": "ProfilUtilisateur"},
    ],
}


def _individuals(entity_type, _search=None, _include_class=False):
    """Réponse simulée de ``sparql_client.list_individuals``."""
    return INDIVIDUALS.get(entity_type, [])


def iri(identifier: str) -> str:
    return sparql_client.ONTOLOGY_NAMESPACE + identifier


class NlpTestCase(unittest.TestCase):
    """Base commune : schéma de repli, individus et résultats simulés."""

    def setUp(self):
        ontology_schema.reset_schema()
        self.addCleanup(ontology_schema.reset_schema)
        for patcher in (
            patch.object(nlp, "_schema", return_value=ontology_schema.fallback_schema()),
            patch.object(sparql_client, "list_individuals", side_effect=_individuals),
            patch.object(sparql_client, "run_query", return_value=[]),
            # Le repli par paraphrase est désactivé par défaut (pas de modèle).
            patch.object(nlp, "_paraphrase_intent", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def analyse(self, question, profil=None):
        return nlp.analyze_question(question, profil)


class ListPerClassTests(NlpTestCase):
    """Une question « liste » par famille de classes."""

    CASES = {
        "Liste les compétences.": "Competence",
        "Liste les formations.": "Formation",
        "Affiche les modules.": "Module",
        "Liste tous les métiers.": "Metier",
        "Liste les familles de métiers.": "FamilleMetier",
        "Liste les niveaux.": "Niveau",
        "Liste les parcours.": "Parcours",
        "Liste les évaluations.": "Evaluation",
        "Liste les profils.": "ProfilUtilisateur",
    }

    def test_list_intent_per_class(self):
        for question, klass in self.CASES.items():
            with self.subTest(question=question):
                intent, info = nlp.detect_intent(question)
                self.assertEqual(intent, f"list_{klass}")
                self.assertEqual(info["target_class"], klass)

    def test_list_query_targets_the_right_class(self):
        response = self.analyse("Liste les compétences.")
        self.assertEqual(response["intent"], "list_Competence")
        self.assertIn(f"rdfs:subClassOf* onto:Competence", response["sparql"])
        self.assertEqual(response["results"], [])

    def test_list_message_lists_names(self):
        rows = [{"item": "comp_Python", "nom": "Python"}, {"item": "comp_SQL", "nom": "SQL"}]
        with patch.object(sparql_client, "run_query", return_value=rows):
            response = self.analyse("Liste les compétences.")
        self.assertIn("Python", response["message"])
        self.assertIn("SQL", response["message"])


class RelationTests(NlpTestCase):
    """Relations directes et inverses, ancrage typé."""

    def test_trainings_teaching_a_skill(self):
        intent, info = nlp.detect_intent("Quelles formations enseignent Python ?")
        self.assertEqual(intent, "relation_enseigne")
        self.assertEqual(info["property"], "enseigne")

        response = self.analyse("Quelles formations enseignent Python ?")
        entity = response["entities"][0]
        self.assertEqual(entity["iri"], iri("comp_Python"))
        self.assertEqual(entity["type"], "Competence")
        self.assertIn(f"onto:enseigne <{iri('comp_Python')}>", response["sparql"])

    def test_modules_teaching_a_skill_uses_module_property(self):
        response = self.analyse("Quels modules enseignent Cloud ?")
        self.assertEqual(response["intent"], "relation_moduleEnseigne")
        self.assertEqual(response["entities"][0]["iri"], iri("comp_Cloud"))

    def test_competences_taught_by_a_module(self):
        # Le module est le sujet : « le module X » -> ``moduleEnseigne`` (et non
        # la propriété générique ``enseigne``).
        response = self.analyse("Quelles compétences enseigne le module Python Base ?")
        self.assertEqual(response["intent"], "relation_moduleEnseigne")
        self.assertEqual(response["entities"][0]["iri"], iri("mod_PythonBase"))

    def test_prerequisites_of_a_training(self):
        response = self.analyse("Quels prérequis possède la formation Data Eng ?")
        self.assertEqual(response["intent"], "relation_aPourPrerequis")
        self.assertEqual(response["entities"][0]["iri"], iri("form_DataEng"))

    def test_trainings_requiring_an_entity_as_prerequisite(self):
        response = self.analyse("Quelles formations ont Python comme prérequis ?")
        self.assertEqual(response["intent"], "relation_aPourPrerequis")
        entity = response["entities"][0]
        self.assertEqual(entity["type"], "Formation")
        self.assertEqual(entity["iri"], iri("form_MoocPython"))

    def test_trainings_containing_a_module(self):
        response = self.analyse("Quelles formations contiennent le module Python Base ?")
        self.assertEqual(response["intent"], "relation_contientModule")
        self.assertEqual(response["entities"][0]["iri"], iri("mod_PythonBase"))

    def test_occupations_requiring_a_skill(self):
        response = self.analyse("Quels métiers requièrent la compétence SQL ?")
        self.assertEqual(response["intent"], "relation_requiert")
        self.assertEqual(response["entities"][0]["iri"], iri("comp_SQL"))

    def test_skills_required_by_an_occupation(self):
        response = self.analyse("Quelles compétences requiert le métier Data Engineer ?")
        self.assertEqual(response["intent"], "relation_requiert")
        self.assertEqual(response["entities"][0]["iri"], iri("met_DataEngineer"))

    def test_family_of_an_occupation(self):
        response = self.analyse("À quelle famille appartient le métier Data Engineer ?")
        self.assertEqual(response["intent"], "relation_appartientA")
        self.assertEqual(response["entities"][0]["iri"], iri("met_DataEngineer"))


class NegationTests(NlpTestCase):
    def test_negated_relation_uses_filter_not_exists(self):
        intent, _ = nlp.detect_intent("Quelles formations ne contiennent pas le module Python Base ?")
        self.assertEqual(intent, "relation_negated_contientModule")

        response = self.analyse("Quelles formations ne contiennent pas le module Python Base ?")
        self.assertIn("FILTER NOT EXISTS", response["sparql"])
        self.assertEqual(response["entities"][0]["iri"], iri("mod_PythonBase"))

    def test_orphan_modules(self):
        intent, info = nlp.detect_intent("Quels modules ne sont associés à aucune formation ?")
        self.assertEqual(intent, "list_Module")
        self.assertEqual(info["target_class"], "Module")

        response = self.analyse("Quels modules ne sont associés à aucune formation ?")
        self.assertEqual(response["entities"], [])
        self.assertIn("FILTER NOT EXISTS", response["sparql"])
        self.assertIn("contientModule", response["sparql"])


class CountTests(NlpTestCase):
    def test_count_relation(self):
        response = self.analyse("Combien de formations enseignent Python ?")
        self.assertEqual(response["intent"], "count_relation_enseigne")
        self.assertIn("COUNT(DISTINCT ?item)", response["sparql"])

    def test_count_list(self):
        response = self.analyse("Combien de compétences existe-t-il ?")
        self.assertEqual(response["intent"], "count_list_Competence")
        self.assertIn("COUNT(DISTINCT ?item)", response["sparql"])


class NumericFilterTests(NlpTestCase):
    def test_less_than(self):
        response = self.analyse("Quelles formations durent moins de 25 heures ?")
        self.assertEqual(response["intent"], "numeric_filter_Formation")
        self.assertIn("FILTER(?value < 25)", response["sparql"])
        self.assertIn("aDureeHeures", response["sparql"])

    def test_more_than(self):
        response = self.analyse("Quelles formations durent plus de 35 h ?")
        self.assertEqual(response["intent"], "numeric_filter_Formation")
        self.assertIn("FILTER(?value > 35)", response["sparql"])


class DetailTests(NlpTestCase):
    def test_detail_of_a_training(self):
        response = self.analyse("Détails de la formation Data Eng.")
        self.assertEqual(response["intent"], "detail_Formation")
        self.assertEqual(response["entities"][0]["iri"], iri("form_DataEng"))
        self.assertIn("SELECT ?propriete ?valeur", response["sparql"])

    def test_detail_of_an_occupation(self):
        response = self.analyse("Quelles informations sur le métier Data Engineer ?")
        self.assertEqual(response["intent"], "detail_Metier")
        self.assertEqual(response["entities"][0]["iri"], iri("met_DataEngineer"))


class CommonAndTransitiveTests(NlpTestCase):
    def test_common_competences_of_two_trainings(self):
        response = self.analyse(
            "Quelles compétences sont communes aux formations Data Eng et Master Cloud ?"
        )
        self.assertEqual(response["intent"], "common_enseigne")
        anchors = [entity["iri"] for entity in response["entities"]]
        self.assertEqual(anchors, [iri("form_DataEng"), iri("form_MasterCloud")])
        self.assertIn(f"<{iri('form_DataEng')}> onto:enseigne ?item", response["sparql"])
        self.assertIn(f"<{iri('form_MasterCloud')}> onto:enseigne ?item", response["sparql"])

    def test_transitive_prerequisites(self):
        response = self.analyse("Tous les prérequis de la formation Data Eng ?")
        self.assertEqual(response["intent"], "transitive_aPourPrerequis")
        self.assertIn("onto:aPourPrerequis+ ?item", response["sparql"])


class EdgeCaseTests(NlpTestCase):
    def test_typo_is_tolerated(self):
        # « Pythn » doit tout de même se résoudre en compétence Python.
        response = self.analyse("Quelles formations enseignent Pythn ?")
        self.assertEqual(response["intent"], "relation_enseigne")
        self.assertEqual(response["entities"][0]["iri"], iri("comp_Python"))

    def test_ambiguous_name_is_restricted_to_expected_type(self):
        # « Python » après « prérequis » est une FORMATION (Mooc Python),
        # jamais la compétence comp_Python.
        response = self.analyse("Quels prérequis possède la formation Python ?")
        self.assertEqual(response["intent"], "relation_aPourPrerequis")
        entity = response["entities"][0]
        self.assertEqual(entity["type"], "Formation")
        self.assertEqual(entity["iri"], iri("form_MoocPython"))

    def test_entity_only_question_returns_details(self):
        response = self.analyse("Data Eng")
        self.assertEqual(response["intent"], "detail_Formation")
        self.assertEqual(response["entities"][0]["iri"], iri("form_DataEng"))
        self.assertTrue(response["message"].startswith("Closest match: everything known about"))

    def test_meaningless_question_returns_examples(self):
        response = self.analyse("Quel temps fait-il à Tunis ?")
        self.assertEqual(response["intent"], "unknown")
        self.assertEqual(response["sparql"], "")
        self.assertEqual(response["results"], [])
        self.assertIn("Intention non reconnue", response["message"])


class InjectionTests(NlpTestCase):
    """Le texte brut de la question ne doit jamais entrer dans la requête."""

    def test_pure_injection_payload(self):
        payload = "'; DROP TABLE utilisateurs; --"
        response = self.analyse(payload)
        sparql = response["sparql"]
        self.assertNotIn("DROP", sparql.upper())
        self.assertNotIn("table", sparql.lower())
        self.assertNotIn("--", sparql)
        self.assertNotIn(payload.lower(), sparql.lower())
        # La requête reste une lecture construite sur un motif de classe validé.
        if sparql:
            self.assertIn("PREFIX onto:", sparql)

    def test_injection_appended_to_a_real_question(self):
        response = self.analyse("Quelles formations enseignent '; DROP TABLE x; --")
        sparql = response["sparql"]
        self.assertNotIn("DROP", sparql.upper())
        self.assertNotIn("drop table", sparql.lower())
        self.assertNotIn("';", sparql)


class ParaphraseFallbackTests(NlpTestCase):
    def test_paraphrase_relation_used_when_rules_fail(self):
        question = "Python Base"
        # Aucune règle ne produit de plan pour cette formulation…
        self.assertIsNone(nlp._plan(question))
        # … la paraphrase choisit alors la propriété « moduleEnseigne ».
        with patch.object(nlp, "_paraphrase_intent", return_value="relation_moduleEnseigne"):
            response = self.analyse(question)
        self.assertEqual(response["intent"], "relation_moduleEnseigne")
        self.assertEqual(response["entities"][0]["iri"], iri("mod_PythonBase"))

    def test_paraphrase_list_intent_used_when_rules_fail(self):
        question = "Cloud Intro"
        self.assertIsNone(nlp._plan(question))
        with patch.object(nlp, "_paraphrase_intent", return_value="list_Module"):
            response = self.analyse(question)
        self.assertEqual(response["intent"], "list_Module")
        self.assertIn("rdfs:subClassOf* onto:Module", response["sparql"])

    def test_paraphrase_unavailable_keeps_rules_only(self):
        # Modèle indisponible : aucune exception, la question inconnue reste
        # classée « unknown » avec des exemples.
        with patch.object(nlp, "_paraphrase_model", return_value=None):
            response = self.analyse("Quel temps fait-il à Tunis ?")
        self.assertEqual(response["intent"], "unknown")


class DedicatedIntentTests(NlpTestCase):
    """Intentions dédiées : elles exploitent le profil fourni dans la requête."""

    def test_missing_skills_for_an_occupation(self):
        response = self.analyse(
            "Quelles compétences me manquent pour le métier Data Engineer ?", "profil_abc"
        )
        self.assertEqual(response["intent"], "competences_manquantes_metier")
        self.assertEqual(response["entities"][0]["iri"], iri("met_DataEngineer"))
        self.assertIn("profil_abc", response["sparql"])

    def test_accessible_occupations(self):
        response = self.analyse("Quels métiers puis-je exercer ?", "profil_abc")
        self.assertEqual(response["intent"], "metiers_eligibles_profil")
        self.assertIn("profil_abc", response["sparql"])

    def test_eligible_profiles_for_an_occupation(self):
        response = self.analyse(
            "Quels profils sont éligibles pour le métier Data Engineer ?", "profil_abc"
        )
        self.assertEqual(response["intent"], "profils_eligibles_metier")
        self.assertEqual(response["entities"][0]["iri"], iri("met_DataEngineer"))

    def test_trainings_closing_the_gaps(self):
        response = self.analyse("Quelles formations comblent mes lacunes ?", "profil_abc")
        self.assertEqual(response["intent"], "formations_combler_ecarts")
        self.assertIn("profil_abc", response["sparql"])

    def test_optimal_path(self):
        response = self.analyse("Quel est mon parcours optimal ?", "profil_abc")
        self.assertEqual(response["intent"], "parcours_optimal")
        self.assertIn("profil_abc", response["sparql"])

    def test_acquired_skills(self):
        response = self.analyse("Quelles compétences ai-je ?", "profil_abc")
        self.assertEqual(response["intent"], "competences_acquises_profil")
        self.assertIn("profil_abc", response["sparql"])

    def test_profile_is_never_read_from_the_question_text(self):
        # L'identifiant « profil_zzz » présent dans le texte est ignoré : sans
        # champ « profil », aucune requête n'est produite.
        response = self.analyse(
            "Quels métiers puis-je exercer avec le profil profil_zzz ?", profil=None
        )
        self.assertEqual(response["intent"], "metiers_eligibles_profil")
        self.assertEqual(response["sparql"], "")
        self.assertNotIn("profil_zzz", response["sparql"])
        self.assertIn("profil", response["message"].lower())


class ResponseShapeTests(NlpTestCase):
    FIELDS = {"question", "intent", "entities", "sparql", "results", "message"}

    def test_response_always_exposes_the_expected_fields(self):
        for question in (
            "Liste les compétences.",
            "Quelles formations enseignent Python ?",
            "Quel temps fait-il à Tunis ?",
        ):
            with self.subTest(question=question):
                response = self.analyse(question)
                self.assertEqual(set(response), self.FIELDS)
                self.assertIsInstance(response["entities"], list)

    def test_displayed_query_is_exactly_the_executed_one(self):
        captured = {}

        def fake_run(query):
            captured["query"] = query
            return [{"item": "form_MoocPython", "nom": "Mooc Python"}]

        with patch.object(sparql_client, "run_query", side_effect=fake_run):
            response = self.analyse("Quelles formations enseignent Python ?")

        self.assertEqual(captured["query"], response["sparql"])
        self.assertIn("Mooc Python", response["message"])

    def test_displayed_query_equals_executed_query_for_dedicated_intent(self):
        captured = {}

        def fake_run(query):
            captured["query"] = query
            return []

        with patch.object(sparql_client, "run_query", side_effect=fake_run):
            response = self.analyse("Quel est mon parcours optimal ?", "profil_abc")

        self.assertEqual(captured["query"], response["sparql"])


class ExamplesPayloadTests(NlpTestCase):
    def test_payload_exposes_questions_and_intents(self):
        payload = nlp.examples_payload()
        self.assertTrue(payload["examples"])
        self.assertEqual(payload["supported_intents"], list(nlp.SUPPORTED_INTENTS))
        self.assertIn("Liste les compétences.", payload["examples"])


if __name__ == "__main__":
    unittest.main()

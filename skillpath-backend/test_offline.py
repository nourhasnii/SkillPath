"""
Test hors-ligne : simule ton dataset SkillPath avec RDFLib en mémoire
(sans avoir besoin de Fuseki), pour valider que les requêtes SPARQL
du backend sont correctes AVANT de les brancher sur ton vrai Fuseki.
"""
from rdflib import Graph, Namespace, RDF

SP = Namespace("http://www.skillpath.tn/onto#")

g = Graph()
g.bind("sp", SP)

# --- Reconstruction minimale de tes données réelles (profil_Ahmed complet, profil_Sara incomplet) ---
g.add((SP.profil_Ahmed, SP.vise, SP.met_DataEngineer))
for c in ["comp_Python", "comp_SQL", "comp_Cloud", "comp_DataPipeline"]:
    g.add((SP.profil_Ahmed, SP.aAcquis, SP[c]))
g.add((SP.profil_Ahmed, SP.aSuivi, SP.form_MoocPython))
g.add((SP.profil_Ahmed, SP.aSuivi, SP.form_MasterCloud))

g.add((SP.profil_Sara, SP.vise, SP.met_DataEngineer))
for c in ["comp_Python", "comp_SQL"]:
    g.add((SP.profil_Sara, SP.aAcquis, SP[c]))
g.add((SP.profil_Sara, SP.aSuivi, SP.form_MoocPython))

for c in ["comp_Python", "comp_SQL", "comp_Cloud", "comp_DataPipeline"]:
    g.add((SP.met_DataEngineer, SP.requiert, SP[c]))

g.add((SP.form_MasterCloud, SP.enseigne, SP.comp_Cloud))
g.add((SP.form_MasterCloud, SP.aPourPrerequis, SP.form_MoocPython))
g.add((SP.form_DataEng, SP.enseigne, SP.comp_DataPipeline))
g.add((SP.form_DataEng, SP.aPourPrerequis, SP.form_MasterCloud))

# --- Les mêmes requêtes SPARQL que dans app/sparql_client.py ---
SP_PREFIX = "PREFIX sp: <http://www.skillpath.tn/onto#>\n"


def run(query):
    return [
        {str(v): str(row[v]).split("#")[-1] for v in row.labels}
        for row in g.query(query)
    ]


def test_competences_manquantes(profil):
    q = SP_PREFIX + f"""
    SELECT ?competence WHERE {{
        sp:{profil} sp:vise ?metier .
        ?metier sp:requiert ?competence .
        FILTER NOT EXISTS {{ sp:{profil} sp:aAcquis ?competence }}
    }}
    """
    return run(q)


def test_metiers_accessibles(profil):
    q = SP_PREFIX + f"""
    SELECT DISTINCT ?metier WHERE {{
        ?metier sp:requiert ?comp .
        FILTER NOT EXISTS {{
            ?metier sp:requiert ?c2 .
            FILTER NOT EXISTS {{ sp:{profil} sp:aAcquis ?c2 }}
        }}
    }}
    """
    return run(q)


def test_chaine_prerequis(formation):
    q = SP_PREFIX + f"""
    SELECT ?prereq WHERE {{
        sp:{formation} sp:aPourPrerequis+ ?prereq .
    }}
    """
    return run(q)


def test_parcours_optimal(profil):
    q = SP_PREFIX + f"""
    SELECT DISTINCT ?formation WHERE {{
        ?formation sp:enseigne ?comp .
        sp:{profil} sp:vise ?metier .
        ?metier sp:requiert ?comp .
        FILTER NOT EXISTS {{ sp:{profil} sp:aAcquis ?comp }}
        FILTER NOT EXISTS {{
            ?formation sp:aPourPrerequis ?prereq .
            FILTER NOT EXISTS {{ sp:{profil} sp:aSuivi ?prereq }}
        }}
    }}
    """
    return run(q)


print("== Q1 : compétences manquantes ==")
print("Ahmed :", test_competences_manquantes("profil_Ahmed"), "(attendu : [])")
print("Sara  :", test_competences_manquantes("profil_Sara"), "(attendu : comp_Cloud, comp_DataPipeline)")

print("\n== Q2 : métiers accessibles ==")
print("Ahmed :", test_metiers_accessibles("profil_Ahmed"), "(attendu : met_DataEngineer)")
print("Sara  :", test_metiers_accessibles("profil_Sara"), "(attendu : [])")

print("\n== Q3 : chaîne de prérequis ==")
print("form_DataEng :", test_chaine_prerequis("form_DataEng"), "(attendu : form_MasterCloud, form_MoocPython)")

print("\n== Q4 : parcours optimal ==")
print("Sara :", test_parcours_optimal("profil_Sara"), "(attendu : form_MasterCloud)")

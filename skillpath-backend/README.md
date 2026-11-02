# SkillPath — Backend API

Couche **Back-end** de l'architecture officielle du projet (Python + RDFLib/SPARQLWrapper),
placée entre **Fuseki** (qui héberge ton ontologie OWL) et le futur **Front-end** (React/Angular).

```
Front-end  --(question)-->  API IA  --(SPARQL)-->  Fuseki  <--  Back-end (ce projet)  <--  Protégé/OWL
```

## 1. Installation

```bash
cd backend
pip install -r requirements.txt
```

## 2. Prérequis : Fuseki doit tourner

Ce backend ne contient pas de données lui-même : il interroge **ton Fuseki local**,
exactement comme tu le faisais à la main dans l'interface web de Fuseki.

1. Lance Fuseki : `fuseki-server.bat` (Windows) depuis ton dossier Fuseki.
2. Vérifie que le dataset `skillpath` est bien chargé avec ton fichier `SkillPath.owl`
   à jour (celui avec les 23 individus : Ahmed, Sara, met_DevOps, etc.).
3. Par défaut, ce backend suppose que Fuseki tourne sur
   `http://localhost:3030/skillpath/sparql`. Si ton URL est différente,
   lance le backend avec :
   ```bash
   set FUSEKI_URL=http://localhost:3030/TON_DATASET/sparql   (Windows)
   export FUSEKI_URL=http://localhost:3030/TON_DATASET/sparql (Mac/Linux)
   ```

## 3. Lancer le backend

```bash
uvicorn app.main:app --reload --port 8000
```

Puis ouvre **http://localhost:8000/docs** — une interface Swagger interactive
se génère automatiquement, tu peux tester chaque route directement dans le navigateur.

## 4. Routes disponibles

| Route | Équivaut à | Exemple |
|---|---|---|
| `GET /dashboard` | Compteurs publics de compétences, formations et métiers | `/dashboard` |
| `GET /formations` | Catalogue public avec types, durées, compétences enseignées et prérequis | `/formations` |
| `GET /formations/{id}` | Détail public d'une formation et de ses modules | `/formations/form_MasterCloud` |
| `GET /modules/{id}` | Détail public d'un module et de ses compétences enseignées | `/modules/mod_CloudIntro` |
| `GET /api/stats` | Compteurs réels du graphe | `/api/stats` |
| `GET /api/{type}?search=` | Individus d'une classe | `/api/Competence?search=python` |
| `GET /api/{type}/classes` | Classes et sous-classes disponibles | `/api/ProfilUtilisateur/classes` |
| `GET /api/{type}/{id}` | Propriétés et relations d'un individu | `/api/ProfilUtilisateur/profil_Ahmed` |
| `POST /me/evaluations/generate` | Générer l'évaluation automatique et son diagnostic | `/me/evaluations/generate` |
| `GET /me/evaluations` | Lire les évaluations avec leur diagnostic | `/me/evaluations` |
| `GET /me/recommendations` | Top 5 des compétences recommandées au profil authentifié | `/me/recommendations` |
| `GET /me/career-bridges` | Métiers proches classés selon les compétences acquises | `/me/career-bridges` |
| `POST /api/{type}` | Création d'un individu | `/api/Parcours` |
| `PUT /api/{type}/{id}` | Mise à jour ciblée | `/api/Formation/form_MasterCloud` |
| `DELETE /api/{type}/{id}` | Suppression si aucune dépendance ne la bloque | `/api/Module/mod_CloudIntro` |
| `GET /profils/{profil}` | Détail complet d'un profil | `/profils/profil_Ahmed` |
| `PUT /profils/{profil}` | Ajouter des formations suivies au profil authentifié | `/profils/profil_Ahmed` |
| `GET /profils/{profil}/competences-manquantes` | Q1 | `/profils/profil_Sara/competences-manquantes` |
| `GET /profils/{profil}/metiers-accessibles` | Q2 | `/profils/profil_Ahmed/metiers-accessibles` |
| `GET /profils/{profil}/parcours-optimal` | Recommandation | `/profils/profil_Sara/parcours-optimal` |
| `GET /formations/{formation}/chaine-prerequis` | Q3 (transitivité) | `/formations/form_DataEng/chaine-prerequis` |
| `GET /learning-path?profil=&metier=` | Parcours personnalisé historique, séquence unique | `/learning-path?profil=profil_Ahmed&metier=met_DevOps` |
| `GET /parcours-optimal?profil=&metier=&max_duration_hours=` | Candidats de parcours comparés et classés | `/parcours-optimal?profil=profil_Ahmed&metier=met_DevOps` |

Chaque route renvoie du **JSON**, exactement comme prévu dans le schéma d'architecture
officiel du projet (bloc "Fuseki → JSON → Back-end / Front-end").

`GET /me/recommendations` est en lecture seule et réservé aux comptes étudiant et
professionnel. Le profil provient de la session authentifiée. Les scores et raisons
sont calculés à partir des compétences acquises et des relations métier, formation,
module et famille de métiers présentes dans Fuseki ; les formations et modules
enseignants incluent leur nom, leur type et leur durée lorsqu'elle est renseignée.

`GET /me/career-bridges` est également réservé aux comptes étudiant et professionnel.
Il compare uniquement les compétences `aAcquis` du profil aux compétences requises par
les autres métiers et retourne les formations/modules du catalogue pour les lacunes.

L'évaluation automatique inclut un diagnostic textuel déterministe (forces, lacunes,
raison du niveau, nombre de compétences restant pour le niveau suivant et formations
enseignant chaque compétence manquante, avec leurs modules). Les données proviennent
de Fuseki et aucun modèle de langage n'est utilisé.

Les types CRUD sont `Competence`, `Formation`, `Module`, `Metier`, `FamilleMetier`,
`ProfilUtilisateur`, `Niveau`, `Parcours` et `Evaluation`. Les classes calculées
`CompetenceManquante`, `ProfilEligible` et `ParcoursOptimal` ne sont pas modifiables.
L'historique des parcours est constitué des individus `Parcours` existants.
Les payloads d'écriture ont la forme
`{"id":"...","class":"ParcoursStandard","properties":{"aNom":"..."},"relations":{"contientFormation":["form_..."]}}`.
Le champ `class` est optionnel et sa valeur doit provenir des classes renvoyées par
`GET /api/{type}/classes`.
Les relations doivent référencer des individus existants du bon type. Une suppression
référencée est refusée avec un détail explicite. Pour un endpoint Fuseki personnalisé,
`FUSEKI_UPDATE_URL` peut désigner son endpoint `/update`; par défaut, il est dérivé de
`FUSEKI_URL`.

### Génération du parcours d'apprentissage

`GET /learning-path` conserve le parcours personnalisé historique : une séquence
déterministe choisie par couverture des compétences manquantes et ordonnée selon
les prérequis. `GET /parcours-optimal` utilise le même profil et métier pour comparer
jusqu'à 10 séquences issues du catalogue. Les formations sont sélectionnées via `enseigne`;
leurs prérequis `aPourPrerequis` sont ajoutés récursivement et ordonnés avant les
formations dépendantes. Les séquences sont classées par compétences manquantes
couvertes, durée cumulée disponible, puis nombre de formations. Le paramètre
optionnel `max_duration_hours` exclut les séquences dépassant la limite ainsi que
celles dont la durée n'est pas renseignée.

Un parcours choisi peut être enregistré avec `POST /account/parcours`. Cette route
vérifie l'ordre des prérequis, conserve la séquence dans `aOrdreFormations` et lie
le parcours au profil via `suitParcours`. Après un déploiement, recharge
`ontology/SkillPath.owl` dans Fuseki pour y appliquer la déclaration de la nouvelle
propriété.

## 5. Test hors-ligne (sans Fuseki)

`test_offline.py` reconstruit un petit graphe RDF en mémoire (RDFLib) avec les mêmes
données qu'Ahmed/Sara, et exécute les mêmes requêtes SPARQL que le backend — utile
pour vérifier que la logique est correcte avant même de lancer Fuseki :

```bash
python test_offline.py
```

## 6. Frontend SkillPath

Le frontend Angular standalone se trouve dans `skillpath-frontend`. Il utilise
les routes `/login`, `/register`, `/forgot-password` et `/reset-password`, puis
redirige chaque rôle vers son espace dédié. Les détails d'installation et de lancement
complet sont dans la section suivante.

La prochaine évolution de l'architecture peut ajouter l'**API IA** (TALN) pour
traduire des questions en langage naturel vers les requêtes SPARQL existantes.

## 7. Authentification et rôles

Les comptes, sessions et demandes de réinitialisation sont conservés dans SQLite,
séparément de Fuseki. Le mot de passe est haché avec Argon2id; les sessions utilisent
un cookie `HttpOnly` et les jetons de réinitialisation ne sont utilisables qu'une fois.
Le profil métier associé au compte reste un individu `ProfilUtilisateur` dans Fuseki;
aucune adresse email ni donnée d'authentification n'est écrite dans l'ontologie.

La base est créée automatiquement au démarrage sous
`skillpath-backend/data/auth.sqlite3`. Pour déplacer la base, configure
`AUTH_DATABASE_PATH`. Le répertoire contenant la base doit être protégé comme toute
donnée de compte.

Les comptes publics ne peuvent choisir que `STUDENT` ou `PROFESSIONAL`. En
environnement `development`, le backend initialise SQLite puis crée le compte
`nour.hasni02@gmail.com` / `Nour Hasni` en rôle `ADMIN`, sans profil OWL, lorsque
l'adresse est absente. S'il existe déjà, son nom, son rôle et son mot de passe sont
actualisés avec les valeurs de développement configurées. Le mot de passe provient de
`SKILLPATH_ADMIN_PASSWORD`, est haché avec Argon2id et n'est jamais affiché.
Cette initialisation est désactivée hors de l'environnement `development`.

Avant le démarrage local, définissez le secret dans votre terminal ou fichier
d'environnement local non versionné :

```powershell
$env:ENVIRONMENT = "development"
$env:SKILLPATH_ADMIN_PASSWORD = "choose-a-local-development-password"
uvicorn app.main:app --reload --port 8000
```

Le backend charge aussi automatiquement `skillpath-backend/.env` au démarrage (sans
écraser les variables déjà fournies par le processus). Les messages `SkillPath startup`
et `Admin seeder` apparaissent dans la console pour indiquer que l'initialisation et le
seeder ont été lancés; le mot de passe n'est jamais journalisé.

Quand `ENVIRONMENT=development`, le rate limiting est complètement désactivé sur
`/auth/login` et `/auth/forgot-password`; `/auth/register` et `/auth/reset-password`
n'appliquent pas de rate limiting. Hors de cet environnement, la protection des routes
login et forgot-password reste active.

Le seeder affiche `Admin créé avec succès` ou `Admin mis à jour avec succès`, ainsi que
l'email du compte, mais jamais son mot de passe. Pour une création manuelle d'un autre
compte ADMIN, l'utilitaire CLI demande le mot de passe de façon masquée :

```powershell
python -m app.create_admin --email admin@example.tn --name "SkillPath Admin"
```

La réinitialisation par email nécessite un serveur SMTP. Exemple PowerShell
(renseigner les secrets uniquement dans l'environnement local ou le gestionnaire de
secrets du déploiement) :

```powershell
$env:SMTP_HOST = "smtp.example.tn"
$env:SMTP_FROM = "no-reply@example.tn"
$env:SMTP_PORT = "587"
$env:SMTP_USER = "..."
$env:SMTP_PASSWORD = "..."
$env:SMTP_STARTTLS = "true"
$env:FRONTEND_BASE_URL = "http://localhost:4200"
```

Variables disponibles : `SMTP_HOST`, `SMTP_FROM`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_USE_SSL`, `SMTP_STARTTLS`, `SMTP_TIMEOUT_SECONDS` et
`FRONTEND_BASE_URL`. Sans SMTP configuré, la route de réinitialisation répond
explicitement `503`; elle ne prétend pas avoir envoyé de mail.

Configure aussi les origines exactes du navigateur qui héberge Angular :

```powershell
$env:CORS_ALLOWED_ORIGINS = "http://localhost:4200,http://127.0.0.1:4200"
```

En production, déployer derrière HTTPS et définir `ENVIRONMENT=production` afin que
le cookie soit `Secure`. `AUTH_COOKIE_SECURE=true` permet de le forcer explicitement.
Ne désactive pas la validation d'origine des requêtes mutantes.

### Tests d'authentification

Depuis `skillpath-backend`, installer les dépendances de test puis exécuter les tests
API (la base SQLite utilisée par les tests est temporaire) :

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
python -m compileall -q app
python test_offline.py
```

### Démarrage complet en local

Dans un terminal, démarrer Fuseki avec le dataset `skillpath`. Dans un deuxième
terminal, depuis `skillpath-backend` :

```powershell
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Dans un troisième terminal, depuis `skillpath-frontend` :

```powershell
npm ci
npm start
```

Angular est servi par défaut sur `http://localhost:4200`. Pour compiler sans lancer
le serveur : `npm run build`. Configure d'abord SMTP si la réinitialisation du mot de
passe doit être utilisée.

# FlaskGPT

Assistant Flask avec réponses progressives, choix de spécialité, historique PostgreSQL, exports et résumés de documents.

## Démarrage

Prérequis : Python 3.11+, Node.js et Docker Desktop pour PostgreSQL local.
Installer les dépendances Python depuis le verrou Poetry, puis construire le CSS :

```powershell
python -m pip install poetry
python -m poetry install --no-root
npm ci
npm run build:css
```

Utiliser `.env.example` comme modèle pour un nouveau fichier `.env` en conservant les valeurs d'un fichier déjà existant.
Configurer `GROQ_API_KEY`, choisir un mot de passe PostgreSQL et reporter ce même mot de passe dans `DATABASE_URL`.
La connexion locale utilise le port `55432` par défaut. Encoder les caractères spéciaux du mot de passe dans l'URL.
Ne pas publier le fichier `.env`.

Démarrer la base et l'application :

```powershell
docker compose up -d --wait
python -m poetry run flask --app app run --port 5001
```

Ouvrir <http://127.0.0.1:5001>.

## Base de données

La variable `DATABASE_URL` active PostgreSQL via SQLAlchemy et Psycopg :

```dotenv
DATABASE_URL=postgresql+psycopg://flaskgpt:mot_de_passe@127.0.0.1:55432/flaskgpt
```

Les tables `conversations`, `messages` et `documents` sont créées automatiquement au démarrage.
Le volume Docker `postgres_data` conserve les données lors des redémarrages du service.
Sans `DATABASE_URL`, le stockage SQLite reste disponible dans `instance/chat.sqlite3` ; `DATABASE_PATH` permet d'en changer le chemin.
La configuration PostgreSQL repose sur le [dialecte SQLAlchemy pour Psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg).

Pour copier les anciennes conversations SQLite vers PostgreSQL, après avoir configuré `DATABASE_URL` :

```powershell
python -m poetry run flask --app app migrate-sqlite
# Autre fichier source : ajouter --source "chemin/ancienne-base.sqlite3"
```

La migration conserve la base source, les dates, les rôles et les documents déjà importés.
Elle ignore les conversations dont l'identifiant existe déjà dans la cible et peut être relancée.

Chaque conversation conserve sa spécialité, un titre tiré du premier message et ses messages avec leurs rôles.
Le message utilisateur est enregistré à l'envoi ; la réponse de l'assistant est enregistrée à la fin de sa génération.
Une réponse interrompue reste exclue de l'historique sauvegardé.

Le menu **Conversations enregistrées** permet de reprendre une discussion.
La conversation active est restaurée au rechargement si le navigateur autorise le stockage local.
**Nouvelle conversation** et le changement de spécialité ouvrent une discussion vierge en conservant les discussions précédentes en base.

L'application est prévue pour un usage local : l'historique est commun aux visiteurs de cette instance, sans gestion de comptes.

## Export des conversations

Choisir **CSV (.csv)** pour un tableur, **Markdown (.md)** pour un document lisible, ou **JSON (.json)** pour les données structurées.
**Exporter cette conversation** télécharge la discussion ouverte ; **Tout exporter** télécharge tout l'historique dans un seul fichier.
Les exports contiennent le titre, la spécialité, les dates et les messages dans leur ordre d'origine, avec le Markdown conservé.
Le format JSON inclut aussi l'identifiant de chaque conversation et la date de chaque message, ainsi qu'une version du format d'export.
Les contrôles d'export sont désactivés pendant une réponse ou le chargement d'une conversation.
Le CSV utilise UTF-8 avec BOM et le point-virgule comme séparateur, avec une ligne par message.
Il conserve les accents, les guillemets et les retours à la ligne ; les cellules pouvant être interprétées comme des formules reçoivent une apostrophe initiale.

## Import et résumé de fichiers

Choisir un fichier dans **Importer un fichier à résumer**, puis cliquer sur **Résumer le fichier**.
Formats : `.txt`, `.md`, `.csv`, `.pdf` et `.docx`.
Limites : 10 Mo, 60 000 caractères de texte extrait et 200 pages pour les PDF.
Les fichiers trop longs sont refusés avec une explication, sans troncature silencieuse.
Les PDF doivent contenir du texte sélectionnable et ne pas être protégés par mot de passe.
Les paragraphes et tableaux Word sont analysés ; les textes UTF-8, UTF-16 avec BOM et Windows-1252 sont acceptés.

Le texte extrait est transmis au modèle Groq configuré pour produire un résumé en français.
Le résumé rejoint la conversation ouverte, ou crée une nouvelle discussion si aucune n'est ouverte.
Le texte extrait est stocké séparément en base pour permettre les questions suivantes sur le même document ; le fichier binaire n'est pas conservé.
Les exports contiennent les messages et les résumés affichés, tandis que les documents sources restent dans la base.

## Vérifications

Les tests utilisent SQLite par défaut et simulent le modèle, sans appel à Groq :

```powershell
python -m poetry run python -m unittest discover -s tests -v
node --check static/js/script.js
npm run build:css
```

Pour lancer la même suite contre PostgreSQL, définir `TEST_DATABASE_URL` avec une base de test existante et dédiée dont le nom se termine par `_test`.
La suite recrée ses tables avant chaque test ; elle n'utilise pas la base applicative configurée dans `.env`.

# FlaskGPT

Assistant Flask avec réponses progressives, choix de spécialité, historique PostgreSQL.

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

## Tests

```powershell
python -m unittest discover -s tests -v
```

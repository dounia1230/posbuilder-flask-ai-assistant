#Importe le type Iterator, qui représente un objet fournissant des valeurs une par une.
from collections.abc import Iterator

# Permet de lire les variables d’environnement.
import os

# Importe la classe du client OpenAI.
from openai import OpenAI

# Permet de charger les variables du fichier .env.
from dotenv import load_dotenv

load_dotenv()

# Crée un client authentifié avec ta clé.
#client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# Utilise la bibliothèque OpenAI pour communiquer avec le serveur Groq.
client = OpenAI(api_key=os.getenv("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1")


#le module "flask" on importe la classe "Flask" qui permet de créer une application
from flask import Flask, render_template, request, Response

#créer l’application web Flask et la stocke dans la variable app
#__name__ : indique à Flask le module courant, ce qui l’aide à localiser notamment les dossiers templates et static.
app = Flask(__name__)

#on met un route en mentionnant la racine comme page d'accueil
@app.route('/')
#on crée une fonction, dans un premier temps -> elle affiche juste un message
def home():
    return render_template('index.html')


from flask import request, Response, jsonify

# Reçoit la conversation envoyée par JavaScript.
@app.route('/prompt', methods=['POST'])
def prompt():
    # Vérifie que la requête contient des données au format JSON.
    if not request.is_json:
        return jsonify(error="Le format JSON est requis."), 415

    # Lit le JSON ; retourne None si son contenu est invalide.
    data = request.get_json(silent=True)

    # Vérifie que le JSON représente un objet.
    if not isinstance(data, dict):
        return jsonify(error="Le JSON doit être un objet valide."), 400

    # Récupère les messages, ou None si la clé est absente.
    messages = data.get("messages")

    # Vérifie que les messages constituent une liste non vide.
    if not isinstance(messages, list) or not messages:
        return jsonify(error="'messages' doit être une liste non vide."), 400

    # Vérifie que chaque message est un texte non vide.
    if any(not isinstance(message, str) or not message.strip()
           for message in messages):
        return jsonify(error="Chaque message doit être un texte non vide."), 400

    # Transforme les messages en dictionnaires avec leurs rôles.
    conversation = build_conversation_dict(messages=messages)

    # Renvoie progressivement la réponse sous forme de texte brut.
    return Response(
        event_stream(conversation),
        content_type="text/plain; charset=utf-8"
    )


# Génère progressivement les fragments de texte de la réponse.
def event_stream(conversation: list[dict]) -> Iterator[str]:
    response = client.chat.completions.create(
        # model="gpt-3.5-turbo",
        model="openai/gpt-oss-20b",
        messages=conversation,
        stream=True
    )
    # Envoie la conversation au modèle et active la réception progressive.


    # Parcourt les fragments reçus depuis l’API.
    for chunk in response:
        # Ignore les fragments qui ne contiennent aucun choix.
        if not chunk.choices:
            continue

        # Récupère le texte du fragment, ou une chaîne vide.
        # Dans le SDK récent, delta est un objet : on utilise .content.
        text = chunk.choices[0].delta.content or ""

        # Transmet le texte à Flask, qui l’envoie au navigateur.
        if text:
            yield text

# Transforme les messages en une liste de dictionnaires contenant le rôle et le contenu.
# Les annotations indiquent une liste en entrée et une liste de dictionnaires en sortie.
def build_conversation_dict(messages: list) -> list[dict]:
    return [
        {
            # Attribue "user" aux indices pairs (0, 2, 4…)
            # et "assistant" aux indices impairs (1, 3, 5…).
            "role": "user" if i % 2 == 0 else "assistant",

            # Stocke le texte du message.
            "content": message
        }
        # Parcourt les messages avec leur indice i et leur contenu message.
        for i, message in enumerate(messages)
    ]

#démarrer le serveur lorsque tu lances directement le fichier
if __name__ == "__main__":
    app.run(debug=True)
    # # Transforme une seule fois les textes en messages avec leurs rôles.
    # conversation = build_conversation_dict(
    #     messages=[
    #         "Hello assistant",
    #         "Hello user",
    #         "Are you ok assistant"
    #     ]
    # )
    #
    # # Affiche les fragments à la suite, sans saut de ligne entre eux.
    # for text in event_stream(conversation):
    #     #print(text)
    #     print(text, end="", flush=True)
    #
    # # Termine la réponse par un saut de ligne.
    # print()


// Crée un nouveau bloc de message à partir du modèle HTML caché.
function createMessageElement() {
    // Récupère le conteneur qui affiche les messages de la conversation.
    const output = document.querySelector("#gpt-output");

    // Récupère le bloc HTML utilisé comme modèle.
    const template = document.querySelector("#chat-template");

    // Copie le modèle avec tous ses éléments enfants.
    const clone = template.cloneNode(true);

    // Retire l’identifiant du clone pour éviter les identifiants en double.
    clone.id = "";

    // Ajoute le nouveau bloc à la fin de la conversation.
    output.appendChild(clone);

    // Retire la classe Tailwind "hidden" pour rendre le bloc visible.
    clone.classList.remove("hidden");

    // Retourne l’élément qui recevra le texte du message.
    return clone.querySelector(".message");
}

// Ajoute un message à la conversation et retourne son élément HTML.
function appendMessage(message) {
    // Crée un bloc visible et récupère son élément ".message".
    const infoBlock = createMessageElement();

    //si _cloneAnswerBlock() retourne null
    // Vérifie que l’élément destiné au message existe.
    if (!infoBlock) {
        // Affiche une erreur dans la console du navigateur.
        console.error("Failed to create the information block");

        // Arrête la fonction en indiquant qu’aucun élément n’est disponible.
        return null;
    }

    // Insère le message comme du texte, sans l’interpréter comme du HTML.
    infoBlock.innerText = message;

    // Retourne l’élément pour pouvoir modifier son contenu ensuite.
    return infoBlock;
}

// Envoie le nouveau message ; Flask récupère l'historique en base de données.
async function fetchPromptResponse(prompt, conversationId, specialty) {
    // Envoie une requête à la route Flask "/prompt" et attend sa réponse initiale.
    const response = await fetch("/prompt", {
        // Utilise POST pour transmettre les données au serveur.
        method: "POST",

        // Indique que le corps de la requête contient du JSON.
        headers: {
            "Content-Type": "application/json",
        },

        body: JSON.stringify({
            messages: [prompt],
            conversation_id: conversationId,
            specialty,
        }),
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `La requête a échoué (${response.status}).`);
    }

    return response;
}

// Lit la réponse progressive et affiche le texte converti en HTML.
async function readResponseChunks(reader, gptOutput) {
    // Décode les octets reçus en texte UTF-8.
    const decoder = new TextDecoder("utf-8");

    // Crée le convertisseur Markdown vers HTML.
    const converter = new showdown.Converter();

    // Conserve le texte complet reçu jusqu’à présent.
    let text = "";

    try {
        while (true) {
            // Attend le prochain fragment.
            // done indique la fin du flux ; value contient les octets reçus.
            const { done, value } = await reader.read();

            // Quitte la boucle lorsque le flux est terminé.
            if (done) break;

            // Décode le fragment en conservant les caractères incomplets
            // pour les compléter lors de la réception suivante.
            text += decoder.decode(value, { stream: true });

            // Convertit le Markdown en HTML et sécurise le résultat.
            gptOutput.innerHTML = DOMPurify.sanitize(
                converter.makeHtml(text)
            );
        }

        // Termine le décodage des éventuels octets restants.
        text += decoder.decode();

        // Affiche le résultat final.
        gptOutput.innerHTML = DOMPurify.sanitize(
            converter.makeHtml(text)
        );
    } finally {
        // Libère le lecteur, même si une erreur survient.
        reader.releaseLock();
    }
}

// Attend que le HTML soit chargé avant d’exécuter ce code.
document.addEventListener("DOMContentLoaded", async () => {
    // Récupère le formulaire grâce à son identifiant.
    const form = document.querySelector("#prompt-form");

    // Récupère le bouton situé dans le formulaire.
    const button = form.querySelector("button");

    const newConversationButton = document.querySelector("#new-conversation");
    const specialtySelect = document.querySelector("#specialty");
    const savedConversations = document.querySelector("#saved-conversations");
    const exportFormat = document.querySelector("#export-format");
    const exportButton = document.querySelector("#export-conversation");
    const exportAllButton = document.querySelector("#export-all-conversations");
    const status = document.querySelector("#conversation-status");
    let activeConversationId = null;
    let busy = false;
    let hasSavedConversations = false;

    function updateExportControls() {
        exportFormat.disabled = busy;
        exportButton.disabled = busy || !activeConversationId;
        exportAllButton.disabled = busy || !hasSavedConversations;
    }

    function setActiveConversation(id) {
        activeConversationId = id;
        updateExportControls();
        // Seul l'identifiant est retenu dans le navigateur, les messages restent en base.
        try {
            if (id) localStorage.setItem("active-conversation", id);
            else localStorage.removeItem("active-conversation");
        } catch (error) {
            console.warn("La conversation ne peut pas être mémorisée dans ce navigateur.", error);
        }
    }

    function setBusy(value) {
        busy = value;
        button.disabled = busy;
        newConversationButton.disabled = busy;
        specialtySelect.disabled = busy;
        savedConversations.disabled = busy;
        updateExportControls();
    }

    async function refreshConversations() {
        const response = await fetch("/conversations");
        if (!response.ok) throw new Error("Impossible de charger les conversations enregistrées.");
        const data = await response.json();
        hasSavedConversations = data.conversations.length > 0;
        savedConversations.replaceChildren(new Option("Nouvelle conversation", ""));
        for (const conversation of data.conversations) {
            const specialty = Array.from(specialtySelect.options)
                .find(option => option.value === conversation.specialty)?.textContent || conversation.specialty;
            savedConversations.add(new Option(`${specialty} — ${conversation.title}`, conversation.id));
        }
        savedConversations.value = activeConversationId || "";
        updateExportControls();
    }

    async function downloadExport(allConversations) {
        if (busy || (allConversations ? !hasSavedConversations : !activeConversationId)) return;
        const format = exportFormat.value;
        const id = activeConversationId;
        const path = allConversations ? "/conversations/export" : `/conversations/${encodeURIComponent(id)}/export`;
        setBusy(true);
        status.textContent = "Préparation de l'export…";
        try {
            const response = await fetch(`${path}?format=${encodeURIComponent(format)}`);
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Impossible d'exporter les conversations.");
            }
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement("a");
            link.href = url;
            link.download = `${allConversations ? "conversations" : `conversation-${id}`}.${format}`;
            document.body.appendChild(link);
            try {
                link.click();
            } finally {
                link.remove();
                setTimeout(() => URL.revokeObjectURL(url), 1000);
            }
            status.textContent = "Export prêt : téléchargement lancé.";
        } catch (error) {
            status.textContent = `Erreur : ${error.message}`;
        } finally {
            setBusy(false);
        }
    }

    exportButton.addEventListener("click", () => downloadExport(false));
    exportAllButton.addEventListener("click", () => downloadExport(true));

    async function loadConversation(id) {
        const response = await fetch(`/conversations/${encodeURIComponent(id)}`);
        if (!response.ok) throw new Error("Impossible d'ouvrir cette conversation.");
        const conversation = await response.json();
        document.querySelector("#gpt-output").replaceChildren();
        const converter = new showdown.Converter();
        for (const message of conversation.messages) {
            const output = appendMessage(message.content);
            if (message.role === "assistant") {
                output.innerHTML = DOMPurify.sanitize(converter.makeHtml(message.content));
            }
        }
        specialtySelect.value = conversation.specialty;
        setActiveConversation(conversation.id);
        savedConversations.value = conversation.id;
        form.reset();
        status.textContent = "Conversation chargée. Vous pouvez la continuer.";
    }

    // Efface l'historique envoyé au modèle et prépare une nouvelle conversation.
    function resetConversation() {
        if (button.disabled) return;

        setActiveConversation(null);
        savedConversations.value = "";
        document.querySelector("#gpt-output").replaceChildren();
        form.reset();
        status.textContent = "Les messages seront enregistrés automatiquement.";
        form.elements.prompt.focus();
    }

    newConversationButton.addEventListener("click", resetConversation);
    specialtySelect.addEventListener("change", resetConversation);
    savedConversations.addEventListener("change", async () => {
        if (button.disabled) return;
        const id = savedConversations.value;
        if (!id) {
            resetConversation();
            return;
        }
        setBusy(true);
        status.textContent = "Chargement de la conversation…";
        try {
            await loadConversation(id);
        } catch (error) {
            savedConversations.value = activeConversationId || "";
            status.textContent = error.message;
        } finally {
            setBusy(false);
        }
    });

    async function displayResponse(message, fetchResponse) {
        appendMessage(message);
        setBusy(true);
        status.textContent = "Réponse en cours…";

        try {
            const response = await fetchResponse();
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Impossible de récupérer la réponse.");
            }
            setActiveConversation(response.headers.get("X-Conversation-ID"));
            const reader = response.body.getReader();

            // Crée un bloc vide destiné à recevoir la réponse de l’IA.
            const output = appendMessage("");

            // Lit et affiche progressivement les fragments de la réponse.
            await readResponseChunks(reader, output);
            status.textContent = "Conversation enregistrée.";
            return true;
        } catch (error) {
            status.textContent = `Erreur : ${error.message}`;
            console.error(error);
            return false;
        } finally {
            try {
                await refreshConversations();
            } catch (error) {
                status.textContent = error.message;
            }
            setBusy(false);
        }
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const prompt = form.elements.prompt.value.trim();
        if (!prompt || busy) return;
        form.reset();
        await displayResponse(prompt, () => fetchPromptResponse(prompt, activeConversationId, specialtySelect.value));
    });


    setBusy(true);
    try {
        await refreshConversations();
        let savedId = null;
        try {
            savedId = localStorage.getItem("active-conversation");
        } catch (error) {
            console.warn(error);
        }
        if (savedId && Array.from(savedConversations.options).some(option => option.value === savedId)) {
            await loadConversation(savedId);
        } else {
            setActiveConversation(null);
            status.textContent = "Les messages seront enregistrés automatiquement.";
        }
    } catch (error) {
        status.textContent = error.message;
    } finally {
        setBusy(false);
    }
});

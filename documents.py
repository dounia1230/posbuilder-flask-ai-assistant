"""Extraction du texte des fichiers importés, sans conserver les fichiers binaires."""

from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile

from docx import Document
from docx.table import Table
from pypdf import PdfReader

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARACTERS = 60_000
SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx"}


class DocumentError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def extract_document(upload):
    filename = PurePosixPath((upload.filename or "").replace("\\", "/")).name[:200]
    suffix = PurePosixPath(filename).suffix.lower()
    if not filename or suffix not in SUPPORTED_EXTENSIONS:
        raise DocumentError("Formats acceptés : TXT, Markdown, CSV, PDF et DOCX.", 415)
    data = upload.stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise DocumentError("Le fichier dépasse la limite de 10 Mo.", 413)
    if not data:
        raise DocumentError("Le fichier est vide.")

    try:
        if suffix == ".pdf":
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise DocumentError("Le PDF est protégé. Importez une copie sans mot de passe.")
            if len(reader.pages) > 200:
                raise DocumentError("Le PDF dépasse la limite de 200 pages.")
            parts = []
            size = 0
            for page in reader.pages:
                content = page.get_contents()
                if content is not None and len(content.get_data()) > 5 * 1024 * 1024:
                    raise DocumentError("Une page du PDF est trop volumineuse à analyser.")
                part = page.extract_text() or ""
                size += len(part) + 1
                if size > MAX_TEXT_CHARACTERS:
                    raise DocumentError("Le document dépasse 60 000 caractères. Importez un extrait plus court.")
                parts.append(part)
            text = "\n".join(parts)
        elif suffix == ".docx":
            with ZipFile(BytesIO(data)) as archive:
                if sum(info.file_size for info in archive.infolist()) > 40 * 1024 * 1024:
                    raise DocumentError("Le document Word est trop volumineux une fois décompressé.")
            document = Document(BytesIO(data))
            parts = []
            for block in document.iter_inner_content():
                if isinstance(block, Table):
                    parts.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
                else:
                    parts.append(block.text)
            text = "\n".join(parts)
        else:
            if data.startswith((b"\xff\xfe", b"\xfe\xff")):
                text = data.decode("utf-16")
            else:
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = data.decode("cp1252")
            if any(ord(character) < 32 and character not in "\n\r\t" for character in text):
                raise DocumentError("Le fichier ne contient pas du texte lisible.")
    except DocumentError:
        raise
    except Exception as error:
        raise DocumentError("Impossible de lire ce fichier. Vérifiez son format et son contenu.") from error

    text = text.replace("\x00", "").strip()
    if not text:
        raise DocumentError("Aucun texte trouvé. Pour un PDF scanné, importez une version avec du texte sélectionnable.")
    if len(text) > MAX_TEXT_CHARACTERS:
        raise DocumentError("Le document dépasse 60 000 caractères. Importez un extrait plus court.")
    return {"filename": filename, "content": text}

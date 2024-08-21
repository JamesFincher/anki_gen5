import os
from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional
import genanki
import uuid
import random
from tempfile import gettempdir

app = FastAPI(
    title="Anki Flashcard Generator API",
    description="A backend API for managing Anki flashcards and decks. This API allows users to create custom flashcard decks, upload media, and download generated Anki packages (.apkg files).",
    version="1.0.0",
    servers=[
        {"url": "https://anki-gen5.onrender.com", "description": "Production server"},
        {"url": "http://localhost:8000", "description": "Local development server"}
    ]
)

# Use a temporary directory for file operations
OUTPUT_FOLDER = os.environ.get('OUTPUT_FOLDER', gettempdir())
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

class CardTemplate(BaseModel):
    """
    Represents a card template in an Anki model.
    """
    name: str = Field(..., description="Name of the card template")
    qfmt: str = Field(..., description="Question format template")
    afmt: str = Field(..., description="Answer format template")

    class Config:
        schema_extra = {
            "example": {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "{{FrontSide}}<hr id='answer'>{{Back}}"
            }
        }

class ModelDefinition(BaseModel):
    """
    Defines the structure of an Anki model.
    """
    name: str = Field(..., description="Name of the model")
    fields: List[str] = Field(..., description="List of field names")
    templates: List[CardTemplate] = Field(..., description="List of card templates")
    css: Optional[str] = Field(default="", description="CSS styling for cards")

    class Config:
        schema_extra = {
            "example": {
                "name": "Basic Model",
                "fields": ["Front", "Back"],
                "templates": [
                    {
                        "name": "Card 1",
                        "qfmt": "{{Front}}",
                        "afmt": "{{FrontSide}}<hr id='answer'>{{Back}}"
                    }
                ],
                "css": ".card { font-family: arial; font-size: 20px; }"
            }
        }

class Note(BaseModel):
    """
    Represents a single Anki note.
    """
    fields: List[str] = Field(..., description="List of field values")
    tags: Optional[List[str]] = Field(default=[], description="List of tags for the note")
    guid: Optional[str] = Field(default=None, description="Custom GUID for the note")

    class Config:
        schema_extra = {
            "example": {
                "fields": ["What is the capital of France?", "Paris"],
                "tags": ["geography", "europe"],
                "guid": "unique_identifier_123"
            }
        }

class Deck(BaseModel):
    """
    Represents an Anki deck containing multiple notes.
    """
    name: str = Field(..., description="Name of the deck")
    description: Optional[str] = Field(default="", description="Description of the deck")
    notes: List[Note] = Field(..., description="List of notes in the deck")

    class Config:
        schema_extra = {
            "example": {
                "name": "Geography Deck",
                "description": "A deck for learning world geography",
                "notes": [
                    {
                        "fields": ["What is the capital of France?", "Paris"],
                        "tags": ["geography", "europe"]
                    }
                ]
            }
        }

class Package(BaseModel):
    """
    Represents a complete Anki package containing multiple decks and a model definition.
    """
    decks: List[Deck] = Field(..., description="List of decks in the package")
    model: ModelDefinition = Field(..., description="Model definition for the package")

class MediaUploadResponse(BaseModel):
    """
    Response model for media upload endpoint.
    """
    filename: str = Field(..., description="Name of the uploaded file")
    status: str = Field(..., description="Status of the upload operation")

class FlashcardGenerationResponse(BaseModel):
    """
    Response model for flashcard generation endpoint.
    """
    message: str = Field(..., description="Status message of the operation")
    download_url: str = Field(..., description="URL to download the generated .apkg file")

@app.post("/generate_flashcards/", 
          summary="Generate and download Anki flashcards",
          description="Generate Anki flashcards based on the provided package definition and return an .apkg file for download",
          response_model=FlashcardGenerationResponse)
async def generate_flashcards(package: Package) -> FlashcardGenerationResponse:
    """
    Generates an Anki package (.apkg file) based on the provided package definition.

    Args:
        package (Package): The package definition containing decks and model information.

    Returns:
        FlashcardGenerationResponse: A response containing the download URL of the generated .apkg file.

    Raises:
        HTTPException: If there's an error during package generation.
    """
    try:
        filename = f"flashcards_{uuid.uuid4().hex}.apkg"
        file_path = os.path.join(OUTPUT_FOLDER, filename)

        model = genanki.Model(
            model_id=random.randrange(1 << 30, 1 << 31),
            name=package.model.name,
            fields=[{'name': field} for field in package.model.fields],
            templates=[template.dict() for template in package.model.templates],
            css=package.model.css
        )

        genanki_decks = []
        for deck in package.decks:
            genanki_deck = genanki.Deck(
                deck_id=random.randrange(1 << 30, 1 << 31),
                name=deck.name,
                description=deck.description
            )
            for note in deck.notes:
                genanki_note = genanki.Note(
                    model=model,
                    fields=note.fields,
                    tags=note.tags,
                    guid=note.guid
                )
                genanki_deck.add_note(genanki_note)
            genanki_decks.append(genanki_deck)

        genanki.Package(genanki_decks).write_to_file(file_path)

        # Generate the full download URL
        base_url = "https://anki-gen5.onrender.com"  # Use the render URL
        download_url = f"{base_url}/download/{filename}"
        
        return FlashcardGenerationResponse(message="Flashcards generated successfully", download_url=download_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during flashcard generation: {str(e)}")

@app.get("/download/{filename}", 
         summary="Download the generated Anki flashcards file",
         description="Endpoint to download the generated .apkg file")
async def download_file(filename: str) -> FileResponse:
    """
    Provides the .apkg file for download based on the filename.

    Args:
        filename (str): The name of the file to be downloaded.

    Returns:
        FileResponse: The .apkg file for download.

    Raises:
        HTTPException: If the file does not exist.
    """
    file_path = os.path.join(OUTPUT_FOLDER, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path, 
        filename=filename, 
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@app.post("/upload_media/", 
          summary="Upload media file",
          description="Upload a media file to be included in the Anki package",
          response_model=MediaUploadResponse)
async def upload_media(file: UploadFile = File(...)) -> MediaUploadResponse:
    """
    Uploads a media file to be included in the Anki package.

    Args:
        file (UploadFile): The file to be uploaded.

    Returns:
        MediaUploadResponse: A response containing the filename and upload status.

    Raises:
        HTTPException: If there's an error during file upload.
    """
    try:
        file_path = os.path.join(OUTPUT_FOLDER, file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
        
        return MediaUploadResponse(filename=file.filename, status="File uploaded successfully")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", summary="Root endpoint", description="Returns a welcome message")
async def root():
    """
    Root endpoint that returns a welcome message.

    Returns:
        dict: A dictionary containing a welcome message.
    """
    return {"message": "Welcome to the Anki Flashcard Generator API"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
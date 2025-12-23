import os
import uuid
import time
from fastapi import FastAPI, Query, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
from dotenv import load_dotenv

# ================================
# Chargement des variables d'environnement
# ================================
load_dotenv()

API_KEY = os.getenv("API_KEY", "CHANGE_ME")
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

# Rate limit simple (par IP)
RATE_LIMIT = 5        # requêtes
RATE_WINDOW = 60      # secondes
clients = {}

# ================================
# Initialisation FastAPI
# ================================
app = FastAPI(
    title="API Téléchargement Vidéos",
    description="API sécurisée de téléchargement vidéo (yt-dlp)",
    version="1.0.0"
)

# ================================
# Configuration CORS
# ================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ================================
# Sécurité : vérification clé API
# ================================
def verify_api_key(request: Request):
    key = request.headers.get("X-API-KEY")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Clé API invalide")

# ================================
# Sécurité : Rate limiting simple
# ================================
def rate_limit(request: Request):
    ip = request.client.host
    now = time.time()

    if ip not in clients:
        clients[ip] = []

    # Nettoyage des anciennes requêtes
    clients[ip] = [t for t in clients[ip] if now - t < RATE_WINDOW]

    if len(clients[ip]) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Trop de requêtes. Réessayez plus tard."
        )

    clients[ip].append(now)

# ================================
# Endpoint téléchargement
# ================================
@app.get("/download")
async def download_video(
    request: Request,
    url: str = Query(..., description="URL de la vidéo"),
    format: str = Query("best", description="Format yt-dlp"),
    _: None = Depends(verify_api_key)
):
    rate_limit(request)

    try:
        # Lecture des métadonnées
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "video") \
                        .replace("/", "-") \
                        .replace("\\", "-")
            filename = f"{title}.mp4"

        # Fichier temporaire unique
        uid = uuid.uuid4().hex[:8]
        output_template = f"/tmp/{uid}.%(ext)s"

        ydl_opts = {
            "format": format,
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "quiet": True,
        }

        # Téléchargement
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Recherche du fichier généré
        file_path = next(
            (os.path.join("/tmp", f) for f in os.listdir("/tmp") if f.startswith(uid)),
            None
        )

        if not file_path or not os.path.exists(file_path):
            raise HTTPException(status_code=500, detail="Échec du téléchargement")

        # Streaming + nettoyage
        def stream_file():
            with open(file_path, "rb") as f:
                yield from f
            os.remove(file_path)

        return StreamingResponse(
            stream_file(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ================================
# Endpoint test
# ================================
@app.get("/")
async def root():
    return {
        "message": "API de téléchargement vidéo opérationnelle",
        "usage": "/download?url=<video_url>&format=best",
    }

# ================================
# Lancement local
# ================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

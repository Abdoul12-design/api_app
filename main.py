import os
import uuid
import time
from fastapi import FastAPI, Query, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
from dotenv import load_dotenv

# =====================================================
# Chargement des variables d'environnement
# =====================================================
load_dotenv()

API_KEY = os.getenv("API_KEY", None)           # Optionnelle
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

# =====================================================
# Rate limiting simple (par IP)
# =====================================================
RATE_LIMIT = 5          # requêtes max
RATE_WINDOW = 60        # secondes
clients = {}

# =====================================================
# Initialisation FastAPI
# =====================================================
app = FastAPI(
    title="API Téléchargement Vidéos",
    description="API sécurisée basée sur yt-dlp (vidéos & playlists)",
    version="1.1.0"
)

# =====================================================
# Configuration CORS
# =====================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# =====================================================
# Sécurité : vérification clé API (optionnelle)
# =====================================================
def verify_api_key(request: Request):
    if API_KEY:
        key = request.headers.get("X-API-KEY")
        if key != API_KEY:
            raise HTTPException(status_code=401, detail="Clé API invalide")

# =====================================================
# Sécurité : Rate limiting simple
# =====================================================
def rate_limit(request: Request):
    ip = request.client.host
    now = time.time()

    if ip not in clients:
        clients[ip] = []

    # Nettoyage
    clients[ip] = [t for t in clients[ip] if now - t < RATE_WINDOW]

    if len(clients[ip]) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Trop de requêtes, réessayez plus tard."
        )

    clients[ip].append(now)

# =====================================================
# 📥 Téléchargement vidéo
# =====================================================
@app.get("/download")
async def download_video(
    request: Request,
    url: str = Query(..., description="URL de la vidéo"),
    format: str = Query("best", description="Format yt-dlp"),
    _: None = Depends(verify_api_key)
):
    rate_limit(request)

    try:
        # Métadonnées
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "video") \
                .replace("/", "-").replace("\\", "-")
            filename = f"{title}.mp4"

        uid = uuid.uuid4().hex[:8]
        output_template = f"/tmp/{uid}.%(ext)s"

        ydl_opts = {
            "format": format,
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "quiet": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        file_path = next(
            (os.path.join("/tmp", f) for f in os.listdir("/tmp") if f.startswith(uid)),
            None
        )

        if not file_path or not os.path.exists(file_path):
            raise HTTPException(status_code=500, detail="Téléchargement échoué")

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

# =====================================================
# ℹ️ Infos vidéo
# =====================================================
@app.get("/info")
async def video_info(url: str = Query(...)):
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)

        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
            "formats": [
                {
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "height": f.get("height"),
                }
                for f in info.get("formats", [])
                if f.get("height")
            ],
        }

    except Exception as e:
        return {"error": str(e)}

# =====================================================
# 📂 Infos playlist (NOUVEAU)
# =====================================================
@app.get("/playlist/info")
async def playlist_info(url: str = Query(...)):
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)

        if 'entries' not in info:
            raise HTTPException(status_code=400, detail="Ce n'est pas une playlist")

        videos = []
        for entry in info['entries']:
            if not entry:
                continue
            videos.append({
                "id": entry.get("id"),
                "title": entry.get("title"),
                "thumbnail": entry.get("thumbnail"),
                "duration": entry.get("duration"),
                "url": entry.get("webpage_url"),
            })

        return {
            "playlist_title": info.get("title"),
            "count": len(videos),
            "videos": videos
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================
# 🏠 Endpoint test
# =====================================================
@app.get("/")
async def root():
    return {
        "message": "API de téléchargement vidéo opérationnelle",
        "usage": {
            "video": "/download?url=<video_url>&format=best",
            "info": "/info?url=<video_url>",
            "playlist": "/playlist/info?url=<playlist_url>"
        }
    }

# =====================================================
# Lancement local
# =====================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


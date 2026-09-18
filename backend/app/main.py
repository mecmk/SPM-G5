from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.config import settings
from app.venues.router import router as venues_router

app = FastAPI(title="ConnectSphere API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # the session cookie must travel with cross-origin requests
    allow_methods=["*"],
    allow_headers=["*"],
)

# One router per feature area (see AGENTS.md "Repository Structure").
app.include_router(auth_router)
app.include_router(venues_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

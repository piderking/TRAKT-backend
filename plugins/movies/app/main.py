import time
from typing import List, Optional
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="Trakt Plugin - Movies & Shows Microservice",
    description="Microservice providing watch progress, up-next recommendations, and metadata for Movies and TV Shows",
    version="1.0.0"
)

class NextEpisode(BaseModel):
    season: int
    number: int
    title: str

class MediaItem(BaseModel):
    id: str
    title: str
    type: str = Field(..., description="'movie' or 'show'")
    year: int
    progress_pct: float
    runtime_min: int
    rating: float
    poster: str
    backdrop: str
    genre: List[str]
    next_episode: Optional[NextEpisode] = None
    last_watched: str

class UpNextResponse(BaseModel):
    plugin: str = "movies-v1"
    timestamp: float
    count: int
    up_next: List[MediaItem]

@app.get("/health")
async def health_check():
    """Health check for movie plugin."""
    return {
        "status": "ok",
        "plugin": "movies-microservice",
        "version": "1.0.0",
        "timestamp": time.time()
    }

@app.get("/up-next", response_model=UpNextResponse)
async def get_up_next_watchlist():
    """Return structured watch history & up-next items."""
    sample_data: List[MediaItem] = [
        MediaItem(
            id="m-101",
            title="Dune: Part Two",
            type="movie",
            year=2024,
            progress_pct=0.0,
            runtime_min=166,
            rating=8.6,
            poster="https://images.unsplash.com/photo-1534447677768-be436bb09401?w=400&q=80",
            backdrop="https://images.unsplash.com/photo-1534447677768-be436bb09401?w=1200&q=80",
            genre=["Sci-Fi", "Adventure"],
            next_episode=None,
            last_watched="2026-07-28T20:15:00Z"
        ),
        MediaItem(
            id="s-202",
            title="Severance",
            type="show",
            year=2022,
            progress_pct=88.5,
            runtime_min=55,
            rating=8.7,
            poster="https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=400&q=80",
            backdrop="https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=1200&q=80",
            genre=["Sci-Fi", "Mystery", "Thriller"],
            next_episode=NextEpisode(season=2, number=1, title="Hello Ms. Cobel"),
            last_watched="2026-08-01T14:30:00Z"
        ),
        MediaItem(
            id="s-303",
            title="The Bear",
            type="show",
            year=2022,
            progress_pct=40.0,
            runtime_min=32,
            rating=8.6,
            poster="https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=400&q=80",
            backdrop="https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=1200&q=80",
            genre=["Drama", "Comedy"],
            next_episode=NextEpisode(season=3, number=4, title="Violet"),
            last_watched="2026-07-30T22:10:00Z"
        ),
        MediaItem(
            id="m-104",
            title="Oppenheimer",
            type="movie",
            year=2023,
            progress_pct=100.0,
            runtime_min=180,
            rating=8.9,
            poster="https://images.unsplash.com/photo-1440404653325-ab127d49abc1?w=400&q=80",
            backdrop="https://images.unsplash.com/photo-1440404653325-ab127d49abc1?w=1200&q=80",
            genre=["Biography", "Drama", "History"],
            next_episode=None,
            last_watched="2026-07-25T19:00:00Z"
        ),
        MediaItem(
            id="s-505",
            title="Shogun",
            type="show",
            year=2024,
            progress_pct=60.0,
            runtime_min=60,
            rating=8.8,
            poster="https://images.unsplash.com/photo-1578632767115-351597cf2477?w=400&q=80",
            backdrop="https://images.unsplash.com/photo-1578632767115-351597cf2477?w=1200&q=80",
            genre=["Action", "Adventure", "Drama"],
            next_episode=NextEpisode(season=1, number=7, title="A Stick of Time"),
            last_watched="2026-07-31T21:45:00Z"
        )
    ]

    return UpNextResponse(
        plugin="movies-v1",
        timestamp=time.time(),
        count=len(sample_data),
        up_next=sample_data
    )

# TRAKT Core Backend Gateway & Microservice Ecosystem (TRAKT-backend)

The core micro-kernel backend service for the Trakt Modular Ecosystem featuring FastAPI, a Tiered Storage Engine (Redis warm cache + PostgreSQL cold storage), Trakt OAuth/Device Auth, and decoupled microservices.

## Architecture

- **Core Gateway (`app/main.py`)**: Handles device authentication flow, proxies requests to domain plugins, and exposes status APIs.
- **Tiered Storage Engine (`app/core/storage.py`)**: Sub-millisecond reads via Redis warm tier for hot objects ($\le 100\text{KB}$) and persistent PostgreSQL cold storage for payloads $>100\text{KB}$ stored with lightweight pointer references.
- **Microservices (`plugins/movies/`)**: Decoupled domain service endpoints (`/up-next`).
- **Test Suite (`tests/`)**: Automated pytest suite for storage engine and gateway endpoints.

## Local Development & Docker Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Run with Docker Compose:
   ```bash
   docker-compose up --build
   ```

3. Run Pytest Suite:
   ```bash
   python3 -m pytest tests
   ```

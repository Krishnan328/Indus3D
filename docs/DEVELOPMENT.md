# Indus3D — Developer Guide

Welcome to Indus3D development! This document provides instructions for setting up your local environment, running tests, and understanding the codebase architecture.

---

## 🛠️ Environment Setup

### 1. Python Virtual Environment
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

---

## 🧪 Running Tests

Indus3D uses `pytest` for all backend unit and integration tests.
```bash
cd backend
pytest tests/ -v
```

---

## 🗄️ Database Migrations

Indus3D manages its SQLite schema through lightweight, versioned Python migrations located in `backend/db/migrations/`:
- To run pending migrations:
  ```bash
  cd backend
  python -m db.migrator
  ```
- Each migration is transactional and tracked in the `schema_migrations` table.

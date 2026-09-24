# CareerCare

CareerCare is a job discovery and application tracking platform focused on the Australian graduate and internship market.

The project is being built to reduce the amount of manual work involved in finding suitable roles, particularly for international students who need to consider factors such as visa eligibility, working rights, sponsorship requirements, and graduate program restrictions.

> **Current status:** Early development — Day 1 focused on establishing the backend architecture and job discovery pipeline.

## Day 1: Backend Foundation

The first development milestone focused on building the core backend services required to collect job listings, evaluate eligibility, and manage application data.

### Database Models

Created the initial SQLAlchemy models in `app/models.py` for storing:

* User profiles
* Internship and graduate job listings
* Application records and statuses
* Resume profiles
* Job source information

The models are designed to work with SQLite during local development while remaining compatible with PostgreSQL for future deployment.

### Eligibility Engine

Implemented the first version of the eligibility logic in `app/eligibility.py`.

The goal of this module is to determine whether a role is worth showing to a user based on available evidence from the job listing and the user's profile.

Initial checks include:

* Visa requirements
* Australian work-rights requirements
* Citizenship or permanent residency restrictions
* Sponsorship information
* Employer eligibility conditions

The eligibility system is intentionally separated from the scraping layer so the rules can evolve independently as the project grows.

### Job Discovery

Built the initial discovery pipeline across:

```text
app/discovery.py
app/scraper.py
```

The discovery layer is responsible for retrieving job listings from external sources, parsing them into a consistent internal format, and preparing them for storage and eligibility evaluation.

The first implementation includes support for:

* Live job listing retrieval
* SmartRecruiters job data
* HTML parsing
* API-based sources
* Source health tracking
* Normalisation of job listing data

This provides the foundation for adding additional job boards and employer career pages without changing the rest of the application.

### API

Set up the initial FastAPI router structure:

```text
app/routers/
├── admin.py
└── internships.py
```

These endpoints provide the starting point for managing job listings and exposing internship data to a future frontend.

### Configuration and Database Setup

Added the supporting infrastructure for running the backend locally:

```text
app/config.py
app/database.py
```

This includes environment-based configuration, database session management, and migration utilities.

Sensitive configuration is kept outside the source code so deployment credentials and environment-specific values can be managed safely.

## Tech Stack

| Area                 | Technology            |
| -------------------- | --------------------- |
| API                  | FastAPI               |
| Language             | Python                |
| ORM                  | SQLAlchemy            |
| Validation           | Pydantic              |
| HTTP Client          | HTTPX                 |
| HTML Parsing         | BeautifulSoup         |
| Development Database | SQLite                |
| Production Database  | PostgreSQL compatible |

## Project Structure

```text
CareerCare/
│
├── app/
│   ├── routers/
│   │   ├── admin.py
│   │   └── internships.py
│   │
│   ├── config.py
│   ├── database.py
│   ├── discovery.py
│   ├── eligibility.py
│   ├── models.py
│   ├── schemas.py
│   └── scraper.py
│
├── .env.example
├── requirements.txt
└── README.md
```

> The project structure will continue to change as the API, discovery pipeline, and frontend are developed.

## Local Development

### Requirements

* Python 3.10+
* pip
* Git

### 1. Clone the repository

```bash
git clone https://github.com/Shekharsainju/Shekharsainju-CareerCare.git
cd Shekharsainju-CareerCare
```

### 2. Create a virtual environment

**Windows**

```bash
python -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a local `.env` file using `.env.example` as a reference.

```bash
cp .env.example .env
```

Update the required values for your local environment.

### 5. Start the API

```bash
uvicorn app.main:app --reload
```

The development server should then be available at:

```text
http://127.0.0.1:8000
```

FastAPI's interactive API documentation is available at:

```text
http://127.0.0.1:8000/docs
```

## Current Architecture

The backend currently follows this general flow:

```text
External Job Sources
        │
        ▼
 Scraper / API Connectors
        │
        ▼
  Discovery Pipeline
        │
        ▼
 Normalised Job Data
        │
        ├────► Eligibility Engine
        │
        ▼
     Database
        │
        ▼
    FastAPI API
```

Keeping discovery, eligibility, persistence, and API logic separate should make it easier to add new job sources and eligibility rules without tightly coupling the system.

## Next Steps

The next development milestones are focused on:

* Expanding job source integrations
* Improving duplicate job detection
* Strengthening eligibility rules
* Adding search and filtering
* Building application tracking workflows
* Connecting the backend to a frontend
* Adding automated tests
* Improving logging and error handling

## Project Status

CareerCare is currently under active development.

The codebase is being developed incrementally, with each milestone focusing on a working part of the overall system rather than attempting to build the entire platform at once.

---

**Day 1:** Core backend architecture, database models, eligibility rules, discovery pipeline, and initial API structure.
## Project Structure
```text
CareerCare/
│
├── app/
│   ├── routers/
│   │   ├── admin.py
│   │   └── internships.py
│   │
│   ├── config.py
│   ├── database.py
│   ├── discovery.py
│   ├── eligibility.py
│   ├── models.py
│   ├── schemas.py
│   └── scraper.py
│
├── .env.example
├── requirements.txt
└── README.md

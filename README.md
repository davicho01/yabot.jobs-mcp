# Yabot Jobs MCP server

A remote [MCP](https://modelcontextprotocol.io) server that lets an MCP
client (Claude Desktop, Claude Code, etc.) search jobs, apply to one, score
your resume against a job, and upload an HTML tailored resume / cover
letter you've drafted — all against your own Yabot Jobs account.

It's a thin process: every tool call is an HTTP request to the FastAPI
backend (`main.py`), authenticated with a short-lived personal access token
minted for that connection via OAuth. It never touches the database
directly.

## 1. Install dependencies

From the repo root, into the existing venv (or a separate one — this
package only needs `mcp` and `httpx`):

```bash
.venv/bin/pip install -r requirements.txt
```

## 2. Start the backend and frontend

The MCP server calls the API (defaults to `http://localhost:8000`), and the
OAuth consent screen lives on the web frontend (defaults to
`http://localhost:3000`) — both need to be running and reachable:

```bash
# in yabot.jobs-backend/
.venv/bin/python main.py

# in yabot.jobs-frontend/
npm run dev
```

## 3. Configure and run this server

```bash
YABOT_API_BASE_URL=http://localhost:8000 \
YABOT_FRONTEND_BASE_URL=http://localhost:3000 \
YABOT_MCP_PUBLIC_URL=http://localhost:8080 \
.venv/bin/python server.py
```

(Or put these in this repo's `.env` — `server.py` loads it automatically
via `python-dotenv`.) `YABOT_MCP_PUBLIC_URL` must be this server's own
publicly reachable URL once deployed (its OAuth issuer identity) —
`http://localhost:8080` only works for local testing.

## 4. Connect it to Claude

No token to mint or paste — Claude does OAuth dynamic client registration
and a browser-based login automatically the first time it connects,
reusing the backend's existing magic-link login (see
`app/services/auth.py`/`app/api/routes/oauth.py` in `yabot.jobs-backend`
and `OAuthAuthorizePage.tsx` in `yabot.jobs-frontend` for the consent
screen).

### Claude Code

```bash
claude mcp add --transport http yabot-jobs http://localhost:8080/mcp
```

### Claude Desktop

Add to your `claude_desktop_config.json` (Settings → Developer → Edit
Config):

```json
{
  "mcpServers": {
    "yabot-jobs": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

Restart Claude Desktop after saving. On first use, Claude opens a browser
tab pointed at the frontend's consent screen; log in (or you're already
logged in) and click Approve. In production, use this server's real public
HTTPS URL instead of `localhost`.

### Fallback: minting a token by hand

`create_token.py` still works standalone against the backend (drives the
magic-link login, then `POST /auth/tokens`) for scripts or CI that want a
long-lived personal access token instead of going through OAuth — it's
unrelated to how Claude itself connects to this server now.

## Tools

| Tool | What it does |
|---|---|
| `search_jobs` | Search known job postings by title keyword / location |
| `list_job_locations` | List distinct locations known across all job postings |
| `get_job` | Fetch one job's full detail by `url_id` |
| `submit_job_url` | Add a new job by URL (queues an extraction scan) |
| `rescan_job` | Force a fresh extraction scan of an existing job posting |
| `apply_to_job` | Create + mark an application as `applied`, by job URL |
| `list_applications` | List your tracked applications and their latest artifacts |
| `update_application` | Update an application's status/notes/archived flag |
| `delete_application` | Delete a tracked application |
| `get_main_resume` | Fetch your main resume, including its extracted text |
| `evaluate_resume` | Score your main resume against a job posting |
| `get_resume_evaluation` | Fetch the latest score for a job posting |
| `upload_resume_evaluation` | Store a fit evaluation you computed yourself (rubric baked into the tool description), skipping the backend's LLM call |
| `upload_tailored_resume_evaluation` | Store a fit evaluation of a specific tailored resume you computed yourself, skipping the backend's LLM call |
| `upload_tailored_resume` | Upload a structured tailored resume for a job (rendered to .docx) |
| `upload_cover_letter` | Upload a structured cover letter for a job (rendered to .docx) |

`upload_tailored_resume` / `upload_cover_letter` take structured content,
not markup — no HTML/Markdown. Tailored resumes: `summary` (string) plus
`sections` (a list of `{heading, bullets}` objects). Cover letters:
`greeting`, `body_paragraphs` (a list of strings), `closing`. This matches
the shape the backend's own LLM generates and the frontend already
expects (`TailoredResume`/`CoverLetter.content` in the frontend's
`src/api/types.ts`) — see `app/services/resume_renderer.py` for how it's
rendered.

## Deploying to Cloud Run

This repo ships a `Dockerfile` and a `.github/workflows/deploy.yml` that
builds the image, pushes it to Artifact Registry, and deploys it to Cloud
Run on every push to `main` (or manually via "Run workflow").

Deploy target: project `yabotjobs`, region `us-central1`, service
`yabot-jobs-mcp`.

One-time setup (creates the Artifact Registry repo, a dedicated deploy
service account, and Workload Identity Federation so GitHub Actions never
needs a stored key):

```bash
gcloud auth login
GITHUB_REPO=davicho01/yabot.jobs-mcp ./deploy/setup-gcp.sh
```

It prints the two values to add as **GitHub Actions secrets**:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

And three **GitHub Actions variables** (Settings → Secrets and variables →
Actions → Variables) — these become the container's env vars, so use real
production URLs, not localhost:

- `YABOT_API_BASE_URL` — the deployed backend's URL
- `YABOT_FRONTEND_BASE_URL` — the deployed frontend's URL
- `YABOT_MCP_PUBLIC_URL` — this service's own public Cloud Run URL (fill
  this in after the first deploy, then re-run the workflow so the OAuth
  issuer identity matches)

Once the secrets and variables are set, push to `main` to deploy.

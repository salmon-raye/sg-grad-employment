# SG Graduate Employment Explorer

An interactive dashboard for exploring graduate employment outcomes across Singapore's universities.

Built as a fully static site — no server, no database. All data is pre-processed into JSON at build time and served via GitHub Pages.

**[View live site →](https://salmon-raye.github.io/sg_grad_unemployment)**

---

## Data source

[Graduate Employment Survey — NTU, NUS, SIT, SMU, SUSS & SUTD](https://data.gov.sg/datasets/d_3c55210de27fcccda2ed0c63fdd2b352/view)

The Graduate Employment Survey (GES) is jointly conducted by the six universities annually, surveying graduates approximately six months after their final examinations. It is published by the Ministry of Education, Singapore. 

---

## Project structure

```
.
├── build.py                        # data pipeline — CSV → JSON
├── GraduateEmployment...csv        # raw source data
├── pyproject.toml                  # uv project config
└── docs/                           # everything served by GitHub Pages
    ├── index.html                  # the entire frontend (single file)
    └── data/
        ├── metadata.json           # universities, schools, degrees for dropdowns
        └── courses/
            └── *.json              # one file per degree, all years of data
```

---

## Running locally

**Prerequisites:** [uv](https://docs.astral.sh/uv/getting-started/installation/)

```bash
# 1. Clone the repo
git clone https://github.com/salmon_raye/sg_grad_unemployment.git
cd sg_grad_unemployment

# 2. Install dependencies
uv sync

# 3. Run the data build
uv run build.py

# 4. Open docs/index.html in VS Code and use Live Server to preview
```

The build script reads the CSV, cleans and deduplicates degree names, removes years with no data, and writes all JSON files into `docs/data/`.

## Updating data

When a new year's GES data is released:

1. Download new CSV file from source and replace the CSV file
2. Run `uv run build.py`
3. Commit and push — GitHub Pages deploys automatically

---

## Deploying to GitHub Pages

1. Push the repo to GitHub
2. Go to **Settings → Pages**
3. Set source to **Deploy from branch**, branch `main`, folder `/docs`
4. Your site will be live at `https://YOUR_USERNAME.github.io/YOUR_REPO`

To use a custom domain, add a `CNAME` file inside `docs/` containing your domain name, then configure your DNS to point to GitHub Pages.

---

## Tech stack

| Layer | What |
|---|---|
| Data pipeline | Python, pandas |
| Package manager | uv |
| Frontend | Vanilla HTML/CSS/JS |
| Charts | Chart.js |
| Hosting | GitHub Pages (free) |
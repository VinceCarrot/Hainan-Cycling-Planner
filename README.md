# Hainan Cycling Planner

A local-first cycling route and attraction planner for Hainan. The project is
being built in stages; attraction experiences and photos are only added with
traceable sources and explicit usage-rights metadata.

## Requirements

- Conda
- Python 3.11

Create and activate the project environment:

```powershell
conda env create -f environment.yml
conda activate cycling
python -m pip install -r requirements.txt
```

Run the development server:

```powershell
python app.py
```

Open <http://127.0.0.1:5000>. The single-page UI has a left sidebar that
switches between seven pages by URL hash: 环岛地图 (map), 景点库 (approved
library), 待审核景点 (candidate review), 行程规划 (itinerary), 住宿与补给
(lodging and resupply), Garmin 导出 (export), and 设置与假设 (settings and
assumptions). Only the two catalog pages load data: the review page lists
researched candidates with their locally stored experience notes and source
links, and the library page lists approved attractions (currently none). The
other pages are placeholders describing planned functionality. Each candidate
on the review page has a **通过审核** button, which marks it `approved` and moves
it to the library, and a **删除** button, which permanently removes the record
from `data/attractions.json` after confirmation. There is no undo; keep the
catalog under version control or back it up before a review session. Editing
candidate content in the UI is not yet supported.
The catalog currently contains 128 candidates in the single canonical file
`data/attractions.json`. Some candidates are small coastal landmarks or
viewpoints; many still need independent sources or verified coordinates. Any
image without a local file is unavailable offline, even when its source is
openly licensed. Catalog records and the UI list follow the Haikou-start,
counterclockwise regional route; stops within a region retain their recorded
order unless a more precise sequence is supported by reliable route evidence.

Run tests:

```powershell
pytest
```

## Project layout

```text
app.py                     Development entry point
hainan_cycling/            Application package
  catalog/                 Attraction data model and repository
  web/                     HTTP routes and web-specific behavior
data/                      Human-readable local catalog data
docs/                      Requirements, architecture, and research rules
static/                    CSS, JavaScript, and browser assets
templates/                 Jinja templates
tests/                     Automated tests
```

## Data and sourcing

The catalog distinguishes discovery candidates from user-approved entries.
Each experience claim and image must be traceable to a source, and image
downloads are limited to material explicitly authorized for reuse or uploaded
by the user. See [docs/attraction-research.md](docs/attraction-research.md).

## Reference

The directory separation is informed by the structure of
[Family-Accounting-Web-UI](https://github.com/VinceCarrot/Family-Accounting-Web-UI)
(Flask entry point, templates, static assets, and separated application
modules). Its business logic, code, and visual design are not reused.

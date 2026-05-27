# Contributing to LawPrep

Thanks for wanting to help! Some easy on-ramps:

## Reporting a wrong answer

Open an issue with:
- Subject and topic
- Exact question text
- The wrong option that's currently marked correct
- The correct option, and a source if you have one

## Adding lessons

Lessons live in the SQLite database (`app/lawprep.db`). The cleanest way
to add or change content is to open the DB in [DB Browser for SQLite](https://sqlitebrowser.org/),
edit rows in the `lessons` table, save, and commit the updated `lawprep.db`.

For bulk changes, please open an issue first so we can coordinate.

## Code style

- Python: black-formatted, 4-space indent.
- Templates: keep the existing Jinja conventions.
- Don't introduce heavy frontend frameworks — the portal is intentionally
  vanilla HTML + a sprinkle of JS so anyone can read it.

## Don't commit

- `.env`, API keys, or any secrets
- Your own `lawprep.db` if it contains private study progress (sessions,
  bookmarks, scores). Re-clone a fresh copy before opening a PR.

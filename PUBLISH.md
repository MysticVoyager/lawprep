# Publishing LawPrep to GitHub

This file is for **you** (the maintainer). Delete it before you share the
repo widely, or leave it in — it's harmless.

There's a partially-initialized `.git/` folder in this directory from the
packaging step. **Delete it first**, then run the commands below from a
fresh Terminal on your Mac.

---

## 1. Reset the git state

```bash
cd "/Users/amit/Desktop/Law Books/lawprep-release"
rm -rf .git
```

## 2. Initialise the repo properly

```bash
git init -b main
git add .
git status            # sanity-check what's about to be committed
git -c user.email="toamitrajput@gmail.com" \
    -c user.name="Amit Rajput" \
    commit -m "Initial release: LawPrep — MH-CET Law 2027 study portal"
```

Make sure `.env` is **not** in the `git status` output. (It won't be — the
`.gitignore` covers it — but always look.)

## 3. Create the GitHub repo and push

### Option A — using the GitHub CLI (recommended)

If you don't already have `gh`:

```bash
brew install gh        # macOS via Homebrew
gh auth login          # follow prompts; choose HTTPS + browser auth
```

Then create the repo and push in one shot:

```bash
gh repo create lawprep \
    --public \
    --source=. \
    --remote=origin \
    --description "Free open-source MH-CET Law 2027 (3-Year LLB) study portal — lessons, MCQs, mock tests." \
    --push
```

Done. Your repo is now live at `https://github.com/<your-username>/lawprep`.

### Option B — using the GitHub website

1. Go to <https://github.com/new>.
2. Name it `lawprep`. Set visibility to **Public**. Leave "Initialize this
   repository" **unchecked**.
3. Click "Create repository". Copy the HTTPS URL it shows you.
4. Back in your Terminal:

   ```bash
   git remote add origin https://github.com/<your-username>/lawprep.git
   git push -u origin main
   ```

## 4. After the first push — polish

On the GitHub repo page:

- Add a description and tagline (top right "About" panel).
- Add topics: `mhcet`, `law`, `llb`, `flask`, `education`, `india`, `exam-prep`.
- Pin the repo on your profile if you want it visible.
- Replace `<your-username>` in `README.md` with your actual GitHub handle,
  then commit and push.

## 5. Rotate the keys that were in your old `.env`

The original `portal/.env` had real API keys in it. Even though they were
never committed to this release, treat them as compromised because they
existed in plaintext on disk for a while:

- Revoke the old **Gemini** key in <https://aistudio.google.com/app/apikey>
- Revoke the old **ElevenLabs** key in <https://elevenlabs.io/app/settings/api-keys>
- Issue new keys, drop them in your **local** `lawprep-release/.env`
  (created from `.env.example`), and never commit that file.

## 6. Share it

Suggested channels for LLB aspirants:

- Reddit: r/LawSchoolIndia, r/IndianEducation, r/MaharashtraLaw
- Telegram/WhatsApp MH-CET prep groups
- Your law college's student forum
- Quora / Twitter under the `#MHCETLaw` tag

That's it — good luck, and hope it helps a lot of students.

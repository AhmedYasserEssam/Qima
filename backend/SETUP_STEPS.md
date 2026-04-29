# Qima Environment Setup

This guide is for all team members to set up the project locally.

## Project structure used in this setup

This setup assumes the repository contains:

- `backend/requirements.txt`
- `backend/requirements-dev.txt`
- `backend/.env.example`


---

## 1) Clone the repository

```bash
git clone <YOUR_REPO_URL>
cd <YOUR_REPO_NAME>
```

---

## 2) Create and activate the Python virtual environment

### Windows PowerShell

Use Python 3.13 if that is what is installed on your machine.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks activation, run this once in the same terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate again:

```powershell
.\.venv\Scripts\Activate.ps1
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

---

## 3) Install backend dependencies

### Windows / macOS / Linux

```bash
pip install -r backend/requirements-dev.txt
```

If you installed `scrapling` with extras (for example `scrapling[fetchers]` or `scrapling[all]`), install the required browser dependencies:

```bash
scrapling install
# scrapling install --force  # force reinstall
```

---

## 4) Create your local environment file

Copy the example environment file to a real `.env` file.

### Windows PowerShell

```powershell
Copy-Item ".\backend\.env.example" ".\backend\.env"
```

### macOS / Linux

```bash
cp backend/.env.example backend/.env
```

---

## 5) Fill in the `.env` values

Open the `.env` file and update it with your local values.

Example:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/qima
GROQ_API_KEY=your_groq_key_here
GEMINI_API_KEY=your_gemini_key_here
APP_ENV=development
APP_DEBUG=true
APP_NAME=Qima API
```

Notes:
- Use your actual PostgreSQL username and password.
- Do not commit `.env` to Git.
- API keys must remain backend-only.

---

## 6) Install PostgreSQL and create the database

Install PostgreSQL locally.

Then create a database named `qima`.

If you are using `psql`, run:

```sql
CREATE DATABASE qima;
```

If you are using pgAdmin, create a new database named `qima` from the UI.

---

## 7) Run a dependency smoke test

Run this command to confirm the Python packages installed correctly:

```bash
python -c "import fastapi, sqlalchemy, psycopg, httpx, scrapling; print('Backend dependencies installed successfully')"
```

If this prints the success message, the backend environment is ready.

---

## 8) Make sure `.env` is ignored by Git

Add these lines to `.gitignore` in the repository root:

```gitignore
.venv/
backend/.env
__pycache__/
*.pyc
```

If `.env` was already tracked before adding `.gitignore`, untrack it:

### Windows / macOS / Linux

```bash
git rm --cached backend/.env
```

---

## 9) Commit the setup files

Commit the shared setup files only.

Do not commit the real `.env`.

```bash
git checkout -b chore/bootstrap-env
git add backend/requirements.txt backend/requirements-dev.txt
git add backend/.env.example
git add .gitignore
git commit -m "Add starter environment setup"
git push -u origin chore/bootstrap-env
```

---

## 10) What each teammate should run after pulling

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt
Copy-Item ".\backend\.env.example" ".\backend\.env"
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env
```

Then:
1. open `backend/.env`
2. fill in the real values
3. create the PostgreSQL database `qima`
4. run the smoke test

---

## 11) Troubleshooting

### Error: `No suitable Python runtime found`
Your machine does not have the requested Python version available to the launcher.

Check installed versions:

```powershell
py -0
```

Then use one of the installed versions, for example:

```powershell
py -3.13 -m venv .venv
```

### Error when using `Copy-Item`
If your path contains spaces, always wrap the path in quotes.

Correct:

```powershell
Copy-Item ".\backend\.env.example" ".\backend\.env"
```

Incorrect:

```powershell
Copy-Item .\backend\.env.example .\backend\.env
```

### PowerShell activation blocked
Run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate again:

```powershell
.\.venv\Scripts\Activate.ps1
```

---

## 12) Setup complete

Your local backend setup is ready when all of the following are true:

- virtual environment is created
- dependencies are installed
- `.env` exists and contains real values
- PostgreSQL database `qima` exists
- smoke test runs successfully

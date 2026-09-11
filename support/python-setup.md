# Python Setup

Use this before installing the instruction payload or running scaffold helper
scripts.

## Requirement

Install one current machine- or user-global Python 3 that works from any repo.
Do not rely on a repo `.venv` as the machine Python launcher.

The scaffold scripts need Python for:

- `scripts/install-to-project.py`
- `.instructions/scripts/configure-ef-packages-feed.py`
- `.instructions/scripts/generate-ontology.py` (also needs `pyyaml`: `python -m pip install pyyaml`)
- `scripts/validate-instructions.py` in this instruction repo

## Windows Launcher Check

Run from a fresh PowerShell session:

```powershell
where.exe python
where.exe py
python --version
python -c "import sys, encodings; print(sys.executable); print(sys.prefix); print(sys.version)"
python -m pip --version
py -0p
py -3 -c "import sys; print(sys.executable); print(sys.prefix)"
```

Pass criteria:

- `python` resolves to a real user-global or machine-wide Python install, not
  the Microsoft Store alias.
- `import encodings` succeeds.
- `python -m pip --version` succeeds.
- `py` works, or is intentionally absent and all scripts use `python`.
- The check works outside any repo without activating `.venv`.

If both `python` and `py` are unavailable or broken, install Python first. On
Windows, use either Python Install Manager for a single developer account, or a
machine-wide CPython install for shared build agents/service accounts. If the
machine has stale Python installs, broken launchers, PATH pins, or `.venv`
references, clean those before running scaffold scripts.

## Project Virtual Environments

After the global/user Python is healthy, recreate project `.venv` folders as
needed:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe --version
```

Existing `.venv` folders may point to removed Python runtimes. If helper
scripts fail from `.venv`, recreate it instead of treating it as a valid
machine-level Python install.

"""
MediaManager 2026 - Utilitaires de versioning

Détection de version locale (git), version GitHub disponible, comparaison.
"""

import logging
import subprocess

import requests

from watcher.config import IS_DEV, PROJECT_ROOT

logger = logging.getLogger(__name__)

_app_version: str | None = None

def get_app_version() -> str:
    """Lit la version depuis le fichier VERSION (mis en cache après le premier appel)."""
    global _app_version
    if _app_version is None:
        version_file = PROJECT_ROOT / "VERSION"
        _app_version = version_file.read_text().strip() if version_file.exists() else "0.1.0-unknown"
    return _app_version


_GITHUB_REPO    = "higs76/mediamanager2026"
_GITHUB_API_URL = f"https://api.github.com/repos/{_GITHUB_REPO}/releases"
_GITHUB_HEADERS = {"Accept": "application/vnd.github.v3+json"}


def get_git_info() -> dict:
    """
    Recupere la branche courante et le hash court du commit.
    Retourne: {"branch": "main"|"dev"|..., "commit": "a1b2c3d"}
    """
    try:
        branch = subprocess.run(
            ["/usr/bin/git", "branch", "--show-current"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=5
        ).stdout.strip() or "unknown"

        commit = subprocess.run(
            ["/usr/bin/git", "rev-parse", "--short", "HEAD"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=5
        ).stdout.strip() or "unknown"

        return {"branch": branch, "commit": commit}
    except Exception:
        return {"branch": "unknown", "commit": "unknown"}


def get_latest_github_version() -> dict:
    """
    Recupere la derniere version disponible depuis GitHub.

    Selon IS_DEV (VERSION contient -dev/-beta/-rc) :
    false → /releases/latest  (releases stables uniquement)
    true  → /releases         (toutes releases, pre-releases incluses)

    Resultat mis en cache 30 minutes.
    """
    import time

    cache = getattr(get_latest_github_version, "_cache", None)
    if cache and (time.time() - cache["ts"]) < 1800:
        return cache["data"]

    try:
        if IS_DEV:
            response = requests.get(
                f"{_GITHUB_API_URL}?per_page=1",
                headers=_GITHUB_HEADERS, timeout=5
            )
            if response.status_code == 200:
                releases = response.json()
                if releases:
                    data   = releases[0]
                    result = {
                        "version":      data.get("tag_name", "").lstrip("v"),
                        "url":          data.get("html_url"),
                        "published_at": data.get("published_at"),
                        "prerelease":   data.get("prerelease", False),
                        "error":        None
                    }
                else:
                    result = {"version": None, "url": None, "prerelease": False,
                              "error": "Aucune release publiee sur GitHub"}
            else:
                result = {"version": None, "url": None, "prerelease": False,
                          "error": f"GitHub API: HTTP {response.status_code}"}
        else:
            response = requests.get(
                f"{_GITHUB_API_URL}/latest",
                headers=_GITHUB_HEADERS, timeout=5
            )
            if response.status_code == 200:
                data   = response.json()
                result = {
                    "version":      data.get("tag_name", "").lstrip("v"),
                    "url":          data.get("html_url"),
                    "published_at": data.get("published_at"),
                    "prerelease":   False,
                    "error":        None
                }
            elif response.status_code == 404:
                result = {"version": None, "url": None, "prerelease": False,
                          "error": "Aucune release stable publiee sur GitHub"}
            else:
                result = {"version": None, "url": None, "prerelease": False,
                          "error": f"GitHub API: HTTP {response.status_code}"}

    except Exception as e:
        result = {"version": None, "url": None, "prerelease": False, "error": str(e)}

    get_latest_github_version._cache = {"ts": time.time(), "data": result}
    return result


def compare_versions(current: str, latest: str) -> dict:
    """
    Compare deux versions et retourne l'info de mise a jour.

    N'utilise pas packaging.version (normalise "0.3.2-dev" → "0.3.2.dev0").
    Comparaison manuelle sur les parties numeriques uniquement.
    Le suffixe (-dev, -beta, -rc) est ignore pour la comparaison
    mais conserve tel quel dans les champs retournes.
    """
    def _numeric_parts(v: str) -> tuple:
        clean = v.lstrip("v").split("-")[0].split(".")
        try:
            return tuple(int(x) for x in clean)
        except ValueError:
            return (0,)

    try:
        current_parts = _numeric_parts(current)
        latest_parts  = _numeric_parts(latest)
        has_update    = latest_parts > current_parts

        return {
            "has_update": has_update,
            "current":    current,
            "latest":     latest,
            "message":    f"Update available: {current} → {latest}" if has_update else "You are up to date",
            "latest_url": None
        }
    except Exception as e:
        return {
            "has_update": False,
            "current":    current,
            "latest":     latest,
            "error":      str(e)
        }

"""
MediaManager 2026 - Assembleur des routers Admin
Ce fichier assemble les routers par domaine sous le prefix /api/admin.
Toute la logique métier est dans watcher/routers/.
"""

from fastapi import APIRouter

from watcher.routers import categories, library, mounts, stats, system

router = APIRouter(prefix="/api/admin")

router.include_router(system.router)
router.include_router(categories.router)
router.include_router(mounts.router)
router.include_router(stats.router)
router.include_router(library.router)

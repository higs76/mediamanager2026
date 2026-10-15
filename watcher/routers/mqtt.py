"""
MediaManager 2026 - Router : MQTT
Routes : /api/admin/mqtt/test
"""

import logging

from fastapi import APIRouter, HTTPException

from watcher.mqtt_client import publish_test

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/mqtt/test")
def test_mqtt():
    """Publie un message de test sur le broker MQTT configuré."""
    ok, message = publish_test()
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}

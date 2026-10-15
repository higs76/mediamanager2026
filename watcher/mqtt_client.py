"""
MediaManager 2026 - Client MQTT (publication vers Home Assistant)

Deux usages distincts :
- publish_test() : publication à la demande d'un message de test (bouton "Tester
  la connexion" de l'onglet Config) — connect / publish / disconnect à chaque appel.
- MqttQueue : publisher persistant (capteurs via MQTT Discovery), connexion
  maintenue avec Last Will and Testament pour que Home Assistant détecte la
  coupure du service en temps réel, pas seulement au prochain cycle périodique.
"""

import json
import logging
import re
import threading
import time

import paho.mqtt.client as mqtt

from watcher.config_db import get_config
from watcher.utils.versioning import get_app_version
from watcher.utils.system_info import get_app_uptime

logger = logging.getLogger(__name__)


def _get_library_stats_dict() -> dict:
    from watcher.routers.system import get_library_stats_dict
    return get_library_stats_dict()


def _get_db_size_mb() -> float:
    from watcher.routers.system import get_db_size_mb
    return get_db_size_mb()


def _get_categories() -> list[str]:
    from watcher.database import engine
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT name FROM categories ORDER BY name")).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")


def _get_jobs_status_dict() -> dict:
    from watcher.routers.stats import get_jobs_status_dict
    return get_jobs_status_dict()


def _get_mounts_status_dict() -> dict:
    from watcher.routers.mounts import get_mounts_status_dict
    return get_mounts_status_dict()


def get_mqtt_host() -> str:
    return get_config("mqtt_host", "")


def get_mqtt_port() -> int:
    try:
        return int(get_config("mqtt_port", "1883"))
    except ValueError:
        return 1883


def get_mqtt_username() -> str:
    return get_config("mqtt_username", "")


def get_mqtt_password() -> str:
    return get_config("mqtt_password", "")


def get_mqtt_topic_prefix() -> str:
    return get_config("mqtt_topic_prefix", "mediamanager") or "mediamanager"


def get_mqtt_enabled() -> bool:
    return get_config("mqtt_enabled", "false").lower() == "true"


def get_mqtt_publish_interval() -> int:
    try:
        return max(10, int(get_config("mqtt_publish_interval_seconds", "60")))
    except ValueError:
        return 60


def get_mqtt_publish_library() -> bool:
    return get_config("mqtt_publish_library", "true").lower() == "true"


def get_mqtt_publish_jobs() -> bool:
    return get_config("mqtt_publish_jobs", "true").lower() == "true"


def get_mqtt_publish_mounts() -> bool:
    return get_config("mqtt_publish_mounts", "true").lower() == "true"


def publish_test() -> tuple[bool, str]:
    """Connecte au broker configuré, publie un message de test, déconnecte.
    Retourne (succès, message) — n'est jamais censé lever d'exception."""
    host = get_mqtt_host()
    if not host:
        return False, "Hôte MQTT non configuré"

    port = get_mqtt_port()
    username = get_mqtt_username()
    topic = f"{get_mqtt_topic_prefix()}/test"
    payload = json.dumps({
        "message": "MediaManager 2026 — test de connexion MQTT",
        "timestamp": int(time.time()),
    })

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="mediamanager-test",
        protocol=mqtt.MQTTv311,
    )
    if username:
        client.username_pw_set(username, get_mqtt_password())

    try:
        client.connect(host, port, keepalive=5)
        client.loop_start()
        info = client.publish(topic, payload, qos=1)
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            return False, "Timeout : le message n'a pas été confirmé par le broker"
        return True, f"Message publié sur {topic}"
    except Exception as e:
        logger.warning(f"mqtt publish_test: {e}")
        return False, str(e)
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass


class MqttQueue:
    """Publisher MQTT persistant : disponibilité (LWT) + version/uptime,
    exposés à Home Assistant via MQTT Discovery. Démarré/arrêté depuis le
    lifespan de l'app, comme MountWatchdog (watcher/routers/mounts.py)."""

    def __init__(self):
        self._client: mqtt.Client | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._availability_topic: str | None = None
        self._topic_prefix: str | None = None
        self._device: dict | None = None
        # Topics de bloc (hors santé) dont la config Discovery a déjà été envoyée
        # depuis le démarrage de cette connexion — évite de la republier à chaque
        # cycle, seulement quand un bloc passe d'inactif à actif.
        self._discovered_blocks: set[str] = set()

    def start(self):
        if not get_mqtt_enabled():
            logger.info("MQTT désactivé (mqtt_enabled=false) — publisher non démarré")
            return
        host = get_mqtt_host()
        if not host:
            logger.warning("MQTT activé mais mqtt_host vide — publisher non démarré")
            return

        prefix = get_mqtt_topic_prefix()
        self._topic_prefix = prefix
        self._availability_topic = f"{prefix}/status"
        self._device = {
            "identifiers": ["mediamanager"],
            "name": "MediaManager 2026",
            "manufacturer": "Higs76",
            "model": "MediaManager 2026",
            "sw_version": get_app_version(),
        }
        self._discovered_blocks = set()

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="mediamanager",
            protocol=mqtt.MQTTv311,
        )
        username = get_mqtt_username()
        if username:
            client.username_pw_set(username, get_mqtt_password())
        client.will_set(self._availability_topic, "offline", retain=True)

        try:
            client.connect(host, get_mqtt_port(), keepalive=30)
        except Exception as e:
            logger.warning(f"MQTT connect échoué : {e}")
            return

        client.loop_start()
        self._client = client
        client.publish(self._availability_topic, "online", retain=True)

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mqtt-publisher")
        self._thread.start()
        logger.info("✓ MqttQueue démarré")

    def stop(self):
        self._stop_event.set()
        if self._client:
            try:
                self._client.publish(self._availability_topic, "offline", retain=True)
                time.sleep(0.2)
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    # Blocs optionnels : nom -> (accesseur "actif ?", méthode de publication)
    _BLOCKS = ("library", "jobs", "mounts")

    def _run(self):
        # Discovery de la santé publiée une fois, dès le premier cycle (toujours actif).
        self._publish_discovery_entities("health", self._health_entities())
        while not self._stop_event.wait(get_mqtt_publish_interval()):
            self._publish_health()
            for name in self._BLOCKS:
                enabled = {
                    "library": get_mqtt_publish_library,
                    "jobs":    get_mqtt_publish_jobs,
                    "mounts":  get_mqtt_publish_mounts,
                }[name]()
                if not enabled:
                    continue
                if name not in self._discovered_blocks:
                    self._publish_discovery_entities(name, getattr(self, f"_{name}_entities")())
                    self._discovered_blocks.add(name)
                getattr(self, f"_publish_{name}")()

    def _health_entities(self) -> list:
        state_topic = f"{self._topic_prefix}/health/state"
        return [
            ("binary_sensor", "status", {
                "name": "MediaManager en ligne",
                "unique_id": "mediamanager_status",
                "device_class": "connectivity",
                "state_topic": self._availability_topic,
                "payload_on": "online",
                "payload_off": "offline",
            }),
            ("sensor", "version", {
                "name": "MediaManager version",
                "unique_id": "mediamanager_version",
                "state_topic": state_topic,
                "value_template": "{{ value_json.version }}",
            }),
            ("sensor", "uptime", {
                "name": "MediaManager uptime",
                "unique_id": "mediamanager_uptime",
                "state_topic": state_topic,
                "value_template": "{{ value_json.uptime }}",
            }),
            ("sensor", "db_size", {
                "name": "MediaManager taille base de données",
                "unique_id": "mediamanager_db_size_mb",
                "state_topic": state_topic,
                "value_template": "{{ value_json.db_size_mb }}",
                "unit_of_measurement": "MB", "state_class": "measurement",
                "icon": "mdi:database-outline",
            }),
        ]

    def _publish_health(self):
        if not self._client:
            return
        payload = json.dumps({
            "version": get_app_version(),
            "uptime": get_app_uptime(),
            "db_size_mb": _get_db_size_mb(),
        })
        self._client.publish(f"{self._topic_prefix}/health/state", payload, retain=True)

    def _library_entities(self) -> list:
        state_topic = f"{self._topic_prefix}/library/state"
        return [
            ("sensor", "library_titles", {
                "name": "MediaManager titres", "unique_id": "mediamanager_library_titles",
                "state_topic": state_topic, "value_template": "{{ value_json.nb_titles }}",
                "state_class": "measurement", "icon": "mdi:movie-open-outline",
            }),
            ("sensor", "library_files", {
                "name": "MediaManager fichiers", "unique_id": "mediamanager_library_files",
                "state_topic": state_topic, "value_template": "{{ value_json.total_files }}",
                "state_class": "measurement", "icon": "mdi:file-video-outline",
            }),
            ("sensor", "library_missing", {
                "name": "MediaManager fichiers manquants", "unique_id": "mediamanager_library_missing",
                "state_topic": state_topic, "value_template": "{{ value_json.missing_files }}",
                "state_class": "measurement", "icon": "mdi:file-alert-outline",
            }),
            ("sensor", "library_size_tb", {
                "name": "MediaManager taille bibliothèque", "unique_id": "mediamanager_library_size_tb",
                "state_topic": state_topic, "value_template": "{{ value_json.total_tb }}",
                "unit_of_measurement": "TB", "state_class": "measurement", "icon": "mdi:database-outline",
            }),
            ("sensor", "library_trash_gb", {
                "name": "MediaManager corbeille récupérable", "unique_id": "mediamanager_library_trash_gb",
                "state_topic": state_topic,
                "value_template": "{{ (value_json.trash_bytes | float / 1073741824) | round(2) }}",
                "unit_of_measurement": "GB", "state_class": "measurement", "icon": "mdi:trash-can-outline",
            }),
        ] + [
            ("sensor", f"library_cat_{_slug(name)}", {
                "name": f"MediaManager taille — {name}",
                "unique_id": f"mediamanager_library_cat_{_slug(name)}",
                "state_topic": state_topic,
                "value_template": (
                    "{{ (value_json.by_category_tb | selectattr('name','equalto','" + name + "') "
                    "| map(attribute='tb') | first | default(0)) }}"
                ),
                "unit_of_measurement": "TB", "state_class": "measurement", "icon": "mdi:folder-multiple-outline",
            })
            for name in _get_categories() if "'" not in name
        ]

    def _publish_library(self):
        if not self._client:
            return
        payload = json.dumps(_get_library_stats_dict())
        self._client.publish(f"{self._topic_prefix}/library/state", payload, retain=True)

    def _jobs_entities(self) -> list:
        state_topic = f"{self._topic_prefix}/jobs/state"
        return [
            ("sensor", "jobs_scanner_status", {
                "name": "MediaManager scanner", "unique_id": "mediamanager_jobs_scanner_status",
                "state_topic": state_topic,
                "value_template": (
                    "{{ 'En cours' if value_json.scanner.last_status == 'running' "
                    "else (value_json.scanner.last_finished or 'Jamais exécuté') }}"
                ),
                "icon": "mdi:magnify-scan",
            }),
            ("sensor", "jobs_analyzer_status", {
                "name": "MediaManager analyseur", "unique_id": "mediamanager_jobs_analyzer_status",
                "state_topic": state_topic,
                "value_template": (
                    "{{ 'En cours' if value_json.analyzer.running "
                    "else (value_json.analyzer.last_finished or 'Jamais exécuté') }}"
                ),
                "icon": "mdi:cog-sync",
            }),
            ("sensor", "jobs_cataloger_status", {
                "name": "MediaManager catalogueur", "unique_id": "mediamanager_jobs_cataloger_status",
                "state_topic": state_topic,
                "value_template": (
                    "{{ 'En cours' if value_json.cataloger.running "
                    "else (value_json.cataloger.last_run or 'Jamais exécuté') }}"
                ),
                "icon": "mdi:tag-multiple-outline",
            }),
            ("sensor", "jobs_proposals_pending", {
                "name": "MediaManager renommages en attente", "unique_id": "mediamanager_jobs_proposals_pending",
                "state_topic": state_topic, "value_template": "{{ value_json.cataloger.proposals_pending }}",
                "state_class": "measurement", "icon": "mdi:file-swap-outline",
            }),
        ]

    def _publish_jobs(self):
        if not self._client:
            return
        payload = json.dumps(_get_jobs_status_dict())
        self._client.publish(f"{self._topic_prefix}/jobs/state", payload, retain=True)

    def _mounts_entities(self) -> list:
        state_topic = f"{self._topic_prefix}/mounts/state"
        return [
            ("sensor", "mounts_mounted", {
                "name": "MediaManager montages montés", "unique_id": "mediamanager_mounts_mounted",
                "state_topic": state_topic, "value_template": "{{ value_json.mounted }}",
                "state_class": "measurement", "icon": "mdi:nas",
            }),
            ("sensor", "mounts_total", {
                "name": "MediaManager montages total", "unique_id": "mediamanager_mounts_total",
                "state_topic": state_topic, "value_template": "{{ value_json.total }}",
                "state_class": "measurement", "icon": "mdi:nas",
            }),
            ("binary_sensor", "mounts_all_ok", {
                "name": "MediaManager montages NAS OK", "unique_id": "mediamanager_mounts_all_ok",
                "state_topic": state_topic,
                "value_template": "{{ 'ON' if value_json.missing == 0 else 'OFF' }}",
                "icon": "mdi:nas",
            }),
            ("sensor", "mounts_pct", {
                "name": "MediaManager montages pourcentage", "unique_id": "mediamanager_mounts_pct",
                "state_topic": state_topic,
                "value_template": (
                    "{{ ((value_json.mounted / value_json.total * 100) | round(0)) "
                    "if value_json.total > 0 else 0 }}"
                ),
                "unit_of_measurement": "%", "state_class": "measurement", "icon": "mdi:nas",
            }),
        ]

    def _publish_mounts(self):
        if not self._client:
            return
        payload = json.dumps(_get_mounts_status_dict())
        self._client.publish(f"{self._topic_prefix}/mounts/state", payload, retain=True)

    def _publish_discovery_entities(self, _block: str, entities: list):
        if not self._client:
            return
        for component, object_id, entity_config in entities:
            entity_config["availability_topic"] = self._availability_topic
            entity_config["device"] = self._device
            topic = f"homeassistant/{component}/mediamanager/{object_id}/config"
            self._client.publish(topic, json.dumps(entity_config), retain=True)


mqtt_queue = MqttQueue()

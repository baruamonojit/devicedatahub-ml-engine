"""MQTT alert publishing for anomaly detection."""

import json
import logging
import os
from typing import Dict, Any
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTAlertPublisher:
    """Publishes anomaly alerts to MQTT broker with device-specific topics."""

    def __init__(
        self,
        broker_host: str = None,
        broker_port: int = 1883,
        base_topic: str = "wifi/alerts",
        client_id: str = "anomaly-detector",
    ):
        """
        Initialize MQTT publisher.

        Args:
            broker_host: MQTT broker hostname (default from env: MQTT_HOST)
            broker_port: MQTT broker port (default from env: MQTT_PORT)
            base_topic: Base topic for alerts (default: wifi/alerts)
            client_id: MQTT client ID
        """
        self.broker_host = broker_host or os.getenv("MQTT_HOST", "localhost")
        self.broker_port = broker_port or int(os.getenv("MQTT_PORT", 1883))
        self.base_topic = base_topic
        self.client_id = client_id
        self.client = None
        self.connected = False

    def connect(self) -> bool:
        """
        Connect to MQTT broker.

        Returns:
            True if successful, False otherwise
        """
        try:
            self.client = mqtt.Client(client_id=self.client_id)
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_publish = self._on_publish

            logger.info(f"Connecting to MQTT broker at {self.broker_host}:{self.broker_port}")
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()  # Start background thread

            return True
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False

    def disconnect(self):
        """Disconnect from MQTT broker."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False

    def _on_connect(self, client, userdata, flags, rc):
        """Callback for when client connects to broker."""
        if rc == 0:
            self.connected = True
            logger.info(f"✅ Connected to MQTT broker (result code {rc})")
        else:
            logger.error(f"❌ Failed to connect to MQTT broker (result code {rc})")

    def _on_disconnect(self, client, userdata, rc):
        """Callback for when client disconnects from broker."""
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection (result code {rc})")

    def _on_publish(self, client, userdata, mid):
        """Callback for when message is published."""
        pass  # Silent success

    def publish_anomaly_alert(
        self, device_id: str, anomaly_data: Dict[str, Any]
    ) -> bool:
        """
        Publish anomaly alert to device-specific MQTT topic.

        Topic structure: {base_topic}/{device_id}/anomaly

        Args:
            device_id: Device identifier
            anomaly_data: Anomaly details (probability, timestamp, metrics, etc.)

        Returns:
            True if published successfully
        """
        if not self.connected:
            logger.warning(f"MQTT not connected, skipping publish for {device_id}")
            return False

        topic = f"{self.base_topic}/{device_id}/anomaly"
        payload = json.dumps(anomaly_data, indent=2)

        try:
            result = self.client.publish(topic, payload, qos=1, retain=False)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published to {topic}")
                return True
            else:
                logger.error(f"Failed to publish to {topic}: {result.rc}")
                return False
        except Exception as e:
            logger.error(f"Error publishing to MQTT: {e}")
            return False

    def publish_device_status(
        self, device_id: str, status: str, metrics: Dict[str, float]
    ) -> bool:
        """
        Publish device status (healthy or anomaly) to MQTT.

        Topic structure: {base_topic}/{device_id}/status

        Args:
            device_id: Device identifier
            status: "healthy" or "anomaly"
            metrics: Current metrics dict

        Returns:
            True if published successfully
        """
        if not self.connected:
            return False

        topic = f"{self.base_topic}/{device_id}/status"
        payload = json.dumps({
            "status": status,
            "timestamp": metrics.get("timestamp", ""),
            "anomaly_prob": metrics.get("anomaly_prob", 0.0),
        })

        try:
            result = self.client.publish(topic, payload, qos=1, retain=True)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Error publishing status: {e}")
            return False

    def publish_batch_summary(self, summary: Dict[str, Any]) -> bool:
        """
        Publish a summary of the inference run.

        Topic structure: {base_topic}/summary

        Args:
            summary: Summary data (healthy_count, anomaly_count, etc.)

        Returns:
            True if published successfully
        """
        if not self.connected:
            return False

        topic = f"{self.base_topic}/summary"
        payload = json.dumps(summary)

        try:
            result = self.client.publish(topic, payload, qos=1, retain=True)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Error publishing summary: {e}")
            return False

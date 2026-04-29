"""
BLE client for Claude Desktop Buddy using bleak.
"""

import asyncio
import logging
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from .protocol import (
    NUS_SERVICE_UUID,
    NUS_RX_UUID,
    NUS_TX_UUID,
    DEVICE_NAME_PREFIX,
    parse_message,
    parse_ack,
    parse_permission_decision,
    build_command,
)
from .state import ConnectionState, DeviceStatus, PermissionResponse

logger = logging.getLogger(__name__)


class BLEClient:
    """
    BLE client for Claude Desktop Buddy device.

    Handles scanning, connection, and message exchange using Nordic UART Service.
    """

    def __init__(self):
        self._client: Optional[BleakClient] = None
        self._state = ConnectionState()
        self._rx_buffer = bytearray()
        self._message_callback: Optional[Callable[[dict], None]] = None

    @property
    def connected(self) -> bool:
        """Check if connected to device."""
        return self._state.connected and self._client is not None

    @property
    def device_name(self) -> Optional[str]:
        """Get connected device name."""
        return self._state.device_name

    @property
    def device_address(self) -> Optional[str]:
        """Get connected device address."""
        return self._state.device_address

    @property
    def mtu(self) -> int:
        """Get negotiated MTU."""
        return self._state.mtu

    @property
    def status(self) -> Optional[DeviceStatus]:
        """Get cached device status."""
        return self._state.status

    async def scan(self, timeout: float = 5.0) -> list[dict]:
        """
        Scan for Claude devices.

        Args:
            timeout: Scan duration in seconds

        Returns:
            List of device info dicts with name, address, rssi
        """
        logger.info(f"Scanning for {DEVICE_NAME_PREFIX}* devices...")

        devices: list[dict] = []

        def detection_callback(device: BLEDevice, advertisement_data):
            name = device.name or ""
            if name.startswith(DEVICE_NAME_PREFIX):
                devices.append({
                    "name": name,
                    "address": device.address,
                    "rssi": advertisement_data.rssi or 0,
                })
                logger.debug(f"Found device: {name} ({device.address})")

        scanner = BleakScanner(detection_callback=detection_callback)
        await scanner.start()
        await asyncio.sleep(timeout)
        await scanner.stop()

        logger.info(f"Found {len(devices)} Claude device(s)")
        return devices

    async def connect(
        self,
        device_address: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict:
        """
        Connect to a Claude device.

        Args:
            device_address: Device address to connect to (auto-select if None)
            timeout: Connection timeout in seconds

        Returns:
            Connection info dict
        """
        if self.connected:
            return {
                "connected": True,
                "device_name": self._state.device_name,
                "device_address": self._state.device_address,
            }

        # Auto-select device if not specified
        if device_address is None:
            devices = await self.scan(timeout=5.0)
            if not devices:
                raise RuntimeError("No Claude devices found")
            device_address = devices[0]["address"]
            logger.info(f"Auto-selecting device: {devices[0]['name']}")

        # Connect
        logger.info(f"Connecting to {device_address}...")
        self._client = BleakClient(device_address, timeout=timeout)

        try:
            await self._client.connect()
        except Exception as e:
            self._client = None
            raise RuntimeError(f"Failed to connect: {e}") from e

        # Get device info
        self._state.connected = True
        self._state.device_address = device_address
        self._state.device_name = self._client.name or "Unknown"

        # Get MTU
        self._state.mtu = self._client.mtu_size
        logger.info(f"Connected to {self._state.device_name}, MTU={self._state.mtu}")

        # Subscribe to TX characteristic for notifications
        try:
            await self._client.start_notify(
                NUS_TX_UUID,
                self._on_tx_notification,
            )
            logger.debug("Subscribed to TX notifications")
        except Exception as e:
            logger.warning(f"Failed to subscribe to TX: {e}")

        return {
            "connected": True,
            "device_name": self._state.device_name,
            "device_address": self._state.device_address,
            "mtu": self._state.mtu,
        }

    async def disconnect(self) -> dict:
        """Disconnect from device."""
        if not self.connected or self._client is None:
            return {"connected": False}

        try:
            await self._client.disconnect()
        except Exception as e:
            logger.warning(f"Disconnect error: {e}")
        finally:
            self._client = None
            self._state.reset()

        logger.info("Disconnected")
        return {"connected": False}

    def _on_tx_notification(self, characteristic, data: bytearray):
        """Handle incoming TX notifications."""
        self._rx_buffer.extend(data)

        # Process complete lines
        while b"\n" in self._rx_buffer:
            line, _, rest = self._rx_buffer.partition(b"\n")
            self._rx_buffer = rest

            if line:
                self._process_line(line)

    def _process_line(self, data: bytes):
        """Process a complete JSON line."""
        parsed = parse_message(data)
        if parsed is None:
            return

        logger.debug(f"Received: {parsed}")

        # Check for permission decision
        decision = parse_permission_decision(parsed)
        if decision:
            response = PermissionResponse(
                prompt_id=decision.prompt_id,
                decision=decision.decision,
            )
            self._state.handle_permission_response(response)
            logger.info(f"Permission response: {decision.prompt_id} -> {decision.decision}")
            return

        # Check for ack response
        ack = parse_ack(parsed)
        if ack:
            if ack.command == "status" and ack.ok and ack.data:
                status = DeviceStatus.from_dict(ack.data)
                self._state.set_status(status)
                self._state.secure = status.secure
            logger.debug(f"ACK: {ack.command} ok={ack.ok}")

        # Call user callback if set
        if self._message_callback:
            self._message_callback(parsed)

    def set_message_callback(self, callback: Optional[Callable[[dict], None]]):
        """Set callback for incoming messages."""
        self._message_callback = callback

    async def send(self, data: bytes) -> bool:
        """
        Send data to device via RX characteristic.

        Handles chunking based on MTU.

        Args:
            data: Raw data to send

        Returns:
            True if sent successfully
        """
        if not self.connected or self._client is None:
            raise RuntimeError("Not connected")

        # Chunk size: MTU - 3 (ATT header) or max 180 bytes
        chunk_size = min(self._state.max_payload_size, 180)
        if chunk_size < 20:
            chunk_size = 20  # Minimum safe size

        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + chunk_size]
            try:
                await self._client.write_gatt_char(NUS_RX_UUID, chunk)
                offset += len(chunk)
                # Small delay between chunks for BLE stack
                await asyncio.sleep(0.004)
            except Exception as e:
                logger.error(f"Send error: {e}")
                return False

        logger.debug(f"Sent {len(data)} bytes")
        return True

    async def send_message(self, message: bytes) -> bool:
        """
        Send a complete message (convenience method).

        Args:
            message: Message bytes (should include newline)

        Returns:
            True if sent successfully
        """
        return await self.send(message)

    async def send_command(self, cmd: str, **params) -> bool:
        """
        Send a command and wait for acknowledgment.

        Args:
            cmd: Command name
            **params: Command parameters

        Returns:
            True if command was acknowledged successfully
        """
        return await self.send(build_command(cmd, **params))

    async def get_status(self, timeout: float = 5.0) -> DeviceStatus:
        """
        Request and return device status.

        Args:
            timeout: Time to wait for response

        Returns:
            DeviceStatus

        Raises:
            RuntimeError: If status not received in time
        """
        if not self.connected:
            raise RuntimeError("Not connected")

        # Clear cached status and request new
        self._state._status = None
        await self.send_command("status")

        # Wait for response
        for _ in range(int(timeout * 10)):
            if self._state.status:
                return self._state.status
            await asyncio.sleep(0.1)

        raise RuntimeError("Status response timeout")

    async def wait_permission_response(
        self,
        prompt_id: str,
        timeout: float = 60.0,
        clear_after: bool = True,
    ) -> Optional[PermissionResponse]:
        """
        Wait for permission response from device.

        Args:
            prompt_id: The prompt ID to wait for
            timeout: Timeout in seconds
            clear_after: Clear the prompt from device display after receiving response

        Returns:
            PermissionResponse or None if timeout
        """
        response = await self._state.wait_permission_response(prompt_id, timeout)

        # Clear prompt from device display
        if response and clear_after:
            await self.clear_prompt()

        return response

    async def clear_prompt(self) -> bool:
        """
        Clear the permission prompt from device display.

        Sends a heartbeat without prompt field to clear the UI.

        Returns:
            True if sent successfully
        """
        from .protocol import build_heartbeat
        msg = build_heartbeat(
            total=0,
            running=0,
            waiting=0,
            msg="",
        )
        return await self.send(msg)

    @property
    def state(self) -> ConnectionState:
        """Get connection state."""
        return self._state


# Global singleton for simplicity
_client: Optional[BLEClient] = None


def get_client() -> BLEClient:
    """Get the global BLE client instance."""
    global _client
    if _client is None:
        _client = BLEClient()
    return _client

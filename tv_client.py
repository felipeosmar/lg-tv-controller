"""
LG webOS TV SSAP Client — Comunicação WebSocket com a TV LG 65UQ8050PSB.
Implementa descoberta, autenticação, controle e monitoramento via protocolo SSAP.
"""

import asyncio
import json
import logging
import socket
import ssl
import struct
import uuid
from pathlib import Path
from typing import Any, Callable

import websockets

logger = logging.getLogger(__name__)

# Arquivo para persistir a client-key entre sessões
KEY_FILE = Path(__file__).parent / ".tv_client_key"

# Manifesto de permissões (handshake de registro)
REGISTER_PAYLOAD = {
    "forcePairing": False,
    "pairingType": "PROMPT",
    "manifest": {
        "manifestVersion": 1,
        "appVersion": "1.1",
        "signed": {
            "created": "20140509",
            "appId": "com.lge.test",
            "vendorId": "com.lge",
            "localizedAppNames": {"": "LG TV Controller", "pt-BR": "Controle LG TV"},
            "localizedVendorNames": {"": "LG Electronics"},
            "permissions": [
                "TEST_SECURE", "CONTROL_INPUT_JOYSTICK", "CONTROL_INPUT_MEDIA_RECORDING",
                "CONTROL_INPUT_MEDIA_PLAYBACK", "CONTROL_INPUT_TV", "CONTROL_POWER",
                "READ_APP_STATUS", "READ_CURRENT_CHANNEL", "READ_INPUT_DEVICE_LIST",
                "READ_NETWORK_STATE", "READ_RUNNING_APPS", "READ_TV_CHANNEL_LIST",
                "WRITE_NOTIFICATION", "READ_POWER_STATE", "READ_COUNTRY_INFO",
                "READ_SETTINGS", "CONTROL_TV_SCREEN", "CONTROL_TV_STANBY",
                "CONTROL_FAVORITE_GROUP", "CONTROL_USER_INFO", "CHECK_BLUETOOTH_DEVICE",
                "CONTROL_BLUETOOTH", "CONTROL_CAPTION", "CONTROL_DEVICE_STORAGE",
                "READ_INSTALLED_APPS", "CONTROL_INPUT_TEXT", "CONTROL_MOUSE_AND_KEYBOARD",
                "READ_TV_CONTENT_STATE", "READ_TV_CURRENT_TIME", "CONTROL_TV_TIMER",
                "LAUNCH", "LAUNCH_WEBAPP", "CONTROL_AUDIO", "CONTROL_DISPLAY",
            ],
            "serial": "2f930e2d2cfe083771f68e4fe7983211",
        },
        "permissions": [
            "LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP", "CLOSE",
            "TEST_OPEN", "TEST_PROTECTED", "CONTROL_AUDIO",
            "CONTROL_DISPLAY", "CONTROL_INPUT_JOYSTICK",
            "CONTROL_INPUT_MEDIA_RECORDING", "CONTROL_INPUT_MEDIA_PLAYBACK",
            "CONTROL_INPUT_TV", "CONTROL_POWER", "READ_APP_STATUS",
            "READ_CURRENT_CHANNEL", "READ_INPUT_DEVICE_LIST",
            "READ_NETWORK_STATE", "READ_INSTALLED_APPS", "READ_RUNNING_APPS",
            "READ_TV_CHANNEL_LIST", "WRITE_NOTIFICATION", "READ_POWER_STATE",
            "READ_COUNTRY_INFO", "READ_SETTINGS", "CONTROL_TV_SCREEN",
            "CONTROL_TV_STANBY", "CONTROL_FAVORITE_GROUP", "CONTROL_USER_INFO",
            "CHECK_BLUETOOTH_DEVICE", "CONTROL_BLUETOOTH", "CONTROL_CAPTION",
            "CONTROL_DEVICE_STORAGE", "READ_TV_CONTENT_STATE",
            "READ_TV_CURRENT_TIME", "CONTROL_TV_TIMER",
            "CONTROL_MOUSE_AND_KEYBOARD", "CONTROL_INPUT_TEXT",
        ],
    },
}

# URIs SSAP conhecidas
SSAP = {
    # Sistema
    "get_services": "ssap://api/getServiceList",
    "power_off": "ssap://system/turnOff",
    "power_state": "ssap://com.webos.service.tvpower/power/getPowerState",
    "get_system_info": "ssap://system/getSystemInfo",
    "get_sw_info": "ssap://com.webos.service.update/getCurrentSWInformation",
    # Áudio
    "get_volume": "ssap://audio/getVolume",
    "set_volume": "ssap://audio/setVolume",
    "volume_up": "ssap://audio/volumeUp",
    "volume_down": "ssap://audio/volumeDown",
    "set_mute": "ssap://audio/setMute",
    "get_mute": "ssap://audio/getStatus",
    # Canais / TV
    "get_channels": "ssap://tv/getChannelList",
    "get_current_channel": "ssap://tv/getCurrentChannel",
    "set_channel": "ssap://tv/openChannel",
    "channel_up": "ssap://tv/channelUp",
    "channel_down": "ssap://tv/channelDown",
    # Inputs / Fontes
    "get_inputs": "ssap://tv/getExternalInputList",
    "set_input": "ssap://tv/switchInput",
    # Apps
    "get_apps": "ssap://com.webos.applicationManager/listApps",
    "launch_app": "ssap://system.launcher/launch",
    "close_app": "ssap://system.launcher/close",
    "get_foreground": "ssap://com.webos.applicationManager/getForegroundAppInfo",
    # Mídia
    "play": "ssap://media.controls/play",
    "pause": "ssap://media.controls/pause",
    "stop": "ssap://media.controls/stop",
    "rewind": "ssap://media.controls/rewind",
    "fast_forward": "ssap://media.controls/fastForward",
    # Notificações
    "toast": "ssap://system.notifications/createToast",
    # Pointer / Input
    "pointer_socket": "ssap://com.webos.service.networkinput/getPointerInputSocket",
    # Tela
    "screen_off": "ssap://com.webos.service.tvpower/power/turnOffScreen",
    "screen_on": "ssap://com.webos.service.tvpower/power/turnOnScreen",
}

# IDs de aplicativos conhecidos
APP_IDS = {
    "netflix": "netflix",
    "youtube": "youtube.leanback.v4",
    "amazon_prime": "amazon.lovefilm.de",
    "disney_plus": "com.disney.disneyplus-prod",
    "spotify": "spotify-beehive",
    "browser": "com.webos.app.browser",
    "hdmi1": "com.webos.app.hdmi1",
    "hdmi2": "com.webos.app.hdmi2",
    "hdmi3": "com.webos.app.hdmi3",
    "live_tv": "com.webos.app.livetv",
    "lg_channels": "com.webos.app.lgchannels",
    "settings": "com.palm.app.settings",
    "media_player": "com.webos.app.mediadiscovery",
}


class LGTVClient:
    """Cliente assíncrono para controlar a TV LG via SSAP/WebSocket."""

    def __init__(self, host: str, port: int = 3001, use_ssl: bool = True):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.ws = None
        self.client_key: str | None = None
        self._callbacks: dict[str, asyncio.Future] = {}
        self._subscriptions: dict[str, Callable] = {}
        self._listener_task: asyncio.Task | None = None
        self._connected = False
        self._load_key()

    def _load_key(self):
        """Carrega a client-key salva."""
        if KEY_FILE.exists():
            self.client_key = KEY_FILE.read_text().strip()
            logger.info("Client key carregada do arquivo.")

    def _save_key(self):
        """Persiste a client-key."""
        if self.client_key:
            KEY_FILE.write_text(self.client_key)
            logger.info("Client key salva.")

    @property
    def is_connected(self) -> bool:
        return self._connected and self.ws is not None

    async def connect(self, timeout: float = 10.0) -> bool:
        """Conecta e registra com a TV."""
        protocol = "wss" if self.use_ssl else "ws"
        uri = f"{protocol}://{self.host}:{self.port}"

        ssl_context = None
        if self.use_ssl:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        try:
            self.ws = await asyncio.wait_for(
                websockets.connect(uri, ssl=ssl_context, ping_interval=None),
                timeout=timeout,
            )
            logger.info(f"WebSocket conectado a {uri}")
        except Exception as e:
            logger.error(f"Falha ao conectar: {e}")
            return False

        # Iniciar listener
        self._listener_task = asyncio.create_task(self._listener())

        # Registrar
        registered = await self._register(timeout=30.0)
        if registered:
            self._connected = True
            logger.info("Registrado com sucesso na TV.")
        return registered

    async def disconnect(self):
        """Desconecta da TV."""
        self._connected = False
        if self._listener_task:
            self._listener_task.cancel()
        if self.ws:
            await self.ws.close()
            self.ws = None
        logger.info("Desconectado da TV.")

    async def _register(self, timeout: float = 30.0) -> bool:
        """Envia handshake de registro."""
        payload = REGISTER_PAYLOAD.copy()
        if self.client_key:
            payload["client-key"] = self.client_key

        msg_id = self._make_id()
        message = {"type": "register", "id": msg_id, "payload": payload}

        # Usamos uma queue para receber múltiplas respostas (response + registered)
        queue: asyncio.Queue = asyncio.Queue()
        self._callbacks[msg_id] = queue

        await self.ws.send(json.dumps(message))
        logger.info("Handshake de registro enviado. Aguardando aprovação na TV...")

        try:
            deadline = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                response = await asyncio.wait_for(queue.get(), timeout=remaining)
                msg_type = response.get("type")
                logger.info(f"Registro - recebido type={msg_type}")
                if msg_type == "registered":
                    new_key = response.get("payload", {}).get("client-key")
                    if new_key:
                        self.client_key = new_key
                        self._save_key()
                    self._callbacks.pop(msg_id, None)
                    return True
                elif msg_type == "error":
                    logger.error(f"Registro falhou: {response}")
                    self._callbacks.pop(msg_id, None)
                    return False
                # type=="response" é intermediário, continuar esperando
        except asyncio.TimeoutError:
            logger.error("Timeout aguardando aprovação na TV.")
            self._callbacks.pop(msg_id, None)
            return False

    async def _listener(self):
        """Loop que escuta mensagens da TV."""
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                msg_id = msg.get("id")
                msg_type = msg.get("type")

                # Callback pode ser Queue (registro) ou Future (request)
                cb = self._callbacks.get(msg_id)
                if cb is not None:
                    if isinstance(cb, asyncio.Queue):
                        await cb.put(msg)
                    elif isinstance(cb, asyncio.Future) and not cb.done():
                        self._callbacks.pop(msg_id)
                        cb.set_result(msg)
                    continue

                # Subscription callback
                if msg_id in self._subscriptions:
                    try:
                        self._subscriptions[msg_id](msg)
                    except Exception as e:
                        logger.error(f"Erro em subscription callback: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Conexão WebSocket fechada.")
            self._connected = False
        except asyncio.CancelledError:
            pass

    def _make_id(self) -> str:
        return str(uuid.uuid4())[:8]

    async def request(self, uri: str, payload: dict | None = None, timeout: float = 10.0) -> dict:
        """Envia um request SSAP e aguarda resposta."""
        if not self.is_connected:
            raise ConnectionError("Não conectado à TV.")

        msg_id = self._make_id()
        message = {"type": "request", "id": msg_id, "uri": uri}
        if payload:
            message["payload"] = payload

        future = asyncio.get_event_loop().create_future()
        self._callbacks[msg_id] = future

        await self.ws.send(json.dumps(message))

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response.get("payload", {})
        except asyncio.TimeoutError:
            self._callbacks.pop(msg_id, None)
            raise TimeoutError(f"Timeout na requisição {uri}")

    async def subscribe(self, uri: str, callback: Callable) -> str:
        """Inscreve para receber eventos de mudança de estado."""
        if not self.is_connected:
            raise ConnectionError("Não conectado à TV.")

        msg_id = self._make_id()
        message = {"type": "subscribe", "id": msg_id, "uri": uri}

        self._subscriptions[msg_id] = callback
        await self.ws.send(json.dumps(message))
        return msg_id

    # ─── Métodos de conveniência ────────────────────────────────

    async def get_volume(self) -> dict:
        return await self.request(SSAP["get_volume"])

    async def set_volume(self, level: int) -> dict:
        return await self.request(SSAP["set_volume"], {"volume": level})

    async def volume_up(self) -> dict:
        return await self.request(SSAP["volume_up"])

    async def volume_down(self) -> dict:
        return await self.request(SSAP["volume_down"])

    async def set_mute(self, mute: bool) -> dict:
        return await self.request(SSAP["set_mute"], {"mute": mute})

    async def power_off(self) -> dict:
        return await self.request(SSAP["power_off"])

    async def get_apps(self) -> list:
        result = await self.request(SSAP["get_apps"])
        return result.get("apps", [])

    async def launch_app(self, app_id: str, params: dict | None = None) -> dict:
        payload = {"id": app_id}
        if params:
            payload["params"] = params
        return await self.request(SSAP["launch_app"], payload)

    async def close_app(self, app_id: str) -> dict:
        return await self.request(SSAP["close_app"], {"id": app_id})

    async def get_foreground_app(self) -> dict:
        return await self.request(SSAP["get_foreground"])

    async def get_inputs(self) -> list:
        result = await self.request(SSAP["get_inputs"])
        return result.get("devices", [])

    async def set_input(self, input_id: str) -> dict:
        return await self.request(SSAP["set_input"], {"inputId": input_id})

    async def get_channels(self) -> list:
        result = await self.request(SSAP["get_channels"])
        return result.get("channelList", [])

    async def get_current_channel(self) -> dict:
        return await self.request(SSAP["get_current_channel"])

    async def set_channel(self, channel_id: str) -> dict:
        return await self.request(SSAP["set_channel"], {"channelId": channel_id})

    async def channel_up(self) -> dict:
        return await self.request(SSAP["channel_up"])

    async def channel_down(self) -> dict:
        return await self.request(SSAP["channel_down"])

    async def play(self) -> dict:
        return await self.request(SSAP["play"])

    async def pause(self) -> dict:
        return await self.request(SSAP["pause"])

    async def stop(self) -> dict:
        return await self.request(SSAP["stop"])

    async def rewind(self) -> dict:
        return await self.request(SSAP["rewind"])

    async def fast_forward(self) -> dict:
        return await self.request(SSAP["fast_forward"])

    async def toast(self, message: str) -> dict:
        return await self.request(SSAP["toast"], {"message": message})

    async def get_services(self) -> list:
        result = await self.request(SSAP["get_services"])
        return result.get("services", [])

    async def get_system_info(self) -> dict:
        return await self.request(SSAP["get_system_info"])

    async def get_sw_info(self) -> dict:
        return await self.request(SSAP["get_sw_info"])

    async def get_power_state(self) -> dict:
        return await self.request(SSAP["power_state"])

    async def screen_off(self) -> dict:
        return await self.request(SSAP["screen_off"])

    async def screen_on(self) -> dict:
        return await self.request(SSAP["screen_on"])

    @staticmethod
    def wake_on_lan(mac: str, broadcast: str = "255.255.255.255", port: int = 9):
        """Envia Magic Packet (WOL) para ligar a TV.
        
        Args:
            mac: Endereço MAC da TV (ex: 'AC:5A:F0:C4:DD:F2')
            broadcast: Endereço de broadcast da rede
            port: Porta UDP (padrão 9)
        """
        mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
        if len(mac_bytes) != 6:
            raise ValueError(f"MAC inválido: {mac}")
        # Magic Packet: 6x 0xFF + 16x MAC
        packet = b"\xff" * 6 + mac_bytes * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, (broadcast, port))
        logger.info(f"Magic Packet enviado para {mac} via {broadcast}:{port}")

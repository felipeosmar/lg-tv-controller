"""
LG TV Controller — Dashboard Web para controle da TV LG 65UQ8050PSB.
Sprint 1: Conexão, volume, mute, power, apps, inputs, controles de mídia.
Sprint 3: Server-Sent Events (SSE) com subscriptions SSAP em tempo real.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import aiohttp_jinja2
import jinja2
from aiohttp import web

import ssl as _ssl

import aiohttp as _aiohttp

from presets import load_presets, save_presets, get_preset, add_preset, remove_preset
from tv_client import LGTVClient, APP_IDS, SSAP

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TV_HOST = os.environ.get("TV_HOST", "192.168.15.3")
TV_PORT = int(os.environ.get("TV_PORT", "3001"))
TV_MAC = os.environ.get("TV_MAC", "AC:5A:F0:C4:DD:F2")
WEB_PORT = int(os.environ.get("WEB_PORT", "8888"))

tv = LGTVClient(TV_HOST, TV_PORT)

# ─── SSE: Gerenciamento de clientes conectados ──────────────

sse_clients: set[web.StreamResponse] = set()
_subscriptions_active = False
_subscription_ids: list[str] = []


async def sse_broadcast(event: str, data: dict):
    """Envia evento SSE para todos os clientes conectados."""
    payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    dead = set()
    for client in sse_clients:
        try:
            await client.write(payload.encode("utf-8"))
        except (ConnectionResetError, ConnectionError, Exception):
            dead.add(client)
    for d in dead:
        sse_clients.discard(d)


async def setup_subscriptions():
    """Inscreve nos eventos SSAP da TV e faz broadcast via SSE."""
    global _subscriptions_active, _subscription_ids

    if _subscriptions_active or not tv.is_connected:
        return

    _subscription_ids = []

    async def _sub(uri, event_name, extractor):
        try:
            def callback(msg):
                return sse_broadcast(event_name, extractor(msg.get("payload", {})))
            sid = await tv.subscribe(uri, callback)
            _subscription_ids.append(sid)
            logger.info(f"Subscribed: {event_name} ({uri})")
        except Exception as e:
            logger.warning(f"Falha ao subscribir {event_name}: {e}")

    await _sub(
        SSAP["get_volume"], "volume",
        lambda p: {"volume": p.get("volume", 0), "muted": p.get("muted", False)}
    )
    await _sub(
        SSAP["get_current_channel"], "channel",
        lambda p: {
            "channelId": p.get("channelId", ""),
            "channelName": p.get("channelName", ""),
            "channelNumber": p.get("channelNumber", ""),
        }
    )
    await _sub(
        SSAP["get_foreground"], "foreground",
        lambda p: {"appId": p.get("appId", ""), "processId": p.get("processId", "")}
    )
    await _sub(
        SSAP["power_state"], "power",
        lambda p: {"state": p.get("state", "Unknown"), "processing": p.get("processing", "")}
    )

    _subscriptions_active = True
    logger.info(f"Subscriptions ativas: {len(_subscription_ids)}")


def teardown_subscriptions():
    """Limpa estado de subscriptions (chamado no disconnect)."""
    global _subscriptions_active, _subscription_ids
    _subscriptions_active = False
    _subscription_ids = []


# ─── API Routes ─────────────────────────────────────────────

async def api_connect(request):
    """Conecta à TV."""
    try:
        ok = await tv.connect(timeout=15.0)
        if ok:
            await setup_subscriptions()
            await sse_broadcast("connection", {"connected": True})
        return web.json_response({"ok": ok, "message": "Conectado" if ok else "Falha na conexão"})
    except Exception as e:
        return web.json_response({"ok": False, "message": str(e)}, status=500)


async def api_disconnect(request):
    """Desconecta da TV."""
    teardown_subscriptions()
    await tv.disconnect()
    await sse_broadcast("connection", {"connected": False})
    return web.json_response({"ok": True, "message": "Desconectado"})


async def api_events(request):
    """SSE endpoint — stream de eventos em tempo real."""
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    sse_clients.add(response)
    logger.info(f"SSE client conectado ({len(sse_clients)} total)")

    # Envia estado atual como evento inicial
    init_data = {"connected": tv.is_connected}
    if tv.is_connected:
        try:
            vol = await tv.get_volume()
            init_data["volume"] = vol.get("volume", 0)
            init_data["muted"] = vol.get("muted", False)
        except Exception:
            pass
        try:
            fg = await tv.get_foreground_app()
            init_data["foreground_app"] = fg.get("appId", "")
        except Exception:
            pass
        try:
            ch = await tv.get_current_channel()
            init_data["channel"] = ch.get("channelName", "")
            init_data["channelNumber"] = ch.get("channelNumber", "")
        except Exception:
            pass

    await response.write(f"event: init\ndata: {json.dumps(init_data)}\n\n".encode("utf-8"))

    # Keep-alive loop
    try:
        while True:
            await asyncio.sleep(15)
            await response.write(b": keepalive\n\n")
    except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
        pass
    finally:
        sse_clients.discard(response)
        logger.info(f"SSE client desconectado ({len(sse_clients)} total)")

    return response


async def api_status(request):
    """Retorna o status atual da conexão e da TV."""
    data = {"connected": tv.is_connected}
    if tv.is_connected:
        try:
            vol = await tv.get_volume()
            data["volume"] = vol.get("volume", 0)
            data["muted"] = vol.get("muted", False)
        except Exception:
            pass
        try:
            fg = await tv.get_foreground_app()
            data["foreground_app"] = fg.get("appId", "")
        except Exception:
            pass
    return web.json_response(data)


async def api_volume(request):
    """GET: volume atual. POST: define volume."""
    if request.method == "GET":
        result = await tv.get_volume()
        return web.json_response(result)
    body = await request.json()
    action = body.get("action", "set")
    if action == "up":
        result = await tv.volume_up()
    elif action == "down":
        result = await tv.volume_down()
    elif action == "mute":
        result = await tv.set_mute(body.get("mute", True))
    else:
        result = await tv.set_volume(int(body.get("level", 10)))
    return web.json_response({"ok": True, "result": result})


async def api_power(request):
    """POST: desliga a TV."""
    body = await request.json()
    action = body.get("action", "off")
    if action == "off":
        result = await tv.power_off()
    elif action == "on":
        try:
            tv.wake_on_lan(TV_MAC)
            return web.json_response({"ok": True, "message": f"Magic Packet enviado para {TV_MAC}"})
        except Exception as e:
            return web.json_response({"ok": False, "message": str(e)}, status=500)
    elif action == "screen_off":
        result = await tv.screen_off()
    elif action == "screen_on":
        result = await tv.screen_on()
    else:
        return web.json_response({"ok": False, "message": "Ação inválida"}, status=400)
    return web.json_response({"ok": True, "result": result})


async def api_apps(request):
    """GET: lista apps. POST: lança ou fecha app."""
    if request.method == "GET":
        apps = await tv.get_apps()
        # Simplificar a lista
        simple = [{"id": a["id"], "title": a.get("title", a["id"]),
                    "icon": a.get("icon", "")} for a in apps]
        simple.sort(key=lambda x: x["title"].lower())
        return web.json_response(simple)
    body = await request.json()
    action = body.get("action", "launch")
    app_id = body.get("app_id", "")
    # Resolver alias
    app_id = APP_IDS.get(app_id, app_id)
    if action == "launch":
        # Netflix deep link com auto-play
        if app_id in ("netflix", "netflix") and body.get("title_id"):
            auto_play = body.get("auto_play", True)
            result = await tv.launch_netflix(body["title_id"], auto_play=auto_play)
            return web.json_response({"ok": True, "result": result, "auto_play": auto_play})
        params = body.get("params")
        result = await tv.launch_app(app_id, params=params)
    elif action == "close":
        result = await tv.close_app(app_id)
    else:
        return web.json_response({"ok": False, "message": "Ação inválida"}, status=400)
    return web.json_response({"ok": True, "result": result})


async def api_inputs(request):
    """GET: lista inputs. POST: troca input."""
    if request.method == "GET":
        inputs = await tv.get_inputs()
        simple = [{"id": i["id"], "label": i.get("label", i["id"]),
                    "icon": i.get("icon", ""), "connected": i.get("connected", False)}
                   for i in inputs]
        return web.json_response(simple)
    body = await request.json()
    input_id = body.get("input_id", "")
    result = await tv.set_input(input_id)
    return web.json_response({"ok": True, "result": result})


async def api_channels(request):
    """GET: lista canais. POST: troca canal."""
    if request.method == "GET":
        channels = await tv.get_channels()
        simple = [{"id": c.get("channelId", ""), "number": c.get("channelNumber", ""),
                    "name": c.get("channelName", "")} for c in channels]
        return web.json_response(simple)
    body = await request.json()
    action = body.get("action", "set")
    if action == "up":
        result = await tv.channel_up()
    elif action == "down":
        result = await tv.channel_down()
    else:
        result = await tv.set_channel(body.get("channel_id", ""))
    return web.json_response({"ok": True, "result": result})


async def api_media(request):
    """POST: controles de mídia (play, pause, stop, rw, ff)."""
    body = await request.json()
    action = body.get("action", "play")
    actions = {
        "play": tv.play, "pause": tv.pause, "stop": tv.stop,
        "rewind": tv.rewind, "fast_forward": tv.fast_forward,
    }
    fn = actions.get(action)
    if not fn:
        return web.json_response({"ok": False, "message": "Ação inválida"}, status=400)
    result = await fn()
    return web.json_response({"ok": True, "result": result})


async def api_toast(request):
    """POST: envia notificação toast na TV."""
    body = await request.json()
    message = body.get("message", "Hello from LG TV Controller!")
    result = await tv.toast(message)
    return web.json_response({"ok": True, "result": result})


async def api_remote(request):
    """POST: comandos do controle remoto (botões, cursor, texto)."""
    body = await request.json()
    action = body.get("action", "")

    if action == "button":
        name = body.get("name", "").upper()
        await tv.send_button(name)
        return web.json_response({"ok": True, "button": name})
    elif action == "move":
        dx = int(body.get("dx", 0))
        dy = int(body.get("dy", 0))
        await tv.pointer_move(dx, dy)
        return web.json_response({"ok": True})
    elif action == "click":
        await tv.pointer_click()
        return web.json_response({"ok": True})
    elif action == "scroll":
        dy = int(body.get("dy", 0))
        await tv.pointer_scroll(dy=dy)
        return web.json_response({"ok": True})
    elif action == "text":
        text = body.get("text", "")
        result = await tv.send_text(text)
        return web.json_response({"ok": True, "result": result})
    elif action == "enter":
        result = await tv.send_enter()
        return web.json_response({"ok": True, "result": result})
    elif action == "delete":
        count = int(body.get("count", 1))
        result = await tv.send_delete(count)
        return web.json_response({"ok": True, "result": result})
    else:
        return web.json_response({"ok": False, "message": "Ação inválida"}, status=400)


async def api_screenshot(request):
    """GET: captura screenshot da TV e retorna a imagem como proxy."""
    try:
        image_url = await tv.screenshot()
        if not image_url:
            return web.json_response({"ok": False, "message": "Falha ao capturar screenshot"}, status=500)

        # Proxy the image (TV uses self-signed cert)
        ssl_ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE
        connector = _aiohttp.TCPConnector(ssl=ssl_ctx)
        async with _aiohttp.ClientSession(connector=connector) as session:
            async with session.get(image_url, timeout=_aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return web.Response(
                        body=data,
                        content_type=resp.content_type or "image/jpeg",
                        headers={"Cache-Control": "no-cache"},
                    )
                else:
                    return web.json_response(
                        {"ok": False, "message": f"TV retornou status {resp.status}"},
                        status=502,
                    )
    except ConnectionError as e:
        return web.json_response({"ok": False, "message": str(e)}, status=503)
    except Exception as e:
        logger.exception("Erro no screenshot")
        return web.json_response({"ok": False, "message": str(e)}, status=500)


async def api_presets(request):
    """GET: lista presets. POST: executa, cria ou deleta preset."""
    if request.method == "GET":
        return web.json_response(load_presets())

    body = await request.json()
    action = body.get("action", "execute")

    if action == "execute":
        preset_id = body.get("id", "")
        preset = get_preset(preset_id)
        if not preset:
            return web.json_response({"ok": False, "message": f"Preset '{preset_id}' não encontrado"}, status=404)

        results = []
        for act in preset.get("actions", []):
            try:
                act_type = act.get("type", "")
                if act_type == "app":
                    await tv.launch_app(act["app_id"])
                    results.append(f"App {act['app_id']} lançado")
                elif act_type == "volume":
                    await tv.set_volume(int(act["level"]))
                    results.append(f"Volume → {act['level']}")
                elif act_type == "mute":
                    await tv.set_mute(act.get("mute", True))
                    results.append(f"Mute → {act.get('mute')}")
                elif act_type == "input":
                    await tv.set_input(act["input_id"])
                    results.append(f"Input → {act['input_id']}")
                elif act_type == "power":
                    if act.get("action") == "off":
                        await tv.power_off()
                        results.append("TV desligada")
                    elif act.get("action") == "screen_off":
                        await tv.screen_off()
                        results.append("Tela desligada")
                elif act_type == "channel":
                    await tv.set_channel(act["channel_id"])
                    results.append(f"Canal → {act['channel_id']}")
                elif act_type == "button":
                    await tv.send_button(act["name"])
                    results.append(f"Botão {act['name']}")
                await asyncio.sleep(0.5)  # Pausa entre ações
            except Exception as e:
                results.append(f"Erro: {e}")
        return web.json_response({"ok": True, "preset": preset["name"], "results": results})

    elif action == "save":
        preset = body.get("preset", {})
        if not preset.get("id") or not preset.get("name"):
            return web.json_response({"ok": False, "message": "ID e nome são obrigatórios"}, status=400)
        presets = add_preset(preset)
        return web.json_response({"ok": True, "presets": presets})

    elif action == "delete":
        preset_id = body.get("id", "")
        presets = remove_preset(preset_id)
        return web.json_response({"ok": True, "presets": presets})

    return web.json_response({"ok": False, "message": "Ação inválida"}, status=400)


async def api_info(request):
    """GET: informações do sistema e serviços."""
    data = {}
    try:
        data["system"] = await tv.get_system_info()
    except Exception as e:
        data["system_error"] = str(e)
    try:
        data["sw_info"] = await tv.get_sw_info()
    except Exception:
        pass  # 401 no webOS 22
    try:
        svc = await tv.get_services()
        data["services"] = [s.get("name", "") for s in svc]
    except Exception:
        pass
    try:
        fg = await tv.get_foreground_app()
        data["foreground"] = fg
    except Exception:
        pass
    return web.json_response(data)


# ─── Middleware de erro ──────────────────────────────────────

@web.middleware
async def error_middleware(request, handler):
    try:
        return await handler(request)
    except ConnectionError as e:
        return web.json_response({"ok": False, "message": f"TV desconectada: {e}"}, status=503)
    except TimeoutError as e:
        return web.json_response({"ok": False, "message": f"Timeout: {e}"}, status=504)
    except Exception as e:
        logger.exception("Erro inesperado")
        return web.json_response({"ok": False, "message": str(e)}, status=500)


# ─── Dashboard HTML ──────────────────────────────────────────

@aiohttp_jinja2.template("dashboard.html")
async def dashboard(request):
    return {"tv_host": TV_HOST, "web_port": WEB_PORT}


# ─── App setup ───────────────────────────────────────────────

def create_app():
    app = web.Application(middlewares=[error_middleware])

    # Templates
    templates_dir = Path(__file__).parent / "templates"
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(str(templates_dir)))

    # Static files
    static_dir = Path(__file__).parent / "static"
    app.router.add_static("/static", str(static_dir), name="static")

    # Routes
    app.router.add_get("/", dashboard)
    app.router.add_get("/api/events", api_events)
    app.router.add_post("/api/connect", api_connect)
    app.router.add_post("/api/disconnect", api_disconnect)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/volume", api_volume)
    app.router.add_post("/api/volume", api_volume)
    app.router.add_post("/api/power", api_power)
    app.router.add_get("/api/apps", api_apps)
    app.router.add_post("/api/apps", api_apps)
    app.router.add_get("/api/inputs", api_inputs)
    app.router.add_post("/api/inputs", api_inputs)
    app.router.add_get("/api/channels", api_channels)
    app.router.add_post("/api/channels", api_channels)
    app.router.add_post("/api/media", api_media)
    app.router.add_post("/api/toast", api_toast)
    app.router.add_post("/api/remote", api_remote)
    app.router.add_get("/api/screenshot", api_screenshot)
    app.router.add_get("/api/presets", api_presets)
    app.router.add_post("/api/presets", api_presets)
    app.router.add_get("/api/info", api_info)

    return app


if __name__ == "__main__":
    app = create_app()
    logger.info(f"Dashboard em http://0.0.0.0:{WEB_PORT}")
    web.run_app(app, host="0.0.0.0", port=WEB_PORT)

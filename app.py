"""
LG TV Controller — Dashboard Web para controle da TV LG 65UQ8050PSB.
Sprint 1: Conexão, volume, mute, power, apps, inputs, controles de mídia.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import aiohttp_jinja2
import jinja2
from aiohttp import web

from tv_client import LGTVClient, APP_IDS, SSAP

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TV_HOST = os.environ.get("TV_HOST", "192.168.15.3")
TV_PORT = int(os.environ.get("TV_PORT", "3001"))
TV_MAC = os.environ.get("TV_MAC", "AC:5A:F0:C4:DD:F2")
WEB_PORT = int(os.environ.get("WEB_PORT", "8888"))

tv = LGTVClient(TV_HOST, TV_PORT)


# ─── API Routes ─────────────────────────────────────────────

async def api_connect(request):
    """Conecta à TV."""
    try:
        ok = await tv.connect(timeout=15.0)
        return web.json_response({"ok": ok, "message": "Conectado" if ok else "Falha na conexão"})
    except Exception as e:
        return web.json_response({"ok": False, "message": str(e)}, status=500)


async def api_disconnect(request):
    """Desconecta da TV."""
    await tv.disconnect()
    return web.json_response({"ok": True, "message": "Desconectado"})


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
        result = await tv.launch_app(app_id)
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
    app.router.add_get("/api/info", api_info)

    return app


if __name__ == "__main__":
    app = create_app()
    logger.info(f"Dashboard em http://0.0.0.0:{WEB_PORT}")
    web.run_app(app, host="0.0.0.0", port=WEB_PORT)

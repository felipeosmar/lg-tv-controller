# LG TV Controller 📺

Dashboard web para controle da TV LG webOS via protocolo SSAP/WebSocket.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## Funcionalidades

- ⚡ Conexão WebSocket com autenticação SSAP e persistência de client-key
- 🔊 Controle de volume (slider, +/-, mute)
- 📺 Power (desligar, tela off/on)
- 🎬 Apps rápidos (Netflix, YouTube, Prime Video, Disney+, Spotify, etc.)
- 📱 Lista completa de apps instalados
- 🔌 Entradas HDMI (1, 2, 3)
- 📡 Canais (lista, up/down, seleção direta)
- ⏯️ Controles de mídia (play, pause, stop, rewind, fast forward)
- 💬 Toast notifications (limitado no webOS 22+)
- ℹ️ Informações do sistema (modelo, serial, serviços)
- ⌨️ Atalhos de teclado (setas, M=mute, espaço=pause)
- 📊 Auto-refresh de status a cada 5s

## Screenshots

Dashboard dark theme com Bootstrap 5, otimizado para desktop e mobile.

## Requisitos

- Python 3.10+
- TV LG webOS (testado com 65UQ8050PSB / webOS 22)
- TV e servidor na mesma rede local
- "LG Connect Apps" ativado na TV

## Instalação

```bash
git clone https://github.com/felipeosmar/lg-tv-controller.git
cd lg-tv-controller
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
# Iniciar (padrão: porta 8888)
python app.py

# Com IP e porta customizados
TV_HOST=192.168.1.100 WEB_PORT=9000 python app.py
```

Acesse `http://localhost:8888` no navegador.

Na primeira conexão, a TV exibirá um popup pedindo autorização. Após aceitar, a client-key é salva automaticamente em `.tv_client_key`.

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `TV_HOST` | `192.168.15.3` | IP da TV na rede local |
| `TV_PORT` | `3001` | Porta WebSocket (3001=SSL, 3000=HTTP) |
| `WEB_PORT` | `8888` | Porta do dashboard web |

## Systemd Service (opcional)

```ini
[Unit]
Description=LG TV Controller Dashboard
After=network.target

[Service]
Type=simple
User=seu_usuario
WorkingDirectory=/caminho/para/lg-tv-controller
ExecStart=/caminho/para/lg-tv-controller/start.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

## Arquitetura

- **`tv_client.py`** — Cliente SSAP/WebSocket (descoberta, autenticação, controle)
- **`app.py`** — Servidor web aiohttp com API REST
- **`templates/dashboard.html`** — Dashboard Bootstrap 5 (dark theme)

### API Endpoints

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/api/connect` | Conectar à TV |
| POST | `/api/disconnect` | Desconectar |
| GET | `/api/status` | Status (volume, mute, app atual) |
| GET/POST | `/api/volume` | Volume (get/set/up/down/mute) |
| POST | `/api/power` | Power (off, screen_off, screen_on) |
| GET/POST | `/api/apps` | Apps (listar/launch/close) |
| GET/POST | `/api/inputs` | Inputs HDMI (listar/trocar) |
| GET/POST | `/api/channels` | Canais (listar/set/up/down) |
| POST | `/api/media` | Mídia (play/pause/stop/rw/ff) |
| POST | `/api/toast` | Notificação toast |
| GET | `/api/info` | Info do sistema |

## Protocolo SSAP

O controle é feito via **Smart TV Software Access Protocol (SSAP)** sobre WebSocket (porta 3001/WSS). O cliente envia mensagens JSON com `type`, `id`, `uri` e `payload`. A TV responde de forma assíncrona.

Referência: [LG webOS SSAP Protocol](https://www.lg.com/us/support)

## Compatibilidade

Testado com:
- LG 65UQ8050PSB (webOS 22 / webOS 7.x)

Deve funcionar com qualquer TV LG webOS que suporte SSAP (modelos 2016+).

## Limitações

- **Toast/Notificações**: Bloqueadas no webOS 22+ por restrição de segurança
- **Ligar a TV**: Requer Wake-on-LAN (WOL) — não implementado ainda
- **Pointer/Cursor**: Emulação do Magic Remote — planejado para sprint futura

## License

MIT

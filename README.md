# 🏡 Monitor de Imóveis OLX Brasil com Alertas no Telegram

Aplicação completa em Python assíncrono (**FastAPI** + **SQLAlchemy** + **APScheduler** + **HTTPX**) desenvolvida para monitorar novos anúncios de imóveis na OLX Brasil, persistir o histórico e disparar alertas em tempo real formatados diretamente no Telegram.

---

## 🚀 Principais Funcionalidades

- ⚡ **Scraping Assíncrono com HTTPX & BeautifulSoup4**: Extração limpa e de alta performance parseando diretamente o JSON embutido na tag `<script id="__NEXT_DATA__">` (`props.pageProps.ads`), evitando seletores CSS frágeis.
- 🤖 **Alertas Automáticos no Telegram**: Disparo de mensagens com imagem (`sendPhoto`) e link formatados com botões interativos (`inline_keyboard`).
- ⏱️ **Monitoramento Periódico com APScheduler**: Background task gerenciada diretamente pelo ciclo de vida (`lifespan`) do FastAPI, checando novos imóveis a cada $X$ minutos.
- 🗄️ **Persistência Assíncrona**: Suporte pronto para **SQLite** (`aiosqlite`) local ou **PostgreSQL** (`asyncpg`) com SQLAlchemy 2.0.
- 📊 **Painel Web (Jinja2)**: Dashboard moderno com estatísticas em tempo real, visualização em cards responsivos e botão para disparo manual sob demanda.
- 🔌 **API REST Completa**: Endpoints documentados com Swagger UI (`/docs`) e ReDoc (`/redoc`).
- 🐳 **Pronto para Produção**: `Dockerfile` e `docker-compose.yml` com persistência de volumes.

---

## 📂 Estrutura do Projeto

```text
imv-olx/
├── app/
│   ├── __init__.py
│   ├── config.py             # Configurações com Pydantic Settings
│   ├── database.py           # Engine assíncrona SQLAlchemy & Session Local
│   ├── models.py             # Modelos ORM (HouseAd) e Schemas Pydantic
│   ├── scraper.py            # Engine de extração do __NEXT_DATA__ da OLX
│   ├── telegram.py           # Serviço de notificações e integração com Bot API
│   ├── scheduler.py          # Agendador APScheduler no Lifespan context
│   ├── services.py           # Regras de negócio, deduplicação e sincronização
│   ├── api/
│   │   ├── __init__.py
│   │   └── router.py         # Endpoints REST (/api/houses, /api/status, etc.)
│   ├── templates/
│   │   └── index.html        # Painel Web interativo com Jinja2
│   └── main.py               # Inicialização da aplicação FastAPI
├── tests/
│   ├── __init__.py
│   ├── test_scraper.py       # Testes unitários do parser OLX
│   └── test_api.py           # Testes assíncronos da API FastAPI
├── .env.example              # Exemplo de configuração das variáveis
├── .gitignore
├── requirements.txt          # Dependências do projeto
├── Dockerfile                # Imagem Docker otimizada
├── docker-compose.yml        # Orquestração do container
└── README.md
```

---

## 🛠️ Configuração e Instalação

### 1. Pré-requisitos
- **Python 3.11+**
- (Opcional) **Docker & Docker Compose**

### 2. Clonar e Configurar Variáveis de Ambiente
Copie o arquivo `.env.example` para `.env`:

```bash
cp .env.example .env
```

Edite o arquivo `.env` com suas configurações:

```ini
# Banco de dados (SQLite local por padrão)
DATABASE_URL=sqlite+aiosqlite:///./data/houses.db

# Configurações do seu Bot no Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=-1001234567890

# URL de busca da OLX Brasil com seus filtros aplicados
OLX_SEARCH_URL=https://www.olx.com.br/imoveis/venda/casas/estado-sp/sao-paulo

# Intervalo de checagem automática (em minutos)
CHECK_INTERVAL_MINUTES=10

# Configurações do Servidor
APP_HOST=0.0.0.0
APP_PORT=8000
DEBUG=False
```

> **💡 Como obter as credenciais do Telegram:**
> 1. Inicie uma conversa com o [@BotFather](https://t.me/BotFather) no Telegram e crie seu bot com `/newbot` para obter o `TELEGRAM_BOT_TOKEN`.
> 2. Adicione o bot ao seu grupo/canal ou envie uma mensagem para ele no privado.
> 3. Use o bot [@userinfobot](https://t.me/userinfobot) ou faça uma requisição para `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` para obter seu `chat_id` numérico.

---

## 💻 Executando Localmente (Python)

1. Crie e ative um ambiente virtual:
   ```bash
   python -m venv venv
   # No Linux/macOS:
   source venv/bin/activate
   # No Windows:
   .\venv\Scripts\activate
   ```

2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

3. Inicie o servidor FastAPI:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. Acesse:
   - **Painel Web:** [http://localhost:8000](http://localhost:8000)
   - **Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
   - **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 🐳 Executando com Docker Compose

Para subir a aplicação completa com persistência do banco em volume:

```bash
docker-compose up -d --build
```

Para visualizar os logs de monitoramento em tempo real:

```bash
docker-compose logs -f
```

---

## 📡 Endpoints da API REST

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Dashboard Web (HTML Jinja2) com cards dos imóveis e estatísticas |
| `GET` | `/api/houses` | Listagem paginada de imóveis com filtros (`min_price`, `max_price`, `search`, `limit`, `offset`) |
| `GET` | `/api/houses/{id}` | Detalhes completos de um imóvel específico pelo ID interno |
| `POST` | `/api/monitor/trigger` | Dispara manualmente a checagem da OLX e envio de alertas (`sync_now=true/false`) |
| `GET` | `/api/status` | Retorna o status de execução, total de imóveis e timestamp do último scrape |

---

## 🧪 Executando os Testes Automatizados

O projeto conta com suite de testes cobrindo o parser de JSON da OLX e todos os endpoints da API:

```bash
pytest -v
```

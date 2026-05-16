# 📄 Памятка для разработчиков: Интеграция с Odoo 19.4a1 через API (Stateless Direct Execution)

## 📌 1. Контекст и статус

**Версия системы:** Odoo 19.4a1 Community (с модулями Roles и Nginx proxy).
**Проблема:** Стандартные эндпоинты авторизации (`/xmlrpc/2/common` и `/web/session/authenticate`) возвращают `AccessDenied` (`result: false`) при использовании валидных API-ключей.
**Статус решения:** Утвержден архитектурный обходной путь (Workaround) — **Direct JSON-RPC Execution**.

## 🚨 2. Директивы для AI (Cursor Rules)

*При написании любого кода для взаимодействия с Odoo в этом проекте, ИИ обязан строго следовать этим правилам:*

1. **ЗАПРЕЩЕНО** использовать методы `common.authenticate` или `/web/session/authenticate`.
2. **ЗАПРЕЩЕНО** использовать библиотеку `xmlrpc.client`. Все запросы должны идти через JSON-RPC с использованием библиотеки `requests`.
3. **ОБЯЗАТЕЛЬНО** использовать прямой вызов метода `execute_kw` к эндпоинту `/jsonrpc`.
4. **ОБЯЗАТЕЛЬНО** передавать учетные данные (Database, UID, API Key) непосредственно в теле каждого RPC-вызова `execute_kw`. UID должен быть задан явно (через `.env`), так как сервер не отдаст его через методы авторизации.

## 🐛 3. Корень проблемы (Root Cause - Для справки)

В сборке 19.4a1 архитектура авторизации сломана сторонними и системными модулями:

* **Модули 2FA (auth_totp_mail):** При stateless API-запросе ожидают наличия ключа `type` в словаре `credentials`, вызывая `KeyError`, если его нет.
* **Модули прав доступа (Roles):** Перехватывают метод `_login` и используют `self.sudo()`. Это сбрасывает контекст пользователя (например, с вашего `uid=2` на системный `uid=1`). Ядро Odoo проверяет API-ключ для `uid=1`, не находит его и блокирует доступ.

## 🛠 4. Архитектура решения (Stateless Direct Execution)

Чтобы обойти сломанный слой маршрутизации `_login`, мы работаем напрямую с Object-сервисом Odoo, самостоятельно собирая пакет `execute_kw`.

### Шаблон базового клиента (`odoo_client.py`)

Этот класс является эталонным для любых интеграций в рамках проекта:

```python
"""JSON-RPC клиент для Odoo (Direct execute_kw Bypass)."""
import requests
import logging

logger = logging.getLogger(__name__)

class OdooDirectClient:
    def __init__(self, url: str, db: str, uid: int, api_key: str):
        self.url = f"{url.rstrip('/')}/jsonrpc"
        self.db = db
        self.uid = uid          # Явно заданный UID (например, 2)
        self.api_key = api_key  # 40-значный API ключ
        self.session = requests.Session() # Для connection pooling
        self._id = 0

    def call(self, model: str, method: str, args: list = None, kwargs: dict = None):
        """Прямой вызов ORM методов в обход контроллера авторизации."""
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.db, 
                    self.uid, 
                    self.api_key, 
                    model, 
                    method, 
                    args or [], 
                    kwargs or {}
                ]
            }
        }
        
        try:
            response = self.session.post(self.url, json=payload, timeout=30).json()
        except requests.RequestException as e:
            logger.error(f"Network error: {e}")
            raise

        if "error" in response:
            error_msg = response["error"].get("data", {}).get("message", response["error"])
            raise RuntimeError(f"Odoo RPC Error: {error_msg}")
            
        return response.get("result")

    def test_connection(self) -> bool:
        """Метод для проверки валидности API-ключа без authenticate()."""
        try:
            result = self.call("res.users", "read", [[self.uid], ["name"]])
            if result:
                logger.info(f"✅ Успешное подключение. Пользователь: {result[0]['name']}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка проверки связи: {e}")
            return False

```

## ⚙️ 5. Переменные окружения (`.env`)

Для работы интеграции требуется наличие следующих переменных:

```ini
ODOO_URL=https://erp.arszap.ru
ODOO_DB=autoparts_arszap
ODOO_UID=2  # ВАЖНО: Целочисленный ID пользователя, сгенерировавшего ключ
ODOO_API_KEY=ваш_40_значный_ключ_без_пробелов

```

## 💡 6. Лучшие практики работы с каталогом

* **Первичный ключ:** При импорте товаров всегда использовать поле `default_code` в качестве первичного ключа для поиска записей (во избежание дублей).
* **Изображения:** Поле `image_1920` принимает строку формата `base64` (декодированную в `utf-8`).
* **Пакетная обработка:** Из-за особенностей ORM Odoo, при загрузке больших массивов данных (10k+ записей) рекомендуется загружать их чанками (например, по 100-500 штук), чтобы не упираться в таймауты Nginx.
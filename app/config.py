"""Конфигурация приложения."""

# Лимиты хранилища
MAX_BYTES = 140 * 1024 * 1024   # было 200, ставим 140
TTL_SECONDS = 60                        # свежесть данных из каталога
DELETED_TTL_SECONDS = 60 * 10           # сколько помнить «снятые» цитаты

# Каталог
CATALOG_TIMEOUT = 2.0                   # сек на один запрос в каталог
CATALOG_MAX_CONCURRENT = 1              # НЕ долбить каталог параллельно
CIRCUIT_FAIL_THRESHOLD = 5              # сколько ошибок подряд → разомкнуть
CIRCUIT_OPEN_SECONDS = 30               # сколько держать разомкнутым
CIRCUIT_DEFAULT_RETRY_AFTER = 5         # если 503 без Retry-After
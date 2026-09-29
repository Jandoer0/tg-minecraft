Задача: создать Telegram-бота для управления сервером Minecraft, развернутым через Podman Quadlet.

## Инфраструктура
- **Пользователь**: Бот работает под пользователем `podman-svc` как systemd user unit (`bot-minecraft.service`).
- **Пути**: 
  - Исходный код проекта: `/home/agent/projects/tg-minecraft`
  - Файлы бота на сервере: `/home/podman-svc/pod/bot-minecraft`
  - Данные Minecraft: `/mnt/library/containers/minecraft/data`
- **Зависимости**: Python venv внутри каталога бота.

## Контейнер Minecraft (Quadlet)
Юнит сервера Minecraft определен в `/home/podman-svc/.config/containers/systemd/minecraft-forge_1.container`:
- Image: `docker.io/itzg/minecraft-server:java17`
- Name: `minecraft-1`
- Port: `25565`
- Memory: `6g`
- Mode: Online Mode FALSE (для пиратских клиентов).

## Функционал бота
1. **Управление сервером**: Старт, Стоп, Рестарт (через `systemctl --user`).
2. **Управление картами**:
   - Просмотр списка карт (папок в `/data` с префиксом `world`).
   - Смена текущей карты с автоматическим рестартом сервера.
   - Создание новой карты (генерация имени $\rightarrow$ запись в `server.properties` $\rightarrow$ рестарт).
   - Удаление карты (удаление папки мира и сопутствующих папок _nether/_the_end).
3. **Мониторинг**: Список игроков в онлайне (через `podman exec rcon-cli list`).
4. **Безопасность**: Доступ только для пользователей из `TELEGRAM_ALLOWED_USERS` в `.env`.
5. **Интерфейс**: Русский язык, HTML-разметка для стабильности, интерактивное меню (FSM для создания карт).

## Развертывание и разработка
- **Скрипт `restart.sh`**: Выполняет полный цикл обновления: копирование файлов $\rightarrow$ обновление venv $\rightarrow$ перезапуск systemd-юнита.
- **Особенности**: Все операции с файлами внутри контейнера (например, смена карты) выполняются через `podman exec` для обхода проблем с правами доступа (UID mismatch).

Думай и отвечай на русском языке.

# Postfix Admin

Веб-панель для администрирования уже установленного Postfix без отдельной базы данных. Приложение работает с файлами в `/etc/postfix`, читает `/var/log/maillog`, вызывает `postmap`, `postfix check`, `postfix reload` и умеет управлять очередью.

Проект рассчитан на внутреннюю сеть: трафик идёт через Nginx по HTTPS, а доступ можно ограничить whitelist-ом IP.

## Что умеет

| Раздел | Назначение |
|--------|------------|
| `Dashboard` | Краткий статус Postfix, очереди, routing rules и статистики |
| `Configuration` | Просмотр и изменение ключевых параметров `main.cf` |
| `Transport` | Редактирование `/etc/postfix/transport` для маршрутизации по домену получателя |
| `Routing` | Маршрутизация по отправителю: relayhost/transport mode, SASL, TLS, bind IP |
| `Relay Hosts` | Просмотр используемых relay hosts, проверка порта, массовая замена |
| `Queue` | Просмотр очереди и операции `hold`, `release`, `requeue`, `delete` |
| `Statistics` | Сводка по `/var/log/maillog` |
| `Logs` | Последние строки maillog с фильтрами |
| `Users` | Учётные записи панели |
| `IP Whitelist` | Разрешённые адреса и сети |

Роль `user` имеет доступ на чтение к большей части интерфейса. Изменение конфигурации, очереди, пользователей и whitelist доступно только `admin`.

## Требования

- CentOS Stream 9 / Rocky Linux 9
- Уже установленный и настроенный Postfix
- Root для установки и запуска панели
- Nginx, Gunicorn, Python 3

Причина запуска от `root`: приложение должно читать и изменять файлы Postfix, выполнять `postmap`, `postfix reload` и `systemctl reload nginx`.

## Архитектура

```text
Browser -> HTTPS :443 -> Nginx -> HTTP 127.0.0.1:8000 -> Gunicorn -> Flask app.py
                                                          |
                                                          +-> /etc/postfix/main.cf
                                                          +-> /etc/postfix/transport
                                                          +-> /etc/postfix/sender_transport
                                                          +-> /etc/postfix/sender_sasl_passwd
                                                          +-> /var/log/maillog
```

Основные пути на сервере:

| Путь | Назначение |
|------|------------|
| `/opt/postfix-admin` | Код панели |
| `/opt/postfix-admin/users.json` | Пользователи |
| `/opt/postfix-admin/ip_whitelist.json` | Белый список IP |
| `/opt/postfix-admin/nginx-allow.conf` | Генерируемые `allow`/`deny` для Nginx |
| `/etc/systemd/system/postfix-admin.service` | Рабочий systemd unit |
| `/etc/nginx/conf.d/postfix-admin.conf` | Конфиг Nginx |

## Установка

```bash
git clone https://github.com/MerlKoryAmber/PostfixAdmin.git
cd PostfixAdmin
chmod +x deploy/install.sh
sudo ./deploy/install.sh
```

Что делает `deploy/install.sh`:

1. Устанавливает системные пакеты через `dnf`.
2. Копирует приложение в `/opt/postfix-admin`.
3. Не перезаписывает существующие sender maps Postfix, а создаёт их только при отсутствии.
4. Определяет активный режим sender routing из `main.cf`.
5. Генерирует self-signed TLS-сертификат для Nginx.
6. Создаёт и включает systemd unit `postfix-admin`.
7. Предлагает создать первого администратора.

После установки панель доступна по адресу:

```text
https://<server-ip>
```

Если используется self-signed сертификат, браузер покажет предупреждение. Для production замените `/etc/nginx/ssl/postfix-admin.crt` и `/etc/nginx/ssl/postfix-admin.key` на свои сертификаты и перезагрузите Nginx.

## Управление пользователями из CLI

Если администратора не создали во время установки:

```bash
cd /opt/postfix-admin
export FLASK_APP=app.py
export USERS_FILE=/opt/postfix-admin/users.json
flask create-user
flask list-users
```

## Sender Routing

Панель читает `main.cf` и выбирает один из двух режимов:

| Режим | Параметр | Формат записи |
|------|----------|---------------|
| `relayhost` (B) | `sender_dependent_relayhost_maps` | `[host]:port` |
| `transport` (A) | `sender_dependent_default_transport_maps` | `smtp:[host]:port` + опции |

Если заданы оба параметра, приоритет у `transport`.

### Рекомендуемый relayhost mode

```text
sender_dependent_relayhost_maps = hash:/etc/postfix/sender_transport
smtp_sender_dependent_authentication = yes
smtp_sasl_password_maps = hash:/etc/postfix/sender_sasl_passwd
```

Пример строки:

```text
user@example.com    [smtp.provider.com]:587
```

### Transport mode

Используется, когда для отдельных отправителей нужны дополнительные параметры, например TLS level или bind IP.

```text
sender_dependent_default_transport_maps = hash:/etc/postfix/sender_transport
```

Пример строки:

```text
user@example.com    smtp:[smtp.provider.com]:587 smtp_tls_security_level=encrypt
```

SASL-пароли хранятся в `/etc/postfix/sender_sasl_passwd` с правами `600`.

## Transport Map

Раздел `Transport` управляет `/etc/postfix/transport`, то есть маршрутизацией по домену получателя. Чтобы Postfix реально использовал этот файл, в `main.cf` должен быть настроен `transport_maps`, например:

```text
transport_maps = hash:/etc/postfix/transport
```

## Обновление

```bash
sudo /opt/postfix-admin/deploy/update.sh
```

Скрипт:

- создаёт бэкап в `/opt/postfix-admin-backup-<date>`;
- скачивает код из GitHub;
- обновляет `app.py`, шаблоны, статику и deploy-скрипты;
- перезапускает `postfix-admin`;
- не затирает `users.json` и `ip_whitelist.json`.

Важно: `update.sh` специально **не переписывает live systemd unit** в `/etc/systemd/system/postfix-admin.service`, чтобы не потерять рабочий `SECRET_KEY` и runtime-настройки. Актуальный пример unit-файла хранится в `deploy/postfix-admin.service` и копируется только как reference в `/opt/postfix-admin/deploy/postfix-admin.service`.

Если изменился `deploy/nginx-https.conf`, обновите `/etc/nginx/conf.d/postfix-admin.conf` вручную:

```bash
cp /opt/postfix-admin/deploy/nginx-https.conf /etc/nginx/conf.d/postfix-admin.conf
nginx -t && systemctl reload nginx
```

## Пример systemd unit

Файл `deploy/postfix-admin.service` является примером. Перед ручной установкой или заменой unit-файла:

- задайте свой случайный `SECRET_KEY`;
- проверьте путь к `gunicorn`;
- помните, что сервис должен иметь права на работу с файлами Postfix и на вызовы `postfix`/`postmap`.

## Удаление

```bash
sudo /opt/postfix-admin/deploy/uninstall.sh
```

Удаляется только панель, её сервис и конфиг Nginx. Сам Postfix и его карты маршрутизации не удаляются.

## Безопасность

- только HTTPS;
- CSRF на POST-формах;
- cookie с `Secure`, `HttpOnly`, `SameSite=Lax`;
- изменения выполняются только через POST;
- IP клиента берётся из `X-Real-IP`;
- конфиги записываются атомарно, резервные копии сохраняются как `*.bak`.

Если whitelist пустой, доступ разрешён всем. Как только в нём появляется хотя бы один IP или CIDR-сеть, все остальные адреса получают отказ.

## Репозиторий

```text
app.py
templates/
static/
requirements.txt
deploy/
  install.sh
  update.sh
  uninstall.sh
  nginx-https.conf
  postfix-admin.service
```

## Интерфейс (DESIGN.md)

Визуальный язык панели задан в корневом [`DESIGN.md`](DESIGN.md). Каталог вдохновений: [VoltAgent/awesome-claude-design](https://github.com/VoltAgent/awesome-claude-design), локальная копия в `vendor/awesome-claude-design/` (взят HashiCorp-inspired набор для infra/ops). Агенты Cursor читают skill `.cursor/skills/awesome-claude-design/` и правило `.cursor/rules/design.mdc`.

## Обслуживание

```bash
systemctl status postfix-admin
journalctl -u postfix-admin -n 50
systemctl restart postfix-admin
nginx -t && systemctl reload nginx
```

Если интерфейс не открывается, проверьте:

1. что ваш IP разрешён в whitelist;
2. что `postfix-admin` запущен;
3. что Nginx слушает `443`;
4. что Gunicorn слушает `127.0.0.1:8000`.

# Postfix Admin

Веб-панель для администрирования уже установленного Postfix. Конфигурация хранится в обычных файлах `/etc/postfix/` — отдельная база данных не нужна.

Панель рассчитана на внутреннюю сеть: доступ по HTTPS, Nginx как reverse proxy, опциональный IP whitelist.

## Возможности

| Раздел | Что делает |
|--------|------------|
| **Configuration** | Просмотр и изменение ключевых параметров `main.cf`, проверка и `postfix reload` |
| **Transport** | Карта `/etc/postfix/transport` — маршруты по домену |
| **Routing** | Маршрутизация по отправителю (relayhost или transport maps), SASL, TLS, bind IP, тест `postmap -q` |
| **Relay Hosts** | Список исходящих хостов, проверка порта, массовая замена |
| **Queue** | Очередь: hold / release / requeue / удаление, фильтр по отправителю и домену |
| **Statistics** | Сводка по `/var/log/maillog` за последние 24 часа |
| **Logs** | Последние 500 строк maillog с фильтром |
| **Users** | Учётные записи панели (роли `admin` и `user`) |
| **IP Whitelist** | Разрешённые сети на уровне Nginx и Flask |

Роль `user` может смотреть большинство разделов. Изменение конфигурации, маршрутов, очереди и пользователей — только `admin`.

## Требования

- CentOS Stream 9 / Rocky Linux 9 (скрипт ставит пакеты через `dnf`)
- Уже работающий Postfix
- Python 3.9+, Nginx, Gunicorn
- Root для установки (сервис панели запускается от root, чтобы читать и писать файлы Postfix)

Зависимости Python: Flask 3, Flask-Login, Flask-WTF, Gunicorn — см. `requirements.txt`.

## Архитектура

```
браузер  --HTTPS:443-->  Nginx  --HTTP:8000-->  Gunicorn (4 worker)  -->  app.py
                                              |
                                              +--> /etc/postfix/main.cf
                                              +--> /etc/postfix/transport
                                              +--> sender maps + postmap + postfix reload
                                              +--> /var/log/maillog
```

- Nginx слушает 80/443, редирект HTTP → HTTPS, TLS 1.2/1.3, HSTS
- Gunicorn слушает только `127.0.0.1:8000`
- Пользователи панели: `/opt/postfix-admin/users.json`
- IP whitelist: `/opt/postfix-admin/ip_whitelist.json` → генерируется `nginx-allow.conf`

Пустой whitelist означает «разрешить всем». Как только добавлен хотя бы один адрес или сеть (`1.2.3.4` или `10.0.0.0/8`), остальные клиенты получают отказ.

## Установка

На сервере с уже настроенным Postfix:

```bash
git clone https://github.com/MerlKoryAmber/PostfixAdmin.git
cd PostfixAdmin
chmod +x deploy/install.sh
sudo ./deploy/install.sh
```

Скрипт:

1. Ставит Python, Nginx, Gunicorn и зависимости
2. Копирует приложение в `/opt/postfix-admin`
3. **Не перезаписывает** существующие map-файлы Postfix — только создаёт пустые, если их нет
4. Определяет текущий режим sender routing из `main.cf`
5. Выпускает self-signed сертификат на 10 лет
6. Настраивает systemd-юнит `postfix-admin` и Nginx
7. Предлагает создать первого администратора

После установки:

```
https://<IP-сервера>
```

Браузер предупредит о self-signed сертификате — это ожидаемо. Для продакшена замените `/etc/nginx/ssl/postfix-admin.{crt,key}` на сертификат организации и перезагрузите Nginx.

### Пользователи из CLI

Если администратора не создали при установке:

```bash
cd /opt/postfix-admin
export FLASK_APP=app.py
export USERS_FILE=/opt/postfix-admin/users.json
flask create-user
flask list-users
```

Смена своего пароля — в меню профиля. Сброс чужого — в разделе Users (admin).

## Маршрутизация по отправителю

Панель читает `main.cf` и выбирает режим:

| Режим | Параметр в `main.cf` | Формат значения в map |
|-------|----------------------|------------------------|
| **B — relayhost** (по умолчанию) | `sender_dependent_relayhost_maps` | `[host]:port` |
| **A — transport** (приоритетнее, если задан) | `sender_dependent_default_transport_maps` | `smtp:[host]:port` + опции TLS/bind |

Если заданы оба параметра, используется режим A.

### Режим B (рекомендуемый для большинства серверов)

```
sender_dependent_relayhost_maps = hash:/etc/postfix/sender_transport
smtp_sender_dependent_authentication = yes
smtp_sasl_password_maps = hash:/etc/postfix/sender_sasl_passwd
```

Пример строки map: `user@example.com    [smtp.provider.com]:587`

SASL-логин и пароль пишутся в `/etc/postfix/sender_sasl_passwd` (права `600`), затем `postmap`.

### Режим A

Нужен, если для отдельных отправителей задаются TLS-уровень или исходящий IP:

```
sender_dependent_default_transport_maps = hash:/etc/postfix/sender_transport
```

Пример: `user@example.com    smtp:[smtp.provider.com]:587 smtp_tls_security_level=encrypt`

Переключение режима — в **Configuration**. После смены параметров выполните Reload Postfix.

Установка не меняет уже работающую маршрутизацию: если maps уже есть в `main.cf`, панель просто начнёт ими пользоваться.

## Обновление

```bash
sudo /opt/postfix-admin/deploy/update.sh
```

Скрипт качает код с GitHub, делает бэкап в `/opt/postfix-admin-backup-<дата>`, обновляет файлы и перезапускает сервис. `users.json` и `ip_whitelist.json` не затираются.

После обновления, если менялись зависимости:

```bash
pip3 install flask-wtf
systemctl restart postfix-admin
```

Если в новой версии изменился `deploy/nginx-https.conf`, скопируйте его в `/etc/nginx/conf.d/postfix-admin.conf` и выполните `nginx -t && systemctl reload nginx`.

## Удаление

```bash
sudo /opt/postfix-admin/deploy/uninstall.sh
```

Снимается только панель: systemd-юнит, `/opt/postfix-admin`, конфиг Nginx и self-signed сертификат. **Postfix, `main.cf` и routing maps сохраняются.** Опционально можно удалить пустые map-файлы, которые создал инсталлятор.

## Безопасность

- HTTPS обязателен; cookie: `Secure`, `HttpOnly`, `SameSite=Lax`
- CSRF на всех POST-формах (Flask-WTF)
- Мутации только через POST
- IP клиента берётся из `X-Real-IP` (Nginx выставляет `$remote_addr`, а не клиентский `X-Forwarded-For`)
- Запись конфигов атомарная, предыдущая версия остаётся в `*.bak`
- `users.json` и `sender_sasl_passwd` — режим `600`

Панель работает от root: ей нужны `postfix reload`, `postmap` и запись в `/etc/postfix`. Не выставляйте её в интернет без IP whitelist и корпоративного TLS.

## Структура репозитория

```
app.py                      # Flask-приложение
templates/                  # HTML
static/                     # CSS, шрифты, Bootstrap, favicon
requirements.txt
deploy/
  install.sh                # установка
  update.sh                 # обновление с GitHub
  uninstall.sh              # удаление панели
  nginx-https.conf          # vhost Nginx
  postfix-admin.service     # пример unit-файла
```

На сервере после установки:

| Путь | Назначение |
|------|------------|
| `/opt/postfix-admin` | Код панели |
| `/opt/postfix-admin/users.json` | Пользователи |
| `/opt/postfix-admin/ip_whitelist.json` | Белый список IP |
| `/opt/postfix-admin/nginx-allow.conf` | `allow`/`deny` для Nginx (генерируется) |
| `/etc/systemd/system/postfix-admin.service` | Сервис |
| `/etc/nginx/conf.d/postfix-admin.conf` | HTTPS vhost |

## Обслуживание

```bash
systemctl status postfix-admin
journalctl -u postfix-admin -n 50
systemctl restart postfix-admin
nginx -t && systemctl reload nginx
```

Gunicorn должен слушать `127.0.0.1:8000`, Nginx — `:443`. Если страница логина не открывается, проверьте, что ваш IP есть в whitelist и что `postfix-admin` / `nginx` запущены.

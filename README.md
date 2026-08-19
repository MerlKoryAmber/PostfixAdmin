# Postfix Admin

Веб-панель для уже установленного Postfix. Отдельной БД нет: читает и пишет файлы в `/etc/postfix`, хвост `/var/log/maillog`, вызывает `postmap`, `postfix check`, `postfix reload`, `postqueue` / `postsuper`.

Рассчитана на внутреннюю сеть: снаружи только HTTPS (Nginx :443), Gunicorn слушает `127.0.0.1:8000`. Доступ можно закрыть IP whitelist.

Сервис крутится от **root**: нужны права на `main.cf`, карты, `postmap`, `postfix reload`, `systemctl reload nginx`.

## Возможности

| Раздел | Назначение |
|--------|------------|
| Дашборд | Статус Postfix, очередь, routing, краткая статистика |
| Конфигурация | Ключевые параметры `main.cf` |
| Транспорт | `/etc/postfix/transport` — маршрут по домену получателя |
| Маршрутизация | Sender-dependent: relayhost или transport, SASL, TLS, bind IP |
| Релей-хосты | Уникальные relay, проверка порта, массовая замена |
| Очередь | hold / release / requeue / delete |
| Статистика | Сводка по `maillog` |
| Логи | Записи за **последние 24 часа**, фильтры по всему окну, пагинация (50/100/200 на страницу) |
| Пользователи | Учётные записи панели |
| IP Whitelist | `allow` в Nginx; пустой список = доступ всем |

Роль `user` — в основном чтение. Менять конфиг, очередь, пользователей и whitelist может только `admin`.

## Требования

- CentOS Stream 9 или Rocky Linux 9 (скрипт ставит пакеты через `dnf`)
- Postfix уже установлен и работает как почтовый сервер
- Root
- Открытые **443** (и **80** только для редиректа на HTTPS)
- Git, чтобы клонировать репозиторий на сервер

Скрипт сам поставит Python 3, Nginx и зависимости. Gunicorn ставится в venv `/opt/postfix-admin/venv`, не из системного rpm.

---

## Установка

Все команды — **на целевом сервере, от root**. Скрипт должен видеть корень репозитория (`app.py` рядом с каталогом `deploy/`). Не копируйте на сервер один только `install.sh`.

### 1. Клон и запуск

```bash
cd /usr/local/src
git clone https://github.com/MerlKoryAmber/PostfixAdmin.git
cd PostfixAdmin
chmod +x deploy/install.sh deploy/update.sh deploy/uninstall.sh
sudo ./deploy/install.sh
```

Если репозиторий уже лежит в другом каталоге — `cd` туда и тот же `sudo ./deploy/install.sh`.

### 2. Что делает `deploy/install.sh`

1. `dnf`: epel, python3, postfix, nginx, openssl, nmap-ncat, curl и связанное.
2. Системный пользователь `postfixadmin` (nologin). Код панели — от него по файлам; **процесс Gunicorn — User=root**.
3. Копирует в `/opt/postfix-admin` только runtime: `app.py`, `templates/`, `static/`, `requirements.txt`, скрипты `deploy/`. Каталоги `vendor/`, `.cursor/`, `DESIGN.md` на хост не кладутся.
4. Спрашивает **название компании** (шапка, логин, футер). Пустой ввод = `Postfix Admin`. Пишет `/opt/postfix-admin/brand.json`. Повторная установка предлагает оставить прежнее имя.
5. Создаёт venv `/opt/postfix-admin/venv` и ставит пакеты из `requirements.txt` (Flask 3, flask-login, flask-wtf, gunicorn).
6. Не затирает существующие `/etc/postfix/sender_transport` и `sender_sasl_passwd`; пустые файлы создаёт только если их нет, затем `postmap`.
7. Смотрит `main.cf` (`postconf`) и печатает режим sender routing.
8. TLS: если **оба** файла `/etc/nginx/ssl/postfix-admin.crt` и `.key` уже есть — оставляет. Если есть только один — **остановка**. Если нет ни одного — self-signed на 10 лет, CN = первый IP хоста, O = название компании.
9. Пишет `/opt/postfix-admin/nginx-allow.conf` (если файла нет: `allow all`), кладёт Nginx-конфиг в `/etc/nginx/conf.d/postfix-admin.conf`, удаляет `default.conf`, `nginx -t`.
10. systemd unit `/etc/systemd/system/postfix-admin.service`: Gunicorn из venv, `127.0.0.1:8000`, `USERS_FILE`, `SECRET_KEY` (новый или прежний, если unit уже был).
11. Сохраняет существующие `users.json` и `ip_whitelist.json`.
12. `firewall-cmd` — сервисы http/https (если firewalld есть).
13. `systemctl enable --now postfix-admin`, **restart** nginx.
14. Спрашивает, создать ли первого admin (`venv/bin/flask create-user`).

Повторный запуск install с тем же деревом — переустановка поверх; ключ и TLS при полных парах не сбрасываются. Название компании можно сменить в том же диалоге или правкой `/opt/postfix-admin/brand.json` и `systemctl restart postfix-admin`.

### 3. После скрипта

```text
https://<IP-сервера>
```

Self-signed — предупреждение браузера. Для нормального TLS замените пару в `/etc/nginx/ssl/` и:

```bash
nginx -t && systemctl reload nginx
```

Создать администратора, если на шаге 13 ответили нет:

```bash
cd /opt/postfix-admin
export FLASK_APP=app.py
export USERS_FILE=/opt/postfix-admin/users.json
/opt/postfix-admin/venv/bin/flask create-user
/opt/postfix-admin/venv/bin/flask list-users
chown postfixadmin:postfixadmin /opt/postfix-admin/users.json
chmod 600 /opt/postfix-admin/users.json
```

Системный `flask` без venv не использовать — там не будет зависимостей панели.

### 4. Проверка

```bash
systemctl is-active postfix-admin nginx postfix
ss -tln | grep -E ':443|:8000'
curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1/login
journalctl -u postfix-admin -n 30 --no-pager
```

Ожидание: 443 и 8000 слушают, gunicorn отвечает редиректом или 200 на `/login`.

### 5. Типичные срывы установки

| Симптом | Что смотреть |
|---------|----------------|
| `Source file not found: …/app.py` | Запуск не из checkout репозитория |
| `ModuleNotFoundError: flask_login` | Старый unit без venv; нужен install/update, который ставит `/opt/postfix-admin/venv` |
| Nginx `-t` fail, нет `nginx-allow.conf` | Скрипт новой версии создаёт файл **до** `nginx -t`; не используйте обрезанный install |
| 443 не слушает | `systemctl restart nginx`, не только `start` |
| 403 / пустая страница с другого IP | Непустой whitelist: свой IP должен быть в списке |
| Только crt или только key | Добить пару вручную; install не генерирует вторую половину поверх обломка |

---

## Обновление

```bash
sudo /opt/postfix-admin/deploy/update.sh
```

Скрипт качает [MerlKoryAmber/PostfixAdmin](https://github.com/MerlKoryAmber/PostfixAdmin) (релиз / `main` / тег), бэкап в `/opt/postfix-admin-backup-<дата>`, останавливает сервис, копирует выбранное (всё / только app / templates+static вместе / deploy), обновляет venv по `requirements.txt`, стартует сервис. `users.json`, whitelist и `brand.json` не затираются.

Live unit `/etc/systemd/system/postfix-admin.service` **не переписывается** (SECRET_KEY). Образец лежит в `/opt/postfix-admin/deploy/postfix-admin.service`.

Если в релизе менялся Nginx-шаблон:

```bash
cp /opt/postfix-admin/deploy/nginx-https.conf /etc/nginx/conf.d/postfix-admin.conf
nginx -t && systemctl reload nginx
```

Откат из бэкапа — в хвосте вывода `update.sh`.

## Удаление

```bash
sudo /opt/postfix-admin/deploy/uninstall.sh
```

Снимает unit, `/opt/postfix-admin`, `postfix-admin.conf` у Nginx. Postfix и `main.cf` не трогает. По запросу: пустые map-файлы панели, TLS-пара, правила firewalld http/https, пользователь `postfixadmin`.

---

## Архитектура

```text
Браузер --HTTPS:443--> Nginx --127.0.0.1:8000--> gunicorn (venv) --> app.py
                                                              |
                                                              +-- /etc/postfix/main.cf
                                                              +-- /etc/postfix/transport
                                                              +-- /etc/postfix/sender_transport
                                                              +-- /etc/postfix/sender_sasl_passwd
                                                              +-- /var/log/maillog
```

| Путь | Назначение |
|------|------------|
| `/opt/postfix-admin` | Код, venv, json, nginx-allow |
| `/opt/postfix-admin/brand.json` | Название компании в UI |
| `/opt/postfix-admin/users.json` | Пользователи панели (`600`) |
| `/opt/postfix-admin/ip_whitelist.json` | Белый список IP |
| `/opt/postfix-admin/nginx-allow.conf` | `allow`/`deny` для Nginx |
| `/opt/postfix-admin/venv` | Python-зависимости |
| `/etc/systemd/system/postfix-admin.service` | Рабочий unit |
| `/etc/nginx/conf.d/postfix-admin.conf` | HTTPS vhost |
| `/etc/nginx/ssl/postfix-admin.crt` / `.key` | TLS панели |

## Sender routing

Панель смотрит `main.cf`. Если заданы оба map — берётся **transport**.

| Режим | Параметр | Пример значения в карте |
|------|----------|-------------------------|
| relayhost (B) | `sender_dependent_relayhost_maps` | `[host]:587` |
| transport (A) | `sender_dependent_default_transport_maps` | `smtp:[host]:587` плюс опции |

Рекомендуемый relayhost:

```text
sender_dependent_relayhost_maps = hash:/etc/postfix/sender_transport
smtp_sender_dependent_authentication = yes
smtp_sasl_password_maps = hash:/etc/postfix/sender_sasl_passwd
```

```text
user@example.com    [smtp.provider.com]:587
```

Transport, если нужны TLS/bind на отправителя:

```text
sender_dependent_default_transport_maps = hash:/etc/postfix/sender_transport
```

```text
user@example.com    smtp:[smtp.provider.com]:587 smtp_tls_security_level=encrypt
```

SASL: `/etc/postfix/sender_sasl_passwd`, права `600`.

Раздел «Транспорт» правит `/etc/postfix/transport`. Чтобы Postfix это использовал:

```text
transport_maps = hash:/etc/postfix/transport
```

## Безопасность

- только HTTPS, HSTS, CSRF на POST;
- cookie `Secure`, `HttpOnly`, `SameSite=Lax`;
- IP клиента для whitelist — `X-Real-IP` (его ставит Nginx);
- конфиги пишутся атомарно, рядом `*.bak`;
- смена TLS панели: Конфигурация → файлы ключа и сертификата/цепочки (PEM). Проверка соответствия ключа, `nginx -t`, затем reload. Старая пара остаётся как `.bak`.

Пустой whitelist = пускать всех. Любая запись (IP или CIDR) — остальные режутся Nginx.

Секреты (`SECRET_KEY`, пароли SASL, `users.json`, ключ TLS) в git не класть.

## Обслуживание

```bash
systemctl status postfix-admin
journalctl -u postfix-admin -n 50 --no-pager
systemctl restart postfix-admin
nginx -t && systemctl reload nginx
```

Панель не открывается:

1. IP в whitelist (если список не пустой);
2. `postfix-admin` active;
3. Nginx слушает 443;
4. Gunicorn на `127.0.0.1:8000`;
5. логи: `journalctl -u postfix-admin`, `/var/log/nginx/postfix-admin-error.log`.

## Состав репозитория (для установки)

```text
app.py
requirements.txt
templates/
static/
deploy/install.sh
deploy/update.sh
deploy/uninstall.sh
deploy/nginx-https.conf
deploy/postfix-admin.service
```

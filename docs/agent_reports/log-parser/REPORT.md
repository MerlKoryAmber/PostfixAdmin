# Парсер логов Postfix — корреляция по queue id

Дата: 19.08.2026, ~15:24 МСК  
Статус: РЕАЛИЗОВАНО НО НЕ ПРИНЯТО

## Факт проблемы

`parse_log_line` смотрел одну syslog-строку. У Postfix `from=` на qmgr, `to=` на smtp, timeout — третья строка без адресов. Таблица показывала пустые From/To рядом с таймаутами.

Полный рерайт не нужен: сырьё уже корректно в `raw`. Нужна склейка по queue id.

## Что сделано

- `parse_log_line` — qid, timeout/lost connection, relay из `conversation with` / `connect to`, timestamp ISO+BSD
- `parse_maillog_lines` — накопление from/to/relay по qid
- хвост: контекст 2000 строк, показ 500
- stats тоже обогащает from по qid
- тесты: `python -m unittest tests.test_log_parser -v` → 4/4 OK

## Сырые числа тестов

4 ran, 0 failed.

## Не покрыто

- from= вне окна 2000 строк — From останется пустым
- UI в живом браузере не гонялся
- строки без qid (`connect to … timed out`) по-прежнему без From/To — это не баг склейки

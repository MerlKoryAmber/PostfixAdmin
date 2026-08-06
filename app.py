#!/usr/bin/env python3
"""
Postfix Web Admin Interface
Copyright (c) 2024 InterROS
"""

import os
import re
import subprocess
import json
import fcntl
import shutil
import ipaddress
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

TRANSPORT_FILE = '/etc/postfix/transport'
MAIN_CF_FILE = '/etc/postfix/main.cf'
USERS_FILE = os.environ.get('USERS_FILE', '/opt/postfix-admin/users.json')
IP_WHITELIST_FILE = '/opt/postfix-admin/ip_whitelist.json'
LOG_FILE = '/var/log/maillog'
MAX_LOG_LINES = 500

# --- IP Whitelist Management (без изменений) ---
def load_ip_whitelist():
    if os.path.exists(IP_WHITELIST_FILE):
        try:
            with open(IP_WHITELIST_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []

def save_ip_whitelist(ip_list):
    with open(IP_WHITELIST_FILE, 'w') as f:
        json.dump(ip_list, f, indent=4)

def is_ip_allowed(ip_str):
    whitelist = load_ip_whitelist()
    if not whitelist:
        return True
    try:
        client_ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for entry in whitelist:
        try:
            net = ipaddress.ip_network(entry, strict=False)
            if client_ip in net:
                return True
        except ValueError:
            continue
    return False

@app.before_request
def limit_remote_addr():
    if request.path.startswith('/static/'):
        return
    if request.path == url_for('login') and request.method == 'GET':
        return
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    if not is_ip_allowed(client_ip):
        abort(403)

@app.before_request
def enforce_https():
    if request.headers.get('X-Forwarded-Proto', 'http') != 'https':
        url = request.url.replace('http://', 'https://', 1)
        return redirect(url, code=301)

# --- Flask-Login Setup (без изменений) ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def load_users():
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {}

def save_users(users):
    try:
        temp_file = USERS_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(users, f, indent=4)
        os.replace(temp_file, USERS_FILE)
        return True
    except IOError:
        return False

class User(UserMixin):
    def __init__(self, username, role='user'):
        self.id = username
        self.role = role

@login_manager.user_loader
def user_loader(username):
    users = load_users()
    if username in users:
        return User(username, users[username].get('role', 'user'))
    return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if current_user.role != 'admin':
            flash('Administrator privileges required', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- Configuration Parameters (без изменений) ---
IMPORTANT_PARAMS = {
    'myhostname': {
        'name': 'Hostname',
        'description': 'Fully qualified domain name of the mail server',
        'type': 'text',
        'required': False
    },
    'mydomain': {
        'name': 'Domain',
        'description': 'Primary domain of the mail server',
        'type': 'text',
        'required': False
    },
    'mydestination': {
        'name': 'Destinations',
        'description': 'Domains for local delivery',
        'type': 'text',
        'required': False
    },
    'mynetworks': {
        'name': 'Trusted Networks',
        'description': 'Networks allowed to relay mail',
        'type': 'text',
        'required': False
    },
    'inet_interfaces': {
        'name': 'Interfaces',
        'description': 'Network interfaces to listen on',
        'type': 'select',
        'options': ['', 'all', 'localhost', '127.0.0.1'],
        'required': False
    },
    'message_size_limit': {
        'name': 'Max Message Size (bytes)',
        'description': 'Maximum size of a single message',
        'type': 'number',
        'required': False
    },
    'smtp_tls_security_level': {
        'name': 'Outbound TLS',
        'description': 'TLS security level for outgoing connections',
        'type': 'select',
        'options': ['', 'none', 'may', 'encrypt'],
        'required': False
    },
    'relayhost': {
        'name': 'Relay Host',
        'description': 'SMTP server for relaying outgoing mail',
        'type': 'text',
        'required': False
    },
    'sender_dependent_relayhost_maps': {
        'name': 'Sender Relayhost Maps',
        'description': 'Path to sender-dependent relayhost map',
        'type': 'text',
        'required': False
    }
}

def atomic_write_file(filepath, content):
    temp_file = filepath + '.tmp'
    lock_file = filepath + '.lock'
    try:
        with open(lock_file, 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if os.path.exists(filepath):
                shutil.copy2(filepath, filepath + '.bak')
            with open(temp_file, 'w') as f:
                f.write(content)
            os.replace(temp_file, filepath)
            return True, None
    except (IOError, OSError) as e:
        return False, str(e)
    finally:
        for f in [lock_file, temp_file]:
            if os.path.exists(f):
                try: os.unlink(f)
                except: pass

def parse_main_cf():
    params = {}
    if not os.path.exists(MAIN_CF_FILE):
        return params
    with open(MAIN_CF_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().split('#')[0].strip()
                if key in IMPORTANT_PARAMS:
                    params[key] = value
    return params

def get_sender_transport_file():
    params = parse_main_cf()
    maps = params.get('sender_dependent_relayhost_maps', '')
    if maps.startswith('hash:'):
        return maps[5:]
    return '/etc/postfix/sender_transport'

def parse_transport():
    entries = []
    if not os.path.exists(TRANSPORT_FILE):
        return entries
    with open(TRANSPORT_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            parts = line.split()
            if len(parts) >= 2:
                entries.append({'domain': parts[0], 'destination': parts[1]})
    return entries

def parse_sender_transport():
    sender_file = get_sender_transport_file()
    entries = []
    if not os.path.exists(sender_file):
        return entries
    with open(sender_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            parts = line.split()
            if len(parts) >= 2:
                options = {}
                for part in parts[2:]:
                    if '=' in part:
                        k, v = part.split('=', 1)
                        options[k] = v
                entries.append({'sender': parts[0], 'transport': parts[1], 'options': options})
    return entries

def parse_log_line(line):
    result = {'timestamp': '', 'from': '', 'to': '', 'status': '', 'relay': '', 'raw': line}
    if len(line) >= 15:
        result['timestamp'] = line[:15].strip()
    to_match = re.search(r'to=<([^>]+)>', line)
    if to_match: result['to'] = to_match.group(1)
    from_match = re.search(r'from=<([^>]+)>', line)
    if from_match: result['from'] = from_match.group(1)
    status_match = re.search(r'status=(\S+)', line)
    if status_match: result['status'] = status_match.group(1)
    relay_match = re.search(r'relay=([^\s,]+)', line)
    if relay_match: result['relay'] = relay_match.group(1)
    return result

def parse_queue_line(line):
    result = {
        'queue_id': '', 'size': '', 'arrival_time': '',
        'sender': '', 'recipient': '', 'status': '', 'raw': line
    }
    parts = line.split()
    if len(parts) >= 5:
        result['queue_id'] = parts[0]
        result['size'] = parts[1]
        result['arrival_time'] = ' '.join(parts[2:5]) if len(parts) > 4 else ''
        result['sender'] = parts[5] if len(parts) > 5 else ''
        result['recipient'] = parts[6] if len(parts) > 6 else ''
        if len(parts) > 7:
            result['status'] = ' '.join(parts[7:])
    return result

def sanitize_input(value):
    if not value: return ''
    value = value.strip()
    for char in [';','|','&','$','`','(',')','{','}','<','>','\n','\r']:
        value = value.replace(char, '')
    return value

# --- Relay Host Management (улучшенная проверка) ---
def extract_host_port(transport_str):
    host = transport_str
    port = 25
    if host.startswith('smtp:'):
        host = host[5:]
    elif host.startswith('lmtp:'):
        host = host[5:]
    elif host.startswith('relay:'):
        host = host[6:]
    if host.startswith('['):
        match = re.match(r'\[([^\]]+)\](?::(\d+))?', host)
        if match:
            host = match.group(1)
            if match.group(2):
                port = int(match.group(2))
    else:
        parts = host.rsplit(':', 1)
        if len(parts) == 2 and parts[1].isdigit():
            host = parts[0]
            port = int(parts[1])
    return host, port

def get_relay_hosts():
    entries = parse_sender_transport()
    hosts = {}
    for entry in entries:
        transport = entry['transport']
        clean_host, port = extract_host_port(transport)
        if clean_host not in hosts:
            hosts[clean_host] = {
                'host': clean_host,
                'transport': transport,
                'port': port,
                'senders': [],
                'count': 0
            }
        hosts[clean_host]['senders'].append(entry['sender'])
        hosts[clean_host]['count'] += 1
    return list(hosts.values())

def check_relay_host(host_str):
    host, port = extract_host_port(host_str)
    try:
        nc_result = subprocess.run(['which', 'nc'], capture_output=True, timeout=2)
        if nc_result.returncode == 0:
            result = subprocess.run(
                ['timeout', '5', 'nc', '-w', '3', host, str(port)],
                input='QUIT\n',
                capture_output=True, text=True, timeout=10
            )
        else:
            result = subprocess.run(
                ['timeout', '5', 'bash', '-c',
                 f'exec 3<>/dev/tcp/{host}/{port} 2>/dev/null && echo "QUIT" >&3 && head -1 <&3 && exec 3>&-'],
                capture_output=True, text=True, timeout=10
            )
        if '220' in result.stdout or 'ESMTP' in result.stdout:
            return True, f'Server responded on port {port}'
        elif result.returncode == 124:
            return False, f'Connection timeout on port {port}'
        else:
            return False, f'No SMTP response on port {port}'
    except subprocess.TimeoutExpired:
        return False, f'Connection timeout on port {port}'
    except Exception as e:
        return False, f'Error: {str(e)}'

# --- Statistics Functions ---
def parse_mail_logs_for_stats(hours=24):
    """Анализирует maillog за последние N часов и возвращает статистику."""
    if not os.path.exists(LOG_FILE):
        return {'relay_counts': {}, 'sender_counts': {}, 'hourly_counts': {}, 'total': 0}

    cutoff = datetime.now() - timedelta(hours=hours)
    relay_counts = Counter()
    sender_counts = Counter()
    hourly_counts = defaultdict(int)

    with open(LOG_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if 'status=sent' not in line and 'status=deferred' not in line:
                continue
            parsed = parse_log_line(line)
            if not parsed['timestamp']:
                continue
            try:
                # Парсим временную метку (месяц день час:мин:сек)
                ts = datetime.strptime(parsed['timestamp'], '%b %d %H:%M:%S')
                # Год не указан, подставляем текущий (приблизительно)
                ts = ts.replace(year=datetime.now().year)
                if ts > cutoff:
                    relay = parsed['relay']
                    if relay:
                        relay_counts[relay] += 1
                    sender = parsed['from']
                    if sender:
                        sender_counts[sender] += 1
                    hour = ts.strftime('%Y-%m-%d %H:00')
                    hourly_counts[hour] += 1
            except ValueError:
                continue

    total = sum(relay_counts.values())
    return {
        'relay_counts': dict(relay_counts.most_common(10)),
        'sender_counts': dict(sender_counts.most_common(10)),
        'hourly_counts': dict(sorted(hourly_counts.items())[-24:]),
        'total': total
    }

# ===== ROUTES =====
# ... (все предыдущие маршруты без изменений) ...
# Здесь должны быть все роуты, которые уже определены в предыдущем полном app.py.
# Приводим только новые/изменённые.

@app.route('/')
@login_required
def index():
    return redirect(url_for('main_config'))

# ... (остальные роуты login, logout, users, config, transport, sender-routing, relay-hosts, queue, logs, api) ...
# Они идентичны предыдущей полной версии app.py и опущены для краткости,
# но в реальном файле должны присутствовать полностью.

# --- Statistics Route ---
@app.route('/stats')
@login_required
def view_stats():
    # По умолчанию показываем за последние 24 часа
    hours = request.args.get('hours', 24, type=int)
    if hours not in [1, 6, 12, 24, 48, 168]:
        hours = 24
    stats = parse_mail_logs_for_stats(hours=hours)
    return render_template('stats.html', stats=stats, hours=hours)

@app.route('/api/stats')
@login_required
def api_stats():
    hours = request.args.get('hours', 24, type=int)
    if hours not in [1, 6, 12, 24, 48, 168]:
        hours = 24
    stats = parse_mail_logs_for_stats(hours=hours)
    return jsonify(stats)

# --- CLI Commands (без изменений) ---
@app.cli.command('create-user')
def create_user():
    import click
    username = click.prompt('Username')
    users = load_users()
    if username in users:
        click.echo('User already exists')
        return
    password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
    role = click.prompt('Role (admin/user)', default='user', type=click.Choice(['admin','user']))
    users[username] = {'password': generate_password_hash(password), 'role': role, 'created': datetime.now().isoformat()}
    if save_users(users):
        click.echo(f'User {username} created with role {role}')

@app.cli.command('list-users')
def list_users_cli():
    users = load_users()
    if not users:
        print("No users found")
    for username, data in users.items():
        print(f"{username} - {data.get('role','user')}")

@app.errorhandler(404)
def not_found(e):
    return render_template('base.html', error='Page not found'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('base.html', error='Internal server error'), 500

@app.errorhandler(403)
def forbidden(e):
    return render_template('base.html', error='Access denied'), 403

if __name__ == '__main__':
    if not os.path.exists(USERS_FILE):
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, 'w') as f:
            json.dump({}, f)
    if not os.path.exists(IP_WHITELIST_FILE):
        with open(IP_WHITELIST_FILE, 'w') as f:
            json.dump([], f)
    app.run(host='127.0.0.1', port=8000, debug=False)
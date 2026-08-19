#!/usr/bin/env python3
"""
Postfix Web Admin Interface
"""

import os
import re
import socket
import subprocess
import json
import shutil
import gzip
import glob
import ipaddress
import tempfile
from datetime import datetime, timedelta
from collections import defaultdict, Counter, deque
from functools import wraps
import threading
import time

try:
    import fcntl
except ImportError:
    fcntl = None

from flask import Flask, render_template, render_template_string, request, redirect, url_for, flash, jsonify, abort, send_from_directory
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
csrf = CSRFProtect(app)

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    MAX_CONTENT_LENGTH=1024 * 1024,
)

TRANSPORT_FILE = '/etc/postfix/transport'
MAIN_CF_FILE = '/etc/postfix/main.cf'
USERS_FILE = os.environ.get('USERS_FILE', '/opt/postfix-admin/users.json')
IP_WHITELIST_FILE = '/opt/postfix-admin/ip_whitelist.json'
NGINX_ALLOW_CONF = '/opt/postfix-admin/nginx-allow.conf'
TLS_CERT_FILE = '/etc/nginx/ssl/postfix-admin.crt'
TLS_KEY_FILE = '/etc/nginx/ssl/postfix-admin.key'
MAX_TLS_UPLOAD = 256 * 1024
_PEM_CERT_RE = re.compile(
    br'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', re.DOTALL
)
_PEM_KEY_RE = re.compile(
    br'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----.*?-----END (?:RSA |EC )?PRIVATE KEY-----',
    re.DOTALL,
)
BRAND_FILE = os.environ.get('BRAND_FILE', '/opt/postfix-admin/brand.json')
LOG_FILE = '/var/log/maillog'
LOG_WINDOW_HOURS = 24
MAX_LOG_LINES = 100000
LOG_PER_PAGE_CHOICES = (50, 100, 200)
LOG_PER_PAGE_DEFAULT = 100
SENDER_MAP_DEFAULT = '/etc/postfix/sender_transport'
SASL_PASSWD_FILE = '/etc/postfix/sender_sasl_passwd'
SASL_PASSWD_MAPS = f'hash:{SASL_PASSWD_FILE}'
TLS_LEVELS = ['none', 'may', 'encrypt']
QUEUE_ID_PATTERN = re.compile(r'^[A-F0-9]{6,20}$', re.IGNORECASE)
HOSTNAME_PATTERN = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$'
)

# --- UX helpers: JSON-aware responses, login rate limiting ---

def wants_json():
    """True if the request came from fetch()/AJAX and expects JSON."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    best = request.accept_mimetypes.best_match(['application/json', 'text/html'])
    return best == 'application/json' and \
        request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']

def respond(message, category='info', redirect_endpoint='index', status=200, **extra):
    """Return JSON for AJAX calls, otherwise classic flash + redirect."""
    if wants_json():
        payload = {'ok': category in ('success', 'info'), 'category': category, 'message': message}
        payload.update(extra)
        return jsonify(payload), status
    flash(message, category)
    return redirect(url_for(redirect_endpoint))

# Простая защита от перебора пароля: 5 неудач -> блокировка IP на 5 минут
_login_attempts = {}
_login_lock = threading.Lock()
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 300

def _client_ip():
    return request.headers.get('X-Real-IP') or request.remote_addr or 'unknown'

def login_is_locked(ip):
    with _login_lock:
        fails, lock_until = _login_attempts.get(ip, (0, 0))
        if lock_until and lock_until < time.time():
            _login_attempts.pop(ip, None)
            return False, 0
        return bool(lock_until and lock_until > time.time()), max(0, int(lock_until - time.time()))

def login_register_fail(ip):
    with _login_lock:
        fails, lock_until = _login_attempts.get(ip, (0, 0))
        fails += 1
        if fails >= LOGIN_MAX_ATTEMPTS:
            lock_until = time.time() + LOGIN_LOCK_SECONDS
            fails = 0
        _login_attempts[ip] = (fails, lock_until)

def login_register_success(ip):
    with _login_lock:
        _login_attempts.pop(ip, None)

# --- Context processor for dynamic year ---
def load_company_name():
    env = (os.environ.get('COMPANY_NAME') or '').strip()
    if env:
        return env[:80]
    if os.path.exists(BRAND_FILE):
        try:
            with open(BRAND_FILE, 'r', encoding='utf-8') as f:
                name = (json.load(f).get('company_name') or '').strip()
                if name:
                    return name[:80]
        except (json.JSONDecodeError, OSError, TypeError, AttributeError):
            pass
    return 'Postfix Admin'


@app.context_processor
def inject_year():
    return {'current_year': datetime.now().year, 'company_name': load_company_name()}

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
    secure_file_permissions(IP_WHITELIST_FILE, 0o640)

def sync_nginx_ip_whitelist():
    """Regenerate nginx allow rules from JSON whitelist and reload nginx."""
    ip_list = load_ip_whitelist()
    lines = ["# Generated by Postfix Admin — do not edit manually\n"]
    if not ip_list:
        lines.append("allow all;\n")
    else:
        for ip in ip_list:
            lines.append(f"allow {ip};\n")
        lines.append("deny all;\n")
    with open(NGINX_ALLOW_CONF, 'w') as f:
        f.writelines(lines)
    os.chmod(NGINX_ALLOW_CONF, 0o644)
    test = subprocess.run(['nginx', '-t'], capture_output=True, text=True, timeout=10)
    if test.returncode != 0:
        return False, (test.stderr or test.stdout or 'nginx -t failed').strip()
    reload = subprocess.run(
        ['systemctl', 'reload', 'nginx'], capture_output=True, text=True, timeout=15
    )
    if reload.returncode != 0:
        return False, (reload.stderr or reload.stdout or 'nginx reload failed').strip()
    return True, None


def _openssl(args, data=None):
    try:
        return subprocess.run(
            ['openssl'] + args,
            input=data,
            capture_output=True,
            timeout=10,
        )
    except FileNotFoundError:
        class _Missing:
            returncode = 1
            stdout = b''
            stderr = b'openssl not found'
        return _Missing()


def tls_cert_info(path=TLS_CERT_FILE):
    info = {
        'present': False,
        'subject': '',
        'issuer': '',
        'not_before': '',
        'not_after': '',
        'path_cert': TLS_CERT_FILE,
        'path_key': TLS_KEY_FILE,
    }
    if not os.path.isfile(path):
        return info
    result = _openssl(['x509', '-in', path, '-noout', '-subject', '-issuer', '-dates'])
    if result.returncode != 0:
        info['present'] = True
        info['subject'] = 'не удалось прочитать сертификат'
        return info
    info['present'] = True
    for line in (result.stdout or b'').decode('utf-8', errors='replace').splitlines():
        if line.startswith('subject='):
            info['subject'] = line[8:].strip()
        elif line.startswith('issuer='):
            info['issuer'] = line[7:].strip()
        elif line.startswith('notBefore='):
            info['not_before'] = line.split('=', 1)[1].strip()
        elif line.startswith('notAfter='):
            info['not_after'] = line.split('=', 1)[1].strip()
    return info


def _read_tls_upload(storage, label):
    if not storage or not storage.filename:
        return None, f'Не выбран файл: {label}'
    data = storage.read(MAX_TLS_UPLOAD + 1)
    if len(data) > MAX_TLS_UPLOAD:
        return None, f'{label}: файл больше {MAX_TLS_UPLOAD} байт'
    if not data.strip():
        return None, f'{label}: пустой файл'
    return data, None


def _parse_tls_pem(cert_raw, key_raw, chain_raw):
    if b'ENCRYPTED PRIVATE KEY' in key_raw:
        return None, None, 'Ключ зашифрован паролем — нужен PEM без passphrase'
    keys = _PEM_KEY_RE.findall(key_raw)
    if len(keys) != 1:
        return None, None, 'В файле ключа должен быть ровно один блок PRIVATE KEY (не encrypted)'
    certs = _PEM_CERT_RE.findall(cert_raw)
    if not certs:
        return None, None, 'В файле сертификата нет блока BEGIN CERTIFICATE'
    if chain_raw:
        certs.extend(_PEM_CERT_RE.findall(chain_raw))
    fullchain = b'\n'.join(certs) + b'\n'
    key_pem = keys[0] + b'\n'
    return fullchain, key_pem, None


def _tls_key_matches_cert(fullchain, key_pem):
    first_cert = _PEM_CERT_RE.search(fullchain)
    if not first_cert:
        return False, 'Нет листового сертификата'
    tmp = tempfile.mkdtemp(prefix='pfa-tls-')
    try:
        os.chmod(tmp, 0o700)
        cert_path = os.path.join(tmp, 'leaf.pem')
        key_path = os.path.join(tmp, 'key.pem')
        with open(cert_path, 'wb') as f:
            f.write(first_cert.group(0) + b'\n')
        with open(key_path, 'wb') as f:
            f.write(key_pem)
        os.chmod(key_path, 0o600)
        leaf = _openssl(['x509', '-in', cert_path, '-noout'])
        if leaf.returncode != 0:
            return False, (leaf.stderr or leaf.stdout or b'openssl x509 failed').decode('utf-8', errors='replace').strip()
        pub_cert = _openssl(['x509', '-in', cert_path, '-noout', '-pubkey'])
        pub_key = _openssl(['pkey', '-in', key_path, '-pubout'])
        if pub_cert.returncode != 0 or pub_key.returncode != 0:
            return False, 'openssl не смог извлечь публичный ключ (проверьте PEM ключа и сертификата)'
        if pub_cert.stdout != pub_key.stdout:
            return False, 'Ключ не соответствует сертификату'
        return True, None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _restore_tls_pair(crt_bak, key_bak):
    if os.path.isfile(crt_bak):
        shutil.copy2(crt_bak, TLS_CERT_FILE)
        os.chmod(TLS_CERT_FILE, 0o644)
    if os.path.isfile(key_bak):
        shutil.copy2(key_bak, TLS_KEY_FILE)
        os.chmod(TLS_KEY_FILE, 0o600)


def install_panel_tls(fullchain, key_pem):
    os.makedirs('/etc/nginx/ssl', mode=0o755, exist_ok=True)
    crt_bak = TLS_CERT_FILE + '.bak'
    key_bak = TLS_KEY_FILE + '.bak'
    if os.path.isfile(TLS_CERT_FILE):
        shutil.copy2(TLS_CERT_FILE, crt_bak)
    if os.path.isfile(TLS_KEY_FILE):
        shutil.copy2(TLS_KEY_FILE, key_bak)
    tmp_crt = TLS_CERT_FILE + '.new'
    tmp_key = TLS_KEY_FILE + '.new'
    try:
        with open(tmp_crt, 'wb') as f:
            f.write(fullchain)
        with open(tmp_key, 'wb') as f:
            f.write(key_pem)
        os.chmod(tmp_crt, 0o644)
        os.chmod(tmp_key, 0o600)
        os.replace(tmp_crt, TLS_CERT_FILE)
        os.replace(tmp_key, TLS_KEY_FILE)
        test = subprocess.run(['nginx', '-t'], capture_output=True, text=True, timeout=10)
        if test.returncode != 0:
            _restore_tls_pair(crt_bak, key_bak)
            return False, (test.stderr or test.stdout or 'nginx -t failed').strip()
        reload = subprocess.run(
            ['systemctl', 'reload', 'nginx'], capture_output=True, text=True, timeout=15
        )
        if reload.returncode != 0:
            _restore_tls_pair(crt_bak, key_bak)
            subprocess.run(['nginx', '-t'], capture_output=True, timeout=10)
            subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True, timeout=15)
            return False, (reload.stderr or reload.stdout or 'nginx reload failed').strip()
        return True, None
    except OSError as e:
        _restore_tls_pair(crt_bak, key_bak)
        for leftover in (tmp_crt, tmp_key):
            if os.path.isfile(leftover):
                os.remove(leftover)
        return False, str(e)


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
    if request.path.startswith('/static/') or request.path == '/favicon.ico':
        return
    # Разрешаем страницу логина без проверки IP
    if request.path == url_for('login') and request.method == 'GET':
        return
    client_ip = request.headers.get('X-Real-IP') or request.remote_addr
    if not client_ip:
        client_ip = request.remote_addr
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
        secure_file_permissions(USERS_FILE, 0o600)
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
            flash('Требуются права администратора', 'danger')
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
        'description': 'Relayhost map (mode B): values as [host]:port. Used when transport maps below is empty.',
        'type': 'text',
        'required': False
    },
    'sender_dependent_default_transport_maps': {
        'name': 'Sender Transport Maps',
        'description': 'Transport map (mode A): values as smtp:[host]:port with per-route options. Takes priority if set.',
        'type': 'text',
        'required': False
    },
    'smtp_sender_dependent_authentication': {
        'name': 'Sender-Dependent SASL',
        'description': 'Enable per-sender SMTP authentication (required for relayhost mode with auth)',
        'type': 'select',
        'options': ['', 'yes', 'no'],
        'required': False
    },
    'smtp_sasl_password_maps': {
        'name': 'SASL Password Maps',
        'description': 'Path to sender SASL credentials map (managed automatically when auth is used)',
        'type': 'text',
        'required': False
    }
}

def atomic_write_file(filepath, content):
    temp_file = filepath + '.tmp'
    lock_file = filepath + '.lock'
    try:
        with open(lock_file, 'w') as lock:
            if fcntl is not None:
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

def _is_main_cf_continuation(line):
    return bool(line) and line[0].isspace() and bool(line.strip()) and not line.strip().startswith('#')

def parse_main_cf():
    params = {}
    if not os.path.exists(MAIN_CF_FILE):
        return params
    with open(MAIN_CF_FILE, 'r') as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip('\n')
        stripped = raw.strip()
        if not stripped or stripped.startswith('#') or '=' not in raw or raw[0].isspace():
            i += 1
            continue
        key, value = raw.split('=', 1)
        key = key.strip()
        if key in IMPORTANT_PARAMS:
            parts = [value.split('#', 1)[0].strip()]
            j = i + 1
            while j < len(lines) and _is_main_cf_continuation(lines[j]):
                parts.append(lines[j].strip().split('#', 1)[0].strip())
                j += 1
            params[key] = ' '.join(part for part in parts if part).strip()
            i = j
            continue
        i += 1
    return params

def get_sender_routing_mode():
    """Detect active sender routing mode from main.cf (transport maps take priority)."""
    params = parse_main_cf()
    transport_maps = params.get('sender_dependent_default_transport_maps', '').strip()
    relayhost_maps = params.get('sender_dependent_relayhost_maps', '').strip()
    if transport_maps:
        return 'transport', parse_map_file_path(transport_maps)
    if relayhost_maps:
        return 'relayhost', parse_map_file_path(relayhost_maps)
    return 'relayhost', SENDER_MAP_DEFAULT

def get_sender_map_file():
    return get_sender_routing_mode()[1]

def parse_map_file_path(maps_value):
    if not maps_value:
        return SENDER_MAP_DEFAULT
    maps_value = maps_value.strip()
    for prefix in ('hash:', 'texthash:', 'btree:', 'cdb:', 'lmdb:', 'sqlite:'):
        if maps_value.startswith(prefix):
            return maps_value[len(prefix):]
    return maps_value

def validate_sender(sender):
    if sender.startswith('@'):
        return bool(re.match(r'^@[\w.-]+\.\w+$', sender))
    return bool(re.match(r'^[\w.+-]+@[\w.-]+\.\w+$', sender))

def read_sasl_passwords():
    passwords = {}
    if not os.path.exists(SASL_PASSWD_FILE):
        return passwords
    with open(SASL_PASSWD_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                passwords[parts[0]] = parts[1]
    return passwords

def parse_sender_transport():
    mode, sender_file = get_sender_routing_mode()
    entries = []
    sasl_passwords = read_sasl_passwords()
    if not os.path.exists(sender_file):
        return entries
    with open(sender_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            options = {}
            for part in parts[2:]:
                if '=' in part:
                    k, v = part.split('=', 1)
                    options[k] = v
            host, port = extract_host_port(parts[1])
            entry = {
                'sender': parts[0],
                'transport': parts[1],
                'host': host,
                'port': port,
                'options': options,
                'has_auth': options.get('smtp_sasl_auth_enable') == 'yes' or parts[0] in sasl_passwords,
            }
            if parts[0] in sasl_passwords:
                cred = sasl_passwords[parts[0]]
                entry['has_auth'] = True
                if ':' in cred:
                    entry['options']['smtp_sasl_username'] = cred.split(':', 1)[0]
                if mode == 'transport' and 'smtp_sasl_auth_enable' not in entry['options']:
                    entry['options']['smtp_sasl_auth_enable'] = 'yes'
            entries.append(entry)
    return entries

def format_postfix_value(host, port, mode):
    if mode == 'relayhost':
        if port and port != 25:
            return f'[{host}]:{port}'
        return f'[{host}]'
    if port and port != 25:
        return f'smtp:[{host}]:{port}'
    return f'smtp:[{host}]'

def format_entry_line(entry, mode):
    host = entry.get('host') or extract_host_port(entry.get('transport', ''))[0]
    port = entry.get('port') or extract_host_port(entry.get('transport', ''))[1]
    value = format_postfix_value(host, port, mode)
    line = f"{entry['sender']}\t{value}"
    if mode == 'transport':
        options = entry.get('options') or {}
        if options.get('smtp_sasl_auth_enable') == 'yes':
            options = dict(options)
            options['smtp_sasl_password_maps'] = SASL_PASSWD_MAPS
        for k, v in options.items():
            if v and not k.startswith('_'):
                line += f" {k}={v}"
    return line

def build_sender_map_content(entries, mode):
    content = f"# Postfix sender-dependent routing map\n# Mode: {mode}\n# Managed via web interface\n\n"
    for entry in entries:
        content += format_entry_line(entry, mode) + "\n"
    return content

def run_postmap(filepath):
    try:
        result = subprocess.run(
            ['/usr/sbin/postmap', filepath],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or 'postmap failed').strip()
        return True, None
    except Exception as e:
        return False, str(e)

def reload_postfix_config():
    try:
        check = subprocess.run(
            ['/usr/sbin/postfix', 'check'],
            capture_output=True, text=True, timeout=10
        )
        if check.returncode != 0:
            return False, (check.stderr or check.stdout or 'postfix check failed').strip()
        reload = subprocess.run(
            ['/usr/sbin/postfix', 'reload'],
            capture_output=True, text=True, timeout=30
        )
        if reload.returncode != 0:
            return False, (reload.stderr or reload.stdout or 'postfix reload failed').strip()
        return True, None
    except Exception as e:
        return False, str(e)

def write_sasl_passwd_map(entries):
    lines = []
    existing = read_sasl_passwords()
    for entry in entries:
        opts = entry.get('options') or {}
        if opts.get('smtp_sasl_auth_enable') != 'yes' and not entry.get('has_auth'):
            continue
        password = opts.get('_smtp_password') or existing.get(entry['sender'])
        if not password:
            continue
        username = opts.get('smtp_sasl_username') or opts.get('smtp_username', '')
        cred = f'{username}:{password}' if username else password
        lines.append(f"{entry['sender']}\t{cred}\n")
    content = "# Sender SASL credentials\n# Managed via web interface\n\n" + ''.join(lines)
    success, error = atomic_write_file(SASL_PASSWD_FILE, content)
    if not success:
        return False, error
    secure_file_permissions(SASL_PASSWD_FILE, 0o600)
    if lines:
        return run_postmap(SASL_PASSWD_FILE)
    if os.path.exists(SASL_PASSWD_FILE + '.db'):
        try:
            os.unlink(SASL_PASSWD_FILE + '.db')
        except OSError:
            pass
    return True, None

def save_sender_routing(entries):
    mode, map_file = get_sender_routing_mode()
    content = build_sender_map_content(entries, mode)
    success, error = atomic_write_file(map_file, content)
    if not success:
        return False, error
    ok, err = run_postmap(map_file)
    if not ok:
        return False, f'postmap failed: {err}'
    ok, err = write_sasl_passwd_map(entries)
    if not ok:
        return False, f'SASL map error: {err}'
    ok, err = reload_postfix_config()
    if not ok:
        return False, f'Map saved but Postfix reload failed: {err}'
    return True, None

def sender_lookup_keys(sender):
    """Keys Postfix tries for sender_dependent_* hash maps: user@domain, then @domain."""
    sender = (sender or '').strip()
    keys = []
    if sender:
        keys.append(sender)
    if '@' in sender and not sender.startswith('@'):
        local, domain = sender.rsplit('@', 1)
        if '+' in local:
            keys.append(f"{local.split('+', 1)[0]}@{domain}")
        if domain:
            keys.append(f'@{domain}')
    seen = set()
    ordered = []
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered

def test_sender_route(sender):
    map_file = get_sender_map_file()
    if not os.path.exists(map_file):
        return False, 'Map file not found'
    try:
        for key in sender_lookup_keys(sender):
            result = subprocess.run(
                ['/usr/sbin/postmap', '-q', key, map_file],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                value = result.stdout.strip()
                if key != sender:
                    return True, f'{value} (matched {key})'
                return True, value
        return False, 'No match found'
    except Exception as e:
        return False, str(e)

def routing_options_from_form(form, existing_options=None):
    existing_options = dict(existing_options or {})
    options = {}
    if form.get('use_auth') == 'yes':
        options['smtp_sasl_auth_enable'] = 'yes'
        username = sanitize_input(form.get('smtp_username', ''))
        if username:
            options['smtp_sasl_username'] = username
        password = form.get('smtp_password', '')
        if password:
            options['_smtp_password'] = password
        elif existing_options.get('_smtp_password'):
            options['_smtp_password'] = existing_options['_smtp_password']
    tls = sanitize_input(form.get('smtp_tls_security_level', ''))
    if tls in TLS_LEVELS:
        options['smtp_tls_security_level'] = tls
    bind = sanitize_input(form.get('smtp_bind_address', ''))
    if bind:
        try:
            ipaddress.ip_address(bind)
            options['smtp_bind_address'] = bind
        except ValueError:
            pass
    return options

def get_sender_sasl_cred(sender):
    cred = read_sasl_passwords().get(sender)
    if not cred:
        return None, None
    if ':' in cred:
        username, password = cred.split(':', 1)
        return username, password
    return '', cred

def entry_from_form(form, existing_entry=None):
    sender = sanitize_input(form.get('sender', ''))
    transport_input = sanitize_input(form.get('transport', ''))
    if not sender or not transport_input:
        raise ValueError('Sender and relay host are required')
    if not validate_sender(sender):
        raise ValueError('Invalid sender format (use user@domain.com or @domain.com)')
    host, port = extract_host_port(transport_input)
    if not host or not validate_hostname(host):
        raise ValueError('Invalid relay host format')
    existing_options = {}
    if existing_entry:
        existing_options = dict(existing_entry.get('options') or {})
        orig_sender = existing_entry['sender']
        if not form.get('smtp_password'):
            username, password = get_sender_sasl_cred(orig_sender)
            if password:
                existing_options['_smtp_password'] = password
            if username and not form.get('smtp_username'):
                existing_options['smtp_sasl_username'] = username
    options = routing_options_from_form(form, existing_options)
    mode, _ = get_sender_routing_mode()
    return {
        'sender': sender,
        'host': host,
        'port': port,
        'transport': format_postfix_value(host, port, mode),
        'options': options,
        'has_auth': options.get('smtp_sasl_auth_enable') == 'yes',
    }

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

# Traditional syslog: "Aug 19 14:20:01" is 15 chars. ISO-8601 if rsyslog uses it.
_SYSLOG_TS_RE = re.compile(
    r'^([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}|'
    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)'
)
# After postfix/service[pid]: queue id (hex or long-queue-id) or NOQUEUE.
_POSTFIX_QID_RE = re.compile(
    r'postfix/[A-Za-z0-9/_-]+\[\d+\]:\s+(NOQUEUE|[A-Za-z0-9]{5,32}):'
)
_LOG_FROM_RE = re.compile(r'from=<([^>]*)>')
_LOG_TO_RE = re.compile(r'to=<([^>]*)>')
_LOG_STATUS_RE = re.compile(r'status=([^\s,]+)')
_LOG_RELAY_RE = re.compile(r'relay=([^\s,]+)')
_LOG_CONV_HOST_RE = re.compile(r'conversation with ([^\s\[]+)')
_LOG_CONNECT_TO_RE = re.compile(r'connect to ([^\s\[]+)')
_READ_BLOCK = 256 * 1024


def syslog_datetime(ts, now=None):
    """Parse maillog timestamp to naive local datetime. BSD syslog has no year."""
    now = now or datetime.now()
    if not ts:
        return None
    ts = ts.strip()
    try:
        if ts[:1].isdigit():
            iso = ts.replace('Z', '+00:00')
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        dt = datetime.strptime(ts, '%b %d %H:%M:%S').replace(year=now.year)
        if dt > now + timedelta(days=2):
            dt = dt.replace(year=now.year - 1)
        return dt
    except ValueError:
        return None


def maillog_source_paths(path):
    """Newest first: current file, then logrotate .1 / .1.gz, then dated copies."""
    ordered = [path, path + '.1', path + '.1.gz']
    ordered.extend(sorted(glob.glob(path + '-*'), reverse=True))
    seen = set()
    out = []
    for p in ordered:
        if p not in seen and os.path.isfile(p):
            seen.add(p)
            out.append(p)
    return out


def _read_file_since(path, cutoff, now):
    """Lines with timestamp >= cutoff, chronological. reached_old: hit a line before cutoff."""
    opener = gzip.open if path.endswith('.gz') else open
    try:
        with opener(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return [], False
            pos = size
            kept = []
            carry = b''
            reached_old = False
            while pos > 0 and not reached_old:
                read_at = max(0, pos - _READ_BLOCK)
                f.seek(read_at)
                data = f.read(pos - read_at)
                pos = read_at
                text = data + carry
                parts = text.split(b'\n')
                if pos > 0:
                    carry = parts[0]
                    parts = parts[1:]
                else:
                    carry = b''
                for chunk in reversed(parts):
                    if not chunk.strip():
                        continue
                    line = chunk.decode('utf-8', errors='replace')
                    dt = syslog_datetime(parse_log_line(line)['timestamp'], now)
                    if dt is None:
                        kept.append(line)
                        continue
                    if dt < cutoff:
                        reached_old = True
                        break
                    kept.append(line)
            kept.reverse()
            return kept, reached_old
    except OSError:
        return [], False


def read_maillog_window(path, hours=LOG_WINDOW_HOURS, now=None, display_max=MAX_LOG_LINES):
    """Entries from the last `hours` (default 24). Truncates at display_max."""
    now = now or datetime.now()
    cutoff = now - timedelta(hours=hours)
    batches = []
    for fp in maillog_source_paths(path):
        batch, reached_old = _read_file_since(fp, cutoff, now)
        if batch:
            batches.append(batch)
        if reached_old:
            break
    raw = []
    for batch in reversed(batches):
        raw.extend(batch)
    parsed = parse_maillog_lines(raw)
    in_window = []
    for entry in parsed:
        dt = syslog_datetime(entry['timestamp'], now)
        if dt is None or dt >= cutoff:
            in_window.append(entry)
    matched = len(in_window)
    truncated = matched > display_max
    if truncated:
        in_window = in_window[-display_max:]
    return {
        'entries': in_window,
        'truncated': truncated,
        'hours': hours,
        'matched': matched,
    }


def paginate_items(items, page, per_page):
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    page = min(max(1, int(page or 1)), pages)
    start = (page - 1) * per_page
    return items[start:start + per_page], page, pages, total


def parse_log_line(line):
    """Parse one syslog line. from=/to= live on different Postfix lines — see parse_maillog_lines."""
    line = (line or '').rstrip('\n')
    result = {
        'timestamp': '', 'queue_id': '', 'from': '', 'to': '',
        'status': '', 'relay': '', 'raw': line,
    }
    ts = _SYSLOG_TS_RE.match(line)
    if ts:
        result['timestamp'] = ts.group(1).strip()
    elif len(line) >= 15:
        result['timestamp'] = line[:15].strip()
    qid = _POSTFIX_QID_RE.search(line)
    if qid:
        result['queue_id'] = qid.group(1)
    from_match = _LOG_FROM_RE.search(line)
    if from_match:
        result['from'] = from_match.group(1)
    to_match = _LOG_TO_RE.search(line)
    if to_match:
        result['to'] = to_match.group(1)
    status_match = _LOG_STATUS_RE.search(line)
    if status_match:
        result['status'] = status_match.group(1).rstrip('.,;')
    lower = line.lower()
    if not result['status']:
        if 'timed out' in lower or 'timeout' in lower:
            result['status'] = 'timeout'
        elif 'lost connection' in lower:
            result['status'] = 'lost connection'
    relay_match = _LOG_RELAY_RE.search(line)
    if relay_match:
        result['relay'] = relay_match.group(1)
    elif not result['relay']:
        conv = _LOG_CONV_HOST_RE.search(line) or _LOG_CONNECT_TO_RE.search(line)
        if conv:
            result['relay'] = conv.group(1)
    return result


def _merge_qid_state(state, entry):
    if entry['from']:
        state['from'] = entry['from']
    if entry['to']:
        if not state['to']:
            state['to'] = entry['to']
        elif entry['to'] not in state['to'].split(', '):
            state['to'] = state['to'] + ', ' + entry['to']
    if entry['relay']:
        state['relay'] = entry['relay']


def _apply_qid_state(entry, state):
    if not entry['from']:
        entry['from'] = state.get('from', '')
    if not entry['to']:
        entry['to'] = state.get('to', '')
    if not entry['relay']:
        entry['relay'] = state.get('relay', '')
    return entry


def parse_maillog_lines(lines):
    """Correlate Postfix syslog by queue id so timeout lines inherit from=/to=."""
    by_qid = {}
    out = []
    for raw in lines:
        entry = parse_log_line(raw if isinstance(raw, str) else str(raw))
        qid = entry['queue_id']
        if qid and qid != 'NOQUEUE':
            state = by_qid.setdefault(qid, {'from': '', 'to': '', 'relay': ''})
            _merge_qid_state(state, entry)
            _apply_qid_state(entry, state)
        out.append(entry)
    return out


QUEUE_LINE_RE = re.compile(
    r'^(?P<qid>[A-F0-9]{6,20})(?P<flag>[*!])?\s+(?P<size>\d+)\s+'
    r'(?P<when>\w{3}\s+\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+(?P<sender>\S*)\s*$'
)

def parse_postqueue(output):
    """Robust `postqueue -p` parser.

    Handles message flags (* active, ! hold), and recipient/reason lines
    that Postfix prints indented on the following lines.
    """
    entries = []
    current = None
    for line in output.splitlines():
        if not line.strip() or line.startswith('-Queue ID-') or line.startswith('-- '):
            continue
        m = QUEUE_LINE_RE.match(line)
        if m:
            qid = m.group('qid').upper()
            flag = m.group('flag') or ''
            status = 'deferred'
            if flag == '*':
                status = 'active'
            elif flag == '!':
                status = 'hold'
            current = {
                'queue_id': qid, 'size': m.group('size'),
                'arrival_time': m.group('when'), 'sender': m.group('sender') or '',
                'recipients': [], 'status': status, 'raw': line,
            }
            entries.append(current)
        elif current is not None:
            text = line.strip()
            if not text:
                continue
            # причина задержки обычно в скобках, получатели — отдельными строками
            if text.startswith('('):
                current['status'] = current['status'] or 'deferred'
                current['reason'] = text.strip('()')
            else:
                current['recipients'].append(text)
    for e in entries:
        e['recipient'] = e['recipients'][0] if e['recipients'] else ''
        e['recipient_count'] = len(e['recipients'])
    return entries

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

def secure_file_permissions(filepath, mode=0o600):
    try:
        os.chmod(filepath, mode)
    except OSError:
        pass

def validate_queue_id(queue_id):
    return bool(queue_id and QUEUE_ID_PATTERN.match(queue_id))

def validate_hostname(host):
    if not host or len(host) > 253:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return bool(HOSTNAME_PATTERN.match(host))

def normalize_queue_id(queue_id):
    if not validate_queue_id(queue_id):
        return None
    return queue_id.upper()

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
        host = entry['host']
        port = entry['port']
        transport = entry['transport']
        key = f'{host}:{port}'
        if key not in hosts:
            hosts[key] = {
                'host': host,
                'transport': transport,
                'port': port,
                'senders': [],
                'count': 0
            }
        hosts[key]['senders'].append(entry['sender'])
        hosts[key]['count'] += 1
    return list(hosts.values())

def check_relay_host(host_str):
    host, port = extract_host_port(host_str)
    if not validate_hostname(host):
        return False, 'Invalid hostname'
    if not isinstance(port, int) or port < 1 or port > 65535:
        return False, 'Invalid port'
    nc = shutil.which('nc') or shutil.which('ncat')
    timeout_bin = shutil.which('timeout')
    try:
        if nc and timeout_bin:
            result = subprocess.run(
                [timeout_bin, '4', nc, '-z', '-w', '3', host, str(port)],
                capture_output=True, text=True, timeout=6
            )
            if result.returncode == 0:
                return True, f'Port {port} is open on {host}'
            if result.returncode in (124, 137):
                return False, f'Connection timeout on {host}:{port}'
            return False, f'Unreachable: {host}:{port}'
        with socket.create_connection((host, port), timeout=3) as sock:
            sock.settimeout(3)
            try:
                sock.sendall(b'QUIT\r\n')
                response = sock.recv(1024).decode('utf-8', errors='replace')
            except OSError:
                response = ''
        if '220' in response or 'ESMTP' in response or response == '':
            return True, f'Server responded on port {port}'
        return False, f'No SMTP response on port {port}'
    except socket.timeout:
        return False, f'Connection timeout on {host}:{port}'
    except socket.gaierror:
        return False, f'DNS lookup failed for {host}'
    except OSError as e:
        return False, f'Error: {e}'
    except Exception as e:
        return False, str(e)

def get_postconf_value(name):
    try:
        result = subprocess.run(
            ['/usr/sbin/postconf', '-h', name],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return (result.stdout or '').strip()
    except Exception:
        pass
    return ''

# --- Statistics Functions ---
def parse_mail_logs_for_stats(hours=24):
    if not os.path.exists(LOG_FILE):
        return {'relay_counts': {}, 'sender_counts': {}, 'hourly_counts': {}, 'total': 0}
    cutoff = datetime.now() - timedelta(hours=hours)
    relay_counts = Counter()
    sender_counts = Counter()
    hourly_counts = defaultdict(int)
    by_qid = {}
    with open(LOG_FILE, 'r', errors='replace') as f:
        for line in f:
            parsed = parse_log_line(line)
            qid = parsed['queue_id']
            if qid and qid != 'NOQUEUE':
                state = by_qid.setdefault(qid, {'from': '', 'to': '', 'relay': ''})
                _merge_qid_state(state, parsed)
                _apply_qid_state(parsed, state)
            if parsed['status'] not in ('sent', 'deferred'):
                continue
            if not parsed['timestamp']:
                continue
            try:
                ts = datetime.strptime(parsed['timestamp'][:15].strip(), '%b %d %H:%M:%S')
                ts = ts.replace(year=datetime.now().year)
            except ValueError:
                continue
            if ts <= cutoff:
                continue
            relay = parsed['relay']
            if relay:
                relay_counts[relay] += 1
            sender = parsed['from']
            if sender:
                sender_counts[sender] += 1
            hour = ts.strftime('%Y-%m-%d %H:00')
            hourly_counts[hour] += 1
    total = sum(relay_counts.values())
    return {
        'relay_counts': dict(relay_counts.most_common(10)),
        'sender_counts': dict(sender_counts.most_common(10)),
        'hourly_counts': dict(sorted(hourly_counts.items())[-24:]),
        'total': total
    }

# ===== ROUTES =====
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.svg',
        mimetype='image/svg+xml'
    )

@app.route('/')
@login_required
def index():
    routing_mode, routing_map = get_sender_routing_mode()
    entries = parse_sender_transport()
    queue = {'total': 0, 'active': 0, 'deferred': 0, 'hold': 0}
    try:
        result = subprocess.run(['/usr/sbin/postqueue', '-p'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for entry in parse_postqueue(result.stdout):
                queue['total'] += 1
                st = entry['status'].lower()
                if 'active' in st:
                    queue['active'] += 1
                elif 'hold' in st:
                    queue['hold'] += 1
                else:
                    queue['deferred'] += 1
    except Exception:
        pass
    postfix_running = False
    try:
        st = subprocess.run(['/usr/bin/systemctl', 'is-active', 'postfix'], capture_output=True, text=True, timeout=5)
        postfix_running = st.stdout.strip() == 'active'
    except Exception:
        pass
    dash = {
        'postfix_running': postfix_running,
        'myhostname': get_postconf_value('myhostname') or '—',
        'mydomain': get_postconf_value('mydomain') or '—',
        'queue': queue,
        'routing_mode': routing_mode,
        'routing_map': routing_map,
        'routing_count': len(entries),
        'routing_preview': entries[:6],
        'transport_count': len(parse_transport()),
        'relay_count': len(get_relay_hosts()),
        'stats': parse_mail_logs_for_stats(24),
    }
    return render_template('dashboard.html', dash=dash)

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        ip = _client_ip()
        locked, wait = login_is_locked(ip)
        if locked:
            flash(f'Слишком много попыток. Повторите через {wait // 60 + 1} мин.', 'danger')
            return render_template('login.html'), 429
        username = sanitize_input(request.form.get('username',''))
        password = request.form.get('password','')
        if not username or not password:
            flash('Введите логин и пароль', 'danger')
            return render_template('login.html')
        users = load_users()
        if username in users and check_password_hash(users[username]['password'], password):
            login_register_success(ip)
            user = User(username, users[username].get('role','user'))
            login_user(user)
            flash('Вход выполнен', 'success')
            return redirect(url_for('index'))
        login_register_fail(ip)
        flash('Неверный логин или пароль', 'danger')
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

# --- User Management ---
@app.route('/users')
@login_required
@admin_required
def list_users():
    users = load_users()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['POST'])
@login_required
@admin_required
def add_user():
    username = sanitize_input(request.form.get('username',''))
    password = request.form.get('password','')
    role = sanitize_input(request.form.get('role','user'))
    if role not in ('admin', 'user'):
        role = 'user'
    if not username or not password:
        flash('Логин и пароль обязательны', 'danger')
        return redirect(url_for('list_users'))
    users = load_users()
    if username in users:
        flash('Пользователь уже существует', 'danger')
        return redirect(url_for('list_users'))
    users[username] = {'password': generate_password_hash(password), 'role': role, 'created': datetime.now().isoformat()}
    if save_users(users):
        flash(f'Пользователь {username} создан', 'success')
    else:
        flash('Ошибка сохранения пользователя', 'danger')
    return redirect(url_for('list_users'))

@app.route('/users/delete/<username>', methods=['POST'])
@login_required
@admin_required
def delete_user(username):
    if username == current_user.id:
        flash('Нельзя удалить самого себя', 'danger')
        return redirect(url_for('list_users'))
    users = load_users()
    if username not in users:
        flash('Пользователь не найден', 'danger')
        return redirect(url_for('list_users'))
    del users[username]
    if save_users(users):
        flash(f'Пользователь {username} удалён', 'success')
    else:
        flash('Ошибка удаления пользователя', 'danger')
    return redirect(url_for('list_users'))

@app.route('/users/reset-password/<username>', methods=['POST'])
@login_required
@admin_required
def admin_reset_password(username):
    new_password = request.form.get('new_password','')
    if not new_password:
        flash('Пароль не может быть пустым', 'danger')
        return redirect(url_for('list_users'))
    users = load_users()
    if username not in users:
        flash('Пользователь не найден', 'danger')
        return redirect(url_for('list_users'))
    users[username]['password'] = generate_password_hash(new_password)
    if save_users(users):
        flash(f'Пароль для {username} изменён', 'success')
    else:
        flash('Ошибка смены пароля', 'danger')
    return redirect(url_for('list_users'))

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_password = request.form.get('current_password','')
        new_password = request.form.get('new_password','')
        if not current_password or not new_password:
            flash('Заполните все поля', 'danger')
            return redirect(url_for('profile'))
        users = load_users()
        if not check_password_hash(users[current_user.id]['password'], current_password):
            flash('Текущий пароль неверен', 'danger')
            return redirect(url_for('profile'))
        users[current_user.id]['password'] = generate_password_hash(new_password)
        if save_users(users):
            flash('Пароль успешно изменён', 'success')
        else:
            flash('Ошибка смены пароля', 'danger')
        return redirect(url_for('profile'))
    return render_template('profile.html')

# --- IP Whitelist ---
@app.route('/ip-whitelist')
@login_required
@admin_required
def ip_whitelist():
    ip_list = load_ip_whitelist()
    return render_template('ip_whitelist.html', ip_list=ip_list)

@app.route('/ip-whitelist/add', methods=['POST'])
@login_required
@admin_required
def add_ip():
    ip = sanitize_input(request.form.get('ip',''))
    if not ip:
        flash('Укажите IP-адрес', 'danger')
        return redirect(url_for('ip_whitelist'))
    try:
        ipaddress.ip_network(ip, strict=False)
    except ValueError:
        flash('Некорректный IP-адрес или подсеть', 'danger')
        return redirect(url_for('ip_whitelist'))
    ip_list = load_ip_whitelist()
    if ip not in ip_list:
        ip_list.append(ip)
        save_ip_whitelist(ip_list)
        ok, err = sync_nginx_ip_whitelist()
        if ok:
            flash(f'IP {ip} добавлен в белый список', 'success')
        else:
            flash(f'IP {ip} сохранён, но nginx не перезагрузился: {err}', 'warning')
    else:
        flash('IP уже в белом списке', 'warning')
    return redirect(url_for('ip_whitelist'))

@app.route('/ip-whitelist/delete', methods=['POST'])
@login_required
@admin_required
def delete_ip():
    ip = sanitize_input(request.form.get('ip', ''))
    ip_list = load_ip_whitelist()
    if ip in ip_list:
        ip_list.remove(ip)
        save_ip_whitelist(ip_list)
        ok, err = sync_nginx_ip_whitelist()
        if ok:
            flash(f'IP {ip} удалён из белого списка', 'success')
        else:
            flash(f'IP {ip} удалён, но nginx не перезагрузился: {err}', 'warning')
    else:
        flash('IP не найден', 'danger')
    return redirect(url_for('ip_whitelist'))

# --- Configuration ---
@app.route('/config')
@login_required
def main_config():
    params = parse_main_cf()
    routing_mode, routing_map = get_sender_routing_mode()
    return render_template(
        'main_config.html',
        params=params,
        config_params=IMPORTANT_PARAMS,
        routing_mode=routing_mode,
        routing_map=routing_map,
        tls_info=tls_cert_info() if current_user.role == 'admin' else None,
    )


@app.route('/config/tls', methods=['POST'])
@login_required
@admin_required
def upload_panel_tls():
    cert_raw, err = _read_tls_upload(request.files.get('tls_cert'), 'сертификат')
    if err:
        flash(err, 'danger')
        return redirect(url_for('main_config'))
    key_raw, err = _read_tls_upload(request.files.get('tls_key'), 'ключ')
    if err:
        flash(err, 'danger')
        return redirect(url_for('main_config'))
    chain_file = request.files.get('tls_chain')
    chain_raw = None
    if chain_file and chain_file.filename:
        chain_raw, err = _read_tls_upload(chain_file, 'цепочка')
        if err:
            flash(err, 'danger')
            return redirect(url_for('main_config'))
    fullchain, key_pem, err = _parse_tls_pem(cert_raw, key_raw, chain_raw)
    if err:
        flash(err, 'danger')
        return redirect(url_for('main_config'))
    ok, err = _tls_key_matches_cert(fullchain, key_pem)
    if not ok:
        flash(err, 'danger')
        return redirect(url_for('main_config'))
    ok, err = install_panel_tls(fullchain, key_pem)
    if ok:
        flash('TLS сертификат панели заменён, Nginx перезагружен', 'success')
    else:
        flash(f'Сертификат не применён: {err}', 'danger')
    return redirect(url_for('main_config'))

@app.route('/config/save', methods=['POST'])
@login_required
@admin_required
def save_config():
    new_params = {}
    for key in IMPORTANT_PARAMS:
        value = sanitize_input(request.form.get(key, ''))
        new_params[key] = value
    if not os.path.exists(MAIN_CF_FILE):
        flash('Файл main.cf не найден', 'danger')
        return redirect(url_for('main_config'))
    with open(MAIN_CF_FILE, 'r') as f:
        lines = f.readlines()
    updated_lines = []
    updated_params = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in line and not line[0].isspace():
            key = line.split('=', 1)[0].strip()
            if key in new_params:
                updated_lines.append(f"{key} = {new_params[key]}\n")
                updated_params.add(key)
                i += 1
                while i < len(lines) and _is_main_cf_continuation(lines[i]):
                    i += 1
                continue
        updated_lines.append(line)
        i += 1
    for key, value in new_params.items():
        if key not in updated_params and value:
            updated_lines.append(f"\n{key} = {value}\n")
    success, error = atomic_write_file(MAIN_CF_FILE, ''.join(updated_lines))
    if success:
        flash('Конфигурация обновлена', 'success')
    else:
        flash(f'Ошибка сохранения конфигурации: {error}', 'danger')
    return redirect(url_for('main_config'))

@app.route('/config/reload', methods=['POST'])
@login_required
@admin_required
def reload_postfix():
    try:
        subprocess.run(['/usr/sbin/postfix', 'check'], check=True, capture_output=True, timeout=10)
        subprocess.run(['/usr/sbin/postfix', 'reload'], check=True, capture_output=True, timeout=30)
        flash('Postfix успешно перезагружен', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Ошибка: {e.stderr.decode().strip()}', 'danger')
    except Exception as e:
        flash(f'Ошибка: {str(e)}', 'danger')
    return redirect(url_for('main_config'))

@app.route('/config/check')
@login_required
@admin_required
def check_config():
    try:
        result = subprocess.run(['/usr/sbin/postfix', 'check'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            flash('✅ Конфигурация Postfix корректна', 'success')
        else:
            flash(f'❌ Ошибки конфигурации:\n{result.stderr}', 'danger')
    except Exception as e:
        flash(f'Ошибка: {str(e)}', 'danger')
    return redirect(url_for('main_config'))

# --- Transport ---
@app.route('/transport')
@login_required
def transport():
    entries = parse_transport()
    return render_template(
        'transport.html',
        entries=entries,
        transport_maps=get_postconf_value('transport_maps'),
    )

@app.route('/transport/add', methods=['POST'])
@login_required
@admin_required
def add_transport():
    domain = sanitize_input(request.form.get('domain',''))
    destination = sanitize_input(request.form.get('destination',''))
    if not domain or not destination:
        flash('Домен и назначение обязательны', 'danger')
        return redirect(url_for('transport'))
    entries = parse_transport()
    if any(e['domain'] == domain for e in entries):
        flash(f'Домен {domain} уже существует', 'warning')
        return redirect(url_for('transport'))
    entries.append({'domain': domain, 'destination': destination})
    content = "# Postfix transport map\n# Managed via web interface\n\n"
    for entry in entries:
        content += f"{entry['domain']}\t{entry['destination']}\n"
    success, error = atomic_write_file(TRANSPORT_FILE, content)
    if success:
        try:
            subprocess.run(['/usr/sbin/postmap', TRANSPORT_FILE], check=True, capture_output=True, timeout=10)
            flash(f'Транспорт добавлен: {domain} → {destination}', 'success')
        except subprocess.CalledProcessError as e:
            message = (e.stderr or e.stdout or b'postmap failed').decode(errors='replace').strip()
            flash(f'Запись сохранена, но postmap завершился с ошибкой: {message}', 'warning')
        except Exception as e:
            flash(f'Запись сохранена, но postmap не выполнен: {e}', 'warning')
    else:
        flash(f'Ошибка сохранения: {error}', 'danger')
    return redirect(url_for('transport'))

@app.route('/transport/delete', methods=['POST'])
@login_required
@admin_required
def delete_transport():
    domain = sanitize_input(request.form.get('domain', ''))
    if not domain:
        flash('Укажите домен', 'danger')
        return redirect(url_for('transport'))
    entries = parse_transport()
    entries = [e for e in entries if e['domain'] != domain]
    content = "# Postfix transport map\n# Managed via web interface\n\n"
    for entry in entries:
        content += f"{entry['domain']}\t{entry['destination']}\n"
    success, error = atomic_write_file(TRANSPORT_FILE, content)
    if success:
        try:
            subprocess.run(['/usr/sbin/postmap', TRANSPORT_FILE], check=True, capture_output=True, timeout=10)
            flash(f'Транспорт для {domain} удалён', 'success')
        except subprocess.CalledProcessError as e:
            message = (e.stderr or e.stdout or b'postmap failed').decode(errors='replace').strip()
            flash(f'Удаление сохранено, но postmap завершился с ошибкой: {message}', 'warning')
        except Exception as e:
            flash(f'Удаление сохранено, но postmap не выполнен: {e}', 'warning')
    else:
        flash(f'Ошибка: {error}', 'danger')
    return redirect(url_for('transport'))

# --- Sender Routing ---
@app.route('/sender-routing')
@login_required
def sender_routing():
    mode, map_file = get_sender_routing_mode()
    entries = parse_sender_transport()
    return render_template(
        'sender_routing.html',
        entries=entries,
        routing_mode=mode,
        routing_map=map_file,
    )

@app.route('/sender-routing/add', methods=['POST'])
@login_required
@admin_required
def add_sender_routing():
    try:
        entry = entry_from_form(request.form)
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('sender_routing'))
    entries = parse_sender_transport()
    if any(e['sender'] == entry['sender'] for e in entries):
        flash(f'Отправитель {entry["sender"]} уже существует. Отредактируйте существующее правило.', 'warning')
        return redirect(url_for('sender_routing'))
    entries.append(entry)
    success, error = save_sender_routing(entries)
    if success:
        flash(f'Правило добавлено: {entry["sender"]} → {entry["transport"]}', 'success')
    else:
        flash(f'Ошибка: {error}', 'danger')
    return redirect(url_for('sender_routing'))

@app.route('/sender-routing/edit', methods=['POST'])
@login_required
@admin_required
def edit_sender_routing():
    original_sender = sanitize_input(request.form.get('original_sender', ''))
    if not original_sender:
        flash('Не указан исходный отправитель', 'danger')
        return redirect(url_for('sender_routing'))
    try:
        entry = entry_from_form(
            request.form,
            existing_entry=next((e for e in parse_sender_transport() if e['sender'] == original_sender), None)
        )
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('sender_routing'))
    entries = parse_sender_transport()
    found = False
    for i, e in enumerate(entries):
        if e['sender'] == original_sender:
            entries[i] = entry
            found = True
            break
    if not found:
        flash('Правило не найдено', 'danger')
        return redirect(url_for('sender_routing'))
    if entry['sender'] != original_sender:
        duplicates = [e for e in entries if e['sender'] == entry['sender']]
        if len(duplicates) > 1:
            flash(f'Отправитель {entry["sender"]} уже существует', 'warning')
            return redirect(url_for('sender_routing'))
    success, error = save_sender_routing(entries)
    if success:
        flash(f'Правило обновлено: {entry["sender"]} → {entry["transport"]}', 'success')
    else:
        flash(f'Ошибка: {error}', 'danger')
    return redirect(url_for('sender_routing'))

@app.route('/sender-routing/delete', methods=['POST'])
@login_required
@admin_required
def delete_sender_routing():
    sender = sanitize_input(request.form.get('sender', ''))
    all_entries = parse_sender_transport()
    entries = [e for e in all_entries if e['sender'] != sender]
    if len(entries) == len(all_entries):
        flash('Правило не найдено', 'warning')
        return redirect(url_for('sender_routing'))
    success, error = save_sender_routing(entries)
    if success:
        flash(f'Правило для {sender} удалено', 'success')
    else:
        flash(f'Ошибка: {error}', 'danger')
    return redirect(url_for('sender_routing'))

@app.route('/sender-routing/test', methods=['POST'])
@login_required
def test_sender_routing():
    sender = sanitize_input(request.form.get('sender', ''))
    if not sender:
        return respond('Укажите адрес отправителя', 'danger', 'sender_routing', 400)
    ok, result = test_sender_route(sender)
    if ok:
        return respond(f'Маршрут для {sender}: {result}', 'success', 'sender_routing', result=result)
    return respond(f'Маршрут для {sender} не найден: {result}', 'warning', 'sender_routing')

# --- Relay Hosts Management ---
@app.route('/relay-hosts')
@login_required
@admin_required
def relay_hosts():
    hosts = get_relay_hosts()
    for host in hosts:
        host['status'] = None
        host['status_msg'] = ''
    return render_template('relay_hosts.html', hosts=hosts)

@app.route('/relay-hosts/check', methods=['POST'])
@login_required
@admin_required
def check_host():
    transport = sanitize_input(request.form.get('transport', ''))
    if not transport:
        return respond('Укажите хост', 'danger', 'relay_hosts', 400)
    status, msg = check_relay_host(transport)
    host, port = extract_host_port(transport)
    label = f'{host}:{port}'
    if status:
        return respond(f'{label} доступен: {msg}', 'success', 'relay_hosts')
    return respond(f'{label} недоступен: {msg}', 'danger', 'relay_hosts')

@app.route('/relay-hosts/replace', methods=['POST'])
@login_required
@admin_required
def replace_relay_host():
    old_key = sanitize_input(request.form.get('old_host', ''))
    new_transport = sanitize_input(request.form.get('new_host', ''))
    if not old_key or not new_transport:
        flash('Укажите старый и новый хост', 'danger')
        return redirect(url_for('relay_hosts'))
    try:
        old_host, old_port = old_key.rsplit(':', 1)
        old_port = int(old_port)
    except ValueError:
        flash('Некорректный выбор старого хоста', 'danger')
        return redirect(url_for('relay_hosts'))
    try:
        new_host, new_port = extract_host_port(new_transport)
    except Exception:
        flash('Некорректный формат нового хоста', 'danger')
        return redirect(url_for('relay_hosts'))
    mode, _ = get_sender_routing_mode()
    entries = parse_sender_transport()
    changed = 0
    for entry in entries:
        if entry['host'] == old_host and entry['port'] == old_port:
            entry['host'] = new_host
            entry['port'] = new_port
            entry['transport'] = format_postfix_value(new_host, new_port, mode)
            changed += 1
    if changed == 0:
        flash(f'Правил для {old_key} не найдено', 'warning')
        return redirect(url_for('relay_hosts'))
    success, error = save_sender_routing(entries)
    if success:
        flash(f'Хост {old_key} заменён в {changed} правилах', 'success')
    else:
        flash(f'Ошибка: {error}', 'danger')
    return redirect(url_for('relay_hosts'))

# --- Mail Queue ---
@app.route('/queue')
@login_required
@admin_required
def view_queue():
    entries = []
    try:
        result = subprocess.run(['/usr/sbin/postqueue', '-p'], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            entries = parse_postqueue(result.stdout)
    except Exception as e:
        flash(f'Не удалось прочитать очередь: {e}', 'danger')

    # поиск по ID / отправителю / получателю / статусу
    q = sanitize_input(request.args.get('q', ''))
    if q:
        ql = q.lower()
        entries = [e for e in entries if
                   ql in e['queue_id'].lower()
                   or ql in (e.get('sender') or '').lower()
                   or ql in (e.get('recipient') or '').lower()
                   or ql in (e.get('status') or '').lower()]

    stats = {'total': len(entries), 'active': 0, 'deferred': 0, 'hold': 0}
    for entry in entries:
        st = entry['status'].lower()
        if 'active' in st:
            stats['active'] += 1
        elif 'hold' in st:
            stats['hold'] += 1
        else:
            stats['deferred'] += 1

    # пагинация
    per_page = request.args.get('per_page', 50, type=int)
    if per_page not in (25, 50, 100, 200):
        per_page = 50
    total = len(entries)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, request.args.get('page', 1, type=int)), pages)
    entries_page = entries[(page - 1) * per_page: page * per_page]

    return render_template('queue.html', entries=entries_page, stats=stats,
                           q=q, page=page, pages=pages, per_page=per_page, total=total)

@app.route('/queue/message/<queue_id>')
@login_required
@admin_required
def view_message_detail(queue_id):
    qid = normalize_queue_id(queue_id)
    if not qid:
        flash('Некорректный ID письма', 'danger')
        return redirect(url_for('view_queue'))
    try:
        result = subprocess.run(['/usr/sbin/postcat', '-q', qid], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            flash(f'Письмо {qid} не найдено', 'danger')
            return redirect(url_for('view_queue'))
        headers = {}
        body = ''
        in_body = False
        for line in result.stdout.split('\n'):
            if in_body:
                body += line + '\n'
            elif line.strip() == '':
                in_body = True
            elif ':' in line and not line.startswith(' '):
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()
        return render_template('message_detail.html', queue_id=qid, headers=headers, body=body)
    except Exception as e:
        flash(f'Ошибка: {str(e)}', 'danger')
        return redirect(url_for('view_queue'))

@app.route('/queue/flush', methods=['POST'])
@login_required
@admin_required
def flush_queue():
    try:
        subprocess.run(['/usr/sbin/postqueue', '-f'], check=True, capture_output=True, timeout=30)
        return respond('Отправка очереди запущена', 'success', 'view_queue')
    except subprocess.CalledProcessError as e:
        return respond(f'Ошибка: {e.stderr.decode().strip()}', 'danger', 'view_queue', 500)

@app.route('/queue/delete/<queue_id>', methods=['POST'])
@login_required
@admin_required
def delete_queue_message(queue_id):
    qid = normalize_queue_id(queue_id)
    if not qid:
        return respond('Некорректный ID письма', 'danger', 'view_queue', 400)
    try:
        subprocess.run(['/usr/sbin/postsuper', '-d', qid], check=True, capture_output=True, timeout=10)
        return respond(f'Письмо {qid} удалено', 'success', 'view_queue', queue_id=qid)
    except subprocess.CalledProcessError as e:
        return respond(f'Ошибка: {e.stderr.decode().strip()}', 'danger', 'view_queue', 500)

@app.route('/queue/hold/<queue_id>', methods=['POST'])
@login_required
@admin_required
def hold_message(queue_id):
    qid = normalize_queue_id(queue_id)
    if not qid:
        return respond('Некорректный ID письма', 'danger', 'view_queue', 400)
    try:
        subprocess.run(['/usr/sbin/postsuper', '-h', qid], check=True, capture_output=True, timeout=10)
        return respond(f'Письмо {qid} поставлено на hold', 'success', 'view_queue', queue_id=qid)
    except subprocess.CalledProcessError as e:
        return respond(f'Ошибка: {e.stderr.decode().strip()}', 'danger', 'view_queue', 500)

@app.route('/queue/release/<queue_id>', methods=['POST'])
@login_required
@admin_required
def release_message(queue_id):
    qid = normalize_queue_id(queue_id)
    if not qid:
        return respond('Некорректный ID письма', 'danger', 'view_queue', 400)
    try:
        subprocess.run(['/usr/sbin/postsuper', '-H', qid], check=True, capture_output=True, timeout=10)
        return respond(f'Письмо {qid} снято с hold', 'success', 'view_queue', queue_id=qid)
    except subprocess.CalledProcessError as e:
        return respond(f'Ошибка: {e.stderr.decode().strip()}', 'danger', 'view_queue', 500)

@app.route('/queue/requeue/<queue_id>', methods=['POST'])
@login_required
@admin_required
def requeue_message(queue_id):
    qid = normalize_queue_id(queue_id)
    if not qid:
        return respond('Некорректный ID письма', 'danger', 'view_queue', 400)
    try:
        subprocess.run(['/usr/sbin/postsuper', '-r', qid], check=True, capture_output=True, timeout=10)
        return respond(f'Письмо {qid} возвращено в очередь', 'success', 'view_queue', queue_id=qid)
    except subprocess.CalledProcessError as e:
        return respond(f'Ошибка: {e.stderr.decode().strip()}', 'danger', 'view_queue', 500)

@app.route('/queue/delete-all', methods=['POST'])
@login_required
@admin_required
def delete_all_queue():
    try:
        subprocess.run(['/usr/sbin/postsuper', '-d', 'ALL'], check=True, capture_output=True, timeout=30)
        return respond('Все письма удалены из очереди', 'success', 'view_queue')
    except subprocess.CalledProcessError as e:
        return respond(f'Ошибка: {e.stderr.decode().strip()}', 'danger', 'view_queue', 500)

@app.route('/queue/delete-deferred', methods=['POST'])
@login_required
@admin_required
def delete_deferred():
    try:
        subprocess.run(['/usr/sbin/postsuper', '-d', 'ALL', 'deferred'], check=True, capture_output=True, timeout=30)
        return respond('Все отложенные (deferred) письма удалены', 'success', 'view_queue')
    except subprocess.CalledProcessError as e:
        return respond(f'Ошибка: {e.stderr.decode().strip()}', 'danger', 'view_queue', 500)

@app.route('/queue/delete-by-sender', methods=['POST'])
@login_required
@admin_required
def delete_by_sender():
    sender = sanitize_input(request.form.get('sender','')).lower()
    if not sender:
        return respond('Укажите отправителя', 'danger', 'view_queue', 400)
    try:
        result = subprocess.run(['/usr/sbin/postqueue', '-p'], capture_output=True, text=True, timeout=10)
        deleted = 0
        for entry in parse_postqueue(result.stdout):
            if (entry.get('sender') or '').lower() == sender:
                try:
                    subprocess.run(['/usr/sbin/postsuper', '-d', entry['queue_id']],
                                   check=True, capture_output=True, timeout=5)
                    deleted += 1
                except subprocess.CalledProcessError:
                    pass
        return respond(f'Удалено писем от {sender}: {deleted}', 'success', 'view_queue', deleted=deleted)
    except Exception as e:
        return respond(f'Ошибка: {e}', 'danger', 'view_queue', 500)

@app.route('/queue/delete-by-domain', methods=['POST'])
@login_required
@admin_required
def delete_by_domain():
    domain = sanitize_input(request.form.get('domain','')).lower().lstrip('@')
    if not domain:
        return respond('Укажите домен', 'danger', 'view_queue', 400)
    try:
        result = subprocess.run(['/usr/sbin/postqueue', '-p'], capture_output=True, text=True, timeout=10)
        deleted = 0
        for entry in parse_postqueue(result.stdout):
            sender_domain = (entry.get('sender') or '').lower().rsplit('@', 1)[-1]
            if entry.get('sender') and sender_domain == domain:
                try:
                    subprocess.run(['/usr/sbin/postsuper', '-d', entry['queue_id']],
                                   check=True, capture_output=True, timeout=5)
                    deleted += 1
                except subprocess.CalledProcessError:
                    pass
        return respond(f'Удалено писем для домена {domain}: {deleted}', 'success', 'view_queue', deleted=deleted)
    except Exception as e:
        return respond(f'Ошибка: {e}', 'danger', 'view_queue', 500)

# --- Statistics ---
@app.route('/stats')
@login_required
def view_stats():
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

# --- Logs ---
@app.route('/logs')
@login_required
def view_logs():
    bundle = read_maillog_window(LOG_FILE)
    parsed = bundle['entries']
    from_filter = sanitize_input(request.args.get('from',''))
    to_filter = sanitize_input(request.args.get('to',''))
    status_filter = sanitize_input(request.args.get('status',''))
    relay_filter = sanitize_input(request.args.get('relay',''))
    search = sanitize_input(request.args.get('search',''))
    filter_type = request.args.get('filter','all')
    filtered = []
    for entry in parsed:
        if filter_type == 'errors' and not any(k in entry['raw'].lower() for k in ['error','fail','reject','warning']):
            continue
        if filter_type == 'postfix' and 'postfix' not in entry['raw'].lower():
            continue
        if search:
            q = search.lower()
            hay = ' '.join((
                entry.get('raw') or '',
                entry.get('from') or '',
                entry.get('to') or '',
                entry.get('status') or '',
                entry.get('relay') or '',
            )).lower()
            if q not in hay:
                continue
        if from_filter and from_filter.lower() not in entry['from'].lower():
            continue
        if to_filter and to_filter.lower() not in entry['to'].lower():
            continue
        if status_filter and status_filter.lower() not in entry['status'].lower():
            continue
        if relay_filter and relay_filter.lower() not in entry['relay'].lower():
            continue
        filtered.append(entry)
    per_page = request.args.get('per_page', LOG_PER_PAGE_DEFAULT, type=int)
    if per_page not in LOG_PER_PAGE_CHOICES:
        per_page = LOG_PER_PAGE_DEFAULT
    logs_page, page, pages, total = paginate_items(
        filtered, request.args.get('page', 1, type=int), per_page
    )
    log_query = {
        'per_page': per_page,
        'filter': filter_type,
    }
    if from_filter:
        log_query['from'] = from_filter
    if to_filter:
        log_query['to'] = to_filter
    if status_filter:
        log_query['status'] = status_filter
    if relay_filter:
        log_query['relay'] = relay_filter
    if search:
        log_query['search'] = search
    return render_template(
        'logs.html',
        logs=logs_page,
        filter_type=filter_type,
        search=search,
        from_filter=from_filter,
        to_filter=to_filter,
        status_filter=status_filter,
        relay_filter=relay_filter,
        log_hours=bundle['hours'],
        log_truncated=bundle['truncated'],
        log_matched=bundle['matched'],
        page=page,
        pages=pages,
        per_page=per_page,
        total=total,
        log_query=log_query,
    )

@app.route('/api/logs')
@login_required
def api_logs():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            lines = list(deque(f, maxlen=100))
    return jsonify({'lines': [l.strip() for l in lines]})

@app.route('/api/status')
@login_required
def api_status():
    try:
        result = subprocess.run(['/usr/bin/systemctl', 'is-active', 'postfix'],
                                capture_output=True, text=True, timeout=5)
        return jsonify({'running': result.stdout.strip() == 'active', 'status': result.stdout.strip()})
    except:
        return jsonify({'running': False, 'error': 'Status check failed'})

# --- CLI Commands ---
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

def render_error_page(message, status_code):
    return render_template_string(
        """<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ status_code }} - {{ message }}</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; }
        main { min-height: 100vh; display: grid; place-items: center; padding: 24px; }
        section { max-width: 640px; background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 32px; }
        h1 { margin-top: 0; }
        p { color: #cbd5e1; line-height: 1.5; }
        a { color: #93c5fd; }
    </style>
</head>
<body>
    <main>
        <section>
            <h1>{{ status_code }}</h1>
            <p>{{ message }}</p>
            <p><a href="{{ url_for('index') }}">Вернуться на дашборд</a></p>
        </section>
    </main>
</body>
</html>""",
        message=message,
        status_code=status_code,
    ), status_code

@app.errorhandler(404)
def not_found(e):
    return render_error_page('Страница не найдена', 404)

@app.errorhandler(500)
def server_error(e):
    return render_error_page('Внутренняя ошибка сервера', 500)

@app.errorhandler(413)
def too_large(e):
    flash('Файл слишком большой (лимит 1 МБ)', 'danger')
    return redirect(url_for('main_config'))

if __name__ == '__main__':
    if not os.path.exists(USERS_FILE):
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, 'w') as f:
            json.dump({}, f)
        secure_file_permissions(USERS_FILE, 0o600)
    if not os.path.exists(IP_WHITELIST_FILE):
        with open(IP_WHITELIST_FILE, 'w') as f:
            json.dump([], f)
        secure_file_permissions(IP_WHITELIST_FILE, 0o640)
    if not os.path.exists(NGINX_ALLOW_CONF):
        with open(NGINX_ALLOW_CONF, 'w') as f:
            f.write("# Generated by Postfix Admin — do not edit manually\nallow all;\n")
        os.chmod(NGINX_ALLOW_CONF, 0o644)
    app.run(host='127.0.0.1', port=8000, debug=False)
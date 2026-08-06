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
from datetime import datetime
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

# --- IP Whitelist Management ---
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

# --- Flask-Login Setup ---
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

# --- Configuration Parameters ---
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

# --- Relay Host Management ---
def get_relay_hosts():
    """Извлекает список уникальных релей-хостов из sender_transport"""
    entries = parse_sender_transport()
    hosts = {}
    for entry in entries:
        transport = entry['transport']
        # Извлекаем хост из smtp:host:port
        host = transport.replace('smtp:', '').replace('lmtp:', '').split(':')[0] if ':' in transport else transport
        if host not in hosts:
            hosts[host] = {
                'host': host,
                'transport': transport,
                'senders': [],
                'count': 0
            }
        hosts[host]['senders'].append(entry['sender'])
        hosts[host]['count'] += 1
    return list(hosts.values())

def check_relay_host(host):
    """Проверка доступности релей-хоста"""
    # Извлекаем хост и порт
    port = 25
    if ':' in host:
        parts = host.split(':')
        host = parts[0]
        try:
            port = int(parts[1]) if len(parts) > 1 else 25
        except:
            pass
    
    try:
        result = subprocess.run(
            ['timeout', '5', 'bash', '-c', f'echo QUIT | nc -w 3 {host} {port} 2>&1'],
            capture_output=True, text=True, timeout=10
        )
        if '220' in result.stdout or 'ESMTP' in result.stdout:
            return True, 'Server responded'
        elif result.returncode == 124:
            return False, 'Connection timeout'
        else:
            return False, result.stderr.strip() or 'No response'
    except Exception as e:
        return False, str(e)

# ===== ROUTES =====
@app.route('/')
@login_required
def index():
    return redirect(url_for('main_config'))

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username',''))
        password = request.form.get('password','')
        if not username or not password:
            flash('Please enter username and password', 'danger')
            return render_template('login.html')
        users = load_users()
        if username in users and check_password_hash(users[username]['password'], password):
            user = User(username, users[username].get('role','user'))
            login_user(user)
            flash('Login successful', 'success')
            return redirect(url_for('index'))
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
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
    if not username or not password:
        flash('Username and password are required', 'danger')
        return redirect(url_for('list_users'))
    users = load_users()
    if username in users:
        flash('User already exists', 'danger')
        return redirect(url_for('list_users'))
    users[username] = {'password': generate_password_hash(password), 'role': role, 'created': datetime.now().isoformat()}
    if save_users(users):
        flash(f'User {username} created', 'success')
    else:
        flash('Error saving user', 'danger')
    return redirect(url_for('list_users'))

@app.route('/users/delete/<username>', methods=['POST'])
@login_required
@admin_required
def delete_user(username):
    if username == current_user.id:
        flash('Cannot delete yourself', 'danger')
        return redirect(url_for('list_users'))
    users = load_users()
    if username not in users:
        flash('User not found', 'danger')
        return redirect(url_for('list_users'))
    del users[username]
    if save_users(users):
        flash(f'User {username} deleted', 'success')
    else:
        flash('Error deleting user', 'danger')
    return redirect(url_for('list_users'))

@app.route('/users/reset-password/<username>', methods=['POST'])
@login_required
@admin_required
def admin_reset_password(username):
    new_password = request.form.get('new_password','')
    if not new_password:
        flash('Password cannot be empty', 'danger')
        return redirect(url_for('list_users'))
    users = load_users()
    if username not in users:
        flash('User not found', 'danger')
        return redirect(url_for('list_users'))
    users[username]['password'] = generate_password_hash(new_password)
    if save_users(users):
        flash(f'Password for {username} changed', 'success')
    else:
        flash('Error changing password', 'danger')
    return redirect(url_for('list_users'))

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_password = request.form.get('current_password','')
        new_password = request.form.get('new_password','')
        if not current_password or not new_password:
            flash('All fields are required', 'danger')
            return redirect(url_for('profile'))
        users = load_users()
        if not check_password_hash(users[current_user.id]['password'], current_password):
            flash('Current password is incorrect', 'danger')
            return redirect(url_for('profile'))
        users[current_user.id]['password'] = generate_password_hash(new_password)
        if save_users(users):
            flash('Password changed successfully', 'success')
        else:
            flash('Error changing password', 'danger')
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
        flash('IP address is required', 'danger')
        return redirect(url_for('ip_whitelist'))
    try:
        ipaddress.ip_network(ip, strict=False)
    except ValueError:
        flash('Invalid IP address or subnet', 'danger')
        return redirect(url_for('ip_whitelist'))
    ip_list = load_ip_whitelist()
    if ip not in ip_list:
        ip_list.append(ip)
        save_ip_whitelist(ip_list)
        flash(f'IP {ip} added to whitelist', 'success')
    else:
        flash('IP already in whitelist', 'warning')
    return redirect(url_for('ip_whitelist'))

@app.route('/ip-whitelist/delete/<path:ip>')
@login_required
@admin_required
def delete_ip(ip):
    ip_list = load_ip_whitelist()
    if ip in ip_list:
        ip_list.remove(ip)
        save_ip_whitelist(ip_list)
        flash(f'IP {ip} removed from whitelist', 'success')
    else:
        flash('IP not found', 'danger')
    return redirect(url_for('ip_whitelist'))

# --- Configuration ---
@app.route('/config')
@login_required
def main_config():
    params = parse_main_cf()
    return render_template('main_config.html', params=params, config_params=IMPORTANT_PARAMS)

@app.route('/config/save', methods=['POST'])
@login_required
@admin_required
def save_config():
    new_params = {}
    for key in IMPORTANT_PARAMS:
        value = sanitize_input(request.form.get(key, ''))
        new_params[key] = value
    if not os.path.exists(MAIN_CF_FILE):
        flash('main.cf file not found', 'danger')
        return redirect(url_for('main_config'))
    with open(MAIN_CF_FILE, 'r') as f:
        lines = f.readlines()
    updated_lines = []
    updated_params = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            key = stripped.split('=')[0].strip()
            if key in new_params:
                updated_lines.append(f"{key} = {new_params[key]}\n")
                updated_params.add(key)
                continue
        updated_lines.append(line)
    for key, value in new_params.items():
        if key not in updated_params and value:
            updated_lines.append(f"\n{key} = {value}\n")
    success, error = atomic_write_file(MAIN_CF_FILE, ''.join(updated_lines))
    if success:
        flash('Configuration updated successfully', 'success')
    else:
        flash(f'Error saving configuration: {error}', 'danger')
    return redirect(url_for('main_config'))

@app.route('/config/reload')
@login_required
@admin_required
def reload_postfix():
    try:
        subprocess.run(['/usr/sbin/postfix', 'check'], check=True, capture_output=True, timeout=10)
        subprocess.run(['/usr/sbin/postfix', 'reload'], check=True, capture_output=True, timeout=30)
        flash('Postfix reloaded successfully', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Error: {e.stderr.decode().strip()}', 'danger')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main_config'))

@app.route('/config/check')
@login_required
@admin_required
def check_config():
    try:
        result = subprocess.run(['/usr/sbin/postfix', 'check'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            flash('✅ Postfix configuration is valid', 'success')
        else:
            flash(f'❌ Configuration errors:\n{result.stderr}', 'danger')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main_config'))

# --- Transport ---
@app.route('/transport')
@login_required
def transport():
    entries = parse_transport()
    return render_template('transport.html', entries=entries)

@app.route('/transport/add', methods=['POST'])
@login_required
@admin_required
def add_transport():
    domain = sanitize_input(request.form.get('domain',''))
    destination = sanitize_input(request.form.get('destination',''))
    if not domain or not destination:
        flash('Domain and destination are required', 'danger')
        return redirect(url_for('transport'))
    entries = parse_transport()
    if any(e['domain'] == domain for e in entries):
        flash(f'Domain {domain} already exists', 'warning')
        return redirect(url_for('transport'))
    entries.append({'domain': domain, 'destination': destination})
    content = "# Postfix transport map\n# Managed via web interface\n\n"
    for entry in entries:
        content += f"{entry['domain']}\t{entry['destination']}\n"
    success, error = atomic_write_file(TRANSPORT_FILE, content)
    if success:
        subprocess.run(['/usr/sbin/postmap', TRANSPORT_FILE], check=True, capture_output=True)
        flash(f'Transport added: {domain} → {destination}', 'success')
    else:
        flash(f'Error saving: {error}', 'danger')
    return redirect(url_for('transport'))

@app.route('/transport/delete/<path:domain>')
@login_required
@admin_required
def delete_transport(domain):
    entries = parse_transport()
    entries = [e for e in entries if e['domain'] != domain]
    content = "# Postfix transport map\n# Managed via web interface\n\n"
    for entry in entries:
        content += f"{entry['domain']}\t{entry['destination']}\n"
    success, error = atomic_write_file(TRANSPORT_FILE, content)
    if success:
        subprocess.run(['/usr/sbin/postmap', TRANSPORT_FILE], check=True, capture_output=True)
        flash(f'Transport deleted for {domain}', 'success')
    else:
        flash(f'Error: {error}', 'danger')
    return redirect(url_for('transport'))

# --- Sender Routing ---
@app.route('/sender-routing')
@login_required
def sender_routing():
    entries = parse_sender_transport()
    return render_template('sender_routing.html', entries=entries)

@app.route('/sender-routing/add', methods=['POST'])
@login_required
@admin_required
def add_sender_routing():
    sender = sanitize_input(request.form.get('sender',''))
    transport = sanitize_input(request.form.get('transport',''))
    if not sender or not transport:
        flash('Sender and transport are required', 'danger')
        return redirect(url_for('sender_routing'))
    options = {}
    if request.form.get('use_auth') == 'yes':
        options['smtp_sasl_auth_enable'] = 'yes'
        username = sanitize_input(request.form.get('smtp_username',''))
        if username: options['smtp_username'] = username
    entries = parse_sender_transport()
    entries.append({'sender': sender, 'transport': transport, 'options': options})
    sender_file = get_sender_transport_file()
    content = "# Postfix sender-dependent relayhost map\n# Managed via web interface\n\n"
    for entry in entries:
        line = f"{entry['sender']}\t{entry['transport']}"
        if entry.get('options'):
            for k, v in entry['options'].items():
                if v: line += f" {k}={v}"
        content += line + "\n"
    success, error = atomic_write_file(sender_file, content)
    if success:
        subprocess.run(['/usr/sbin/postmap', sender_file], check=True, capture_output=True)
        flash(f'Routing rule added: {sender} → {transport}', 'success')
    else:
        flash(f'Error saving: {error}', 'danger')
    return redirect(url_for('sender_routing'))

@app.route('/sender-routing/delete', methods=['POST'])
@login_required
@admin_required
def delete_sender_routing():
    sender = sanitize_input(request.form.get('sender',''))
    entries = parse_sender_transport()
    entries = [e for e in entries if e['sender'] != sender]
    sender_file = get_sender_transport_file()
    content = "# Postfix sender-dependent relayhost map\n# Managed via web interface\n\n"
    for entry in entries:
        line = f"{entry['sender']}\t{entry['transport']}"
        if entry.get('options'):
            for k, v in entry['options'].items():
                if v: line += f" {k}={v}"
        content += line + "\n"
    success, error = atomic_write_file(sender_file, content)
    if success:
        subprocess.run(['/usr/sbin/postmap', sender_file], check=True, capture_output=True)
        flash(f'Routing rule deleted for {sender}', 'success')
    else:
        flash(f'Error: {error}', 'danger')
    return redirect(url_for('sender_routing'))

# --- Relay Hosts Management ---
@app.route('/relay-hosts')
@login_required
@admin_required
def relay_hosts():
    hosts = get_relay_hosts()
    # Проверяем статус каждого хоста
    for host in hosts:
        host['status'], host['status_msg'] = check_relay_host(host['host'])
    return render_template('relay_hosts.html', hosts=hosts)

@app.route('/relay-hosts/check/<path:host>')
@login_required
@admin_required
def check_host(host):
    status, msg = check_relay_host(host)
    if status:
        flash(f'✅ Host {host} is reachable: {msg}', 'success')
    else:
        flash(f'❌ Host {host} is unreachable: {msg}', 'danger')
    return redirect(url_for('relay_hosts'))

@app.route('/relay-hosts/replace', methods=['POST'])
@login_required
@admin_required
def replace_relay_host():
    """Массовая замена релей-хоста во всех правилах"""
    old_host = sanitize_input(request.form.get('old_host',''))
    new_host = sanitize_input(request.form.get('new_host',''))
    
    if not old_host or not new_host:
        flash('Both old and new host are required', 'danger')
        return redirect(url_for('relay_hosts'))
    
    entries = parse_sender_transport()
    changed = 0
    for entry in entries:
        if old_host in entry['transport']:
            entry['transport'] = entry['transport'].replace(old_host, new_host)
            changed += 1
    
    if changed == 0:
        flash(f'No rules found with host {old_host}', 'warning')
        return redirect(url_for('relay_hosts'))
    
    sender_file = get_sender_transport_file()
    content = "# Postfix sender-dependent relayhost map\n# Managed via web interface\n\n"
    for entry in entries:
        line = f"{entry['sender']}\t{entry['transport']}"
        if entry.get('options'):
            for k, v in entry['options'].items():
                if v: line += f" {k}={v}"
        content += line + "\n"
    
    success, error = atomic_write_file(sender_file, content)
    if success:
        subprocess.run(['/usr/sbin/postmap', sender_file], check=True, capture_output=True)
        flash(f'Replaced {old_host} → {new_host} in {changed} rules', 'success')
    else:
        flash(f'Error saving: {error}', 'danger')
    
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
            lines = result.stdout.strip().split('\n')
            in_queue = False
            for line in lines:
                if line.startswith('-Queue ID-'):
                    in_queue = True
                    continue
                if line.startswith('-- '):
                    in_queue = False
                    continue
                if in_queue and line.strip():
                    entry = parse_queue_line(line)
                    if entry['queue_id']:
                        entries.append(entry)
    except Exception as e:
        flash(f'Error reading queue: {str(e)}', 'danger')
    
    stats = {'total': len(entries), 'active': 0, 'deferred': 0, 'hold': 0}
    for entry in entries:
        if 'active' in entry['status'].lower():
            stats['active'] += 1
        elif 'deferred' in entry['status'].lower():
            stats['deferred'] += 1
        elif 'hold' in entry['status'].lower():
            stats['hold'] += 1
    
    return render_template('queue.html', entries=entries, stats=stats)

@app.route('/queue/message/<queue_id>')
@login_required
@admin_required
def view_message_detail(queue_id):
    try:
        result = subprocess.run(['/usr/sbin/postcat', '-q', queue_id], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            flash(f'Message {queue_id} not found', 'danger')
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
        
        return render_template('message_detail.html', queue_id=queue_id, headers=headers, body=body)
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('view_queue'))

@app.route('/queue/flush')
@login_required
@admin_required
def flush_queue():
    try:
        subprocess.run(['/usr/sbin/postqueue', '-f'], check=True, capture_output=True, timeout=30)
        flash('Queue flush initiated', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Error: {e.stderr.decode().strip()}', 'danger')
    return redirect(url_for('view_queue'))

@app.route('/queue/delete/<queue_id>')
@login_required
@admin_required
def delete_queue_message(queue_id):
    try:
        subprocess.run(['/usr/sbin/postsuper', '-d', queue_id], check=True, capture_output=True, timeout=10)
        flash(f'Message {queue_id} deleted', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Error: {e.stderr.decode().strip()}', 'danger')
    return redirect(url_for('view_queue'))

@app.route('/queue/hold/<queue_id>')
@login_required
@admin_required
def hold_message(queue_id):
    try:
        subprocess.run(['/usr/sbin/postsuper', '-h', queue_id], check=True, capture_output=True, timeout=10)
        flash(f'Message {queue_id} placed on hold', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Error: {e.stderr.decode().strip()}', 'danger')
    return redirect(url_for('view_queue'))

@app.route('/queue/release/<queue_id>')
@login_required
@admin_required
def release_message(queue_id):
    try:
        subprocess.run(['/usr/sbin/postsuper', '-H', queue_id], check=True, capture_output=True, timeout=10)
        flash(f'Message {queue_id} released from hold', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Error: {e.stderr.decode().strip()}', 'danger')
    return redirect(url_for('view_queue'))

@app.route('/queue/requeue/<queue_id>')
@login_required
@admin_required
def requeue_message(queue_id):
    try:
        subprocess.run(['/usr/sbin/postsuper', '-r', queue_id], check=True, capture_output=True, timeout=10)
        flash(f'Message {queue_id} requeued', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Error: {e.stderr.decode().strip()}', 'danger')
    return redirect(url_for('view_queue'))

@app.route('/queue/delete-all')
@login_required
@admin_required
def delete_all_queue():
    try:
        subprocess.run(['/usr/sbin/postsuper', '-d', 'ALL'], check=True, capture_output=True, timeout=30)
        flash('All messages deleted', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Error: {e.stderr.decode().strip()}', 'danger')
    return redirect(url_for('view_queue'))

@app.route('/queue/delete-deferred')
@login_required
@admin_required
def delete_deferred():
    try:
        subprocess.run(['/usr/sbin/postsuper', '-d', 'ALL', 'deferred'], check=True, capture_output=True, timeout=30)
        flash('All deferred messages deleted', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Error: {e.stderr.decode().strip()}', 'danger')
    return redirect(url_for('view_queue'))

@app.route('/queue/delete-by-sender', methods=['POST'])
@login_required
@admin_required
def delete_by_sender():
    sender = sanitize_input(request.form.get('sender',''))
    if not sender:
        flash('Sender is required', 'danger')
        return redirect(url_for('view_queue'))
    try:
        result = subprocess.run(['/usr/sbin/postqueue', '-p'], capture_output=True, text=True, timeout=10)
        deleted = 0
        for line in result.stdout.split('\n'):
            if sender in line:
                parts = line.split()
                if parts:
                    try:
                        subprocess.run(['/usr/sbin/postsuper', '-d', parts[0]], check=True, capture_output=True, timeout=5)
                        deleted += 1
                    except: pass
        flash(f'Deleted {deleted} messages from sender {sender}', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('view_queue'))

@app.route('/queue/delete-by-domain', methods=['POST'])
@login_required
@admin_required
def delete_by_domain():
    domain = sanitize_input(request.form.get('domain',''))
    if not domain:
        flash('Domain is required', 'danger')
        return redirect(url_for('view_queue'))
    try:
        result = subprocess.run(['/usr/sbin/postqueue', '-p'], capture_output=True, text=True, timeout=10)
        deleted = 0
        for line in result.stdout.split('\n'):
            if domain in line:
                parts = line.split()
                if parts:
                    try:
                        subprocess.run(['/usr/sbin/postsuper', '-d', parts[0]], check=True, capture_output=True, timeout=5)
                        deleted += 1
                    except: pass
        flash(f'Deleted {deleted} messages for domain {domain}', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('view_queue'))

# --- Logs ---
@app.route('/logs')
@login_required
def view_logs():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            all_lines = f.readlines()
            lines = all_lines[-MAX_LOG_LINES:]
    parsed = [parse_log_line(line.strip()) for line in lines]
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
        if search and search.lower() not in entry['raw'].lower():
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
    return render_template('logs.html', logs=filtered, filter_type=filter_type, search=search,
                           from_filter=from_filter, to_filter=to_filter,
                           status_filter=status_filter, relay_filter=relay_filter)

@app.route('/api/logs')
@login_required
def api_logs():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            all_lines = f.readlines()
            lines = all_lines[-100:]
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
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
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# --- HTTPS Configuration ---
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

@app.before_request
def before_request():
    if request.headers.get('X-Forwarded-Proto', 'http') != 'https':
        url = request.url.replace('http://', 'https://', 1)
        return redirect(url, code=301)

# --- File Paths ---
TRANSPORT_FILE = '/etc/postfix/transport'
SENDER_TRANSPORT_FILE = '/etc/postfix/sender_transport'
MAIN_CF_FILE = '/etc/postfix/main.cf'
USERS_FILE = os.environ.get('USERS_FILE', '/opt/postfix-admin/users.json')
LOG_FILE = '/var/log/maillog'
MAX_LOG_LINES = 500

# --- Configuration Parameters ---
IMPORTANT_PARAMS = {
    'myhostname': {
        'name': 'Hostname',
        'description': 'Fully qualified domain name of the mail server',
        'type': 'text',
        'required': True
    },
    'mydomain': {
        'name': 'Domain',
        'description': 'Primary domain of the mail server',
        'type': 'text',
        'required': True
    },
    'mydestination': {
        'name': 'Destinations',
        'description': 'Domains for local delivery',
        'type': 'text',
        'required': True
    },
    'mynetworks': {
        'name': 'Trusted Networks',
        'description': 'Networks allowed to relay mail',
        'type': 'text',
        'required': True
    },
    'inet_interfaces': {
        'name': 'Interfaces',
        'description': 'Network interfaces to listen on',
        'type': 'select',
        'options': ['all', 'localhost', '127.0.0.1'],
        'required': True
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
        'options': ['none', 'may', 'encrypt'],
        'required': False
    },
    'relayhost': {
        'name': 'Relay Host',
        'description': 'SMTP server for relaying outgoing mail',
        'type': 'text',
        'required': False
    }
}

# --- Flask-Login Setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- User Management ---
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

# --- File Operations ---
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
                try:
                    os.unlink(f)
                except:
                    pass

# --- Parsers ---
def parse_main_cf():
    params = {}
    if not os.path.exists(MAIN_CF_FILE):
        return params

    with open(MAIN_CF_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().split('#')[0].strip()
                if key in IMPORTANT_PARAMS:
                    params[key] = value
    return params

def parse_transport():
    entries = []
    if not os.path.exists(TRANSPORT_FILE):
        return entries

    with open(TRANSPORT_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                entries.append({
                    'domain': parts[0],
                    'destination': parts[1]
                })
    return entries

def parse_sender_transport():
    entries = []
    if not os.path.exists(SENDER_TRANSPORT_FILE):
        return entries

    with open(SENDER_TRANSPORT_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                options = {}
                for part in parts[2:]:
                    if '=' in part:
                        k, v = part.split('=', 1)
                        options[k] = v
                entries.append({
                    'sender': parts[0],
                    'transport': parts[1],
                    'options': options
                })
    return entries

def sanitize_input(value):
    if not value:
        return ''
    value = value.strip()
    dangerous_chars = [';', '|', '&', '$', '`', '(', ')', '{', '}', '<', '>', '\n', '\r']
    for char in dangerous_chars:
        value = value.replace(char, '')
    return value

# --- Routes ---
@app.route('/')
@login_required
def index():
    return redirect(url_for('main_config'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username', ''))
        password = request.form.get('password', '')

        if not username or not password:
            flash('Please enter username and password', 'danger')
            return render_template('login.html')

        users = load_users()
        
        if username in users:
            if check_password_hash(users[username]['password'], password):
                user = User(username, users[username].get('role', 'user'))
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
        if IMPORTANT_PARAMS[key].get('required') and not value:
            flash(f"Parameter '{IMPORTANT_PARAMS[key]['name']}' is required", 'danger')
            return redirect(url_for('main_config'))
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
        flash(f'Error reloading Postfix: {e.stderr}', 'danger')
    return redirect(url_for('main_config'))

@app.route('/transport')
@login_required
def transport():
    entries = parse_transport()
    return render_template('transport.html', entries=entries)

@app.route('/transport/add', methods=['POST'])
@login_required
@admin_required
def add_transport():
    domain = sanitize_input(request.form.get('domain', ''))
    destination = sanitize_input(request.form.get('destination', ''))

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

@app.route('/sender-routing')
@login_required
def sender_routing():
    entries = parse_sender_transport()
    return render_template('sender_routing.html', entries=entries)

@app.route('/sender-routing/add', methods=['POST'])
@login_required
@admin_required
def add_sender_routing():
    sender = sanitize_input(request.form.get('sender', ''))
    transport = sanitize_input(request.form.get('transport', ''))
    
    if not sender or not transport:
        flash('Sender and transport are required', 'danger')
        return redirect(url_for('sender_routing'))

    options = {}
    if request.form.get('use_auth') == 'yes':
        options['smtp_sasl_auth_enable'] = 'yes'
        username = sanitize_input(request.form.get('smtp_username', ''))
        if username:
            options['smtp_username'] = username

    entries = parse_sender_transport()
    entries.append({
        'sender': sender,
        'transport': transport,
        'options': options
    })

    content = "# Postfix sender-dependent transport map\n# Managed via web interface\n\n"
    for entry in entries:
        line = f"{entry['sender']}\t{entry['transport']}"
        if entry.get('options'):
            for k, v in entry['options'].items():
                if v:
                    line += f" {k}={v}"
        content += line + "\n"

    success, error = atomic_write_file(SENDER_TRANSPORT_FILE, content)
    
    if success:
        subprocess.run(['/usr/sbin/postmap', SENDER_TRANSPORT_FILE], check=True, capture_output=True)
        flash(f'Routing rule added: {sender} → {transport}', 'success')
    else:
        flash(f'Error saving: {error}', 'danger')

    return redirect(url_for('sender_routing'))

@app.route('/logs')
@login_required
def view_logs():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            all_lines = f.readlines()
            lines = all_lines[-MAX_LOG_LINES:]

    filter_type = request.args.get('filter', 'all')
    search = sanitize_input(request.args.get('search', ''))

    filtered_lines = []
    for line in lines:
        if search and search.lower() not in line.lower():
            continue
        if filter_type == 'errors' and not any(k in line.lower() for k in ['error', 'fail', 'reject']):
            continue
        elif filter_type == 'postfix' and 'postfix' not in line.lower():
            continue
        filtered_lines.append(line.strip())

    return render_template('logs.html', lines=filtered_lines, filter_type=filter_type, search=search)

@app.route('/api/status')
@login_required
def api_status():
    try:
        result = subprocess.run(['/usr/bin/systemctl', 'is-active', 'postfix'], 
                              capture_output=True, text=True, timeout=5)
        return jsonify({
            'running': result.stdout.strip() == 'active',
            'status': result.stdout.strip()
        })
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
    
    password = click.prompt('Password', hide_confirmation=True)
    role = click.prompt('Role (admin/user)', default='user', type=click.Choice(['admin', 'user']))

    users[username] = {
        'password': generate_password_hash(password),
        'role': role,
        'created': datetime.now().isoformat()
    }
    
    if save_users(users):
        click.echo(f'User {username} created with role {role}')

@app.cli.command('list-users')
def list_users():
    users = load_users()
    for username, data in users.items():
        print(f"{username} - {data.get('role', 'user')}")

@app.errorhandler(404)
def not_found(e):
    return render_template('base.html', error='Page not found'), 404

if __name__ == '__main__':
    if not os.path.exists(USERS_FILE):
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, 'w') as f:
            json.dump({}, f)
    app.run(host='127.0.0.1', port=5000, debug=False)
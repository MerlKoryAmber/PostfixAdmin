#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root${NC}"
    exit 1
fi

INSTALL_DIR="/opt/postfix-admin"
APP_USER="postfixadmin"
APP_GROUP="postfixadmin"

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}Postfix Admin Installation${NC}"
echo -e "${BLUE}=========================================${NC}"

echo -e "\n${GREEN}Installing system dependencies...${NC}"
dnf install -y epel-release
dnf install -y python3 python3-pip python3-flask python3-gunicorn postfix nginx openssl gcc

echo -e "\n${GREEN}Installing Flask-Login...${NC}"
pip3 install flask-login

echo -e "\n${GREEN}Creating application user...${NC}"
useradd -r -s /sbin/nologin -d $INSTALL_DIR $APP_USER 2>/dev/null || true

echo -e "\n${GREEN}Setting up directory structure...${NC}"
mkdir -p $INSTALL_DIR/{templates,static,deploy}
cp app.py $INSTALL_DIR/
cp -r templates/* $INSTALL_DIR/templates/
cp -r static/* $INSTALL_DIR/static/
cp deploy/nginx-https.conf $INSTALL_DIR/deploy/
cp deploy/postfix-admin.service $INSTALL_DIR/deploy/

echo -e "\n${GREEN}Generating self-signed SSL certificate...${NC}"
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:4096 \
    -keyout /etc/nginx/ssl/postfix-admin.key \
    -out /etc/nginx/ssl/postfix-admin.crt \
    -subj "/C=RU/ST=Moscow/L=Moscow/O=InterROS/CN=$(hostname -I | awk '{print $1}')"

chmod 600 /etc/nginx/ssl/postfix-admin.key
chmod 644 /etc/nginx/ssl/postfix-admin.crt

echo -e "\n${GREEN}Configuring Nginx...${NC}"
rm -f /etc/nginx/conf.d/default.conf
cp $INSTALL_DIR/deploy/nginx-https.conf /etc/nginx/conf.d/postfix-admin.conf

if nginx -t 2>&1; then
    echo -e "${GREEN}Nginx configuration is OK.${NC}"
else
    echo -e "${RED}Nginx configuration test failed! Aborting.${NC}"
    exit 1
fi

# --- Создание C-обёртки для postfix reload ---
echo -e "\n${GREEN}Creating SUID C-wrapper for postfix reload...${NC}"
cat > /tmp/postfix-reload.c << 'EOF'
#include <unistd.h>
#include <stdlib.h>
#include <sys/types.h>

int main() {
    setreuid(0, 0);
    setregid(0, 0);
    return system("/usr/sbin/postfix reload");
}
EOF

gcc -o /usr/local/bin/postfix-reload /tmp/postfix-reload.c
rm -f /tmp/postfix-reload.c

chown root:$APP_GROUP /usr/local/bin/postfix-reload
chmod 4750 /usr/local/bin/postfix-reload

echo -e "\n${GREEN}Creating systemd service with Gunicorn...${NC}"
SECRET_KEY=$(openssl rand -hex 32)
cat > /etc/systemd/system/postfix-admin.service << EOF
[Unit]
Description=Postfix Admin Web Interface
After=network.target postfix.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$INSTALL_DIR
Environment="SECRET_KEY=$SECRET_KEY"
Environment="USERS_FILE=$INSTALL_DIR/users.json"
Environment="PYTHONPATH=/usr/local/lib/python3.9/site-packages"
ExecStart=/usr/bin/gunicorn -w 4 -b 127.0.0.1:8000 app:app
Restart=always
RestartSec=10

# Разрешаем выполнение SUID-бинарников
NoNewPrivileges=no

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable postfix-admin

echo -e "\n${GREEN}Setting permissions...${NC}"
chown -R $APP_USER:$APP_GROUP $INSTALL_DIR
usermod -a -G postfix $APP_USER

# Права на /etc/postfix
chown root:postfix /etc/postfix
chmod 775 /etc/postfix
chmod 664 /etc/postfix/main.cf 2>/dev/null || true
chmod 664 /etc/postfix/transport 2>/dev/null || true
chmod 664 /etc/postfix/sender_transport 2>/dev/null || true

echo "{}" > $INSTALL_DIR/users.json
chown $APP_USER:$APP_GROUP $INSTALL_DIR/users.json
chmod 640 $INSTALL_DIR/users.json

echo "[]" > $INSTALL_DIR/ip_whitelist.json
chown $APP_USER:$APP_GROUP $INSTALL_DIR/ip_whitelist.json
chmod 640 $INSTALL_DIR/ip_whitelist.json

echo -e "\n${GREEN}Configuring log file access...${NC}"
if getent group adm > /dev/null; then
    usermod -a -G adm $APP_USER
fi
if [ -f /var/log/maillog ]; then
    chmod 644 /var/log/maillog
fi

echo -e "\n${GREEN}Firewall...${NC}"
firewall-cmd --permanent --add-service=http --add-service=https 2>/dev/null || true
firewall-cmd --reload 2>/dev/null || true

# --- SELinux (если включен) ---
if command -v semanage &> /dev/null && [ "$(getenforce)" != "Disabled" ]; then
    echo -e "\n${YELLOW}SELinux detected, adding policy for SUID wrapper...${NC}"
    semanage fcontext -a -t bin_t /usr/local/bin/postfix-reload 2>/dev/null || true
    restorecon -v /usr/local/bin/postfix-reload
fi

# Запуск сервисов
echo -e "\n${GREEN}Starting postfix-admin with Gunicorn...${NC}"
systemctl start postfix-admin
sleep 2
if systemctl is-active --quiet postfix-admin; then
    echo -e "${GREEN}postfix-admin is running.${NC}"
else
    echo -e "${RED}postfix-admin failed to start!${NC}"
    journalctl -u postfix-admin --no-pager -n 10
    exit 1
fi

echo -e "\n${GREEN}Starting Nginx...${NC}"
systemctl start nginx
sleep 2
if systemctl is-active --quiet nginx; then
    echo -e "${GREEN}Nginx is running.${NC}"
else
    echo -e "${RED}Nginx failed to start!${NC}"
    journalctl -u nginx --no-pager -n 10
    exit 1
fi

echo -e "\n${GREEN}Checking listening ports...${NC}"
if ss -tlnp | grep ':443 ' && ss -tlnp | grep ':8000 '; then
    echo -e "${GREEN}Both ports 443 and 8000 are listening.${NC}"
else
    echo -e "${RED}Port missing! Something went wrong.${NC}"
fi

# Проверка C-обёртки
echo -e "\n${GREEN}Testing SUID wrapper...${NC}"
if sudo -u $APP_USER /usr/local/bin/postfix-reload 2>&1; then
    echo -e "${GREEN}SUID wrapper works correctly.${NC}"
else
    echo -e "${RED}SUID wrapper test failed! Check permissions and SELinux.${NC}"
fi

# --- Создание администратора ---
echo -e "\n${BLUE}=========================================${NC}"
echo -e "${BLUE}Creating admin user${NC}"
echo -e "${BLUE}=========================================${NC}"
read -p "Create admin user now? (y/N): " CREATE_ADMIN
if [[ "$CREATE_ADMIN" =~ ^[Yy]$ ]]; then
    cd $INSTALL_DIR
    export FLASK_APP=app.py
    export USERS_FILE=$INSTALL_DIR/users.json
    flask create-user
    chown $APP_USER:$APP_GROUP $INSTALL_DIR/users.json
    echo -e "${GREEN}Admin user created successfully!${NC}"
else
    echo -e "${YELLOW}Skipping admin creation.${NC}"
fi

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}Installation complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo -e "Access: ${YELLOW}https://$(hostname -I | awk '{print $1}')${NC}"
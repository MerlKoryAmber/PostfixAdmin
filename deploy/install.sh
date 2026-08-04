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

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}Postfix Admin Installation${NC}"
echo -e "${BLUE}=========================================${NC}"

echo -e "\n${GREEN}Installing dependencies...${NC}"
dnf install -y epel-release
dnf install -y python3 python3-pip postfix nginx openssl

echo -e "\n${GREEN}Creating application user...${NC}"
useradd -r -s /sbin/nologin -d $INSTALL_DIR $APP_USER 2>/dev/null || true

echo -e "\n${GREEN}Setting up application directory...${NC}"
mkdir -p $INSTALL_DIR/{templates,static}
cp app.py $INSTALL_DIR/
cp requirements.txt $INSTALL_DIR/
cp -r templates/* $INSTALL_DIR/templates/
cp -r static/* $INSTALL_DIR/static/

echo -e "\n${GREEN}Installing Python packages...${NC}"
python3 -m venv $INSTALL_DIR/venv
source $INSTALL_DIR/venv/bin/activate
pip install -r $INSTALL_DIR/requirements.txt
deactivate

echo -e "\n${GREEN}Generating SSL certificate...${NC}"
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:4096 \
    -keyout /etc/nginx/ssl/postfix-admin.key \
    -out /etc/nginx/ssl/postfix-admin.crt \
    -subj "/C=RU/ST=Moscow/L=Moscow/O=InterROS/CN=$(hostname -I | awk '{print $1}')"

echo -e "\n${GREEN}Configuring Nginx...${NC}"
cp deploy/nginx-https.conf /etc/nginx/conf.d/postfix-admin.conf

echo -e "\n${GREEN}Configuring systemd service...${NC}"
cp deploy/postfix-admin.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable postfix-admin

echo -e "\n${GREEN}Setting permissions...${NC}"
chown -R $APP_USER:$APP_USER $INSTALL_DIR
usermod -a -G postfix $APP_USER
echo "{}" > $INSTALL_DIR/users.json
chown $APP_USER:$APP_USER $INSTALL_DIR/users.json
chmod 640 $INSTALL_DIR/users.json

echo -e "\n${GREEN}Configuring firewall...${NC}"
firewall-cmd --permanent --add-service=http 2>/dev/null || true
firewall-cmd --permanent --add-service=https 2>/dev/null || true
firewall-cmd --reload 2>/dev/null || true

echo -e "\n${GREEN}Starting services...${NC}"
systemctl start postfix-admin
systemctl start nginx

echo -e "\n${GREEN}Creating admin user...${NC}"
cd $INSTALL_DIR
source venv/bin/activate
export FLASK_APP=app.py
export USERS_FILE=$INSTALL_DIR/users.json
flask create-user
deactivate

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo -e "Access: ${YELLOW}https://$(hostname -I | awk '{print $1}')${NC}"
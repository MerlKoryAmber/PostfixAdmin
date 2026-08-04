#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
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

echo -e "\n${GREEN}Setting up directory...${NC}"
mkdir -p $INSTALL_DIR/{templates,static,deploy}
cp app.py requirements.txt $INSTALL_DIR/
cp -r templates/* $INSTALL_DIR/templates/
cp -r static/* $INSTALL_DIR/static/
cp deploy/nginx-https.conf $INSTALL_DIR/deploy/
cp deploy/postfix-admin.service $INSTALL_DIR/deploy/

echo -e "\n${GREEN}Creating Python virtual environment...${NC}"
python3 -m venv --without-pip $INSTALL_DIR/venv
source $INSTALL_DIR/venv/bin/activate
curl -sS https://bootstrap.pypa.io/pip/3.9/get-pip.py | python
pip install -r $INSTALL_DIR/requirements.txt
deactivate

echo -e "\n${GREEN}Generating self-signed SSL certificate...${NC}"
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:4096 \
    -keyout /etc/nginx/ssl/postfix-admin.key \
    -out /etc/nginx/ssl/postfix-admin.crt \
    -subj "/C=RU/ST=Moscow/L=Moscow/O=InterROS/CN=$(hostname -I | awk '{print $1}')"

echo -e "\n${GREEN}Configuring Nginx...${NC}"
cp $INSTALL_DIR/deploy/nginx-https.conf /etc/nginx/conf.d/postfix-admin.conf

echo -e "\n${GREEN}Configuring systemd...${NC}"
cp $INSTALL_DIR/deploy/postfix-admin.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable postfix-admin

echo -e "\n${GREEN}Setting permissions...${NC}"
chown -R $APP_USER:$APP_USER $INSTALL_DIR
usermod -a -G postfix $APP_USER
echo "{}" > $INSTALL_DIR/users.json
chown $APP_USER:$APP_USER $INSTALL_DIR/users.json
chmod 640 $INSTALL_DIR/users.json

echo -e "\n${GREEN}Firewall...${NC}"
firewall-cmd --permanent --add-service=http --add-service=https 2>/dev/null || true
firewall-cmd --reload 2>/dev/null || true

echo -e "\n${GREEN}Starting services...${NC}"
systemctl start postfix-admin
systemctl start nginx

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}Installation complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo -e "Now create an admin user by running:"
echo -e "cd $INSTALL_DIR && source venv/bin/activate && export FLASK_APP=app.py && flask create-user"
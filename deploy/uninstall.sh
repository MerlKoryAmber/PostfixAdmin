#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root${NC}"
    exit 1
fi

INSTALL_DIR="/opt/postfix-admin"
APP_USER="postfixadmin"

echo -e "${YELLOW}=========================================${NC}"
echo -e "${YELLOW}Postfix Admin Uninstall${NC}"
echo -e "${YELLOW}=========================================${NC}"
echo ""

read -p "This will completely remove Postfix Admin web interface. Continue? (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo -e "\n${GREEN}Stopping and disabling postfix-admin service...${NC}"
systemctl stop postfix-admin 2>/dev/null || true
systemctl disable postfix-admin 2>/dev/null || true

echo -e "\n${GREEN}Removing systemd unit...${NC}"
rm -f /etc/systemd/system/postfix-admin.service
systemctl daemon-reload

echo -e "\n${GREEN}Removing SUID wrapper...${NC}"
rm -f /usr/local/bin/postfix-reload

echo -e "\n${GREEN}Removing application directory...${NC}"
rm -rf "$INSTALL_DIR"

echo -e "\n${GREEN}Removing Nginx configuration...${NC}"
rm -f /etc/nginx/conf.d/postfix-admin.conf

echo -e "\n${GREEN}Removing SSL certificate...${NC}"
rm -f /etc/nginx/ssl/postfix-admin.crt
rm -f /etc/nginx/ssl/postfix-admin.key

echo -e "\n${GREEN}Removing application user...${NC}"
userdel "$APP_USER" 2>/dev/null || true

echo -e "\n${GREEN}Removing firewall rules...${NC}"
firewall-cmd --permanent --remove-service=http 2>/dev/null || true
firewall-cmd --permanent --remove-service=https 2>/dev/null || true
firewall-cmd --reload 2>/dev/null || true

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}Uninstall complete.${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo -e "${YELLOW}Note: Postfix and Nginx packages were not removed.${NC}"
echo "To reload Nginx configuration changes, run: systemctl reload nginx"
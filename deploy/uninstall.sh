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
SENDER_MAP="/etc/postfix/sender_transport"
SASL_PASSWD="/etc/postfix/sender_sasl_passwd"
TLS_CERT="/etc/nginx/ssl/postfix-admin.crt"
TLS_KEY="/etc/nginx/ssl/postfix-admin.key"

echo -e "${YELLOW}=========================================${NC}"
echo -e "${YELLOW}Postfix Admin Uninstall${NC}"
echo -e "${YELLOW}=========================================${NC}"
echo ""
echo -e "${YELLOW}The following Postfix files will be preserved:${NC}"
echo "  - $SENDER_MAP"
echo "  - ${SENDER_MAP}.db"
echo "  - $SASL_PASSWD"
echo "  - ${SASL_PASSWD}.db"
echo "  - /etc/postfix/main.cf"
echo ""

read -p "Remove Postfix Admin web interface only? (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

read -p "Also remove empty panel-created map files if unused? (y/N): " REMOVE_MAPS
read -p "Also remove Postfix Admin TLS certificate/key from /etc/nginx/ssl? (y/N): " REMOVE_TLS
read -p "Also remove firewall-cmd http/https service rules added for the panel? (y/N): " REMOVE_FIREWALL
read -p "Also remove local user $APP_USER if it exists? (y/N): " REMOVE_APP_USER
if [[ "$REMOVE_MAPS" =~ ^[Yy]$ ]]; then
    for f in "$SENDER_MAP" "$SASL_PASSWD"; do
        if [ -f "$f" ] && grep -q "Managed via web interface" "$f" 2>/dev/null; then
            if [ "$(grep -cve '^[[:space:]]*$' -e '^#' "$f")" -eq 0 ]; then
                echo -e "${YELLOW}Removing empty map: $f${NC}"
                rm -f "$f" "${f}.db" "${f}.bak"
            else
                echo -e "${YELLOW}Keeping non-empty map: $f${NC}"
            fi
        fi
    done
fi

echo -e "\n${GREEN}Stopping and disabling postfix-admin service...${NC}"
systemctl stop postfix-admin 2>/dev/null || true
systemctl disable postfix-admin 2>/dev/null || true

echo -e "\n${GREEN}Removing systemd unit...${NC}"
rm -f /etc/systemd/system/postfix-admin.service
systemctl daemon-reload

echo -e "\n${GREEN}Removing application directory...${NC}"
rm -rf "$INSTALL_DIR"

echo -e "\n${GREEN}Removing Nginx configuration...${NC}"
rm -f /etc/nginx/conf.d/postfix-admin.conf
if nginx -t 2>/dev/null; then
    systemctl reload nginx 2>/dev/null || true
    echo -e "${GREEN}Nginx reloaded.${NC}"
else
    echo -e "${YELLOW}Nginx config test failed — reload skipped.${NC}"
fi

if [[ "$REMOVE_TLS" =~ ^[Yy]$ ]]; then
    echo -e "\n${GREEN}Removing TLS certificate/key...${NC}"
    rm -f "$TLS_CERT" "$TLS_KEY"
else
    echo -e "\n${YELLOW}Keeping TLS certificate/key:${NC} $TLS_CERT $TLS_KEY"
fi

if [[ "$REMOVE_APP_USER" =~ ^[Yy]$ ]]; then
    echo -e "\n${GREEN}Removing application user...${NC}"
    userdel "$APP_USER" 2>/dev/null || true
else
    echo -e "\n${YELLOW}Keeping application user:${NC} $APP_USER"
fi

if [[ "$REMOVE_FIREWALL" =~ ^[Yy]$ ]]; then
    echo -e "\n${GREEN}Removing firewall rules...${NC}"
    firewall-cmd --permanent --remove-service=http 2>/dev/null || true
    firewall-cmd --permanent --remove-service=https 2>/dev/null || true
    firewall-cmd --reload 2>/dev/null || true
else
    echo -e "\n${YELLOW}Keeping firewall rules unchanged.${NC}"
fi

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}Uninstall complete.${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo -e "${YELLOW}Postfix configuration and routing maps were kept (unless you opted to remove empty maps).${NC}"
echo -e "${YELLOW}Postfix and Nginx packages were not removed.${NC}"

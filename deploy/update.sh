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
BACKUP_DIR="/opt/postfix-admin-backup-$(date +%Y%m%d-%H%M%S)"

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}Postfix Admin Update Script${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

read -p "This will update Postfix Admin. Continue? (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Проверка существования установки
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}Postfix Admin is not installed in $INSTALL_DIR${NC}"
    exit 1
fi

# Выбор режима обновления
echo ""
echo -e "${YELLOW}Update mode:${NC}"
echo "  1) Update all files (app.py, templates, static, deploy scripts)"
echo "  2) Update app.py only"
echo "  3) Update templates only"
echo "  4) Update static files only"
echo "  5) Update deploy scripts only"
read -p "Select mode [1-5]: " UPDATE_MODE

case $UPDATE_MODE in
    1) UPDATE_ALL=true ;;
    2) UPDATE_APP=true ;;
    3) UPDATE_TEMPLATES=true ;;
    4) UPDATE_STATIC=true ;;
    5) UPDATE_DEPLOY=true ;;
    *) echo -e "${RED}Invalid selection${NC}"; exit 1 ;;
esac

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Starting update...${NC}"
echo -e "${GREEN}=========================================${NC}"

# 1. Создание резервной копии
echo -e "\n${YELLOW}Creating backup in $BACKUP_DIR...${NC}"
mkdir -p "$BACKUP_DIR"
cp -r "$INSTALL_DIR"/* "$BACKUP_DIR/" 2>/dev/null || true
echo -e "${GREEN}Backup created.${NC}"

# 2. Остановка сервиса
echo -e "\n${YELLOW}Stopping postfix-admin service...${NC}"
systemctl stop postfix-admin
sleep 2

# 3. Обновление файлов
if [ "$UPDATE_ALL" = true ] || [ "$UPDATE_APP" = true ]; then
    echo -e "\n${GREEN}Updating app.py...${NC}"
    if [ -f app.py ]; then
        cp app.py "$INSTALL_DIR/app.py"
        echo -e "${GREEN}app.py updated.${NC}"
    else
        echo -e "${YELLOW}app.py not found in current directory. Skipping.${NC}"
    fi
fi

if [ "$UPDATE_ALL" = true ] || [ "$UPDATE_TEMPLATES" = true ]; then
    echo -e "\n${GREEN}Updating templates...${NC}"
    if [ -d templates ]; then
        cp -r templates/* "$INSTALL_DIR/templates/"
        echo -e "${GREEN}Templates updated.${NC}"
    else
        echo -e "${YELLOW}templates/ not found in current directory. Skipping.${NC}"
    fi
fi

if [ "$UPDATE_ALL" = true ] || [ "$UPDATE_STATIC" = true ]; then
    echo -e "\n${GREEN}Updating static files...${NC}"
    if [ -d static ]; then
        cp -r static/* "$INSTALL_DIR/static/"
        echo -e "${GREEN}Static files updated.${NC}"
    else
        echo -e "${YELLOW}static/ not found in current directory. Skipping.${NC}"
    fi
fi

if [ "$UPDATE_ALL" = true ] || [ "$UPDATE_DEPLOY" = true ]; then
    echo -e "\n${GREEN}Updating deploy scripts...${NC}"
    if [ -d deploy ]; then
        cp deploy/install.sh "$INSTALL_DIR/deploy/" 2>/dev/null || true
        cp deploy/uninstall.sh "$INSTALL_DIR/deploy/" 2>/dev/null || true
        cp deploy/update.sh "$INSTALL_DIR/deploy/" 2>/dev/null || true
        cp deploy/nginx-https.conf "$INSTALL_DIR/deploy/" 2>/dev/null || true
        cp deploy/postfix-admin.service "$INSTALL_DIR/deploy/" 2>/dev/null || true
        
        # Обновление systemd unit если он изменился
        if [ -f deploy/postfix-admin.service ]; then
            cp deploy/postfix-admin.service /etc/systemd/system/postfix-admin.service
            systemctl daemon-reload
            echo -e "${GREEN}Systemd unit updated.${NC}"
        fi
        echo -e "${GREEN}Deploy scripts updated.${NC}"
    else
        echo -e "${YELLOW}deploy/ not found in current directory. Skipping.${NC}"
    fi
fi

# 4. Обновление прав
echo -e "\n${GREEN}Updating permissions...${NC}"
chown -R $APP_USER:$APP_GROUP "$INSTALL_DIR"
echo -e "${GREEN}Permissions updated.${NC}"

# 5. Запуск сервиса
echo -e "\n${GREEN}Starting postfix-admin service...${NC}"
systemctl start postfix-admin
sleep 2

# 6. Проверка статуса
if systemctl is-active --quiet postfix-admin; then
    echo -e "${GREEN}✅ postfix-admin is running. Update successful!${NC}"
else
    echo -e "${RED}❌ postfix-admin failed to start! Rolling back...${NC}"
    
    # Откат
    systemctl stop postfix-admin 2>/dev/null || true
    rm -rf "$INSTALL_DIR"
    cp -r "$BACKUP_DIR" "$INSTALL_DIR"
    chown -R $APP_USER:$APP_GROUP "$INSTALL_DIR"
    systemctl start postfix-admin
    
    if systemctl is-active --quiet postfix-admin; then
        echo -e "${YELLOW}⚠️  Rollback successful. Previous version restored.${NC}"
    else
        echo -e "${RED}❌ Rollback failed! Check logs: journalctl -u postfix-admin -n 50${NC}"
        exit 1
    fi
    exit 1
fi

# 7. Вывод информации
echo ""
echo -e "${BLUE}=========================================${NC}"
echo -e "${GREEN}Update completed!${NC}"
echo -e "${BLUE}=========================================${NC}"
echo -e "Backup location: ${YELLOW}$BACKUP_DIR${NC}"
echo -e "To rollback manually: ${YELLOW}systemctl stop postfix-admin && rm -rf $INSTALL_DIR && cp -r $BACKUP_DIR $INSTALL_DIR && systemctl start postfix-admin${NC}"
echo ""
echo -e "${YELLOW}Note: User data (users.json, ip_whitelist.json) was preserved.${NC}"
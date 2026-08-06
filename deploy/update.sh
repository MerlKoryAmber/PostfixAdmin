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
GITHUB_REPO="https://github.com/MerlKoryAmber/PostfixAdmin"
TEMP_DIR="/tmp/postfix-admin-update"

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}Postfix Admin Update Script${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

read -p "This will update Postfix Admin from GitHub. Continue? (y/N): " CONFIRM
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
echo -e "${YELLOW}Update source:${NC}"
echo "  1) Download latest release (stable)"
echo "  2) Download from main branch (latest)"
echo "  3) Download specific tag/version"
read -p "Select [1-3]: " UPDATE_SOURCE

case $UPDATE_SOURCE in
    1) BRANCH="latest release" ;;
    2) BRANCH="main" ;;
    3) 
        read -p "Enter tag/version (e.g., v1.2.3): " TAG
        BRANCH="$TAG"
        ;;
    *) echo -e "${RED}Invalid selection${NC}"; exit 1 ;;
esac

echo ""
echo -e "${YELLOW}Update mode:${NC}"
echo "  1) Update all files"
echo "  2) Update app.py only"
echo "  3) Update templates only"
echo "  4) Update static files only"
echo "  5) Update deploy scripts only"
read -p "Select [1-5]: " UPDATE_MODE

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

# 2. Загрузка файлов из GitHub
echo -e "\n${YELLOW}Downloading files from GitHub...${NC}"

# Очистка временной директории
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

# Проверяем наличие git или используем wget/curl
if command -v git &> /dev/null; then
    echo -e "${GREEN}Using git to clone repository...${NC}"
    
    if [ "$UPDATE_SOURCE" = "1" ]; then
        # Получаем URL последнего релиза
        LATEST_RELEASE=$(curl -s https://api.github.com/repos/MerlKoryAmber/PostfixAdmin/releases/latest | grep "tarball_url" | cut -d '"' -f 4)
        if [ -n "$LATEST_RELEASE" ]; then
            curl -L -o "$TEMP_DIR/release.tar.gz" "$LATEST_RELEASE"
            tar -xzf "$TEMP_DIR/release.tar.gz" -C "$TEMP_DIR"
            # Перемещаем файлы из поддиректории
            mv "$TEMP_DIR"/MerlKoryAmber-PostfixAdmin-*/* "$TEMP_DIR/" 2>/dev/null || true
        else
            echo -e "${YELLOW}No releases found. Falling back to main branch.${NC}"
            git clone --depth 1 "$GITHUB_REPO" "$TEMP_DIR"
        fi
    elif [ "$UPDATE_SOURCE" = "2" ]; then
        git clone --depth 1 "$GITHUB_REPO" "$TEMP_DIR"
    else
        git clone --depth 1 --branch "$TAG" "$GITHUB_REPO" "$TEMP_DIR" 2>/dev/null || {
            echo -e "${RED}Tag $TAG not found. Trying as branch...${NC}"
            git clone --depth 1 --branch "$TAG" "$GITHUB_REPO" "$TEMP_DIR"
        }
    fi
else
    echo -e "${YELLOW}Git not found. Using wget to download archive...${NC}"
    
    if [ "$UPDATE_SOURCE" = "1" ]; then
        # Последний релиз
        LATEST_RELEASE=$(curl -s https://api.github.com/repos/MerlKoryAmber/PostfixAdmin/releases/latest | grep "tarball_url" | cut -d '"' -f 4)
        if [ -n "$LATEST_RELEASE" ]; then
            curl -L -o "$TEMP_DIR/release.tar.gz" "$LATEST_RELEASE"
        else
            curl -L -o "$TEMP_DIR/repo.zip" "$GITHUB_REPO/archive/refs/heads/main.zip"
        fi
    elif [ "$UPDATE_SOURCE" = "2" ]; then
        curl -L -o "$TEMP_DIR/repo.zip" "$GITHUB_REPO/archive/refs/heads/main.zip"
    else
        curl -L -o "$TEMP_DIR/repo.zip" "$GITHUB_REPO/archive/refs/tags/$TAG.zip"
    fi
    
    # Распаковка
    if [ -f "$TEMP_DIR/release.tar.gz" ]; then
        tar -xzf "$TEMP_DIR/release.tar.gz" -C "$TEMP_DIR"
        mv "$TEMP_DIR"/MerlKoryAmber-PostfixAdmin-*/* "$TEMP_DIR/" 2>/dev/null || true
    elif [ -f "$TEMP_DIR/repo.zip" ]; then
        unzip -q "$TEMP_DIR/repo.zip" -d "$TEMP_DIR"
        mv "$TEMP_DIR"/PostfixAdmin-*/* "$TEMP_DIR/" 2>/dev/null || true
    fi
fi

echo -e "${GREEN}Files downloaded successfully.${NC}"

# 3. Остановка сервиса
echo -e "\n${YELLOW}Stopping postfix-admin service...${NC}"
systemctl stop postfix-admin
sleep 2

# 4. Обновление файлов
if [ "$UPDATE_ALL" = true ] || [ "$UPDATE_APP" = true ]; then
    echo -e "\n${GREEN}Updating app.py...${NC}"
    if [ -f "$TEMP_DIR/app.py" ]; then
        cp "$TEMP_DIR/app.py" "$INSTALL_DIR/app.py"
        echo -e "${GREEN}app.py updated.${NC}"
    else
        echo -e "${YELLOW}app.py not found in repository. Skipping.${NC}"
    fi
fi

if [ "$UPDATE_ALL" = true ] || [ "$UPDATE_TEMPLATES" = true ]; then
    echo -e "\n${GREEN}Updating templates...${NC}"
    if [ -d "$TEMP_DIR/templates" ]; then
        cp -r "$TEMP_DIR/templates"/* "$INSTALL_DIR/templates/"
        echo -e "${GREEN}Templates updated.${NC}"
    else
        echo -e "${YELLOW}templates/ not found in repository. Skipping.${NC}"
    fi
fi

if [ "$UPDATE_ALL" = true ] || [ "$UPDATE_STATIC" = true ]; then
    echo -e "\n${GREEN}Updating static files...${NC}"
    if [ -d "$TEMP_DIR/static" ]; then
        cp -r "$TEMP_DIR/static"/* "$INSTALL_DIR/static/"
        echo -e "${GREEN}Static files updated.${NC}"
    else
        echo -e "${YELLOW}static/ not found in repository. Skipping.${NC}"
    fi
fi

if [ "$UPDATE_ALL" = true ] || [ "$UPDATE_DEPLOY" = true ]; then
    echo -e "\n${GREEN}Updating deploy scripts...${NC}"
    if [ -d "$TEMP_DIR/deploy" ]; then
        cp "$TEMP_DIR/deploy/install.sh" "$INSTALL_DIR/deploy/" 2>/dev/null || true
        cp "$TEMP_DIR/deploy/uninstall.sh" "$INSTALL_DIR/deploy/" 2>/dev/null || true
        cp "$TEMP_DIR/deploy/update.sh" "$INSTALL_DIR/deploy/" 2>/dev/null || true
        cp "$TEMP_DIR/deploy/nginx-https.conf" "$INSTALL_DIR/deploy/" 2>/dev/null || true
        cp "$TEMP_DIR/deploy/postfix-admin.service" "$INSTALL_DIR/deploy/" 2>/dev/null || true
        
        # Обновление systemd unit если он изменился
        if [ -f "$TEMP_DIR/deploy/postfix-admin.service" ]; then
            if ! cmp -s "$TEMP_DIR/deploy/postfix-admin.service" /etc/systemd/system/postfix-admin.service; then
                cp "$TEMP_DIR/deploy/postfix-admin.service" /etc/systemd/system/postfix-admin.service
                systemctl daemon-reload
                echo -e "${GREEN}Systemd unit updated.${NC}"
            fi
        fi
        echo -e "${GREEN}Deploy scripts updated.${NC}"
    else
        echo -e "${YELLOW}deploy/ not found in repository. Skipping.${NC}"
    fi
fi

# 5. Обновление прав
echo -e "\n${GREEN}Updating permissions...${NC}"
chown -R $APP_USER:$APP_GROUP "$INSTALL_DIR"
echo -e "${GREEN}Permissions updated.${NC}"

# 6. Очистка временных файлов
rm -rf "$TEMP_DIR"

# 7. Запуск сервиса
echo -e "\n${GREEN}Starting postfix-admin service...${NC}"
systemctl start postfix-admin
sleep 2

# 8. Проверка статуса
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

# 9. Вывод информации
echo ""
echo -e "${BLUE}=========================================${NC}"
echo -e "${GREEN}Update completed!${NC}"
echo -e "${BLUE}=========================================${NC}"
echo -e "Backup location: ${YELLOW}$BACKUP_DIR${NC}"
echo -e "Repository: ${YELLOW}$GITHUB_REPO${NC}"
echo ""
echo -e "${YELLOW}To rollback manually:${NC}"
echo -e "  systemctl stop postfix-admin"
echo -e "  rm -rf $INSTALL_DIR"
echo -e "  cp -r $BACKUP_DIR $INSTALL_DIR"
echo -e "  chown -R $APP_USER:$APP_GROUP $INSTALL_DIR"
echo -e "  systemctl start postfix-admin"
echo ""
echo -e "${GREEN}Note: User data (users.json, ip_whitelist.json) was preserved.${NC}"
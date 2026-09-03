
## Docker Setup (Recommended)

### Quick start
```bash
chmod +x docker-start.sh
./docker-start.sh
```

### Manual
```bash
# Build and start app + Telegram server
docker compose up -d

# App only (no Telegram)
docker compose up -d subz-studio

# With Nginx reverse proxy
docker compose --profile nginx up -d

# View logs
docker compose logs -f subz-studio

# Stop everything
docker compose down
```

### Services
| Service | Port | Description |
|---|---|---|
| subz-studio | 5000 | Main Flask app |
| tg-server | 8081 | Telegram Local Bot API (2GB uploads) |
| nginx | 80/443 | Reverse proxy (optional, --profile nginx) |

### Volumes (persisted)
- `./uploads/` — temp processing files
- `./downloads/` — encoded output videos
- `./fontcache/` — fontconfig cache
- `./tg-data/` — Telegram server data

### Environment variables
Edit `docker-compose.yml` or create a `.env` file:
```env
TG_API_ID=36668698
TG_API_HASH=5e1172b296563abf8ba9939c557c9f66
TG_PORT=8081
```

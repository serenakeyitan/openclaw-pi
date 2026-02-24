# Xiaohongshu MCP Integration for OpenClaw

This directory contains the Xiaohongshu (RedNote) MCP server integration for OpenClaw, enabling full control of a Xiaohongshu social media account.

## Installation Status

✅ **COMPLETE** - All components have been installed and configured:

- Docker Compose service configured
- SystemD service created and enabled
- MCP plugin files created in OpenClaw
- Monitoring and login scripts ready
- Service is running and accessible at http://localhost:18060/mcp

## Architecture

- **Service Type**: Docker container (xpzouying/xiaohongshu-mcp:latest)
- **Platform**: linux/amd64 (running via QEMU emulation on ARM64)
- **Port**: 127.0.0.1:18060 (localhost only - not exposed externally)
- **Protocol**: MCP (Model Context Protocol) via HTTP
- **Tools Available**: 13 MCP tools for content publishing and management

## Directory Structure

```
/root/.openclaw/services/xiaohongshu-mcp/
├── docker-compose.yml          # Docker service configuration
├── data/                       # Authentication cookies (auto-created)
├── images/                     # Uploaded images storage
├── check-login.sh             # Check authentication status
├── login.sh                   # Interactive login helper
├── verify-installation.sh     # Installation verification
├── test-mcp.sh               # MCP endpoint testing
└── README.md                 # This file
```

## Quick Start

### 1. Check Service Status

```bash
systemctl status xiaohongshu-mcp.service
docker ps | grep xiaohongshu-mcp
```

### 2. Authenticate with Xiaohongshu

**CRITICAL**: Only one active web session is allowed per account. Once logged in via MCP, do NOT login via web browser.

```bash
cd /root/.openclaw/services/xiaohongshu-mcp
./login.sh
```

This will display a QR code. Scan it with your Xiaohongshu mobile app to authenticate.

### 3. Verify Authentication

```bash
./check-login.sh
```

Expected output: `Login status: OK`

### 4. Verify OpenClaw Integration

OpenClaw was automatically restarted during installation to load the plugin.

Test via OpenClaw CLI or Discord bot:
```
Query: "What Xiaohongshu tools are available to me?"
```

Claude should list the available xiaohongshu MCP tools.

## Available MCP Tools

The integration provides 13 tools:

### Authentication
- `check_login_status` - Verify login and get username
- `get_login_qrcode` - Get QR code for re-authentication
- `delete_cookies` - Logout

### Content Publishing
- `publish_content` - Post text and images
  - Title: max 20 characters
  - Description: max 1,000 characters
  - Images: local file paths
- `publish_with_video` - Upload and publish videos
  - Local files only (no HTTP URLs)
  - Size: <1GB recommended

### Content Discovery
- `list_feeds` - Get homepage recommendations
- `search_feeds` - Search by keywords
- `get_feed_detail` - Get detailed post info with metrics and comments
- `user_profile` - Retrieve user information

### Engagement
- `post_comment_to_feed` - Comment on posts
- `reply_comment` - Reply to comments
- `like_feed` - Toggle like on a post
- `favorite_feed` - Toggle favorite on a post

## Usage Examples

### Example 1: Search for Posts

Via OpenClaw:
```
Search Xiaohongshu for posts about "旅游" (travel) and show me the top 3 results
```

### Example 2: Publish Content

Via OpenClaw:
```
Publish a post to Xiaohongshu with:
- Title: "新产品发布"
- Description: "很高兴向大家介绍我们的新产品..."
- Images: /root/images/product1.jpg
```

### Example 3: Engage with Content

Via OpenClaw:
```
Comment "很棒的分享!" on Xiaohongshu post [POST_ID]
```

## Monitoring & Maintenance

### Check Login Status

```bash
./check-login.sh
```

### View Service Logs

```bash
docker logs xiaohongshu-mcp
journalctl -u xiaohongshu-mcp.service -f
```

### Restart Service

```bash
systemctl restart xiaohongshu-mcp.service
```

### Update Docker Image

```bash
cd /root/.openclaw/services/xiaohongshu-mcp
docker compose pull
systemctl restart xiaohongshu-mcp.service
```

### Re-authenticate

If authentication expires:
```bash
./login.sh
# Scan the new QR code
./check-login.sh  # Verify
```

## Important Constraints

### Content Limits
- Title: Maximum 20 characters
- Description: Maximum 1,000 characters
- Images: Local file paths preferred over HTTP URLs
- Videos: Local files only, no HTTP links, <1GB recommended
- Posting rate: ~50 posts/day maximum to avoid platform restrictions

### Session Management
- **Single session only**: Do NOT login to the same account via web browser while MCP is active
- Cookies persist in `./data/` directory
- Monitor authentication status regularly
- Re-authenticate if session expires

### Performance Notes
- Running via QEMU emulation (x86_64 on ARM64)
- Slightly slower than native execution
- First run downloads ~150MB headless browser
- Requires active network connectivity

## Troubleshooting

### Service won't start
```bash
# Check Docker status
systemctl status docker

# Check logs
journalctl -u xiaohongshu-mcp.service -n 50

# Try manual start
cd /root/.openclaw/services/xiaohongshu-mcp
docker compose up
```

### Authentication fails
```bash
# Delete old cookies
rm -rf ./data/*

# Re-authenticate
./login.sh
```

### Tools not available in OpenClaw
```bash
# Verify MCP endpoint is accessible
curl http://localhost:18060/mcp

# Restart OpenClaw
systemctl restart openclaw.service
```

## Technical Details

### MCP Configuration

Plugin location:
```
/root/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/xiaohongshu/
├── .mcp.json              # MCP server connection config
└── .claude-plugin/
    └── plugin.json        # Plugin metadata
```

### SystemD Service

Service file: `/etc/systemd/system/xiaohongshu-mcp.service`

- Auto-starts on boot
- Pulls latest image on start
- Logs to systemd journal
- Restarts on failure

### Security

- Service binds to localhost only (127.0.0.1:18060)
- Not exposed to external network
- Authentication cookies stored in ./data/
- Images stored in ./data/images/

## Support & Documentation

- **MCP Server**: https://github.com/xpzouying/xiaohongshu-mcp
- **OpenClaw**: Local instance at `/root/.openclaw/`
- **Docker Logs**: `docker logs xiaohongshu-mcp`
- **Service Logs**: `journalctl -u xiaohongshu-mcp.service`

## Next Steps

1. **Authenticate**: Run `./login.sh` and scan the QR code
2. **Verify**: Run `./check-login.sh` to confirm authentication
3. **Test**: Ask OpenClaw to search or interact with Xiaohongshu
4. **Monitor**: Set up daily authentication checks (optional)

---

**Installation Date**: 2026-02-11
**Version**: 1.0.0
**Status**: ✅ Operational (authentication required)

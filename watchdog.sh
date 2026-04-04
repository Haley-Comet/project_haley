#!/bin/bash

DISCORD_WEBHOOK="https://discord.com/api/webhooks/1487262567855292619/291f4_dPF3kiWjxwTHfxt03ijceIaLPhxbo-O44QoebpDbv7uPrTDTZmoPOYNc4X2Imn"
CONTAINERS=("haley-discord-bot" "traefik-traefik-1" "n8n" "cometmessenger-delivery")
DOMAIN="n8n.cometmessenger.delivery"
SSL_WARN_DAYS=14
ALERTS=()

for container in "${CONTAINERS[@]}"; do
  STATUS=$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null)
  if [ "$STATUS" != "true" ]; then
    docker start "$container" 2>/dev/null
    ALERTS+=("🔴 Container *$container* was down — restarted")
  fi
done

EXPIRY=$(echo | openssl s_client -connect ${DOMAIN}:443 -servername ${DOMAIN} 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$EXPIRY" ]; then
  EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s)
  NOW_EPOCH=$(date +%s)
  DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
  if [ "$DAYS_LEFT" -lt "$SSL_WARN_DAYS" ]; then
    ALERTS+=("⚠️ SSL cert expires in *${DAYS_LEFT} days*")
  fi
fi

if [ ${#ALERTS[@]} -gt 0 ]; then
  MESSAGE="**VPS Watchdog Alert** $(date '+%Y-%m-%d %H:%M UTC')\n"
  for alert in "${ALERTS[@]}"; do
    MESSAGE+="$alert\n"
  done
  curl -s -X POST "$DISCORD_WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "{\"content\": \"$MESSAGE\"}"
fi

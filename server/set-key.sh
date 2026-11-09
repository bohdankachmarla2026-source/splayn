#!/bin/sh
# Saves the Anthropic API key into server/.env without showing it on screen.
# Run from anywhere:  sh server/set-key.sh
cd "$(dirname "$0")" || exit 1
trap 'stty echo 2>/dev/null' EXIT INT TERM

printf 'Вставте ключ Anthropic API і натисніть Enter (символи не відображатимуться): '
stty -echo
IFS= read -r KEY
stty echo
printf '\n'

case "$KEY" in
  "") echo "Ключ порожній, нічого не збережено."; exit 1 ;;
  sk-ant-*) ;;
  *) echo "Увага: ключ зазвичай починається з sk-ant-. Зберігаю як є." ;;
esac

umask 077
printf 'ANTHROPIC_API_KEY=%s\n' "$KEY" > .env
KEY=""
echo "Ключ збережено в server/.env. Можна повертатися в чат."

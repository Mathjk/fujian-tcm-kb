#!/usr/bin/env bash
cd ~/fujian-tcm
while true; do
  pages=$(find pages -name '*.png' | wc -l)
  jsons=$(find ocr -name '*.json' | wc -l)
  renderers=$(pgrep -c pdftoppm 2>/dev/null || echo 0)
  echo "[sweep] pages=$pages ocr=$jsons renderers=$renderers"
  if [ "$pages" -gt 0 ] && [ "$jsons" -ge "$pages" ] && [ "$renderers" -eq 0 ]; then
    echo "[sweep] ALL COMPLETE"
    break
  fi
  if ! pgrep -f ocr_all.py >/dev/null; then
    if [ "$jsons" -lt "$pages" ]; then
      echo "[sweep] launching ocr_all.py for remaining $((pages-jsons)) pages"
      .venv/bin/python scripts/ocr_all.py >> ocr.log 2>&1
    elif [ "$renderers" -eq 0 ] && [ "$pages" -lt 2273 ]; then
      echo "[sweep] WARN pages=$pages < 2273 but no renderers left"
      break
    fi
  fi
  sleep 20
done

#!/usr/bin/env bash
set -uo pipefail
cd ~/fujian-tcm
for pdf in pdf/*.pdf; do
  name=$(basename "$pdf" .pdf)
  out="pages/$name"
  mkdir -p "$out"
  done_count=$(ls "$out" 2>/dev/null | wc -l)
  total=$(pdfinfo "$pdf" | awk '/^Pages/ {print $2}')
  if [ "$done_count" -ge "$total" ]; then echo "SKIP $name ($done_count pages)"; continue; fi
  echo "RENDER $name ($total pages)"
  pdftoppm -r 200 -png "$pdf" "$out/page"
  echo "DONE $name -> $(ls "$out" | wc -l) pages"
done

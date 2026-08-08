#!/bin/sh
set -eu
source_db=/opt/warframe-tracker/data/tracker.db
backup_dir=/var/backups/warframe-tracker
mkdir -p "$backup_dir"
i=7
while [ "$i" -gt 1 ]; do
  previous=$((i - 1))
  [ ! -f "$backup_dir/tracker-$previous.db" ] || mv "$backup_dir/tracker-$previous.db" "$backup_dir/tracker-$i.db"
  i=$previous
done
sqlite3 "$source_db" ".backup '$backup_dir/tracker-1.db'"

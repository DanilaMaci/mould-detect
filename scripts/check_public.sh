#!/usr/bin/env bash
# Check the files git would commit for credentials, house data and private files.
# Run from anywhere inside the repo before every commit/push: scripts/check_public.sh
# Exit code 0 = nothing found, 1 = problems listed above.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 2

fail=0
problem() { echo "FAIL: $*"; fail=1; }

# Tracked files plus untracked files that are not ignored = what `git add -A` would commit
files=$(git ls-files --cached --others --exclude-standard)

# 1. Paths that must never be published
while IFS= read -r f; do
    [ -z "$f" ] && continue
    case "$f" in
        .env.example)                       ;;
        *secrets.h|.env|.env.*|*.pem|*.key|dashboard/config.js) problem "credential file: $f" ;;
        data/*|models/*|datasheets/*)       problem "private data folder: $f" ;;
        CLAUDE.md|CLAUDE.local.md|STATE.md|DECISIONS.md|.claude/*|docs/handoff.md)
                                            problem "local Claude file: $f" ;;
        docs/images/*.jpg|docs/images/*.png) ;;   # made by scripts/prepare_image.py; metadata checked in 5.
        *.[jJ][pP][gG]|*.[jJ][pP][eE][gG]|*.[hH][eE][iI][cC]|room_pics/*)
                                            problem "photo (may contain GPS location): $f" ;;
        analysis/samples/*.csv)             ;;
        *.csv|*.parquet|*.feather|*.sqlite|*.db|*.pkl|*.joblib)
                                            problem "data/model file: $f" ;;
    esac
    if [ -f "$f" ] && [ "$(wc -c < "$f")" -gt 1000000 ]; then
        problem "file over 1 MB: $f"
    fi
done <<< "$files"

# 2. Credentials and personal data inside files (never reads *secrets.h)
patterns='sb_secret_|sb_publishable_|eyJhbGciOi|[a-z0-9]{20}\.supabase\.co|BEGIN [A-Z ]*PRIVATE KEY|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z.]{2,}'
while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in *secrets.h|scripts/check_public.sh) continue ;; esac
    if hits=$(grep -nIE "$patterns" "$f"); then
        problem "possible credential or e-mail in $f:"; echo "$hits" | sed 's/^/    /'
    fi
done <<< "$files"

# 3. Example credential files must contain placeholders only
while IFS= read -r f; do
    case "$f" in
        *secrets.example.h) hits=$(grep -nE '^#define [A-Z_]+ +"' "$f" | grep -vE '"(your|https://your)') ;;
        .env.example)       hits=$(grep -nE '^[A-Z_]+=.' "$f" | grep -vE '=(your|https://your)') ;;
        *) continue ;;
    esac
    if [ -n "$hits" ]; then
        problem "non-placeholder value in $f:"; echo "$hits" | sed 's/^/    /'
    fi
done <<< "$files"

# 4. Notebooks must be committed without outputs (they can show real data)
while IFS= read -r f; do
    case "$f" in *.ipynb) ;; *) continue ;; esac
    if ! python3 -c 'import json,sys; nb=json.load(open(sys.argv[1])); sys.exit(any(c.get("outputs") for c in nb.get("cells",[])))' "$f"; then
        problem "notebook has outputs (clear them): $f"
    fi
done <<< "$files"

# 5. Images must carry no metadata (EXIF holds the GPS position of phone photos; XMP can too)
while IFS= read -r f; do
    case "$f" in *.[jJ][pP][gG]|*.[jJ][pP][eE][gG]|*.[pP][nN][gG]|*.[wW][eE][bB][pP]|*.[hH][eE][iI][cC]|*.[tT][iI][fF]*) ;; *) continue ;; esac
    [ -f "$f" ] || continue
    if left=$(python3 -c 'import sys; d=open(sys.argv[1],"rb").read(); m={"EXIF":b"Exif\x00\x00","PNG eXIf":b"eXIf","XMP":b"<x:xmpmeta"}; l=[k for k,v in m.items() if v in d]; print(", ".join(l)); sys.exit(1 if l else 0)' "$f"); then :; else
        problem "image metadata ($left) in $f: run scripts/prepare_image.py"
    fi
done <<< "$files"

[ "$fail" -eq 0 ] && echo "OK: $(echo "$files" | grep -c .) files checked, nothing found"
exit "$fail"

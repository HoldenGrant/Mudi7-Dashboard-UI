#!/bin/sh
# Builds dist/gl-e5800-touch-ui_<version>_all.ipk from ../router. Nothing to compile: all Python and shell.
#
#   ./build.sh [version]        (default 1.0.0)
#
# An .ipk on this router's opkg is a plain gzip-compressed tar holding debian-binary, data.tar.gz and
# control.tar.gz IN THAT ORDER. It is not an `ar` archive: opkg rejects those ("Malformed package file").
set -eu
cd "$(dirname "$0")"
VERSION="${1:-1.0.0}"
NAME=gl-e5800-touch-ui
OUT=dist
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/data/root/e5ui" "$STAGE/data/etc/init.d" "$STAGE/control" "$OUT"
for f in app.py lib.py run.sh toggle.sh screen_sleep.sh button_watch.py; do
    install -m 755 "../router/$f" "$STAGE/data/root/e5ui/$f"
done
install -m 755 ../router/init.d/e5ui ../router/init.d/homebutton "$STAGE/data/etc/init.d/"

SIZE=$(find "$STAGE/data" -type f -exec wc -c {} + | awk 'END{print $1}')
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" control/control > "$STAGE/control/control"
chmod 644 "$STAGE/control/control"
for s in postinst prerm postrm; do install -m 755 "control/$s" "$STAGE/control/$s"; done
printf '2.0\n' > "$STAGE/debian-binary"

# bsdtar (macOS) and GNU tar spell the "root-owned, plain format" flags differently
if tar --version 2>/dev/null | grep -qi bsdtar; then
    TAR="tar --format=gnutar --uid=0 --gid=0 --uname=root --gname=root --no-xattrs --no-acls --no-fflags"
else
    TAR="tar --format=gnu --owner=root:0 --group=root:0 --numeric-owner"
fi
export COPYFILE_DISABLE=1   # no macOS ._ files

(cd "$STAGE/control" && $TAR -czf ../control.tar.gz ./control ./postinst ./prerm ./postrm)
# files only: listing ./root and ./etc as directories would make the package claim /etc and /root themselves
(cd "$STAGE/data" && find . -type f | sort | $TAR -czf ../data.tar.gz -T -)
(cd "$STAGE" && $TAR -czf "$OLDPWD/$OUT/${NAME}_${VERSION}_all.ipk" ./debian-binary ./data.tar.gz ./control.tar.gz)
echo "built $OUT/${NAME}_${VERSION}_all.ipk ($(wc -c < "$OUT/${NAME}_${VERSION}_all.ipk") bytes)"

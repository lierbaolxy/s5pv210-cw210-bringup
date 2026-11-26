#!/bin/bash
set -e
ROOT=/tmp/rootfs_new_ext
OUT=/tmp/rootfs_new.cramfs
SRC=/mnt/g/lcd/bootimg/rootfs_orig.cramfs
rm -rf "$ROOT" "$OUT"

# 解包原始 cramfs（保留原始 uid/gid，需在 fakeroot 内执行）
fsck.cramfs --extract="$ROOT" "$SRC"
echo "== busybox owner =="
ls -ln "$ROOT/bin/busybox"

# 放入两张启动画面原始帧
mkdir -p "$ROOT/usr/share/splash"
cp /mnt/g/lcd/bootimg/cola.fb "$ROOT/usr/share/splash/cola.fb"
cp /mnt/g/lcd/bootimg/lesening.fb "$ROOT/usr/share/splash/lesening.fb"
chmod 755 "$ROOT/usr/share" "$ROOT/usr/share/splash"
chmod 644 "$ROOT/usr/share/splash/cola.fb" "$ROOT/usr/share/splash/lesening.fb"

# 修改启动脚本 rcS
cat > "$ROOT/etc/init.d/rcS" << "EOS"
#/bin/sh
# This is the first script called by init process
/bin/mount -a
mkdir /dev/pts
mount -t devpts devpts /dev/pts
echo /sbin/mdev > /proc/sys/kernel/hotplug
mdev -s

# hide text console cursor (avoid covering splash)
printf '\033[?25l' > /dev/tty1 2>/dev/null

# boot logo: show Coca-Cola as early as possible
[ -e /dev/fb0 ] && cat /usr/share/splash/cola.fb > /dev/fb0

/usr/sbin/telnetd
inetd

# after boot: show Lesening static picture
sleep 3
[ -e /dev/fb0 ] && cat /usr/share/splash/lesening.fb > /dev/fb0

#exec /usr/local/net.sh
EOS
chmod 755 "$ROOT/etc/init.d/rcS"

# 重新打包 cramfs（块大小 4096，小端，卷名与原镜像一致）
mkfs.cramfs -b 4096 -N little -n Compressed "$ROOT" "$OUT"
ls -l "$OUT"

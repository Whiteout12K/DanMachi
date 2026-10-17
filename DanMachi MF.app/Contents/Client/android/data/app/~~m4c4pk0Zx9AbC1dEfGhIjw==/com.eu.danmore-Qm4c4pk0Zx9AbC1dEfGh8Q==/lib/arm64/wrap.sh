#!/system/bin/sh
here=${0%/*}
export LD_PRELOAD="$here/libzipreader.so"
exec "$@"

/*
 * Deferred H.264 setup. Some retained movies provide SPS/PPS decoder parameters in
 * queued packets instead of initial configuration.
 *
 * Editing notes: Wait for both parameter sets before opening the decoder. Duplicate the
 * ByteBuffer so inspection does not move the runtime buffer position; weak keys avoid
 * retaining released codecs.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

import java.lang.reflect.*;
import java.nio.ByteBuffer;
import java.util.*;
public class MovieDeferred {
    static final Map<Object, byte[][]> params =
        Collections.synchronizedMap(new WeakHashMap<>());
    static Field field(Object c, String n) throws Exception {
        Field f = c.getClass().getDeclaredField(n);
        f.setAccessible(true);
        return f;
    }
    static Object get(Object c, String n) throws Exception {
        return field(c, n).get(c);
    }
    public static boolean defer(Object c) {
        try {
            return Boolean.TRUE.equals(get(c, "mIsVideo")) &&
                "video/avc".equals(get(c, "mVidMime")) &&
                (get(c, "mCsd0Vid") == null ||
                 ((byte[])get(c, "mCsd0Vid")).length == 0);
        } catch (Exception e) {
            return false;
        }
    }
    public static void input(Object c, int index, int offset, int size, int flags) {
        try {
            if (!defer(c) || ((Number)get(c, "mVidDec")).longValue() != 0 || size <= 0)
                return;
            ByteBuffer[] bufs = (ByteBuffer[])get(c, "mIn");
            if (bufs == null || index < 0 || index >= bufs.length)
                return;
            ByteBuffer b = bufs[index].duplicate();
            b.position(offset);
            b.limit(offset + size);
            byte[] data = new byte[size];
            b.get(data);
            byte[][] ps = params.computeIfAbsent(c, k -> new byte[2][]);
            for (int i = 0; i + 4 < data.length; i++) {
                int start = -1;
                if (data[i] == 0 && data[i + 1] == 0) {
                    if (data[i + 2] == 1)
                        start = i + 3;
                    else if (data[i + 2] == 0 && data[i + 3] == 1)
                        start = i + 4;
                }
                if (start < 0)
                    continue;
                int type = data[start] & 31;
                if (type != 7 && type != 8)
                    continue;
                int end = data.length;
                for (int j = start + 1; j + 3 < data.length; j++)
                    if (data[j] == 0 && data[j + 1] == 0 &&
                        (data[j + 2] == 1 || (data[j + 2] == 0 && data[j + 3] == 1))) {
                        end = j;
                        break;
                    }
                byte[] nal = new byte[end - start + 4];
                nal[3] = 1;
                System.arraycopy(data, start, nal, 4, end - start);
                ps[type - 7] = nal;
                i = start;
            }
            if (ps[0] != null && ps[1] != null) {
                Class<?> nativeMedia =
                    Class.forName("com.macapk.loader.NativeMedia", true,
                                  c.getClass().getClassLoader());
                long dec =
                    (Long)nativeMedia
                        .getMethod("nativeVidOpen", String.class, int.class, int.class,
                                   byte[].class, byte[].class, boolean.class)
                        .invoke(null, "video/avc", get(c, "mVidWidth"),
                                get(c, "mVidHeight"), ps[0], ps[1],
                                get(c, "mHasSurface"));
                if (dec != 0) {
                    field(c, "mVidDec").setLong(c, dec);
                    field(c, "mCsd0Vid").set(c, ps[0]);
                    field(c, "mCsd1Vid").set(c, ps[1]);
                    params.remove(c);
                    System.err.println(
                        "[movie] H264 decoder opened from queued parameter sets");
                }
            }
        } catch (Throwable e) {
            System.err.println("[movie] deferred setup: " + e);
        }
    }
}

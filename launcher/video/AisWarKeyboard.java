/*
 * Ais WAR held-key profile. Bind W/S to original touch regions and update coordinates
 * from the native window geometry.
 *
 * Editing notes: Suppress movement bindings during text entry. Geometry is read through
 * JNI from window_fit.m; this helper must not change mouse mapping.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

/** In-memory W/S touch bindings using the runtime's own held-key handling. */
public final class AisWarKeyboard {
    private static native long inputPoint(float x, float y);
    private static boolean geometryLoaded;
    private static java.util.List<Object> movementKeys;
    private static java.lang.reflect.Constructor<?> bindingMaker;
    private static java.lang.reflect.Constructor<?> profileMaker;
    private static java.lang.reflect.Method setProfile;
    private static int lastWidth, lastHeight;
    private static long lastUp = -1, lastDown = -1;
    public static boolean install(Class<?> owner, String pkg) {
        if (pkg == null || !pkg.equals("com.eu.danmore"))
            return false;
        try {
            ClassLoader loader = owner.getClassLoader();
            Class<?> binding = Class.forName(
                "com.macapk.loader.KeyBindProfiles$Binding", true, loader);
            Class<?> profile = Class.forName(
                "com.macapk.loader.KeyBindProfiles$Profile", true, loader);
            java.lang.reflect.Constructor<?> make = binding.getConstructor(
                int.class, float.class, float.class, String.class);
            java.util.List<Object> keys = new java.util.ArrayList<>();
            // Diagonal points select the same directions in both the original
            // left/right and up/down touch layouts, away from the HUD and buttons.
            keys.add(make.newInstance(51, .30f, .35f, "Ais WAR: up (W)"));
            keys.add(make.newInstance(47, .70f, .82f, "Ais WAR: down (S)"));
            movementKeys = keys;
            bindingMaker = make;
            profileMaker = profile.getConstructor(String.class, String.class,
                                                  java.util.List.class);
            setProfile = owner.getMethod("setActive", profile);
            String geometry = System.getProperty("danmachi.input.geometry");
            if (geometry != null) {
                System.load(geometry);
                geometryLoaded = true;
            }
            Object value =
                profile.getConstructor(String.class, String.class, java.util.List.class)
                    .newInstance("Ais WAR W/S", pkg, keys);
            owner.getMethod("setActive", profile).invoke(null, value);
            System.err.println("[ais-war] W/S held movement bindings installed");
            return true;
        } catch (ReflectiveOperationException e) {
            System.err.println("[ais-war] bindings unavailable: " + e);
            return false;
        }
    }
    public static boolean typing(Class<?> owner) {
        try {
            ClassLoader loader = owner.getClassLoader();
            Class<?> imm = Class.forName("android.view.inputmethod.InputMethodManager",
                                         true, loader);
            if (imm.getMethod("macapkActiveConnection").invoke(null) == null) {
                refreshPoints(loader);
                return false;
            }
            Class<?> touch =
                Class.forName("com.macapk.loader.TouchDispatcher", true, loader);
            // Release a movement key if editing starts while it is held.
            touch.getMethod("macapkKeyBindUp", int.class).invoke(null, 51);
            touch.getMethod("macapkKeyBindUp", int.class).invoke(null, 47);
            return true;
        } catch (ReflectiveOperationException e) {
            System.err.println("[ais-war] typing guard unavailable: " + e);
            return true;
        }
    }
    private static void refreshPoints(ClassLoader loader)
        throws ReflectiveOperationException {
        if (!geometryLoaded || movementKeys == null)
            return;
        Class<?> touch =
            Class.forName("com.macapk.loader.TouchDispatcher", true, loader);
        java.lang.reflect.Field width = touch.getDeclaredField("sSurfaceW"),
                                height = touch.getDeclaredField("sSurfaceH");
        width.setAccessible(true);
        height.setAccessible(true);
        int w = width.getInt(null), h = height.getInt(null);
        long up = inputPoint(.30f, .35f), down = inputPoint(.70f, .70f);
        if (w <= 0 || h <= 0 || up == -1 || down == -1)
            return;
        if (w == lastWidth && h == lastHeight && up == lastUp && down == lastDown)
            return;
        movementKeys.set(0, bindingMaker.newInstance(51, (float)(up >>> 32) / w,
                                                     (float)(up & 0xffffffffL) / h,
                                                     "Ais WAR: up (W)"));
        movementKeys.set(1, bindingMaker.newInstance(47, (float)(down >>> 32) / w,
                                                     (float)(down & 0xffffffffL) / h,
                                                     "Ais WAR: down (S)"));
        // Profile copies its bindings into an immutable list; publish a new one.
        setProfile.invoke(null, profileMaker.newInstance(
                                    "Ais WAR W/S", "com.eu.danmore", movementKeys));
        lastWidth = w;
        lastHeight = h;
        lastUp = up;
        lastDown = down;
        System.err.println("[ais-war] touch geometry " + w + "x" + h +
                           " W=" + (up >>> 32) + "," + (up & 0xffffffffL) +
                           " S=" + (down >>> 32) + "," + (down & 0xffffffffL));
    }
}

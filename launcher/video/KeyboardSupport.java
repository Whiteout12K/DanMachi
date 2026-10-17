/*
 * Cocos text-entry helpers. Find a usable window token and notify text watchers after
 * handled edits.
 *
 * Editing notes: Preserve the runtime key listener result and propagate its actual
 * exception. Notifications are scoped to the retained Cocos edit box.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

/** Null-safe Cocos focus lookup; leave normal Mac.apk text input handling intact. */
public class KeyboardSupport {
    public static Object windowToken(Object view, Object owner) {
        try {
            if (view == null) {
                Class<?> imm =
                    Class.forName("android.view.inputmethod.InputMethodManager", true,
                                  owner.getClass().getClassLoader());
                view = imm.getMethod("macapkActiveInput").invoke(null);
            }
            if (view == null)
                return null;
            return view.getClass().getMethod("getWindowToken").invoke(view);
        } catch (ReflectiveOperationException e) {
            System.err.println("[keyboard] token lookup: " + e);
            return null;
        }
    }
    public static boolean keyListener(Object listener, Object view, Object editable,
                                      int key, Object event) {
        try {
            ClassLoader loader = view.getClass().getClassLoader();
            Class<?> v = Class.forName("android.view.View", true, loader),
                     ed = Class.forName("android.text.Editable", true, loader),
                     ev = Class.forName("android.view.KeyEvent", true, loader),
                     kl =
                         Class.forName("android.text.method.KeyListener", true, loader);
            String before = editable.toString();
            boolean handled = (Boolean)kl.getMethod("onKeyDown", v, ed, int.class, ev)
                                  .invoke(listener, view, editable, key, event);
            String after = editable.toString();
            if (handled &&
                view.getClass().getName().equals("org.cocos2dx.lib.Cocos2dxEditBox") &&
                !before.equals(after)) {
                Class<?> tv = Class.forName("android.widget.TextView", true, loader);
                java.lang.reflect.Field f = tv.getDeclaredField("textWatchers");
                f.setAccessible(true);
                Object list = f.get(view);
                if (list instanceof java.util.Collection) {
                    Class<?> watcher =
                        Class.forName("android.text.TextWatcher", true, loader);
                    for (Object w :
                         new java.util.ArrayList<>((java.util.Collection<?>)list))
                        watcher
                            .getMethod("onTextChanged", CharSequence.class, int.class,
                                       int.class, int.class)
                            .invoke(w, after, 0, before.length(), after.length());
                }
                view.getClass().getMethod("requestLayout").invoke(view);
                view.getClass().getMethod("invalidate").invoke(view);
            }
            return handled;
        } catch (java.lang.reflect.InvocationTargetException e) {
            throw new RuntimeException(e.getCause());
        } catch (ReflectiveOperationException e) {
            throw new RuntimeException(e);
        }
    }
}

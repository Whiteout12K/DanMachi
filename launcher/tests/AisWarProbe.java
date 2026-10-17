/*
 * Java diagnostic for retained Ais WAR input/runtime behavior.
 *
 * Editing notes: This is a maintenance probe, not a gameplay dependency or account
 * fixture.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

import com.macapk.loader.KeyBindProfiles;
public class AisWarProbe {
    public static void main(String[] args) {
        KeyBindProfiles.autoSelectForPackage("com.eu.danmore");
        var p = KeyBindProfiles.active();
        if (p == null || p.forKey(51) == null || p.forKey(47) == null ||
            p.forKey(29) != null)
            throw new AssertionError("Wrong bindings");
        if (p.forKey(51).ny >= p.forKey(47).ny)
            throw new AssertionError("W must be above S");
        System.out.println("Ais WAR W/S profile verified against original runtime");
    }
}

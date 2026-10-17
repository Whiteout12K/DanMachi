/*
 * Rendering compatibility shim. Ask EGL for at least eight stencil bits so native UI
 * masks render correctly.
 *
 * Editing notes: If the requested configuration fails, retain the original EGL
 * fallback. The diagnostic log reports the actual framebuffer, not just the requested
 * attributes.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

#include <stdio.h>
extern unsigned eglChooseConfig(void *, const int *, void **, int, int *);
extern unsigned eglMakeCurrent(void *, void *, void *, void *);
extern unsigned eglGetError(void);
extern void glGetIntegerv(unsigned, int *);
static unsigned choose(void *d, const int *attrs, void **configs, int size,
                       int *count) {
    int corrected[132], n = 0, found = 0, changed = 0;
    if (attrs) {
        for (int i = 0; i < 128 && attrs[i] != 0x3038; i += 2) {
            corrected[n++] = attrs[i];
            int value = attrs[i + 1];
            if (attrs[i] == 0x3026) {
                found = 1;
                if (value < 8) {
                    value = 8;
                    changed = 1;
                }
            }
            corrected[n++] = value;
        }
        if (n >= 128)
            return eglChooseConfig(d, attrs, configs, size, count);
    }
    if (!found) {
        corrected[n++] = 0x3026;
        corrected[n++] = 8;
        changed = 1;
    }
    corrected[n] = 0x3038;
    if (!changed)
        return eglChooseConfig(d, attrs, configs, size, count);
    unsigned result = eglChooseConfig(d, corrected, configs, size, count);
    if (result && count && *count > 0) {
        static int logged;
        if (!__sync_lock_test_and_set(&logged, 1))
            fprintf(stderr,
                    "[dm-stencil] selected EGL config with at least 8 stencil bits\n");
        return result;
    }
    if (!result)
        eglGetError();
    return eglChooseConfig(d, attrs, configs, size, count);
}
static unsigned current(void *d, void *draw, void *read, void *ctx) {
    unsigned result = eglMakeCurrent(d, draw, read, ctx);
    if (result && ctx) {
        static int logged;
        if (!__sync_lock_test_and_set(&logged, 1)) {
            int depth = 0, stencil = 0;
            glGetIntegerv(0xd56, &depth);
            glGetIntegerv(0xd57, &stencil);
            fprintf(stderr, "[dm-stencil] current framebuffer depth=%d stencil=%d\n",
                    depth, stencil);
        }
    }
    return result;
}
#define HOOK(r, o)                                                                     \
    __attribute__((used)) static struct {                                              \
        const void *a;                                                                 \
        const void *b;                                                                 \
    } hook_##o __attribute__((section("__DATA,__interpose"))) = {(void *)r, (void *)o};
HOOK(choose, eglChooseConfig)
HOOK(current, eglMakeCurrent)

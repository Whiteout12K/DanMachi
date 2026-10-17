/*
 * Native keyboard-coordinate probe for the window geometry bridge.
 *
 * Editing notes: Diagnostic source only; it is not a normal game entry point.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

// Verify keyboard targets remain inside the original viewport after resizing.
#include "../window_fit.m"
#include <assert.h>
int main(void) {
    assert(Java_AisWarKeyboard_inputPoint(0, 0, .3f, .35f) == -1);
    atomic_store(&sourceX, 100);
    atomic_store(&sourceY, 0);
    atomic_store(&sourceW, 600);
    atomic_store(&sourceH, 338);
    atomic_store(&sourceCanvasH, 450);
    for (int width = 640; width <= 1920; width += 640) {
        atomic_store(&displayW, width);
        atomic_store(&displayH, width * 9 / 16);
        unsigned long long up = Java_AisWarKeyboard_inputPoint(0, 0, .3f, .35f);
        unsigned long long down = Java_AisWarKeyboard_inputPoint(0, 0, .7f, .7f);
        assert((up >> 32) == 280 && (up & 0xffffffff) == 230);
        assert((down >> 32) == 520 && (down & 0xffffffff) == 349);
        assert((down >> 32) < 700 && (down & 0xffffffff) < 450);
    }
    return 0;
}

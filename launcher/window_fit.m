/*
 * Game window adapter. Fit the main framebuffer to the window, then map mouse and
 * keyboard touches back into the original game canvas.
 *
 * Editing notes: Rendering and input use the same source geometry. Preserve offscreen
 * framebuffer dimensions and the protected mouse mapping when editing viewport
 * restoration.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

#import <Foundation/NSObject.h>
#import <Foundation/NSString.h>
#import <Foundation/NSArray.h>
#import <Foundation/NSTimer.h>
#import <Foundation/NSGeometry.h>
#import <QuartzCore/CALayer.h>
#import <QuartzCore/CATransaction.h>
#import <dispatch/dispatch.h>
#import <objc/runtime.h>
#import <stdatomic.h>
#import <math.h>
#import <stdio.h>
@interface CAMetalLayer : CALayer
@property CGSize drawableSize;
@end
@interface NSView : NSObject
@property(readonly) CALayer *layer;
@property(readonly) NSRect bounds;
- (NSPoint)convertPoint:(NSPoint)point fromView:(NSView *)view;
- (NSPoint)convertPoint:(NSPoint)point toView:(NSView *)view;
@end
@interface NSWindow : NSObject
@property(readonly) NSString *title;
@property(readonly) NSView *contentView;
@end
@interface NSApplication : NSObject
@property(readonly) NSArray<NSWindow *> *windows;
@end
@interface NSEvent : NSObject
@property(readonly) NSUInteger type, modifierFlags;
@property(readonly) NSPoint locationInWindow;
@property(readonly) NSTimeInterval timestamp;
@property(readonly) NSInteger windowNumber, eventNumber, clickCount;
@property(readonly) float pressure;
@property(readonly) id context;
+ (NSEvent *)mouseEventWithType:(NSUInteger)t
                       location:(NSPoint)p
                  modifierFlags:(NSUInteger)f
                      timestamp:(NSTimeInterval)s
                   windowNumber:(NSInteger)w
                        context:(id)c
                    eventNumber:(NSInteger)e
                     clickCount:(NSInteger)n
                       pressure:(float)pressure;
@end
extern NSApplication *NSApp;
extern void glViewport(int, int, int, int);
extern void glScissor(int, int, int, int);
extern void glGetIntegerv(unsigned int, int *);
static _Atomic int displayW, displayH, sourceX, sourceY, sourceW, sourceH;
static _Atomic int sourceCanvasH, renderW, renderH;
static _Thread_local int gameViewport;
// Only resize the main game viewport; framebuffer zero is the visible window.
static void dmViewport(int x, int y, int w, int h) {
    int fb = 0;
    glGetIntegerv(0x8ca6, &fb);
    gameViewport =
        fb == 0 && x > 0 && w > 0 && h > 0 && fabs((double)w / h - 16.0 / 9.0) < .02;
    if (gameViewport) {
        atomic_store(&sourceX, x);
        atomic_store(&sourceY, y);
        atomic_store(&sourceW, w);
        atomic_store(&sourceH, h);
        int dw = atomic_load(&displayW), dh = atomic_load(&displayH);
        if (dw > 0 && dh > 0) {
            static int lastW, lastH;
            if (lastW != dw || lastH != dh) {
                fprintf(stderr, "[dm-fit] viewport %d,%d %dx%d -> %dx%d\n", x, y, w, h,
                        dw, dh);
                lastW = dw;
                lastH = dh;
            }
            atomic_store(&renderW, dw);
            atomic_store(&renderH, dh);
            glViewport(0, 0, dw, dh);
            return;
        }
    }
    glViewport(x, y, w, h);
}
// Apply the same scale/offset to clipping rectangles as to the visible viewport.
static void dmScissor(int x, int y, int w, int h) {
    int fb = 0;
    glGetIntegerv(0x8ca6, &fb);
    int sw = atomic_load(&sourceW), sh = atomic_load(&sourceH),
        dw = atomic_load(&displayW), dh = atomic_load(&displayH);
    if (gameViewport && fb == 0 && sw > 0 && sh > 0 && dw > 0 && dh > 0) {
        double sx = (double)dw / sw, sy = (double)dh / sh;
        glScissor((int)floor((x - atomic_load(&sourceX)) * sx),
                  (int)floor((y - atomic_load(&sourceY)) * sy), (int)ceil(w * sx),
                  (int)ceil(h * sy));
        return;
    }
    glScissor(x, y, w, h);
}
#define DMHOOK(replacement, original)                                                  \
    __attribute__((used)) static struct {                                              \
        const void *r;                                                                 \
        const void *o;                                                                 \
    } interpose_##original __attribute__((section("__DATA,__interpose"))) = {          \
        (void *)replacement, (void *)original};
DMHOOK(dmViewport, glViewport)
DMHOOK(dmScissor, glScissor)
static void fitLayers(CALayer *layer, int depth) {
    if (!layer || depth > 5)
        return;
    if (depth == 2 && ![layer isKindOfClass:[CAMetalLayer class]] &&
        layer.zPosition == .5 && atomic_load(&sourceW) > 0)
        layer.opacity = 0;
    for (CALayer *child in layer.sublayers)
        fitLayers(child, depth + 1);
}
// Undo display scaling before the runtime performs its Android coordinate flip.
static NSEvent *mapEvent(NSView *view, NSEvent *event) {
    int sw = atomic_load(&sourceW), sh = atomic_load(&sourceH);
    NSRect bounds = NSMakeRect(0, 0, atomic_load(&renderW), atomic_load(&renderH));
    if (sw <= 0 || sh <= 0 || bounds.size.width <= 0 || bounds.size.height <= 0)
        return event;
    NSPoint p = [view convertPoint:event.locationInWindow fromView:nil];
    p.x = atomic_load(&sourceX) + p.x * sw / bounds.size.width;
    // AppKit uses bottom-origin coordinates; Android flips against view.bounds.
    // Restore the original canvas height before Android performs that flip.
    p.y = view.bounds.size.height - atomic_load(&sourceCanvasH) +
          atomic_load(&sourceY) + p.y * sh / bounds.size.height;
    p = [view convertPoint:p toView:nil];
    return [NSEvent mouseEventWithType:event.type
                              location:p
                         modifierFlags:event.modifierFlags
                             timestamp:event.timestamp
                          windowNumber:event.windowNumber
                               context:event.context
                           eventNumber:event.eventNumber
                            clickCount:event.clickCount
                              pressure:event.pressure];
}
// Wrap each mouse callback while retaining its original implementation.
static void installMouseMap(Class cls, SEL selector) {
    Method method = class_getInstanceMethod(cls, selector);
    if (!method)
        return;
    IMP original = method_getImplementation(method);
    IMP replacement = imp_implementationWithBlock(^(NSView *view, NSEvent *event) {
      ((void (*)(id, SEL, id))original)(view, selector, mapEvent(view, event));
    });
    class_replaceMethod(cls, selector, replacement, method_getTypeEncoding(method));
}
__attribute__((constructor)) static void start(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
      Class cls = objc_getClass("MacApkMetalView");
      for (NSString *name in @[ @"mouseDown:", @"mouseUp:", @"mouseDragged:" ])
          installMouseMap(cls, NSSelectorFromString(name));
      [NSTimer
          scheduledTimerWithTimeInterval:.05
                                 repeats:YES
                                   block:^(NSTimer *timer) {
                                     [CATransaction begin];
                                     [CATransaction setDisableActions:YES];
                                     for (NSWindow *window in NSApp.windows)
                                         if ([window.title isEqualToString:
                                                               @"Memoria Freese EU"] ||
                                             [window.title
                                                 isEqualToString:@"DanMachi MF"]) {
                                             NSRect bounds = window.contentView.bounds;
                                             if (atomic_load(&sourceCanvasH) == 0 &&
                                                 bounds.size.height > 0)
                                                 atomic_store(&sourceCanvasH,
                                                              (int)bounds.size.height);
                                             atomic_store(&displayW,
                                                          (int)bounds.size.width);
                                             atomic_store(&displayH,
                                                          (int)bounds.size.height);
                                             fitLayers(window.contentView.layer, 0);
                                         }
                                     [CATransaction commit];
                                   }];
    });
}

// RenderTexture can restore its viewport while an offscreen framebuffer is
// still bound. Fit that restored viewport when it returns to the window.
// Do not change the protected input/source geometry or offscreen dimensions.
extern void glBindFramebuffer(unsigned int, unsigned int);
extern void glBindFramebufferOES(unsigned int, unsigned int);
void danmachi_scene_viewport(int x, int y, int w, int h) {
    dmViewport(x, y, w, h);
}
void danmachi_scene_scissor(int x, int y, int w, int h) {
    dmScissor(x, y, w, h);
}
// Repair a restored scene viewport only after returning from offscreen rendering.
static void fitRestoredWindow(unsigned int target, unsigned int framebuffer) {
    if (framebuffer != 0 || (target != 0x8d40 && target != 0x8ca9))
        return;
    int fb = -1, v[4] = {0};
    glGetIntegerv(0x8ca6, &fb);
    if (fb != 0)
        return;
    glGetIntegerv(0x0ba2, v);
    int sw = atomic_load(&sourceW), sh = atomic_load(&sourceH);
    int dw = atomic_load(&renderW), dh = atomic_load(&renderH);
    if (sw > 0 && sh > 0 && dw > 0 && dh > 0 && v[0] == atomic_load(&sourceX) &&
        v[1] == atomic_load(&sourceY) && v[2] == sw && v[3] == sh) {
        gameViewport = 1;
        glViewport(0, 0, dw, dh);
        static int reported;
        if (!reported++) {
            fprintf(
                stderr,
                "[dm-scene-restored] fitted restored window viewport %d,%d,%d,%d -> %d,%d\n",
                v[0], v[1], v[2], v[3], dw, dh);
        }
    }
}
void danmachi_scene_framebuffer(unsigned int target, unsigned int framebuffer) {
    glBindFramebuffer(target, framebuffer);
    fitRestoredWindow(target, framebuffer);
}
static void dmFramebufferOES(unsigned int target, unsigned int framebuffer) {
    glBindFramebufferOES(target, framebuffer);
    fitRestoredWindow(target, framebuffer);
}
DMHOOK(danmachi_scene_framebuffer, glBindFramebuffer)
DMHOOK(dmFramebufferOES, glBindFramebufferOES)

// Read-only JNI access for keyboard touch bindings. Use the same source
// geometry as mapEvent without changing mouse handling or window sizing.
// Pack original-canvas x/y coordinates for the Java held-key profile; -1 means not ready.
long long Java_AisWarKeyboard_inputPoint(void *env, void *owner, float nx, float ny) {
    int sw = atomic_load(&sourceW), sh = atomic_load(&sourceH),
        ch = atomic_load(&sourceCanvasH);
    if (sw <= 0 || sh <= 0 || ch <= 0)
        return -1;
    unsigned int x = (unsigned int)lroundf(atomic_load(&sourceX) + nx * sw);
    unsigned int y = (unsigned int)lroundf(ch - atomic_load(&sourceY) - (1 - ny) * sh);
    return (long long)(((unsigned long long)x << 32) | y);
}

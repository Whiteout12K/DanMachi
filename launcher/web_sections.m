/*
 * Native web-menu adapter. Adjust embedded local HTML views and route supported
 * navigation to the folder-local service.
 *
 * Editing notes: Keep view geometry and navigation handling scoped to the intended game
 * windows; inspect offline/menu_pages.py for page content.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

#import <Foundation/NSObject.h>
#import <Foundation/NSString.h>
#import <Foundation/NSArray.h>
#import <Foundation/NSGeometry.h>
#import <Foundation/NSData.h>
#import <Foundation/NSURL.h>
#import <Foundation/NSURLRequest.h>
#import <Foundation/NSValue.h>
#import <Foundation/NSTimer.h>
#import <dispatch/dispatch.h>
#import <objc/runtime.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <math.h>
#include <stdio.h>

@interface DMWebView : NSObject
@property NSRect frame;
@property(readonly) NSRect bounds;
@property(readonly) DMWebView *superview;
@property(readonly) NSArray *subviews;
@property(readonly) id window;
- (id)loadHTMLString:(NSString *)html baseURL:(NSURL *)url;
@end
@interface DMWindow : NSObject
@property(readonly) NSString *title;
@property(readonly) DMWebView *contentView;
@end
@interface DMApplication : NSObject
@property(readonly) NSArray *windows;
@end
@interface DMNavigation : NSObject
@property(readonly) NSURLRequest *request;
@property(readonly) NSInteger navigationType;
@end
extern DMApplication *NSApp;
static IMP originalFrame;
static char generationKey, inlineNavigationKey;

static BOOL gameWindow(DMWebView *view) {
    NSString *title = [(DMWindow *)view.window title];
    return [title isEqualToString:@"DanMachi MF"] ||
           [title isEqualToString:@"Memoria Freese EU"];
}
static NSRect menuFrame(DMWebView *view, NSRect fallback) {
    if (!gameWindow(view) || !view.superview)
        return fallback;
    NSRect host = view.superview.bounds;
    if (host.size.width <= 0 || host.size.height <= 0)
        return fallback;
    // Full-page native menus have a close control at the upper right. Leave
    // its row outside WebKit so it keeps receiving native game clicks.
    CGFloat margin = fmin(16, fmax(6, host.size.width * .015));
    CGFloat closeRow = fmin(44, fmax(24, host.size.height * .06));
    return NSMakeRect(host.origin.x + margin, host.origin.y + margin,
                      fmax(1, host.size.width - 2 * margin),
                      fmax(1, host.size.height - margin - closeRow));
}
static void fitView(DMWebView *view) {
    Class cls = objc_getClass("MacApkWKWebView");
    if ([view isKindOfClass:cls] && gameWindow(view)) {
        NSRect frame = menuFrame(view, view.frame);
        if (!NSEqualRects(frame, view.frame))
            ((void (*)(id, SEL, NSRect))originalFrame)(view, @selector(setFrame:),
                                                       frame);
        return;
    }
    for (DMWebView *child in view.subviews)
        fitView(child);
}
static BOOL localPage(NSURL *url) {
    if (![url.scheme isEqualToString:@"http"] ||
        ![url.host isEqualToString:@"127.0.0.1"] || url.port.intValue != 28766 ||
        url.user || url.password)
        return NO;
    NSString *path = url.path;
    return [path isEqualToString:@"/content"] || [path isEqualToString:@"/content/"] ||
           [path isEqualToString:@"/webview/production/help"] ||
           [path isEqualToString:@"/api/asset/notice/index"] ||
           [path isEqualToString:@"/offline/page"] ||
           [path isEqualToString:@"/offline/policy/index"] ||
           [path isEqualToString:@"/offline/policy/terms"] ||
           [path isEqualToString:@"/offline/policy/privacy"] ||
           [path isEqualToString:@"/offline/policy/currency"];
}
static NSString *readPage(NSURL *url) {
    // Fetch only the exact local read-only page routes above. AF_INET avoids
    // WebKit's denied delegated connection; no network rules are expanded.
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0)
        return nil;
    struct timeval timeout = {5, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    int noSignal = 1;
    setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, sizeof(noSignal));
    struct sockaddr_in address = {0};
    address.sin_len = sizeof(address);
    address.sin_family = AF_INET;
    address.sin_port = htons(28766);
    inet_pton(AF_INET, "127.0.0.1", &address.sin_addr);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        close(fd);
        return nil;
    }
    // Preserve the percent-encoded query rather than converting it to raw HTML.
    NSString *path =
        [url.absoluteString substringFromIndex:[@"http://127.0.0.1:28766" length]];
    NSRange fragment = [path rangeOfString:@"#"];
    if (fragment.location != NSNotFound)
        path = [path substringToIndex:fragment.location];
    NSString *request = [NSString
        stringWithFormat:
            @"GET %@ HTTP/1.0\r\nHost: 127.0.0.1:28766\r\nConnection: close\r\n\r\n",
            path];
    NSData *bytes = [request dataUsingEncoding:NSUTF8StringEncoding];
    const char *cursor = bytes.bytes;
    NSUInteger remaining = bytes.length;
    while (remaining) {
        ssize_t sent = send(fd, cursor, remaining, 0);
        if (sent <= 0) {
            close(fd);
            return nil;
        }
        cursor += sent;
        remaining -= sent;
    }
    NSMutableData *response = [NSMutableData data];
    char buffer[8192];
    ssize_t count;
    while ((count = recv(fd, buffer, sizeof(buffer), 0)) > 0) {
        [response appendBytes:buffer length:count];
        if (response.length > 2 * 1024 * 1024) {
            close(fd);
            return nil;
        }
    }
    close(fd);
    if (count < 0)
        return nil;
    NSString *text = [[NSString alloc] initWithData:response
                                           encoding:NSUTF8StringEncoding];
    if (![text hasPrefix:@"HTTP/1.0 200 "] && ![text hasPrefix:@"HTTP/1.1 200 "])
        return nil;
    NSRange header = [text rangeOfString:@"\r\n\r\n"];
    return header.location == NSNotFound ? nil
                                         : [text substringFromIndex:NSMaxRange(header)];
}
__attribute__((constructor)) static void installWebSections(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
      Class cls = objc_getClass("MacApkWKWebView");
      Method frameMethod = class_getInstanceMethod(cls, @selector(setFrame:));
      if (frameMethod) {
          originalFrame = method_getImplementation(frameMethod);
          IMP replacement =
              imp_implementationWithBlock(^(DMWebView *view, NSRect frame) {
                ((void (*)(id, SEL, NSRect))originalFrame)(view, @selector(setFrame:),
                                                           menuFrame(view, frame));
              });
          class_replaceMethod(cls, @selector(setFrame:), replacement,
                              method_getTypeEncoding(frameMethod));
          [NSTimer scheduledTimerWithTimeInterval:.05
                                          repeats:YES
                                            block:^(NSTimer *timer) {
                                              for (DMWindow *window in NSApp.windows)
                                                  fitView(window.contentView);
                                            }];
      }
      Class holder = objc_getClass("MacApkWvHolder");
      SEL policy = NSSelectorFromString(
          @"webView:decidePolicyForNavigationAction:preferences:decisionHandler:");
      Method method = class_getInstanceMethod(holder, policy);
      if (method) {
          IMP original = method_getImplementation(method);
          IMP replacement = imp_implementationWithBlock(^(
              id owner, DMWebView *view, DMNavigation *action, id preferences,
              void (^decision)(NSInteger, id)) {
            NSURL *url = action.request.URL;
            NSURL *inlineURL = objc_getAssociatedObject(view, &inlineNavigationKey);
            BOOL generatedNavigation =
                action.navigationType == -1 &&
                [url.absoluteString isEqualToString:inlineURL.absoluteString];
            if (!gameWindow(view) || !localPage(url) || generatedNavigation) {
                if (generatedNavigation)
                    objc_setAssociatedObject(view, &inlineNavigationKey, nil,
                                             OBJC_ASSOCIATION_RETAIN_NONATOMIC);
                ((void (*)(id, SEL, id, id, id, id))original)(
                    owner, policy, view, action, preferences, decision);
                return;
            }
            decision(0, preferences); // WKNavigationActionPolicyCancel
            id ticket = [NSObject new];
            objc_setAssociatedObject(view, &generationKey, ticket,
                                     OBJC_ASSOCIATION_RETAIN_NONATOMIC);
            dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
              NSString *html = readPage(url);
              if (!html)
                  html =
                      @"<!doctype html><meta name='viewport' content='width=device-width, initial-scale=1'><h2>Page unavailable</h2><p>The local page could not be loaded. Close this menu and try again.</p>";
              dispatch_async(dispatch_get_main_queue(), ^{
                if (objc_getAssociatedObject(view, &generationKey) != ticket ||
                    !view.window)
                    return;
                // Base URL preserves local policy navigation, intercepted
                // again above. Inline Gacha Details keeps its original path.
                objc_setAssociatedObject(view, &inlineNavigationKey, url,
                                         OBJC_ASSOCIATION_RETAIN_NONATOMIC);
                [view loadHTMLString:html baseURL:url];
                fprintf(stderr, "[dm-web] local page rendered: %s\n",
                        url.path.UTF8String);
              });
            });
          });
          class_replaceMethod(holder, policy, replacement,
                              method_getTypeEncoding(method));
      }
      fprintf(stderr,
              "[dm-web] responsive menu frames and local page loading installed\n");
    });
}

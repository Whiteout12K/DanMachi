/*
 * Native web-section diagnostic used to inspect embedded view behavior.
 *
 * Editing notes: Keep probes separate from the active adapter and never use them to
 * modify player data.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

// Native WebKit regression: run against the local server under the launch sandbox.
#import "../web_sections.m"
#import <Foundation/NSDictionary.h>
@interface NSApplication : NSObject
+ (id)sharedApplication;
- (void)run;
@end
@interface NSWindow : NSObject
- (id)initWithContentRect:(NSRect)rect
                styleMask:(NSUInteger)style
                  backing:(NSUInteger)backing
                    defer:(BOOL)defer;
@property NSString *title;
@property DMWebView *contentView;
- (void)setContentSize:(NSSize)size;
@end
@interface WKWebView : NSObject
@property NSRect frame;
- (id)initWithFrame:(NSRect)frame;
@property id navigationDelegate;
- (id)loadHTMLString:(NSString *)html baseURL:(NSURL *)url;
- (id)loadRequest:(NSURLRequest *)request;
- (void)evaluateJavaScript:(NSString *)script
         completionHandler:(void (^)(id, id))handler;
@end
@interface MacApkWKWebView : WKWebView
@end
@implementation MacApkWKWebView
@end
static NSWindow *testWindow;
static MacApkWKWebView *testWeb;
static id testHolder;
static int phase;
static CGFloat priorWidth;
static NSString *gachaHTML;
@interface MacApkWvHolder : NSObject
- (void)webView:(id)view
    decidePolicyForNavigationAction:(id)action
                        preferences:(id)p
                    decisionHandler:(void (^)(NSInteger, id))decision;
@end
static void verifySize(void) {
    [testWeb
        evaluateJavaScript:
            @"JSON.stringify({width:innerWidth,scroll:document.documentElement.scrollWidth,title:document.querySelector('h1,h2').innerText,fits:document.documentElement.scrollWidth<=innerWidth+1,details:document.querySelectorAll('details[open]').length,links:document.querySelectorAll('a').length})"
         completionHandler:^(id result, id error) {
           fprintf(stderr, "[test-web] phase %d frame %.0fx%.0f result %s\n", phase,
                   testWeb.frame.size.width, testWeb.frame.size.height,
                   [result UTF8String]);
           NSString *wanted = phase < 3 ? @"Offline Help" : @"Privacy Policy";
           if (error || (phase < 4 && ![result containsString:wanted]) ||
               ![result containsString:@"\"fits\":true"] ||
               testWeb.frame.size.width < 500)
               exit(2);
           if (phase == 0) {
               priorWidth = testWeb.frame.size.width;
               phase = 1;
               [testWindow setContentSize:NSMakeSize(1200, 675)];
           } else if (phase == 1) {
               if (testWeb.frame.size.width <= priorWidth)
                   exit(3);
               phase = 2;
               [testWindow setContentSize:NSMakeSize(640, 360)];
           } else if (phase == 2) {
               if (testWeb.frame.size.width >= priorWidth)
                   exit(4);
               phase = 3;
               [testWeb
                   evaluateJavaScript:
                       @"location.href='http://127.0.0.1:28766/offline/policy/privacy'"
                    completionHandler:nil];
               return;
           } else if (phase == 3) {
               phase = 4;
               [testWeb loadHTMLString:gachaHTML baseURL:nil];
               return;
           } else if (phase == 4) {
               phase = 5;
               [testWeb
                   evaluateJavaScript:@"document.querySelector('details').open=true"
                    completionHandler:^(id r, id e) {
                      verifySize();
                    }];
               return;
           } else {
               if (![result containsString:@"\"details\":1"])
                   exit(8);
               fprintf(
                   stderr,
                   "[test-web] Help, policy navigation, three viewport sizes, Gacha tables and disclosure passed\n");
               exit(0);
           }
           dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 250 * NSEC_PER_MSEC),
                          dispatch_get_main_queue(), ^{
                            verifySize();
                          });
         }];
}
@implementation MacApkWvHolder
- (void)webView:(id)view
    decidePolicyForNavigationAction:(id)action
                        preferences:(id)p
                    decisionHandler:(void (^)(NSInteger, id))decision {
    decision(1, p);
}
- (void)webView:(id)view didFinishNavigation:(id)navigation {
    verifySize();
}
- (void)webView:(id)view didFailProvisionalNavigation:(id)n withError:(id)e {
    fprintf(stderr, "[test-web] navigation failed\n");
    exit(5);
}
@end
int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 2)
            exit(9);
        gachaHTML =
            [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]
                                      encoding:NSUTF8StringEncoding
                                         error:nil];
        if (!gachaHTML)
            exit(9);
        [NSApplication sharedApplication];
        // No network outside the fixed local read-only page endpoint is accepted.
        for (NSString *url in @[
                 @"https://127.0.0.1:28766/content", @"http://127.0.0.1:28767/content",
                 @"http://127.0.0.1:28766/health",
                 @"http://127.0.0.1:28766@evil.example/content"
             ])
            if (localPage([NSURL URLWithString:url]))
                exit(6);
        testWindow = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 800, 450)
                                                 styleMask:15
                                                   backing:2
                                                     defer:NO];
        testWindow.title = @"DanMachi MF";
        testWeb = [[MacApkWKWebView alloc] initWithFrame:NSMakeRect(80, 100, 300, 150)];
        [testWindow.contentView performSelector:@selector(addSubview:)
                                     withObject:testWeb];
        testHolder = [MacApkWvHolder new];
        testWeb.navigationDelegate = testHolder;
        dispatch_after(
            dispatch_time(DISPATCH_TIME_NOW, 200 * NSEC_PER_MSEC),
            dispatch_get_main_queue(), ^{
              [testWeb
                  loadRequest:
                      [NSURLRequest
                          requestWithURL:
                              [NSURL URLWithString:@"http://127.0.0.1:28766/content"]]];
            });
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 15 * NSEC_PER_SEC),
                       dispatch_get_main_queue(), ^{
                         fprintf(stderr, "[test-web] timeout\n");
                         exit(7);
                       });
        [(NSApplication *)NSApp run];
    }
}

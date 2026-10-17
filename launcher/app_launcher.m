/*
 * Finder app entry point. Locate the project beside the app, run launcher/game.py with
 * the bundled Python, and show an error dialog if launch fails.
 *
 * Editing notes: The Objective-C shell owns UI/log presentation; Python owns game
 * startup and shutdown. Keep inherited Python settings out of the child environment.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

#import <dispatch/dispatch.h>
#include <fcntl.h>
#include <unistd.h>
#import <Foundation/NSObject.h>
#import <Foundation/NSString.h>
#import <Foundation/NSBundle.h>
#import <Foundation/NSFileManager.h>
#import <Foundation/NSFileHandle.h>
#import <Foundation/NSTask.h>
#import <Foundation/NSProcessInfo.h>
#import <Foundation/NSDictionary.h>
#import <Foundation/NSArray.h>
#import <Foundation/NSURL.h>
#import <Foundation/NSData.h>
#import <Foundation/NSError.h>
// Minimal declarations avoid an unrelated incomplete Carbon header in the local SDK.
@interface NSApplication : NSObject
+ (NSApplication *)sharedApplication;
- (BOOL)setActivationPolicy:(NSInteger)policy;
- (void)activateIgnoringOtherApps:(BOOL)flag;
- (void)run;
- (void)terminate:(id)sender;
@end
@interface NSAlert : NSObject
@property(copy) NSString *messageText;
@property(copy) NSString *informativeText;
@property NSInteger alertStyle;
- (NSInteger)runModal;
@end

int main(void) {
    @autoreleasepool {
        NSApplication *application = [NSApplication sharedApplication];
        [application setActivationPolicy:1];
        dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
          @autoreleasepool {
              NSString *root = [[[NSBundle mainBundle] bundlePath]
                  stringByDeletingLastPathComponent];
              NSString *logs = [root stringByAppendingPathComponent:@"state/logs"];
              NSString *logPath =
                  [logs stringByAppendingPathComponent:@"mf-launcher.log"];
              NSFileManager *files = [NSFileManager defaultManager];
              NSError *error = nil;
              BOOL ready = [files createDirectoryAtPath:logs
                            withIntermediateDirectories:YES
                                             attributes:nil
                                                  error:&error];
              NSFileHandle *log = nil;
              if (ready) {
                  // Avoid Foundation atomic replacement: Drive can block its rename on app launch.
                  int descriptor = open(logPath.fileSystemRepresentation,
                                        O_WRONLY | O_CREAT | O_TRUNC, 0600);
                  ready = descriptor >= 0;
                  if (ready)
                      log = [[NSFileHandle alloc] initWithFileDescriptor:descriptor
                                                          closeOnDealloc:YES];
              }
              NSTask *task = [NSTask new];
              task.executableURL =
                  [NSURL fileURLWithPath:[root stringByAppendingPathComponent:
                                                   @"runtime/python/bin/python3.10"]];
              task.arguments =
                  @[ @"-B", [root stringByAppendingPathComponent:@"launcher/game.py"] ];
              task.currentDirectoryURL = [NSURL fileURLWithPath:root];
              NSMutableDictionary *environment =
                  [[[NSProcessInfo processInfo] environment] mutableCopy];
              for (NSString *key in @[
                       @"PYTHONHOME", @"PYTHONPATH", @"PYTHONSTARTUP", @"PYTHONUSERBASE"
                   ])
                  [environment removeObjectForKey:key];
              environment[@"PYTHONNOUSERSITE"] = @"1";
              task.environment = environment;
              if (ready) {
                  task.standardOutput = log;
                  task.standardError = log;
                  ready = [task launchAndReturnError:&error];
              }
              BOOL launched = ready;
              if (launched)
                  [task waitUntilExit];
              [log closeFile];
              dispatch_async(dispatch_get_main_queue(), ^{
                if (!launched || task.terminationStatus != 0) {
                    [application activateIgnoringOtherApps:YES];
                    NSAlert *alert = [NSAlert new];
                    alert.messageText = @"DanMachi MF could not open";
                    alert.informativeText = [NSString
                        stringWithFormat:@"%@\nLaunch log: %@",
                                         error.localizedDescription
                                             ?: @"See the launch log for details.",
                                         logPath];
                    alert.alertStyle = 2;
                    [alert runModal];
                }
                [application terminate:nil];
              });
          }
        });
        [application run];
        return 0;
    }
}

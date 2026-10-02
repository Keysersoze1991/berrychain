import Flutter
import UIKit
import workmanager_apple

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  // Opt-in instant notices: Dart asks for the APNs token over this channel,
  // signs it with the wallet and hands it to a seed's push relay. Nothing is
  // sent anywhere from here; the token is only returned to Dart.
  private var pushToken: String?
  private var pushWaiters: [FlutterResult] = []

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // Background refresh: the same identifier the Dart side registers, and the
    // plugins the background isolate needs.
    WorkmanagerPlugin.setPluginRegistrantCallback { registry in
      GeneratedPluginRegistrant.register(with: registry)
    }
    WorkmanagerPlugin.registerPeriodicTask(withIdentifier: "link.berrychain.wallet.refresh", earliestBeginInSeconds: NSNumber(value: 15 * 60))
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    let channel = FlutterMethodChannel(name: "berrychain/push", binaryMessenger: engineBridge.applicationRegistrar.messenger())
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self = self else { return result(nil) }
      switch call.method {
      case "requestToken":
        if let t = self.pushToken { return result(t) }
        self.pushWaiters.append(result)
        DispatchQueue.main.async { UIApplication.shared.registerForRemoteNotifications() }
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }

  override func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
    super.application(application, didRegisterForRemoteNotificationsWithDeviceToken: deviceToken)
    let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
    pushToken = hex
    let waiters = pushWaiters
    pushWaiters = []
    for w in waiters { w(hex) }
  }

  override func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
    super.application(application, didFailToRegisterForRemoteNotificationsWithError: error)
    let waiters = pushWaiters
    pushWaiters = []
    for w in waiters { w(nil) }
  }
}

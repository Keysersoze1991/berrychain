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
    // Sensitive clipboard entries (the twelve words, the sealed chest file):
    // local to this device, never Handoff'd, and gone after the ttl. And the
    // screen guard for the words: iOS cannot refuse a screenshot, so while
    // "protect" is on the content is hidden during recording or mirroring and
    // a screenshot is reported to Dart the moment it happens.
    let secure = FlutterMethodChannel(name: "berrychain/secure", binaryMessenger: engineBridge.applicationRegistrar.messenger())
    self.secureChannel = secure
    secure.setMethodCallHandler { [weak self] call, result in
      switch call.method {
      case "copySensitive":
        guard let args = call.arguments as? [String: Any], let text = args["text"] as? String else { return result(nil) }
        let ttl = (args["ttl"] as? Int) ?? 60
        UIPasteboard.general.setItems([[UIPasteboard.typeAutomatic: text]],
                                      options: [.localOnly: true, .expirationDate: Date().addingTimeInterval(TimeInterval(ttl))])
        result("expires")
      case "protect":
        let on = (call.arguments as? [String: Any])?["on"] as? Bool ?? false
        self?.setProtected(on)
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }

  // MARK: screen guard
  private var secureChannel: FlutterMethodChannel?
  private var guardOn = false
  private var captureCover: UIView?
  private var guardObservers: [NSObjectProtocol] = []

  private func setProtected(_ on: Bool) {
    guard on != guardOn else { return }
    guardOn = on
    let nc = NotificationCenter.default
    if on {
      guardObservers.append(nc.addObserver(forName: UIApplication.userDidTakeScreenshotNotification, object: nil, queue: .main) { [weak self] _ in
        self?.secureChannel?.invokeMethod("screenshotTaken", arguments: nil)
      })
      guardObservers.append(nc.addObserver(forName: UIScreen.capturedDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
        self?.updateCaptureCover()
      })
      updateCaptureCover()
    } else {
      for o in guardObservers { nc.removeObserver(o) }
      guardObservers = []
      captureCover?.removeFromSuperview()
      captureCover = nil
    }
  }

  private func updateCaptureCover() {
    let captured = UIScreen.main.isCaptured
    if captured && guardOn {
      if captureCover == nil, let w = self.window {
        let v = UIView(frame: w.bounds)
        v.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        v.backgroundColor = UIColor(red: 0.04, green: 0.13, blue: 0.22, alpha: 1)
        let l = UILabel(frame: v.bounds)
        l.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        l.textAlignment = .center
        l.numberOfLines = 0
        l.textColor = .white
        l.text = "Your recovery words are hidden while the screen is being recorded or mirrored."
        v.addSubview(l)
        w.addSubview(v)
        captureCover = v
      }
    } else {
      captureCover?.removeFromSuperview()
      captureCover = nil
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

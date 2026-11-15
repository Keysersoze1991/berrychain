import Flutter
import MultipeerConnectivity
import UIKit
import workmanager_apple

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  // Opt-in instant notices: Dart asks for the APNs token over this channel,
  // signs it with the wallet and hands it to a seed's push relay. Nothing is
  // sent anywhere from here; the token is only returned to Dart.
  private var pushToken: String?
  private var pushWaiters: [FlutterResult] = []
  private var carry: CarryLink?

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
    // Carrying sealed letters between nearby iPhones. Dart decides what is sent
    // and what is kept (lib/nearby.dart); this side only finds the other phones
    // and moves the bytes.
    let carryChannel = FlutterMethodChannel(name: "berrychain/carry", binaryMessenger: engineBridge.applicationRegistrar.messenger())
    let link = CarryLink(channel: carryChannel)
    self.carry = link
    carryChannel.setMethodCallHandler { [weak link] call, result in
      guard let link = link else { return result(nil) }
      let args = call.arguments as? [String: Any]
      switch call.method {
      case "start":
        link.start(name: (args?["name"] as? String) ?? "")
        result(nil)
      case "stop":
        link.stop()
        result(nil)
      case "send":
        if let to = args?["to"] as? String, let data = args?["data"] as? FlutterStandardTypedData {
          result(link.send(data.data, to: to))
        } else {
          result(false)
        }
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

// MARK: carrying
// The link between nearby iPhones, on Apple's Multipeer Connectivity (Bluetooth,
// and Wi-Fi with or without a shared network). Every phone both advertises and
// browses for the service; of two that see each other the one with the lower
// name invites, and invitations are always accepted, because what is handed
// over is only signed, sealed transactions that the receiving phone checks for
// itself. The session is encrypted. iOS keeps this alive only while the app is
// on screen, so Dart stops it when the app leaves and starts it again on return.
final class CarryLink: NSObject, MCSessionDelegate, MCNearbyServiceAdvertiserDelegate, MCNearbyServiceBrowserDelegate {
  private static let service = "berry-carry"
  private let channel: FlutterMethodChannel
  private var me: MCPeerID?
  private var session: MCSession?
  private var advertiser: MCNearbyServiceAdvertiser?
  private var browser: MCNearbyServiceBrowser?

  init(channel: FlutterMethodChannel) {
    self.channel = channel
    super.init()
  }

  func start(name: String) {
    stop()
    // a peer name must be 1 to 63 bytes; ours are short and plain, this is only a guard
    let trimmed = String(name.prefix(40))
    let peer = MCPeerID(displayName: trimmed.isEmpty ? "berry" : trimmed)
    let s = MCSession(peer: peer, securityIdentity: nil, encryptionPreference: .required)
    s.delegate = self
    let a = MCNearbyServiceAdvertiser(peer: peer, discoveryInfo: nil, serviceType: CarryLink.service)
    a.delegate = self
    let b = MCNearbyServiceBrowser(peer: peer, serviceType: CarryLink.service)
    b.delegate = self
    me = peer
    session = s
    advertiser = a
    browser = b
    a.startAdvertisingPeer()
    b.startBrowsingForPeers()
  }

  func stop() {
    advertiser?.stopAdvertisingPeer()
    browser?.stopBrowsingForPeers()
    advertiser?.delegate = nil
    browser?.delegate = nil
    session?.delegate = nil
    session?.disconnect()
    advertiser = nil
    browser = nil
    session = nil
    me = nil
  }

  func send(_ data: Data, to name: String) -> Bool {
    guard let s = session, let peer = s.connectedPeers.first(where: { $0.displayName == name }) else { return false }
    do {
      try s.send(data, toPeers: [peer], with: .reliable)
      return true
    } catch {
      return false
    }
  }

  private func fail(_ error: Error) {
    let text = error.localizedDescription
    DispatchQueue.main.async { [weak self] in
      self?.channel.invokeMethod("error", arguments: text)
    }
  }

  // The delegates are called on queues of the framework's own; everything is
  // taken to the main queue, where the channel lives and start and stop run.

  func session(_ session: MCSession, peer peerID: MCPeerID, didChange state: MCSessionState) {
    let name = peerID.displayName
    DispatchQueue.main.async { [weak self] in
      guard let self = self, session === self.session else { return }
      switch state {
      case .connected:
        self.channel.invokeMethod("connected", arguments: name)
      case .notConnected:
        self.channel.invokeMethod("gone", arguments: name)
      default:
        break
      }
    }
  }

  func session(_ session: MCSession, didReceive data: Data, fromPeer peerID: MCPeerID) {
    let name = peerID.displayName
    DispatchQueue.main.async { [weak self] in
      guard let self = self, session === self.session else { return }
      let arguments: [String: Any] = ["from": name, "data": FlutterStandardTypedData(bytes: data)]
      self.channel.invokeMethod("payload", arguments: arguments)
    }
  }

  // Streams and files are not part of carrying; the protocol requires the methods.
  func session(_ session: MCSession, didReceive stream: InputStream, withName streamName: String, fromPeer peerID: MCPeerID) {}
  func session(_ session: MCSession, didStartReceivingResourceWithName resourceName: String, fromPeer peerID: MCPeerID, with progress: Progress) {}
  func session(_ session: MCSession, didFinishReceivingResourceWithName resourceName: String, fromPeer peerID: MCPeerID, at localURL: URL?, withError error: Error?) {}

  func advertiser(_ advertiser: MCNearbyServiceAdvertiser, didReceiveInvitationFromPeer peerID: MCPeerID, withContext context: Data?, invitationHandler: @escaping (Bool, MCSession?) -> Void) {
    DispatchQueue.main.async { [weak self] in
      guard let self = self, advertiser === self.advertiser, let s = self.session else {
        invitationHandler(false, nil)
        return
      }
      invitationHandler(true, s)
    }
  }

  func advertiser(_ advertiser: MCNearbyServiceAdvertiser, didNotStartAdvertisingPeer error: Error) {
    fail(error)
  }

  func browser(_ browser: MCNearbyServiceBrowser, foundPeer peerID: MCPeerID, withDiscoveryInfo info: [String: String]?) {
    DispatchQueue.main.async { [weak self] in
      guard let self = self, browser === self.browser, let s = self.session, let mine = self.me else { return }
      // two phones that see each other would both invite; the lower name does, so only one invitation is made
      guard mine.displayName < peerID.displayName, !s.connectedPeers.contains(peerID) else { return }
      browser.invitePeer(peerID, to: s, withContext: nil, timeout: 20)
    }
  }

  func browser(_ browser: MCNearbyServiceBrowser, lostPeer peerID: MCPeerID) {}

  func browser(_ browser: MCNearbyServiceBrowser, didNotStartBrowsingForPeers error: Error) {
    fail(error)
  }
}

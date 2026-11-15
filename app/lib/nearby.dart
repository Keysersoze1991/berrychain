import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:nearby_connections/nearby_connections.dart';
import 'package:permission_handler/permission_handler.dart';

import 'core/outbox.dart';

/// Carrying sealed letters between nearby phones, with no internet involved.
///
/// Every phone with the switch on both advertises and looks for other
/// BerryChain phones over Bluetooth and Wi-Fi. When two meet they swap their
/// outboxes: signed, sealed transactions only. Whichever phone next reaches a
/// seed hands everything it carries to the chain.
///
/// Two links, one per system, and they do not see each other: Google's Nearby
/// Connections on Android, Apple's Multipeer Connectivity on iPhone (the
/// native half is CarryLink in ios/Runner/AppDelegate.swift, reached over the
/// "berrychain/carry" channel). What travels is the same on both. The iPhone
/// link lives only while the app is on screen; see [foreground].
class Carrier {
  static const serviceId = 'link.berrychain.carry';
  static const wireVersion = 1;
  static const _link = MethodChannel('berrychain/carry');

  final Outbox outbox;
  final Future<void> Function() onReceived;   // the session drains and redraws
  Future<int> Function(List<dynamic> notes)? onNotes;   // the session takes in carried bottles; returns how many were new
  final void Function() onChange;
  bool running = false;
  String? error;
  final Set<String> _connected = {};
  final Set<String> _pending = {};
  String _name = '';
  Timer? _restart;
  bool _asleep = false;                       // iPhone: put down because the app left the screen

  Carrier(this.outbox, {required this.onReceived, required this.onChange});

  static bool get apple => !kIsWeb && Platform.isIOS;
  static bool get supported => !kIsWeb && (Platform.isAndroid || Platform.isIOS);
  /// Who this phone can carry for, in the words the settings page uses.
  static String get reach => apple
      ? 'Works between iPhones, and only while BerryChain is open on the screen of both.'
      : 'Android phones carry for Android phones and iPhones for iPhones; the two cannot hand letters to each other yet.';
  int get peers => _connected.length;

  /// Ask for the Bluetooth and nearby-device permissions this needs. Returns
  /// a plain reason when something was refused.
  Future<String?> requestPermissions() async {
    if (!supported) return 'Carrying letters between phones needs the phone app.';
    if (apple) return null;                   // the iPhone asks about the local network itself, the first time the link starts
    final wanted = <Permission>[Permission.bluetoothScan, Permission.bluetoothAdvertise, Permission.bluetoothConnect, Permission.nearbyWifiDevices, Permission.location];
    final results = await wanted.request();
    final refused = results.entries.where((e) => !e.value.isGranted && !e.value.isLimited).map((e) => e.key.toString().replaceFirst('Permission.', '')).toList();
    // Older Android versions do not have the newer permissions at all; those come back as denied without a prompt, which is fine.
    final essential = refused.where((r) => r == 'bluetoothConnect' || r == 'bluetoothScan' || r == 'bluetoothAdvertise' || r == 'location').toList();
    if (essential.length == refused.length && refused.length >= 4) return 'Bluetooth and nearby-device permission was refused. Allow it in the phone\'s app settings to carry letters.';
    return null;
  }

  Future<void> start() async {
    if (running || !supported) return;
    error = null;
    _name = 'berry-${DateTime.now().millisecondsSinceEpoch.toRadixString(36)}';
    if (apple) {
      try {
        _link.setMethodCallHandler(_fromLink);
        await _link.invokeMethod('start', {'name': _name});
        running = true;
      } catch (e) {
        error = 'Could not start carrying: $e';
        running = false;
      }
      onChange();
      return;
    }
    try {
      await Nearby().startAdvertising(_name, Strategy.P2P_CLUSTER, serviceId: serviceId,
          onConnectionInitiated: _initiated, onConnectionResult: _result, onDisconnected: _gone);
      await Nearby().startDiscovery(_name, Strategy.P2P_CLUSTER, serviceId: serviceId,
          onEndpointFound: _found, onEndpointLost: (id) => _pending.remove(id));
      running = true;
    } catch (e) {
      error = 'Could not start carrying: $e';
      running = false;
      try { await Nearby().stopAdvertising(); await Nearby().stopDiscovery(); } catch (_) {}
    }
    onChange();
  }

  Future<void> stop() async {
    _restart?.cancel();
    running = false;
    _asleep = false;
    try {
      if (apple) {
        await _link.invokeMethod('stop');
      } else {
        await Nearby().stopAdvertising();
        await Nearby().stopDiscovery();
        await Nearby().stopAllEndpoints();
      }
    } catch (_) {}
    _connected.clear();
    _pending.clear();
    onChange();
  }

  /// The iPhone link only lives while the app is on screen: put it down when the app leaves, and pick it up
  /// again with a fresh search when the app comes back. Nothing to do on Android.
  Future<void> foreground(bool on) async {
    if (!apple) return;
    if (!on) {
      if (!running) return;
      await stop();
      _asleep = true;
    } else if (_asleep) {
      _asleep = false;
      await start();
    }
  }

  /// What the iPhone link reports: a phone joined or left, bytes arrived, or the search could not start.
  Future<void> _fromLink(MethodCall call) async {
    final a = call.arguments;
    switch (call.method) {
      case 'connected':
        if (!running) return;
        _connected.add(a as String);
        onChange();
        await _handOver(a);
      case 'gone':
        _gone(a as String);
      case 'payload':
        final m = a as Map;
        await _takeIn(m['from'] as String, m['data'] as Uint8List);
      case 'error':
        error = 'Could not look for nearby iPhones ($a). Check that Local Network is allowed for BerryChain in the iPhone Settings, then switch carrying off and on.';
        onChange();
    }
  }

  void _found(String id, String name, String service) {
    if (service != serviceId || _connected.contains(id) || _pending.contains(id)) return;
    // Two phones that see each other both try to connect; let the lower name initiate, so only one request is made.
    if (_name.compareTo(name) > 0) return;
    _pending.add(id);
    Nearby().requestConnection(_name, id, onConnectionInitiated: _initiated, onConnectionResult: _result, onDisconnected: _gone).catchError((_) {
      _pending.remove(id);
      return false;
    });
  }

  void _initiated(String id, ConnectionInfo info) {
    Nearby().acceptConnection(id, onPayLoadRecieved: _payload, onPayloadTransferUpdate: (_, __) {}).catchError((_) => false);
  }

  void _result(String id, Status status) {
    _pending.remove(id);
    if (status == Status.CONNECTED) {
      _connected.add(id);
      onChange();
      _handOver(id);
    }
  }

  void _gone(String id) {
    _connected.remove(id);
    _pending.remove(id);
    onChange();
  }

  /// Give a freshly connected phone everything we hold.
  Future<void> _handOver(String id) async {
    try {
      final wire = outbox.toWire();
      final bytes = Uint8List.fromList(utf8.encode(jsonEncode({'v': wireVersion, 'txs': wire, 'notes': outbox.notesWire()})));
      if (apple) {
        await _link.invokeMethod('send', {'to': id, 'data': bytes});
      } else {
        await Nearby().sendBytesPayload(id, bytes);
      }
    } catch (_) {}
  }

  Future<void> _payload(String id, Payload payload) async {
    if (payload.type != PayloadType.BYTES || payload.bytes == null) return;
    await _takeIn(id, payload.bytes!);
  }

  /// Something arrived from a nearby phone: keep what is new, then let the
  /// session try the chain and redraw.
  Future<void> _takeIn(String id, Uint8List bytes) async {
    try {
      final m = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
      if (m['v'] != wireVersion) return;
      var added = await outbox.fromWire((m['txs'] as List?) ?? const []);
      final notes = (m['notes'] as List?) ?? const [];
      if (notes.isNotEmpty && onNotes != null) added += await onNotes!(notes);
      if (added > 0) {
        await onReceived();
        // pass the new ones on to everyone else we are connected to
        for (final other in _connected.where((o) => o != id)) {
          _handOver(other);
        }
      }
    } catch (_) {}
  }

  /// Tell connected phones about letters queued after the hand-over.
  Future<void> announce() async {
    for (final id in _connected) {
      await _handOver(id);
    }
  }
}

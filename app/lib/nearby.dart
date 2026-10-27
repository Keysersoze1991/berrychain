import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:nearby_connections/nearby_connections.dart';
import 'package:permission_handler/permission_handler.dart';

import 'core/outbox.dart';

/// Carrying sealed letters between nearby phones, with no internet involved.
///
/// Every phone with the switch on both advertises and looks for other
/// BerryChain phones over Bluetooth and Wi-Fi Direct (Google's Nearby
/// Connections). When two meet they swap their outboxes: signed, sealed
/// transactions only. Whichever phone next reaches a seed hands everything
/// it carries to the chain. Android only for now; iPhone carries nothing
/// until a later version.
class Carrier {
  static const serviceId = 'link.berrychain.carry';
  static const wireVersion = 1;

  final Outbox outbox;
  final Future<void> Function() onReceived;   // the session drains and redraws
  final void Function() onChange;
  bool running = false;
  String? error;
  final Set<String> _connected = {};
  final Set<String> _pending = {};
  String _name = '';
  Timer? _restart;

  Carrier(this.outbox, {required this.onReceived, required this.onChange});

  static bool get supported => !kIsWeb && Platform.isAndroid;
  int get peers => _connected.length;

  /// Ask for the Bluetooth and nearby-device permissions this needs. Returns
  /// a plain reason when something was refused.
  Future<String?> requestPermissions() async {
    if (!supported) return 'Carrying letters between phones is Android only for now.';
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
    try {
      await Nearby().stopAdvertising();
      await Nearby().stopDiscovery();
      await Nearby().stopAllEndpoints();
    } catch (_) {}
    _connected.clear();
    _pending.clear();
    onChange();
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
      final bytes = Uint8List.fromList(utf8.encode(jsonEncode({'v': wireVersion, 'txs': wire})));
      await Nearby().sendBytesPayload(id, bytes);
    } catch (_) {}
  }

  /// Something arrived from a nearby phone: keep what is new, then let the
  /// session try the chain and redraw.
  Future<void> _payload(String id, Payload payload) async {
    if (payload.type != PayloadType.BYTES || payload.bytes == null) return;
    try {
      final m = jsonDecode(utf8.decode(payload.bytes!)) as Map<String, dynamic>;
      if (m['v'] != wireVersion) return;
      final added = await outbox.fromWire((m['txs'] as List?) ?? const []);
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

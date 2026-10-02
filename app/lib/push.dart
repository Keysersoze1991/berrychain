import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'core/crypto.dart' as c;
import 'core/node.dart';
import 'core/wallet.dart';

/// Opt-in instant notices: the phone hands its Apple push token to a seed's
/// push relay, signed by the wallet, and the relay sends a push the moment a
/// letter to this address lands in a block. The relay learns only the pairing
/// of token and address; the push says that a letter arrived, nothing more.
///
/// iOS only: Android's own scheduler runs the background check often enough.
const _channel = MethodChannel('berrychain/push');

bool get pushSupported => !kIsWeb && Platform.isIOS;

/// The device's APNs token as hex, or null when the platform cannot give one
/// (no network, simulator, denied, or not iOS).
Future<String?> requestPushToken() async {
  if (!pushSupported) return null;
  try {
    return await _channel.invokeMethod<String>('requestToken');
  } catch (_) {
    return null;
  }
}

/// The bytes the relay verifies: must match berrychain/push.py register_message.
List<int> _message(String action, String address, String platform, String token, int ts) =>
    'berrychain-push|$action|$address|$platform|$token|$ts'.codeUnits;

Future<Map<String, dynamic>> _signed(Wallet w, String action, String token) async {
  final ts = DateTime.now().millisecondsSinceEpoch ~/ 1000;
  final t = token.toLowerCase();
  final sig = await c.sign(w.signPriv, _message(action, w.address, 'ios', t, ts));
  return {'address': w.address, 'pub': w.signPub, 'token': t, 'platform': 'ios', 'ts': ts, 'sig': sig};
}

/// Register with the first node that answers. Returns the node that took it.
Future<String> registerPush(Wallet w, String token, List<String> nodes) async {
  Object? last;
  for (final url in nodes) {
    try {
      await Node(url, timeout: const Duration(seconds: 15)).post('/push/register', await _signed(w, 'register', token));
      return url;
    } catch (e) {
      last = e;
    }
  }
  throw NodeError('no node took the registration: $last');
}

/// Best effort: tell every node to forget the token. Errors are ignored.
Future<void> unregisterPush(Wallet w, String token, List<String> nodes) async {
  for (final url in nodes) {
    try {
      await Node(url, timeout: const Duration(seconds: 10)).post('/push/unregister', await _signed(w, 'unregister', token));
    } catch (_) {}
  }
}

// Quick unlock with Face ID, Touch ID or a fingerprint. Opt-in, after a
// passphrase unlock. The passphrase stays the master: it is kept in the
// device keychain (iOS) or keystore-backed storage (Android) and handed back
// only after the platform's biometric check passes. It is still required to
// export the chest, to rotate a key with no backup, and whenever the
// biometric check fails or is cancelled. Not offered in the browser.
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';

class BiometricUnlock {
  static const _kEnabled = 'bio.enabled';
  static const _kPass = 'bio.passphrase';

  final _auth = LocalAuthentication();
  final _store = const FlutterSecureStorage(
    iOptions: IOSOptions(accessibility: KeychainAccessibility.unlocked_this_device),
  );

  bool get supported =>
      !kIsWeb && (defaultTargetPlatform == TargetPlatform.iOS || defaultTargetPlatform == TargetPlatform.android);

  /// The device has a biometric sensor with something enrolled.
  Future<bool> available() async {
    if (!supported) return false;
    try {
      return await _auth.isDeviceSupported() && await _auth.canCheckBiometrics;
    } catch (_) {
      return false;
    }
  }

  /// What to call it in the interface.
  Future<String> label() async {
    final ios = defaultTargetPlatform == TargetPlatform.iOS;
    try {
      final kinds = await _auth.getAvailableBiometrics();
      if (ios) return kinds.contains(BiometricType.face) ? 'Face ID' : 'Touch ID';
      if (kinds.contains(BiometricType.fingerprint) || !kinds.contains(BiometricType.face)) return 'fingerprint';
      return 'face unlock';
    } catch (_) {
      return ios ? 'Face ID' : 'fingerprint';
    }
  }

  Future<bool> enabled() async {
    if (!supported) return false;
    try {
      return (await _store.read(key: _kEnabled)) == '1';
    } catch (_) {
      return false;
    }
  }

  Future<bool> _prompt(String reason) async {
    try {
      return await _auth.authenticate(localizedReason: reason, biometricOnly: true, persistAcrossBackgrounding: true);
    } catch (_) {
      return false;
    }
  }

  /// Turns quick unlock on. The caller has just verified [passphrase].
  Future<bool> enable(String passphrase) async {
    if (!await available()) return false;
    if (!await _prompt('Confirm it is you to turn on quick unlock')) return false;
    await _store.write(key: _kPass, value: passphrase);
    await _store.write(key: _kEnabled, value: '1');
    return true;
  }

  Future<void> disable() async {
    try {
      await _store.delete(key: _kPass);
      await _store.delete(key: _kEnabled);
    } catch (_) {}
  }

  /// The passphrase, after a successful biometric check; null when quick
  /// unlock is off, the check failed, or the stored copy is gone.
  Future<String?> passphrase() async {
    if (!await enabled()) return null;
    if (!await _prompt('Unlock your chest')) return null;
    try {
      return await _store.read(key: _kPass);
    } catch (_) {
      return null;
    }
  }
}

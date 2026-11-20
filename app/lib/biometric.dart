// Quick unlock with Face ID, Touch ID or a fingerprint. Opt-in, after a
// passphrase unlock. The passphrase stays the master. It is still required to
// export the chest, to rotate a key with no backup, and whenever the
// biometric check fails or is cancelled. Not offered in the browser.
//
// Since 0.16.4 the operating system itself guards the stored passphrase:
//   iOS      a Keychain item with access control biometryCurrentSet, readable
//            only on this device, only while a passcode is set, and only after
//            a Face ID / Touch ID match. Enrolling a new face or finger
//            invalidates it.
//   Android  an AES key in the Android Keystore that requires a strong
//            (class 3) biometric for every use; the passphrase is encrypted
//            under it. A new fingerprint enrolment invalidates the key.
// Before 0.16.4 the passphrase sat in ordinary secure storage and the app
// asked for the biometric itself, a check a rooted or jailbroken phone could
// skip. Such an old copy is moved into the guarded store the first time it is
// used, and then deleted.
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';

class BiometricUnlock {
  static const _kEnabled = 'bio.enabled';
  static const _kPass = 'bio.passphrase';      // before 0.16.4, unguarded
  static const _kGuarded = 'bio.passphrase.v2'; // since 0.16.4, behind the biometric

  final _auth = LocalAuthentication();

  /// Plain secure storage: the on/off flag, and the old unguarded copy.
  final _plain = const FlutterSecureStorage(
    iOptions: IOSOptions(accessibility: KeychainAccessibility.unlocked_this_device),
  );

  /// The guarded store: the system shows the biometric prompt on every read.
  final _guarded = const FlutterSecureStorage(
    iOptions: IOSOptions(
      accountName: 'berrychain.quick-unlock',
      accessibility: KeychainAccessibility.passcode,
      accessControlFlags: [AccessControlFlag.biometryCurrentSet],
    ),
    aOptions: AndroidOptions.biometric(
      enforceBiometrics: true,
      requireBiometricsPerOperation: true,
      biometricType: AndroidBiometricType.strongBiometricOnly,
      storageNamespace: 'berrychain_quick_unlock',
      biometricPromptTitle: 'Unlock your chest',
      biometricPromptSubtitle: 'Confirm it is you',
      biometricPromptNegativeButton: 'Use the passphrase',
    ),
  );

  bool get supported =>
      !kIsWeb && (defaultTargetPlatform == TargetPlatform.iOS || defaultTargetPlatform == TargetPlatform.android);

  bool get _ios => defaultTargetPlatform == TargetPlatform.iOS;

  /// The device has a strong biometric sensor with something enrolled.
  Future<bool> available() async {
    if (!supported) return false;
    try {
      if (!await _auth.isDeviceSupported() || !await _auth.canCheckBiometrics) return false;
      final kinds = await _auth.getAvailableBiometrics();
      // Android: the guarded key accepts only class 3 biometrics.
      return _ios || kinds.contains(BiometricType.strong) || kinds.contains(BiometricType.fingerprint);
    } catch (_) {
      return false;
    }
  }

  /// What to call it in the interface.
  Future<String> label() async {
    try {
      final kinds = await _auth.getAvailableBiometrics();
      if (_ios) return kinds.contains(BiometricType.face) ? 'Face ID' : 'Touch ID';
      if (kinds.contains(BiometricType.fingerprint) || !kinds.contains(BiometricType.face)) return 'fingerprint';
      return 'face unlock';
    } catch (_) {
      return _ios ? 'Face ID' : 'fingerprint';
    }
  }

  Future<bool> enabled() async {
    if (!supported) return false;
    try {
      return (await _plain.read(key: _kEnabled)) == '1';
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
    // iOS does not prompt when an item is written, so confirm the person
    // first; on Android the write itself asks for the fingerprint.
    if (_ios && !await _prompt('Confirm it is you to turn on quick unlock')) return false;
    try {
      await _guarded.write(key: _kGuarded, value: passphrase);
    } catch (_) {
      return false; // cancelled, or the phone has no strong biometric / screen lock
    }
    try {
      await _plain.delete(key: _kPass);
    } catch (_) {}
    await _plain.write(key: _kEnabled, value: '1');
    return true;
  }

  Future<void> disable() async {
    for (final f in [() => _guarded.delete(key: _kGuarded), () => _plain.delete(key: _kPass), () => _plain.delete(key: _kEnabled)]) {
      try {
        await f();
      } catch (_) {}
    }
  }

  /// The passphrase, after the system's biometric check; null when quick
  /// unlock is off, the check failed or was cancelled, or the stored copy is
  /// gone (for example a new face or finger was enrolled).
  Future<String?> passphrase() async {
    if (!await enabled()) return null;
    // An unguarded copy from before 0.16.4: check the person the old way this
    // once, then move it behind the biometric.
    String? old;
    try {
      old = await _plain.read(key: _kPass);
    } catch (_) {}
    if (old != null) {
      if (!await _prompt('Unlock your chest')) return null;
      try {
        await _guarded.write(key: _kGuarded, value: old);
        await _plain.delete(key: _kPass);
      } catch (_) {
        // Could not move it (no strong biometric): turn quick unlock off rather
        // than keep an unguarded copy. This unlock still goes through.
        await disable();
      }
      return old;
    }
    final String? p;
    try {
      p = await _guarded.read(key: _kGuarded);
    } catch (_) {
      return null; // cancelled or not recognised: the passphrase field is still there
    }
    // Gone: a new face or finger was enrolled and the system dropped the key.
    // Turn quick unlock off so the person sets it up again after a passphrase unlock.
    if (p == null) await disable();
    return p;
  }
}
